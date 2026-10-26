import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (
    ClassificationFeedback,
    ClassificationSource,
    EmailMessage,
    EmailMessageGroup,
    Label,
    LabelOrigin,
    MailGroup,
    ProcessingStatus,
    User,
)
from app.schemas.email import ClassificationUpdate, EmailDetail, EmailPage, EmailStats
from app.schemas.preferences import UserPreferences
from app.services import labels as label_service
from app.services.email_domains import domain_of
from app.services.google_credentials import get_integration
from app.tasks import enqueue, process_email_task, refresh_email_task

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=EmailPage)
def list_emails(
    folder: MailGroup | None = None,
    label_id: uuid.UUID | None = None,
    status: ProcessingStatus | None = None,
    unread: bool | None = None,
    suspicious: bool | None = None,
    q: str | None = Query(None, max_length=200),
    sender: str | None = Query(None, max_length=320),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailPage:
    query = select(EmailMessage).where(EmailMessage.user_id == user.id)
    if folder:
        query = query.where(EmailMessage.groups.any(EmailMessageGroup.group_name == folder))
    if label_id:
        query = query.where(EmailMessage.label_id == label_id)
    if status:
        query = query.where(EmailMessage.processing_status == status)
    if unread is not None:
        query = query.where(EmailMessage.is_unread.is_(unread))
    if suspicious is not None:
        query = query.where(EmailMessage.is_suspicious.is_(suspicious))
    if q:
        pattern = _like_pattern(q)
        query = query.where(
            or_(
                EmailMessage.subject.ilike(pattern, escape="\\"),
                EmailMessage.sender_email.ilike(pattern, escape="\\"),
                EmailMessage.sender_name.ilike(pattern, escape="\\"),
                EmailMessage.snippet.ilike(pattern, escape="\\"),
            )
        )
    if sender:
        query = query.where(EmailMessage.sender_email.ilike(_like_pattern(sender), escape="\\"))
    query = _filter_dates(query, date_from, date_to, UserPreferences.of(user.preferences).timezone)

    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    items = db.scalars(
        query.order_by(EmailMessage.received_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return EmailPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=EmailStats)
def email_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> EmailStats:
    mine = EmailMessage.user_id == user.id
    by_status = dict(
        db.execute(
            select(EmailMessage.processing_status, func.count()).where(mine).group_by(EmailMessage.processing_status)
        ).all()
    )
    by_group = dict(
        db.execute(
            select(EmailMessageGroup.group_name, func.count())
            .join(EmailMessage, EmailMessage.id == EmailMessageGroup.email_message_id)
            .where(mine)
            .group_by(EmailMessageGroup.group_name)
        ).all()
    )
    gmail = get_integration(db, user.id, "gmail")
    return EmailStats(
        total=sum(by_status.values()),
        unread=_count(db, mine, EmailMessage.is_unread.is_(True)),
        pending=by_status.get(ProcessingStatus.PENDING, 0) + by_status.get(ProcessingStatus.PROCESSING, 0),
        needs_review=by_status.get(ProcessingStatus.REVIEW_REQUIRED, 0),
        failed=by_status.get(ProcessingStatus.FAILED, 0),
        suspicious=_count(db, mine, EmailMessage.is_suspicious.is_(True)),
        by_group={group.value: by_group.get(group.value, 0) for group in MailGroup},
        last_gmail_sync_at=gmail.last_sync_at if gmail else None,
    )


@router.get("/{email_id}", response_model=EmailDetail)
def get_email(email_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> EmailMessage:
    return _owned_email(db, user, email_id)


@router.patch("/{email_id}/classification", response_model=EmailDetail)
def update_classification(
    email_id: uuid.UUID,
    body: ClassificationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailMessage:
    """Confirm or correct a classification. Corrections are recorded to suggest rules later."""
    email = _owned_email(db, user, email_id)
    label = _resolve_label_choice(db, user, body)
    previous_group, previous_label_id = email.primary_group, email.label_id

    email.set_groups(body.primary_group, body.secondary_groups)
    email.label = label
    if body.primary_group == MailGroup.RECRUITMENT and previous_group != MailGroup.RECRUITMENT:
        email.recruitment_processed_at = None  # extract recruitment details for the corrected email
        email.recruitment_note = None
    if label:
        label.last_used_at = utcnow()
    email.label_suggestion = None
    email.confidence = 1.0
    email.classification_source = ClassificationSource.USER
    email.classification_explanation = "Set by you."
    email.processing_status = ProcessingStatus.CLASSIFIED
    email.processing_error = None
    email.classified_at = utcnow()
    email.labels_synced_at = None
    if body.is_suspicious is not None:
        email.is_suspicious = body.is_suspicious
        if not body.is_suspicious:
            email.suspicious_reasons = []

    if previous_group != body.primary_group or previous_label_id != (label.id if label else None):
        db.add(
            ClassificationFeedback(
                user_id=user.id,
                email_message_id=email.id,
                sender_email=email.sender_email,
                sender_domain=domain_of(email.sender_email),
                previous_group=previous_group,
                corrected_group=body.primary_group,
                previous_label_id=previous_label_id,
                corrected_label_id=label.id if label else None,
            )
        )
    db.commit()
    enqueue(refresh_email_task, str(email.id))  # labels in Gmail, recruitment details if needed
    db.refresh(email)
    return email


@router.post("/{email_id}/reprocess", response_model=EmailDetail)
def reprocess_email(email_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> EmailMessage:
    email = _owned_email(db, user, email_id)
    if email.processing_status == ProcessingStatus.PROCESSING:
        raise HTTPException(409, "This email is being processed right now.")
    email.processing_status = ProcessingStatus.PENDING
    email.processing_error = None
    email.recruitment_processed_at = None
    email.recruitment_note = None
    db.commit()
    enqueue(process_email_task, str(email.id), f":reprocess:{uuid.uuid4().hex[:8]}")
    db.refresh(email)
    return email


def _owned_email(db: Session, user: User, email_id: uuid.UUID) -> EmailMessage:
    email = db.get(EmailMessage, email_id)
    if email is None or email.user_id != user.id:
        raise HTTPException(404, "Email not found")
    return email


def _resolve_label_choice(db: Session, user: User, body: ClassificationUpdate) -> Label | None:
    if body.label_id:
        label = db.get(Label, body.label_id)
        if label is None or label.user_id != user.id or label.system_key:
            raise HTTPException(404, "Label not found")
        return label
    if body.new_label_name:
        try:
            return label_service.resolve_label(db, user.id, body.new_label_name, created_by=LabelOrigin.USER)
        except label_service.LabelNameError as exc:
            raise HTTPException(422, str(exc)) from exc
    return None


def _count(db: Session, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(EmailMessage).where(*conditions))


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filter_dates(query: Select, date_from: date | None, date_to: date | None, timezone: str | None) -> Select:
    """Dates are whole days in the user's timezone; timestamps are stored in UTC."""
    zone = ZoneInfo(timezone or "UTC")
    if date_from:
        query = query.where(EmailMessage.received_at >= datetime.combine(date_from, time.min, zone))
    if date_to:
        query = query.where(EmailMessage.received_at < datetime.combine(date_to + timedelta(days=1), time.min, zone))
    return query
