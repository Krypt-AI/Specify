"""Celery application. Run a worker and the beat scheduler alongside the API:

    celery -A app.worker worker --loglevel=info     (add --pool=solo on Windows)
    celery -A app.worker beat --loglevel=info
"""
import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import after_setup_logger, after_setup_task_logger

from app.core.config import get_settings
from app.core.logging import install_redaction

settings = get_settings()

celery_app = Celery("specify", broker=settings.redis_url, include=["app.tasks"])
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    # Eager mode (tests, no-Redis trials) retries like a worker and never fails the calling request.
    task_eager_propagates=False,
    task_acks_late=True,  # a task lost with its worker is redelivered
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    # Give up publishing quickly so an API request never hangs on a broker outage.
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5, "interval_max": 1},
    timezone="UTC",
    beat_schedule={
        "poll-mailboxes": {"task": "app.tasks.poll_mailboxes", "schedule": 60.0},
        "daily-maintenance": {"task": "app.tasks.daily_maintenance", "schedule": crontab(hour=3, minute=0)},
    },
)


@after_setup_logger.connect
@after_setup_task_logger.connect
def _redact_worker_logs(logger: logging.Logger, **_) -> None:
    """Worker logs carry Google API errors; keep tokens out of them as in the API."""
    install_redaction(logger)
