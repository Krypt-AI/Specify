import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import EmailMessage, RunStatus, User, WorkflowDefinition, WorkflowNodeRun, WorkflowRun
from app.schemas.workflows import (
    ConfigFieldOut,
    EnableRequest,
    NodeTypeOut,
    RunDetail,
    RunSummary,
    TemplateOut,
    TestRunRequest,
    WorkflowCreate,
    WorkflowOut,
    WorkflowSave,
)
from app.services.audit import record_audit
from app.services.workflows import engine
from app.services.workflows.definitions import BUILT_IN_TEMPLATES, ensure_default_workflow, normalize, trigger_type, validate
from app.services.workflows.nodes import NODE_TYPES
from app.tasks import enqueue, run_workflow_task

router = APIRouter(prefix="/workflows", tags=["workflows"])

RUN_ACTIONS = {
    "retry": engine.retry_failed,
    "cancel": engine.cancel,
    "pause": engine.pause,
    "resume": engine.unpause,
    "approve": lambda db, run: engine.answer_approval(db, run, True),
    "reject": lambda db, run: engine.answer_approval(db, run, False),
}


@router.get("/node-types", response_model=list[NodeTypeOut], dependencies=[Depends(get_current_user)])
def node_types() -> list[NodeTypeOut]:
    return [
        NodeTypeOut(
            key=t.key, label=t.label, category=t.category, description=t.description, handles=list(t.handles),
            fields=[ConfigFieldOut(**{**f.__dict__, "options": list(f.options)}) for f in t.fields],
            trigger=t.trigger, requires_email=t.requires_email, retryable=t.retryable, defaults=t.defaults(),
        )
        for t in NODE_TYPES.values()
    ]


@router.get("", response_model=list[WorkflowOut])
def list_workflows(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[WorkflowOut]:
    ensure_default_workflow(db, user)
    definitions = db.scalars(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.user_id == user.id, WorkflowDefinition.is_template.is_(False))
        .order_by(WorkflowDefinition.is_default.desc(), WorkflowDefinition.created_at)
    )
    return [_workflow_out(db, d) for d in definitions]


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TemplateOut]:
    built_in = [TemplateOut(key=key, name=name, description=description, built_in=True) for key, (name, description, _) in BUILT_IN_TEMPLATES.items()]
    saved = db.scalars(
        select(WorkflowDefinition).where(WorkflowDefinition.user_id == user.id, WorkflowDefinition.is_template.is_(True))
    )
    return built_in + [TemplateOut(key=str(t.id), name=t.name, description=t.description, built_in=False) for t in saved]


