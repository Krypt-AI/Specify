from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.base import utcnow
from app.models import (
    EmailDraft,
    EmailMessage,
    Notification,
    ProcessingStatus,
    RunStatus,
    User,
    WorkflowDefinition,
    WorkflowNodeRun,
    WorkflowRun,
)
from app.services.classification import ai
from app.services.llm import AIUnavailable
from app.services.workflows import engine, executors
from app.services.workflows.definitions import ensure_default_workflow
from tests.conftest import connect_gmail, login_as, make_user
from tests.fakes import FakeClassifier, ai_output, gmail_message


@pytest.fixture
def auto(client, user, gmail_integration, fake_gmail, fake_classifier, fake_extractor):
    """Signed in, Gmail connected, AI faked: new mail flows through the workflow engine."""
    login_as(client, user)
    return client


def _deliver(client, fake_gmail, **message) -> None:
    fake_gmail.deliver(gmail_message(**message))
    assert client.post("/api/sync/gmail").status_code == 202


def _run(db) -> WorkflowRun:
    run = db.scalar(select(WorkflowRun).order_by(WorkflowRun.created_at.desc()))
    db.refresh(run)
    return run


def _steps(db, run) -> dict[str, str]:
    return {n.node_id: n.status for n in db.scalars(select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run.id))}


def test_non_recruitment_email_completes_the_default_workflow(auto, db, fake_gmail, fake_classifier):
    fake_classifier.output = ai_output("other", new_label="Newsletters")
    _deliver(auto, fake_gmail, subject="Weekly digest")

    run = _run(db)
    assert run.status == RunStatus.COMPLETED
    steps = _steps(db, run)
    assert steps["classify"] == "completed" and steps["extract"] == "skipped"
    assert steps["is_new_opportunity"] == "completed" and "await_decision" not in steps
    assert db.scalar(select(EmailMessage)).processing_status == ProcessingStatus.CLASSIFIED


def test_recruitment_email_waits_for_the_decision_then_drafts(auto, db, fake_gmail):
    _deliver(auto, fake_gmail)
    run = _run(db)
    assert run.status == RunStatus.WAITING and run.waiting_for["kind"] == "decision"
    assert db.scalar(select(Notification)).title == "New opportunity: Software Engineer"

    opportunity_id = run.waiting_for["opportunity_id"]
    auto.post(f"/api/opportunities/{opportunity_id}/decision", json={"decision": "request_salary"})

    run = _run(db)
    assert run.status == RunStatus.COMPLETED
    assert _steps(db, run)["write_draft"] == "completed"
    draft = db.scalar(select(EmailDraft))
    assert draft.scenario == "request_salary" and draft.gmail_draft_id in fake_gmail.drafts
    assert db.scalar(select(func.count()).select_from(EmailDraft)) == 1  # no second draft from the direct path


def test_the_same_event_never_runs_twice(auto, db, fake_gmail):
    _deliver(auto, fake_gmail)
    email = db.scalar(select(EmailMessage))
    assert engine.start_email_workflows(db, email.id) == []
    assert db.scalar(select(func.count()).select_from(WorkflowRun)) == 1


def test_transient_ai_failures_retry_with_backoff(auto, db, fake_gmail, fake_classifier):
    fake_classifier.error = AIUnavailable("overloaded")
    _deliver(auto, fake_gmail)

    run = _run(db)
    attempts = db.scalars(
        select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run.id, WorkflowNodeRun.node_id == "classify")
    ).all()
    assert [a.status for a in attempts] == ["retrying", "retrying", "completed"]
    assert db.scalar(select(EmailMessage)).processing_status == ProcessingStatus.REVIEW_REQUIRED  # rules fallback
    assert run.status == RunStatus.COMPLETED


