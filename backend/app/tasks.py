"""Background tasks. They stay thin: open a session, call a service, schedule follow-up work."""
import logging
import uuid
from datetime import timedelta

from celery import Task
from kombu.exceptions import OperationalError

from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models import EmailDraft, RunStatus, SyncJob, SyncJobStatus, WorkflowRun
from app.services import llm
from app.services.classification import ai
from app.services.classification.pipeline import process_email, recoverable_email_ids
from app.services.drafting.service import generate_draft
from app.services.gmail.client import GmailRetryableError
from app.services.gmail.sync import due_mailbox_user_ids, sync_mailbox
from app.services.llm import AIUnavailable
from app.services.privacy import purge_expired_data
from app.services.google_api import GoogleApiError, GoogleRetryableError
from app.services.google_credentials import ReconnectRequired
from app.services.recruitment import extraction
from app.services.reminders import notify, notify_due_reminders
from app.services.sheets.sync import LeaseBusy, SheetsNotReady, due_sheet_syncs, request_sync, run_sync
from app.services.workflows.engine import due_runs, execute, scheduled_workflows_due, start_email_workflows
from app.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    autoretry_for=(GmailRetryableError,),
    retry_backoff=30,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=5,
)
def sync_mailbox_task(user_id: str) -> None:
    with SessionLocal() as db:
        outcome = sync_mailbox(db, uuid.UUID(user_id))
    for email_id in outcome.new_email_ids:
        process_email_task.delay(str(email_id))


@celery_app.task
def process_email_task(email_id: str, event_suffix: str = "") -> None:
    """Start the enabled email workflows for a new (or reprocessed) email."""
    with SessionLocal() as db:
        run_ids = start_email_workflows(db, uuid.UUID(email_id), event_suffix)
    for run_id in run_ids:
        enqueue(run_workflow_task, str(run_id))


@celery_app.task(soft_time_limit=900, time_limit=960)
def run_workflow_task(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(WorkflowRun, uuid.UUID(run_id))
        if run is not None and run.status == RunStatus.RETRYING:
            run.status = RunStatus.RUNNING
            db.commit()
        run = execute(db, uuid.UUID(run_id))
        if run is not None and run.status == RunStatus.RETRYING and run.resume_at:
            delay = max(1, int((run.resume_at - utcnow()).total_seconds()))
            enqueue(run_workflow_task, run_id, countdown=delay)


@celery_app.task(bind=True, max_retries=4)
def refresh_email_task(self: Task, email_id: str) -> None:
    """Finish the steps a corrected email still needs: recruitment details and Gmail labels."""
    final_attempt = self.request.retries >= self.max_retries
    with SessionLocal() as db:
        try:
            email = process_email(
                db,
                uuid.UUID(email_id),
                ai.get_classifier(),
                extractor=extraction.get_extractor(),
                final_attempt=final_attempt,
            )
        except (AIUnavailable, GmailRetryableError) as exc:
            raise self.retry(exc=exc, countdown=min(60 * 2**self.request.retries, 1800))
        if email is not None:
            schedule_sheets_sync(db, email.user_id)


@celery_app.task
def poll_mailboxes() -> None:
    """Scheduled every minute: sync mailboxes that are due and re-queue work lost in a restart."""
    with SessionLocal() as db:
        user_ids = due_mailbox_user_ids(db)
        email_ids = recoverable_email_ids(db)
    for user_id in user_ids:
        sync_mailbox_task.delay(str(user_id))
    for email_id in email_ids:
        process_email_task.delay(str(email_id))
    with SessionLocal() as db:
        for user_id in due_sheet_syncs(db):
            schedule_sheets_sync(db, user_id, trigger="schedule")
        run_ids = due_runs(db) + scheduled_workflows_due(db)
        notify_due_reminders(db)
    for run_id in run_ids:
        enqueue(run_workflow_task, str(run_id))


@celery_app.task
def daily_maintenance() -> None:
    """Scheduled daily: apply each user's retention setting and clear old read notifications."""
    with SessionLocal() as db:
        purged = purge_expired_data(db)
    logger.info("Retention: removed %(email_bodies)s email bodies and %(notifications)s notifications", purged)


@celery_app.task(bind=True, max_retries=4)
def sync_sheets_task(self: Task, job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(SyncJob, uuid.UUID(job_id))
        if job is None or job.status in (SyncJobStatus.SUCCEEDED, SyncJobStatus.FAILED):
            return
        try:
            run_sync(db, job)
        except (GoogleRetryableError, LeaseBusy) as exc:
            db.rollback()
            job = db.get(SyncJob, uuid.UUID(job_id))
            job.last_error = str(exc) or "Google Sheets is busy."
            if self.request.retries >= self.max_retries:
                job.status, job.finished_at = SyncJobStatus.FAILED, utcnow()
                notify(db, job.user_id, "integration", "Google Sheets sync failed", job.last_error, "/settings?tab=sheets",
                       key=f"sheets-failed:{job.id}", commit=False)
                db.commit()
                return
            countdown = min(60 * 2**self.request.retries, 1800)
            job.status, job.next_retry_at = SyncJobStatus.QUEUED, utcnow() + timedelta(seconds=countdown)
            db.commit()
            raise self.retry(exc=exc, countdown=countdown)
        except (SheetsNotReady, ReconnectRequired, GoogleApiError) as exc:
            db.rollback()
            job = db.get(SyncJob, uuid.UUID(job_id))
            job.status, job.last_error, job.finished_at = SyncJobStatus.FAILED, str(exc), utcnow()
            db.commit()


@celery_app.task(bind=True, max_retries=3)
def generate_draft_task(self: Task, draft_id: str) -> None:
    final_attempt = self.request.retries >= self.max_retries
    with SessionLocal() as db:
        try:
            generate_draft(db, uuid.UUID(draft_id), llm.get_backend(), final_attempt=final_attempt)
        except (AIUnavailable, GoogleRetryableError) as exc:
            db.rollback()
            if final_attempt:  # only Gmail can still be failing here; the AI falls back to the template
                draft = db.get(EmailDraft, uuid.UUID(draft_id))
                draft.error = "Gmail was unavailable. Use “Save to Gmail” to try again."
                db.commit()
                return
            raise self.retry(exc=exc, countdown=min(60 * 2**self.request.retries, 900))


def schedule_sheets_sync(db, user_id: uuid.UUID, trigger: str = "auto") -> None:
    """Queue a spreadsheet sync shortly after changes; bursts of changes share one sync."""
    job = request_sync(db, user_id, trigger)
    if job:
        enqueue(sync_sheets_task, str(job.id), countdown=0 if trigger == "manual" else 15)


def enqueue(task: Task, *args: str, countdown: int = 0) -> bool:
    """Queue a task without failing the request when the broker is down; the poller catches up."""
    try:
        task.apply_async(args=args, countdown=countdown or None)
    except OperationalError:
        logger.warning("Task broker unavailable; %s will run on the next scheduled poll", task.name)
        return False
    return True