@router.post("", response_model=WorkflowOut, status_code=201)
def create_workflow(body: WorkflowCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WorkflowOut:
    graph = _graph_from(db, user, body)
    definition = WorkflowDefinition(
        user_id=user.id, name=body.name.strip(), description=body.description.strip(),
        definition_json=graph, trigger_type=trigger_type(graph), enabled=False,
    )
    db.add(definition)
    db.commit()
    return _workflow_out(db, definition)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(
    workflow_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RunSummary]:
    query = select(WorkflowRun).where(WorkflowRun.user_id == user.id)
    if workflow_id:
        query = query.where(WorkflowRun.workflow_definition_id == workflow_id)
    if status:
        query = query.where(WorkflowRun.status == status)
    runs = db.scalars(query.order_by(WorkflowRun.created_at.desc()).limit(limit)).all()
    names = dict(db.execute(select(WorkflowDefinition.id, WorkflowDefinition.name).where(WorkflowDefinition.user_id == user.id)).all())
    return [RunSummary.model_validate(run).model_copy(update={"workflow_name": names.get(run.workflow_definition_id, "")}) for run in runs]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RunDetail:
    return _run_detail(db, _owned_run(db, user, run_id))


@router.post("/runs/{run_id}/{action}", response_model=RunDetail)
def run_action(run_id: uuid.UUID, action: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RunDetail:
    if action not in RUN_ACTIONS:
        raise HTTPException(404, "Unknown action")
    run = _owned_run(db, user, run_id)
    if not RUN_ACTIONS[action](db, run):
        raise HTTPException(409, f"That is not possible while the run is {run.status}.")
    record_audit(db, user, f"workflow.run_{action}", run_id=str(run.id))
    db.commit()
    if run.status == RunStatus.RUNNING:
        enqueue(run_workflow_task, str(run.id))
    db.refresh(run)
    return _run_detail(db, run)


@router.get("/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WorkflowOut:
    return _workflow_out(db, _owned(db, user, workflow_id))


@router.put("/{workflow_id}", response_model=WorkflowOut)
def save_workflow(workflow_id: uuid.UUID, body: WorkflowSave, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Save the graph. An enabled workflow that becomes invalid is switched off rather than run."""
    definition = _owned(db, user, workflow_id)
    graph = normalize(body.definition_json)
    definition.name, definition.description = body.name.strip(), body.description.strip()
    definition.definition_json, definition.trigger_type = graph, trigger_type(graph)
    definition.version += 1
    if definition.enabled and validate(graph):
        definition.enabled = False
    record_audit(db, user, "workflow.saved", workflow_id=str(definition.id), version=definition.version)
    db.commit()
    return _workflow_out(db, definition)


@router.post("/{workflow_id}/enabled", response_model=WorkflowOut)
def set_enabled(workflow_id: uuid.UUID, body: EnableRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    definition = _owned(db, user, workflow_id)
    if definition.is_template:
        raise HTTPException(409, "Templates cannot run. Create a workflow from it instead.")
    problems = validate(definition.definition_json)
    if body.enabled and problems:
        raise HTTPException(422, problems)
    definition.enabled = body.enabled
    record_audit(db, user, "workflow.enabled" if body.enabled else "workflow.disabled", workflow_id=str(definition.id))
    db.commit()
    return _workflow_out(db, definition)


@router.post("/{workflow_id}/duplicate", response_model=WorkflowOut, status_code=201)
def duplicate(workflow_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WorkflowOut:
    source = _owned(db, user, workflow_id)
    return _workflow_out(db, _copy(db, source, f"Copy of {source.name}", template=False))


@router.post("/{workflow_id}/save-template", response_model=WorkflowOut, status_code=201)
def save_as_template(workflow_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WorkflowOut:
    source = _owned(db, user, workflow_id)
    return _workflow_out(db, _copy(db, source, source.name, template=True))


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    definition = _owned(db, user, workflow_id)
    if definition.is_default:
        raise HTTPException(409, "The default workflow can be switched off but not deleted.")
    db.delete(definition)
    db.commit()


@router.post("/{workflow_id}/test", response_model=RunSummary, status_code=202)
def test_run(workflow_id: uuid.UUID, body: TestRunRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A dry run: steps that would change records, Gmail or Sheets only report what they would do."""
    definition = _owned(db, user, workflow_id)
    problems = validate(definition.definition_json)
    if problems:
        raise HTTPException(422, problems)
    context = {}
    if definition.trigger_type == "gmail_new_email":
        email = db.get(EmailMessage, body.email_id) if body.email_id else None
        if email is None or email.user_id != user.id:
            raise HTTPException(422, "Choose one of your emails to test with.")
        context["email_id"] = str(email.id)
    run = engine.start_run(db, definition, f"test:{uuid.uuid4()}", context, is_test=True)
    enqueue(run_workflow_task, str(run.id))
    db.refresh(run)
    return RunSummary.model_validate(run).model_copy(update={"workflow_name": definition.name})


def _owned(db: Session, user: User, workflow_id: uuid.UUID) -> WorkflowDefinition:
    definition = db.get(WorkflowDefinition, workflow_id)
    if definition is None or definition.user_id != user.id:
        raise HTTPException(404, "Workflow not found")
    return definition


def _owned_run(db: Session, user: User, run_id: uuid.UUID) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(404, "Run not found")
    return run


def _graph_from(db: Session, user: User, body: WorkflowCreate) -> dict:
    if body.definition_json:
        return normalize(body.definition_json)
    if body.template in BUILT_IN_TEMPLATES:
        return BUILT_IN_TEMPLATES[body.template][2]()
    if body.template:
        try:
            saved = _owned(db, user, uuid.UUID(body.template))
        except ValueError as exc:
            raise HTTPException(404, "Template not found") from exc
        return normalize(saved.definition_json)
    return normalize({"nodes": [{"id": "trigger", "type": "gmail_new_email", "position": {"x": 0, "y": 0}},
                                {"id": "end", "type": "end", "position": {"x": 0, "y": 160}}],
                      "edges": [{"source": "trigger", "target": "end"}]})


def _copy(db: Session, source: WorkflowDefinition, name: str, template: bool) -> WorkflowDefinition:
    copy = WorkflowDefinition(
        user_id=source.user_id, name=name[:120], description=source.description,
        definition_json=normalize(source.definition_json), trigger_type=source.trigger_type,
        enabled=False, is_template=template,
    )
    db.add(copy)
    db.commit()
    return copy


def _workflow_out(db: Session, definition: WorkflowDefinition) -> WorkflowOut:
    last = db.scalar(
        select(WorkflowRun).where(WorkflowRun.workflow_definition_id == definition.id).order_by(WorkflowRun.created_at.desc())
    )
    counts = dict(
        db.execute(
            select(WorkflowRun.status, func.count())
            .where(WorkflowRun.workflow_definition_id == definition.id, WorkflowRun.is_test.is_(False))
            .group_by(WorkflowRun.status)
        ).all()
    )
    return WorkflowOut.model_validate(definition).model_copy(
        update={
            "problems": validate(definition.definition_json),
            "last_run": RunSummary.model_validate(last).model_copy(update={"workflow_name": definition.name}) if last else None,
            "waiting_runs": counts.get(RunStatus.WAITING, 0),
            "failed_runs": counts.get(RunStatus.FAILED, 0),
        }
    )


def _run_detail(db: Session, run: WorkflowRun) -> RunDetail:
    node_runs = db.scalars(
        select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run.id).order_by(WorkflowNodeRun.created_at)
    ).all()
    name = db.scalar(select(WorkflowDefinition.name).where(WorkflowDefinition.id == run.workflow_definition_id)) or ""
    return RunDetail.model_validate(run).model_copy(
        update={"workflow_name": name, "node_runs": node_runs, "last_error": run.execution_context.get("last_error")}
    )