def test_failed_runs_stop_and_can_be_retried(auto, db, fake_gmail, monkeypatch):
    original = executors.EXECUTORS["gmail_label"]
    monkeypatch.setitem(executors.EXECUTORS, "gmail_label", lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
    definition_graph_without_error_path(db)
    _deliver(auto, fake_gmail)

    run = _run(db)
    assert run.status == RunStatus.FAILED and run.current_node_id == "labels"
    assert "is_new_opportunity" not in _steps(db, run)  # dependent steps never ran
    assert db.scalar(select(Notification).where(Notification.kind == "workflow_error")) is not None

    monkeypatch.setitem(executors.EXECUTORS, "gmail_label", original)
    detail = auto.post(f"/api/workflows/runs/{run.id}/retry").json()
    assert detail["status"] in (RunStatus.WAITING, RunStatus.COMPLETED)


def definition_graph_without_error_path(db) -> None:
    user = db.scalar(select(User))
    ensure_default_workflow(db, user)
    definition = db.scalar(select(WorkflowDefinition))
    graph = dict(definition.definition_json)
    graph["edges"] = [e for e in graph["edges"] if not (e["source"] == "labels" and e["handle"] == "error")]
    definition.definition_json = graph
    db.commit()


def test_global_pause_holds_everything_until_resumed(auto, db, fake_gmail):
    auto.put("/api/settings", json={"preferences": {"automation": {"paused": True}}})
    _deliver(auto, fake_gmail)
    assert db.scalar(select(WorkflowRun)) is None
    assert db.scalar(select(EmailMessage)).processing_status == ProcessingStatus.PENDING

    auto.put("/api/settings", json={"preferences": {"automation": {"paused": False}}})

    assert _run(db).status == RunStatus.WAITING
    assert db.scalar(select(EmailMessage)).processing_status == ProcessingStatus.CLASSIFIED


def test_test_runs_change_nothing(auto, db, fake_gmail, fake_classifier):
    auto.put("/api/settings", json={"preferences": {"automation": {"paused": True}}})
    _deliver(auto, fake_gmail)
    email = db.scalar(select(EmailMessage))
    workflow = auto.get("/api/workflows").json()[0]

    response = auto.post(f"/api/workflows/{workflow['id']}/test", json={"email_id": str(email.id)})

    detail = auto.get(f"/api/workflows/runs/{response.json()['id']}").json()
    assert detail["status"] == RunStatus.COMPLETED and detail["is_test"]
    statuses = {n["node_id"]: n["status"] for n in detail["node_runs"]}
    assert statuses["classify"] == "simulated" and statuses["labels"] == "simulated"
    db.refresh(email)
    assert email.processing_status == ProcessingStatus.PENDING and fake_gmail.modifications == []


def test_invalid_graphs_cannot_be_enabled(auto, db):
    workflow = auto.get("/api/workflows").json()[0]
    graph = workflow["definition_json"]
    graph["edges"].append({"source": "end", "target": "trigger", "handle": "out"})

    saved = auto.put(f"/api/workflows/{workflow['id']}", json={"name": workflow["name"], "definition_json": graph}).json()

    assert saved["enabled"] is False and saved["problems"]
    response = auto.post(f"/api/workflows/{workflow['id']}/enabled", json={"enabled": True})
    assert response.status_code == 422


def test_scheduled_workflows_cannot_use_email_steps(auto):
    created = auto.post("/api/workflows", json={"name": "Daily", "template": "daily_sync"}).json()
    graph = created["definition_json"]
    graph["nodes"].append({"id": "classify", "type": "classification", "position": {"x": 0, "y": 0}})
    graph["edges"] = [e for e in graph["edges"] if e["source"] != "notify"] + [
        {"source": "notify", "target": "classify"}, {"source": "classify", "target": "end"}
    ]
    saved = auto.put(f"/api/workflows/{created['id']}", json={"name": "Daily", "definition_json": graph}).json()
    assert any("needs an email" in problem for problem in saved["problems"])


def test_approval_pauses_until_answered(auto, db, fake_gmail):
    graph = {
        "nodes": [
            {"id": "trigger", "type": "gmail_new_email"},
            {"id": "ask", "type": "user_approval", "config": {"message": "Track {subject}?"}},
            {"id": "yes", "type": "notification", "config": {"title": "Approved", "message": ""}},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"source": "trigger", "target": "ask"},
            {"source": "ask", "target": "yes", "handle": "true"},
            {"source": "ask", "target": "end", "handle": "false"},
            {"source": "yes", "target": "end"},
        ],
    }
    default = auto.get("/api/workflows").json()[0]
    auto.post(f"/api/workflows/{default['id']}/enabled", json={"enabled": False})
    created = auto.post("/api/workflows", json={"name": "Approve", "definition_json": graph}).json()
    assert auto.post(f"/api/workflows/{created['id']}/enabled", json={"enabled": True}).status_code == 200

    _deliver(auto, fake_gmail, subject="Hackathon")
    run = _run(db)
    assert run.status == RunStatus.WAITING and run.waiting_for["message"] == "Track Hackathon?"

    detail = auto.post(f"/api/workflows/runs/{run.id}/approve").json()
    assert detail["status"] == RunStatus.COMPLETED
    assert db.scalar(select(Notification).where(Notification.title == "Approved")) is not None


def test_runs_can_be_paused_resumed_and_cancelled(auto, db, fake_gmail):
    _deliver(auto, fake_gmail)
    run = _run(db)
    assert auto.post(f"/api/workflows/runs/{run.id}/pause").json()["status"] == RunStatus.PAUSED
    assert auto.post(f"/api/workflows/runs/{run.id}/resume").json()["status"] == RunStatus.WAITING
    assert auto.post(f"/api/workflows/runs/{run.id}/cancel").json()["status"] == RunStatus.CANCELLED
    assert auto.post(f"/api/workflows/runs/{run.id}/cancel").status_code == 409


def test_scheduled_workflows_run_once_per_interval(auto, db):
    created = auto.post("/api/workflows", json={"name": "Daily", "template": "daily_sync"}).json()
    auto.post(f"/api/workflows/{created['id']}/enabled", json={"enabled": True})

    first = engine.scheduled_workflows_due(db)
    second = engine.scheduled_workflows_due(db)

    assert len(first) == 1 and second == []


def test_interrupted_runs_are_recovered(auto, db, fake_gmail):
    _deliver(auto, fake_gmail)
    run = _run(db)
    run.status = RunStatus.RUNNING
    run.updated_at = utcnow() - timedelta(hours=1)
    db.commit()
    assert run.id in engine.due_runs(db)


def test_workflows_are_private(auto, db, fake_gmail):
    _deliver(auto, fake_gmail)
    run = _run(db)
    workflow_id = run.workflow_definition_id
    intruder = make_user("intruder@example.com", "sub-x")
    connect_gmail(intruder)
    login_as(auto, intruder)

    assert all(w["id"] != str(workflow_id) for w in auto.get("/api/workflows").json())
    assert auto.get(f"/api/workflows/{workflow_id}").status_code == 404
    assert auto.get(f"/api/workflows/runs/{run.id}").status_code == 404
    assert auto.post(f"/api/workflows/runs/{run.id}/cancel").status_code == 404
    assert auto.get("/api/workflows/runs").json() == []
