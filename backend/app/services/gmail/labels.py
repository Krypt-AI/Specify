"""Mirrors Specify labels into Gmail. Only Specify-managed labels are ever added or removed."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import GMAIL_LABEL_ROOT, LEGACY_LABEL_ROOTS, EmailMessage, Label
from app.services.gmail.client import GmailApi, GmailConflict


def sync_message_labels(db: Session, gmail: GmailApi, email: EmailMessage, desired: list[Label]) -> None:
    """Make the message carry exactly the desired Specify labels, leaving every other label alone."""
    user_labels = list(db.scalars(select(Label).where(Label.user_id == email.user_id)))
    remote = _migrate_legacy_root(gmail, gmail.list_labels(), user_labels)
    by_name = {label["name"].lower(): label for label in remote}
    remote_ids = {label["id"] for label in remote}

    desired_ids = []
    for label in desired:
        if label.gmail_label_id not in remote_ids:
            label.gmail_label_id = None  # deleted in Gmail (or never created); recreate it
        desired_ids.append(_ensure_gmail_label(gmail, label, by_name))

    managed_ids = {label.gmail_label_id for label in user_labels if label.gmail_label_id}
    current = set(email.gmail_label_ids)
    add = [label_id for label_id in desired_ids if label_id not in current]
    remove = sorted((current & managed_ids) - set(desired_ids))
    if add or remove:
        gmail.modify_message(email.gmail_message_id, add=add, remove=remove)
        email.gmail_label_ids = sorted((current | set(add)) - set(remove))
    email.labels_synced_at = utcnow()


def _migrate_legacy_root(gmail: GmailApi, remote: list[dict], labels: list[Label]) -> list[dict]:
    """Rename labels this app created under an earlier name (MailUp/…) to the current root.

    Only labels whose id and exact legacy name match a record of ours are renamed.
    """
    by_id = {item["id"]: item for item in remote}
    taken = {item["name"].lower() for item in remote}
    renamed = False
    for legacy in LEGACY_LABEL_ROOTS:
        root = next((item for item in remote if item["name"] == legacy), None)
        if root and GMAIL_LABEL_ROOT.lower() not in taken:
            gmail.rename_label(root["id"], GMAIL_LABEL_ROOT)
            taken.add(GMAIL_LABEL_ROOT.lower())
            renamed = True
        for label in labels:
            current = by_id.get(label.gmail_label_id or "")
            if current and current["name"] == f"{legacy}/{label.name}" and label.gmail_name.lower() not in taken:
                gmail.rename_label(current["id"], label.gmail_name)
                taken.add(label.gmail_name.lower())
                renamed = True
    return gmail.list_labels() if renamed else remote


def _ensure_gmail_label(gmail: GmailApi, label: Label, by_name: dict[str, dict]) -> str:
    """Return the Gmail id of a label, creating it and the Specify parent when missing.

    An existing Gmail label with the same name is reused as-is, never renamed or overwritten.
    """
    if label.gmail_label_id:
        return label.gmail_label_id
    for name in (GMAIL_LABEL_ROOT, label.gmail_name):
        if name.lower() in by_name:
            continue
        try:
            by_name[name.lower()] = gmail.create_label(name)
        except GmailConflict:  # created concurrently; pick up the existing label
            by_name.update({item["name"].lower(): item for item in gmail.list_labels()})
    label.gmail_label_id = by_name[label.gmail_name.lower()]["id"]
    return label.gmail_label_id
