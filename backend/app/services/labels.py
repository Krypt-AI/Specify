"""Context labels: names proposed by the AI are cleaned and matched to existing labels to avoid sprawl."""
import re
import uuid
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Label, LabelOrigin

MAX_LABEL_LENGTH = 60
MAX_ACTIVE_LABELS = 300
SIMILARITY_THRESHOLD = 0.88

SYSTEM_LABELS = {
    "needs_review": ("Needs Review", "Emails Specify could not label confidently; review them in Specify."),
    "suspicious": ("Suspicious", "Emails showing signs of phishing or fraud."),
}


class LabelNameError(ValueError):
    pass


def clean_label_name(raw: str) -> str:
    name = " ".join(raw.replace("/", "-").split()).strip(" -–—:;,.")
    if not 2 <= len(name) <= MAX_LABEL_LENGTH:
        raise LabelNameError(f"Label names must be 2–{MAX_LABEL_LENGTH} characters.")
    return name


def normalize_label_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def find_similar(labels: list[Label], name: str) -> Label | None:
    """Exact match on the normalized name, else a close match whose numbers agree (CS301 ≠ CS302)."""
    key = normalize_label_name(name)
    numbers = re.findall(r"\d+", key)
    best, best_ratio = None, 0.0
    for label in labels:
        if label.normalized_name == key:
            return label
        if re.findall(r"\d+", label.normalized_name) != numbers:
            continue
        ratio = SequenceMatcher(None, label.normalized_name, key).ratio()
        if ratio > best_ratio:
            best, best_ratio = label, ratio
    return best if best_ratio >= SIMILARITY_THRESHOLD else None


def context_labels(db: Session, user_id: uuid.UUID, include_disabled: bool = False) -> list[Label]:
    """Context labels in a stable order (the classifier prompt is cached on this order)."""
    query = select(Label).where(Label.user_id == user_id, Label.system_key.is_(None))
    if not include_disabled:
        query = query.where(Label.enabled.is_(True))
    return list(db.scalars(query.order_by(Label.created_at, Label.id)))


def resolve_label(
    db: Session,
    user_id: uuid.UUID,
    name: str,
    description: str = "",
    created_by: LabelOrigin = LabelOrigin.AI,
) -> Label | None:
    """Return a matching label or create one.

    A label the user disabled is never revived by the AI; returns None in that case, or when the
    label limit is reached. A user who names a disabled label explicitly re-enables it.
    """
    cleaned = clean_label_name(name)
    existing = find_similar(context_labels(db, user_id, include_disabled=True), cleaned)
    if existing:
        if not existing.enabled and created_by == LabelOrigin.USER:
            existing.enabled = True
        return existing if existing.enabled else None

    if created_by == LabelOrigin.AI and _active_count(db, user_id) >= MAX_ACTIVE_LABELS:
        return None
    label = Label(
        user_id=user_id,
        name=cleaned,
        normalized_name=normalize_label_name(cleaned),
        description=description.strip()[:300],
        created_by=created_by,
    )
    db.add(label)
    db.flush()
    return label


def system_label(db: Session, user_id: uuid.UUID, key: str) -> Label:
    label = db.scalar(select(Label).where(Label.user_id == user_id, Label.system_key == key))
    if label is None:
        name, description = SYSTEM_LABELS[key]
        label = Label(
            user_id=user_id,
            name=name,
            normalized_name=normalize_label_name(f"system {key}"),
            description=description,
            system_key=key,
            created_by=LabelOrigin.SYSTEM,
        )
        db.add(label)
        db.flush()
    return label


def _active_count(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Label)
        .where(Label.user_id == user_id, Label.system_key.is_(None), Label.enabled.is_(True))
    )
