"""Runs workflows step by step and keeps every run's state in the database.

- One run per workflow per trigger event (the idempotency key), so duplicate events never run twice.
- A run pauses (decision, approval, delay, global pause) and later continues from the saved step.
- Transient failures retry the step with exponential backoff; when attempts run out the run
  follows the step's error path, or stops as failed and stays available for a manual retry.
- A failed step never lets the steps that depend on it run.
"""
import logging
import uuid
from datetime import timedelta

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    EmailMessage,
    Notification,
    RunStatus,
    User,
    WorkflowDefinition,
    WorkflowNodeRun,
    WorkflowRun,
)
from app.schemas.preferences import UserPreferences
from app.services.google_api import GoogleRetryableError
from app.services.google_credentials import ReconnectRequired
from app.services.llm import AIUnavailable
from app.services.sheets.sync import LeaseBusy
from app.services.workflows.definitions import ensure_default_workflow, validate
from app.services.workflows.executors import NodeContext, NodeError, run_node
from app.services.workflows.nodes import NODE_TYPES, NodeResult

logger = logging.getLogger(__name__)

TRANSIENT = (AIUnavailable, GoogleRetryableError, LeaseBusy, SoftTimeLimitExceeded)
MAX_STEPS = 200
STALE_RUN = timedelta(minutes=15)


class Graph:
    def __init__(self, definition: dict):
        self.nodes = {n["id"]: n for n in definition.get("nodes", [])}
        self.edges = {(e["source"], e.get("handle", "out")): e["target"] for e in definition.get("edges", [])}

    def trigger(self) -> str:
        return next(node_id for node_id, n in self.nodes.items() if NODE_TYPES[n["type"]].trigger)

    def next(self, node_id: str, handle: str) -> str | None:
        return self.edges.get((node_id, handle))


def start_run(
    db: Session,
    definition: WorkflowDefinition,
    trigger_event_id: str,
    context: dict,
    *,
    is_test: bool = False,
) -> WorkflowRun | None:
    """Create a run unless this workflow already handled the event. Invalid workflows never start."""
    problems = validate(definition.definition_json)
    if problems:
        logger.warning("Workflow %s not started: %s", definition.id, problems[0])
        return None
    graph = Graph(definition.definition_json)
    run = WorkflowRun(
        user_id=definition.user_id,
        workflow_definition_id=definition.id,
        definition_snapshot=definition.definition_json,
        workflow_version=definition.version,
        trigger_event_id=trigger_event_id,
        is_test=is_test,
        status=RunStatus.RUNNING,
        current_node_id=graph.trigger(),
        execution_context={**context, "attempts": {}, "outputs": {}},
        started_at=utcnow(),
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return run


def start_email_workflows(db: Session, email_id: uuid.UUID, event_suffix: str = "") -> list[uuid.UUID]:
    """Start every enabled email workflow for a newly synchronized email."""
    email = db.get(EmailMessage, email_id)
    if email is None:
        return []
    user = db.get(User, email.user_id)
    ensure_default_workflow(db, user)
    if UserPreferences.of(user.preferences).automation.paused:
        return []  # the email stays queued and starts once automation is resumed
    definitions = db.scalars(
        select(WorkflowDefinition).where(
            WorkflowDefinition.user_id == user.id,
            WorkflowDefinition.enabled.is_(True),
            WorkflowDefinition.is_template.is_(False),
            WorkflowDefinition.trigger_type == "gmail_new_email",
        )
    )
    event = f"email:{email_id}{event_suffix}"
    started = [start_run(db, d, event, {"email_id": str(email_id)}) for d in definitions]
    return [run.id for run in started if run is not None]


def execute(db: Session, run_id: uuid.UUID) -> WorkflowRun | None:
    """Advance a running run until it finishes, pauses, waits to retry, or fails."""
    run = db.get(WorkflowRun, run_id)
    if run is None or run.status != RunStatus.RUNNING:
        return run
    user = db.get(User, run.user_id)
    prefs = UserPreferences.of(user.preferences)
    if prefs.automation.paused and not run.is_test:
        return _wait(db, run, {"kind": "paused", "message": "Automation is paused."})
    graph = Graph(run.definition_snapshot)

    for _ in range(MAX_STEPS):
        db.refresh(run, ["status"])
        if run.status != RunStatus.RUNNING:
            return run  # paused or cancelled by the user meanwhile
        node_id = run.current_node_id
        node = graph.nodes[node_id]
        node_type = NODE_TYPES[node["type"]]
        config = {**node_type.defaults(), **(node.get("config") or {})}
        attempts = dict(run.execution_context.get("attempts", {}))
        attempt = attempts.get(node_id, 0) + 1
        max_attempts = int(config.get("max_attempts", 1)) if node_type.retryable else 1
        started = utcnow()
        inputs = _inputs(run)
        ctx = NodeContext(db, run, node_id, node["type"], config, user, prefs, attempt, attempt >= max_attempts)

        try:
            result = run_node(ctx)
        except TRANSIENT as exc:
            db.rollback()
            message, category = str(exc) or exc.__class__.__name__, "timeout" if isinstance(exc, SoftTimeLimitExceeded) else "transient"
            if attempt < max_attempts:
                backoff = int(config.get("backoff_seconds", 60)) * 2 ** (attempt - 1)
                _record_node(db, run, node, "retrying", attempt, inputs, {}, started, message, category)
                run.execution_context = {**run.execution_context, "attempts": {**attempts, node_id: attempt}}
                run.status, run.resume_at, run.error_message = RunStatus.RETRYING, utcnow() + timedelta(seconds=backoff), message
                db.commit()
                return run
            if not _fail_step(db, run, graph, node, attempt, inputs, started, message, category, prefs):
                return run
            continue
        except ReconnectRequired as exc:
            db.rollback()
            if not _fail_step(db, run, graph, node, attempt, inputs, started, str(exc), "integration", prefs):
                return run
            continue
        except NodeError as exc:
            db.rollback()
            if not _fail_step(db, run, graph, node, attempt, inputs, started, str(exc), "configuration", prefs):
                return run
            continue
        except Exception as exc:
            logger.exception("Workflow step %s failed in run %s", node_id, run.id)
            db.rollback()
            if not _fail_step(db, run, graph, node, attempt, inputs, started, "Unexpected error in this step.", "unexpected", prefs):
                return run
            continue

        _record_node(db, run, node, result.status, attempt, inputs, result.output, started)
        run.execution_context = {
            **run.execution_context,
            "attempts": {**attempts, node_id: 0},
            "outputs": {**run.execution_context.get("outputs", {}), node_id: _small(result.output)},
        }
        run.error_message = None
        if result.status == "waiting":
            return _wait(db, run, result.waiting_for or {}, result.resume_after_seconds)
        if result.status == "rewind":
            run.current_node_id = result.rewind_to
            run.execution_context = {**run.execution_context, "attempts": {**run.execution_context["attempts"], result.rewind_to: 0}}
            run.status, run.resume_at = RunStatus.RETRYING, utcnow() + timedelta(seconds=result.resume_after_seconds or 60)
            db.commit()
            return run
        target = None if node_type.key == "end" else graph.next(node_id, result.branch)
        if target is None:
            run.status, run.finished_at, run.current_node_id = RunStatus.COMPLETED, utcnow(), node_id
            run.waiting_for = None
            db.commit()
            return run
        run.current_node_id = target
        db.commit()

    run.status, run.error_message, run.finished_at = RunStatus.FAILED, "Too many steps; check the workflow for loops.", utcnow()
    db.commit()
    return run


def resume(db: Session, run: WorkflowRun, **context) -> bool:
    """Continue a waiting run from its saved step, adding what it was waiting for to its context."""
    if run.status != RunStatus.WAITING:
        return False
    run.execution_context = {**run.execution_context, **context}
    run.status, run.waiting_for, run.resume_at = RunStatus.RUNNING, None, None
    db.commit()
    return True


def resume_for_decision(db: Session, user_id: uuid.UUID, opportunity_id: uuid.UUID, decision_id: uuid.UUID) -> list[uuid.UUID]:
    waiting = db.scalars(select(WorkflowRun).where(WorkflowRun.user_id == user_id, WorkflowRun.status == RunStatus.WAITING))
    resumed = []
    for run in waiting:
        if (run.waiting_for or {}).get("kind") == "decision" and run.waiting_for.get("opportunity_id") == str(opportunity_id):
            if resume(db, run, decision_id=str(decision_id), opportunity_id=str(opportunity_id)):
                resumed.append(run.id)
    return resumed


def answer_approval(db: Session, run: WorkflowRun, approved: bool) -> bool:
    node_id = (run.waiting_for or {}).get("node_id")
    if run.status != RunStatus.WAITING or (run.waiting_for or {}).get("kind") != "approval" or not node_id:
        return False
    return resume(db, run, **{f"approval:{node_id}": approved})


def retry_failed(db: Session, run: WorkflowRun) -> bool:
    """Run a failed run again from the step that failed."""
    if run.status != RunStatus.FAILED:
        return False
    attempts = {**run.execution_context.get("attempts", {}), run.current_node_id: 0}
    run.execution_context = {**run.execution_context, "attempts": attempts}
    run.status, run.error_message, run.finished_at = RunStatus.RUNNING, None, None
    db.commit()
    return True


def cancel(db: Session, run: WorkflowRun) -> bool:
    if run.status not in (RunStatus.RUNNING, RunStatus.WAITING, RunStatus.RETRYING, RunStatus.PAUSED):
        return False
    run.status, run.finished_at, run.resume_at = RunStatus.CANCELLED, utcnow(), None
    db.commit()
    return True


def pause(db: Session, run: WorkflowRun) -> bool:
    if run.status not in (RunStatus.RUNNING, RunStatus.WAITING, RunStatus.RETRYING):
        return False
    run.execution_context = {**run.execution_context, "paused_from": run.status}
    run.status = RunStatus.PAUSED
    db.commit()
    return True


def unpause(db: Session, run: WorkflowRun) -> bool:
    if run.status != RunStatus.PAUSED:
        return False
    context = dict(run.execution_context)
    previous = context.pop("paused_from", RunStatus.RUNNING)
    run.execution_context = context
    # A run paused during a backoff continues straight away; one paused while waiting waits again.
    run.status = RunStatus.RUNNING if previous == RunStatus.RETRYING else previous
    db.commit()
    return True


def due_runs(db: Session) -> list[uuid.UUID]:
    """Runs to continue now: finished delays and backoffs, globally paused runs whose automation was
    resumed, and running runs whose worker disappeared (recovery after a restart)."""
    now = utcnow()
    ready = []
    for run in db.scalars(select(WorkflowRun).where(WorkflowRun.status.in_([RunStatus.WAITING, RunStatus.RETRYING]))):
        kind = (run.waiting_for or {}).get("kind")
        if run.resume_at and run.resume_at <= now:
            run.status, run.resume_at = RunStatus.RUNNING, None
            ready.append(run.id)
        elif kind == "paused" and not UserPreferences.of(db.get(User, run.user_id).preferences).automation.paused:
            run.status, run.waiting_for = RunStatus.RUNNING, None
            ready.append(run.id)
    stale = db.scalars(select(WorkflowRun.id).where(WorkflowRun.status == RunStatus.RUNNING, WorkflowRun.updated_at < now - STALE_RUN))
    db.commit()
    return ready + list(stale)


def scheduled_workflows_due(db: Session) -> list[uuid.UUID]:
    """Start scheduled workflows whose interval has passed; one run per interval window."""
    started = []
    now = utcnow()
    for definition in db.scalars(
        select(WorkflowDefinition).where(
            WorkflowDefinition.enabled.is_(True),
            WorkflowDefinition.is_template.is_(False),
            WorkflowDefinition.trigger_type == "scheduled_trigger",
        )
    ):
        if UserPreferences.of(db.get(User, definition.user_id).preferences).automation.paused:
            continue
        trigger = next(n for n in definition.definition_json["nodes"] if n["type"] == "scheduled_trigger")
        interval = int(trigger.get("config", {}).get("interval_minutes", 1440)) * 60
        window = int(now.timestamp() // interval)
        run = start_run(db, definition, f"schedule:{window}", {"scheduled_at": now.isoformat()})
        if run:
            started.append(run.id)
    return started


def _wait(db: Session, run: WorkflowRun, waiting_for: dict, resume_after_seconds: int | None = None) -> WorkflowRun:
    run.status, run.waiting_for = RunStatus.WAITING, waiting_for
    run.resume_at = utcnow() + timedelta(seconds=resume_after_seconds) if resume_after_seconds else None
    db.commit()
    return run


def _fail_step(db, run, graph, node, attempt, inputs, started, message, category, prefs) -> bool:
    """Record the failure. Returns True when the run continues on the step's error path."""
    _record_node(db, run, node, "failed", attempt, inputs, {}, started, message, category)
    run.execution_context = {
        **run.execution_context,
        "last_error": {"node_id": node["id"], "node_type": node["type"], "message": message, "category": category},
    }
    handler = graph.next(node["id"], "error")
    if handler:
        run.current_node_id = handler
        db.commit()
        return True
    run.status, run.error_message, run.finished_at = RunStatus.FAILED, f"{node['id']}: {message}", utcnow()
    if prefs.automation.notify_failures and not run.is_test:
        db.add(
            Notification(
                user_id=run.user_id, kind="workflow_error", title="A workflow stopped",
                body=f"{node['id']}: {message}", link=f"/activity?run={run.id}", idempotency_key=f"failed:{run.id}:{node['id']}:{attempt}",
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return False


def _record_node(db, run, node, status, attempt, inputs, output, started, error=None, category=None) -> None:
    db.add(
        WorkflowNodeRun(
            workflow_run_id=run.id, node_id=node["id"], node_type=node["type"], status=status, attempt=attempt,
            input_summary=inputs, output_summary=_small(output), started_at=started, finished_at=utcnow(),
            error_message=error, error_category=category,
        )
    )


def _inputs(run: WorkflowRun) -> dict:
    keys = ("email_id", "opportunity_id", "decision_id", "draft_id", "company_id")
    return {key: run.execution_context[key] for key in keys if run.execution_context.get(key)}


def _small(value: dict) -> dict:
    """Keep stored summaries small; never store whole email bodies."""
    text = str(value)
    return value if len(text) <= 4000 else {"summary": text[:4000] + "…"}
