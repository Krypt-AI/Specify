"""Workflow graphs: the default incoming-email workflow, built-in templates and validation."""
import copy
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, WorkflowDefinition
from app.services.workflows.nodes import CONDITION_FIELDS, NODE_TYPES, OPERATORS


def _node(node_id: str, node_type: str, x: int, y: int, **config) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "config": {**NODE_TYPES[node_type].defaults(), **config},
        "position": {"x": x, "y": y},
    }


def _edge(source: str, target: str, handle: str = "out") -> dict:
    return {"id": f"{source}-{handle}-{target}", "source": source, "target": target, "handle": handle}


def default_email_workflow() -> dict:
    """The spec's incoming-email workflow (section 11.1) as a graph."""
    nodes = [
        _node("trigger", "gmail_new_email", 0, 0),
        _node("filter", "email_filter", 0, 120),
        _node("classify", "classification", 0, 240),
        _node("extract", "information_extraction", 0, 360),
        _node("labels", "gmail_label", 0, 480),
        _node("date_reminders", "date_reminders", 0, 600),
        _node("is_new_opportunity", "conditional_branch", 0, 720, field="opportunity.awaiting_decision", operator="is_true", value=""),
        _node("notify_new", "notification", -260, 840, title="New opportunity: {job_title}", message="{company} · decide in the Decision Queue"),
        _node("sync_before_decision", "sheets_sync", -260, 960),
        _node("await_decision", "decision_input", -260, 1080),
        _node("write_draft", "gmail_draft", -260, 1200),
        _node("sync_after_decision", "sheets_sync", -260, 1320),
        _node("sync_records", "sheets_sync", 260, 840),
        _node("handle_error", "error_handler", 520, 480),
        _node("end", "end", 0, 1440),
        _node("end_skipped", "end", 300, 240),
    ]
    edges = [
        _edge("trigger", "filter"),
        _edge("filter", "classify", "true"),
        _edge("filter", "end_skipped", "false"),
        _edge("classify", "extract"),
        _edge("classify", "handle_error", "error"),
        _edge("extract", "labels"),
        _edge("extract", "handle_error", "error"),
        _edge("labels", "date_reminders"),
        _edge("date_reminders", "is_new_opportunity"),
        _edge("date_reminders", "handle_error", "error"),
        _edge("labels", "handle_error", "error"),
        _edge("is_new_opportunity", "notify_new", "true"),
        _edge("is_new_opportunity", "sync_records", "false"),
        _edge("notify_new", "sync_before_decision"),
        _edge("sync_before_decision", "await_decision"),
        _edge("await_decision", "write_draft"),
        _edge("write_draft", "sync_after_decision"),
        _edge("write_draft", "handle_error", "error"),
        _edge("sync_after_decision", "end"),
        _edge("sync_records", "end"),
        _edge("handle_error", "end"),
    ]
    return {"nodes": nodes, "edges": edges}


def follow_up_digest_workflow() -> dict:
    return {
        "nodes": [
            _node("trigger", "scheduled_trigger", 0, 0, interval_minutes=1440),
            _node("sync", "sheets_sync", 0, 120),
            _node("notify", "notification", 0, 240, title="Daily sync finished", message="Your spreadsheet is up to date."),
            _node("end", "end", 0, 360),
        ],
        "edges": [_edge("trigger", "sync"), _edge("sync", "notify"), _edge("notify", "end")],
    }


def interview_reminder_workflow() -> dict:
    return {
        "nodes": [
            _node("trigger", "gmail_new_email", 0, 0),
            _node("classify", "classification", 0, 120),
            _node("extract", "information_extraction", 0, 240),
            _node("is_interview", "conditional_branch", 0, 360, field="opportunity.status", operator="equals", value="interview_scheduled"),
            _node("remind", "reminder", -200, 480, title="Prepare for the {job_title} interview", due_in_days=1),
            _node("end", "end", 0, 600),
        ],
        "edges": [
            _edge("trigger", "classify"),
            _edge("classify", "extract"),
            _edge("extract", "is_interview"),
            _edge("is_interview", "remind", "true"),
            _edge("is_interview", "end", "false"),
            _edge("remind", "end"),
        ],
    }


BUILT_IN_TEMPLATES = {
    "incoming_email": ("Incoming email", "Classify, extract, label, wait for your decision and draft the reply.", default_email_workflow),
    "interview_reminders": ("Interview reminders", "Create a reminder when an interview is scheduled.", interview_reminder_workflow),
    "daily_sync": ("Daily spreadsheet sync", "Sync Google Sheets once a day and let you know.", follow_up_digest_workflow),
}


def ensure_default_workflow(db: Session, user: User) -> None:
    """Every user starts with the default workflow, enabled. Users may change or disable it."""
    existing = db.scalars(select(WorkflowDefinition).where(WorkflowDefinition.user_id == user.id, WorkflowDefinition.is_template.is_(False))).all()
    if existing:
        _upgrade_untouched_default(db, existing)
        return
    graph = default_email_workflow()
    db.add(
        WorkflowDefinition(
            user_id=user.id,
            name="Incoming email",
            description=BUILT_IN_TEMPLATES["incoming_email"][1],
            definition_json=graph,
            trigger_type=trigger_type(graph),
            enabled=True,
            is_default=True,
        )
    )
    db.commit()


def _upgrade_untouched_default(db: Session, definitions: list[WorkflowDefinition]) -> None:
    """Give a default workflow the user never edited the latest built-in steps."""
    for definition in definitions:
        node_ids = {n["id"] for n in definition.definition_json.get("nodes", [])}
        if definition.is_default and definition.version == 1 and "date_reminders" not in node_ids:
            definition.definition_json = default_email_workflow()
            db.commit()


def trigger_type(graph: dict) -> str:
    return next((n["type"] for n in graph.get("nodes", []) if NODE_TYPES.get(n.get("type", ""), None) and NODE_TYPES[n["type"]].trigger), "")


def normalize(graph: dict) -> dict:
    """Fill node defaults and give edges ids, so stored graphs are complete."""
    graph = copy.deepcopy(graph)
    for node in graph.get("nodes", []):
        node_type = NODE_TYPES.get(node.get("type", ""))
        if node_type:
            node["config"] = {**node_type.defaults(), **(node.get("config") or {})}
        node.setdefault("position", {"x": 0, "y": 0})
    for edge in graph.get("edges", []):
        edge.setdefault("handle", "out")
        edge.setdefault("id", f"{edge.get('source')}-{edge['handle']}-{edge.get('target')}-{uuid.uuid4().hex[:6]}")
    return graph


def validate(graph: dict) -> list[str]:
    """Return problems that stop the workflow from running; an empty list means it is valid."""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    errors: list[str] = []
    by_id = {}
    for node in nodes:
        node_id, node_type = node.get("id"), NODE_TYPES.get(node.get("type", ""))
        if not node_id or node_id in by_id:
            errors.append(f"Node ids must be present and unique ({node_id!r}).")
            continue
        if node_type is None:
            errors.append(f"{node_id}: unknown step type {node.get('type')!r}.")
            continue
        by_id[node_id] = node
        errors += [f"{node_id}: {problem}" for problem in _config_problems(node_type, node.get("config") or {})]

    triggers = [n for n in by_id.values() if NODE_TYPES[n["type"]].trigger]
    if len(triggers) != 1:
        errors.append("A workflow needs exactly one trigger.")
    outgoing: dict[str, dict[str, str]] = {node_id: {} for node_id in by_id}
    incoming: dict[str, int] = {node_id: 0 for node_id in by_id}
    for edge in edges:
        source, target, handle = edge.get("source"), edge.get("target"), edge.get("handle", "out")
        if source not in by_id or target not in by_id:
            errors.append(f"A connection points to a missing step ({source} → {target}).")
            continue
        allowed = (*NODE_TYPES[by_id[source]["type"]].handles, "error")
        if handle not in allowed or (NODE_TYPES[by_id[source]["type"]].trigger and handle == "error"):
            errors.append(f"{source}: no {handle!r} output.")
            continue
        if handle in outgoing[source]:
            errors.append(f"{source}: the {handle!r} output is connected twice.")
            continue
        outgoing[source][handle] = target
        incoming[target] += 1
    if errors:
        return errors

    trigger = triggers[0]
    if incoming[trigger["id"]]:
        errors.append("Nothing can lead back into the trigger.")
    if _has_cycle(outgoing):
        errors.append("The workflow loops back on itself. Use a Retry step to repeat a failed step.")
    reachable = _reachable(trigger["id"], outgoing)
    errors += [f"{node_id}: not connected to the trigger." for node_id in by_id if node_id not in reachable]
    if trigger["type"] == "scheduled_trigger":
        errors += [
            f"{n['id']}: needs an email, but this workflow starts on a schedule."
            for n in by_id.values()
            if NODE_TYPES[n["type"]].requires_email
        ]
    return errors


def _config_problems(node_type, config: dict) -> list[str]:
    problems = []
    for spec in node_type.fields:
        value = config.get(spec.key, spec.default)
        if spec.kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"{spec.label} must be a number.")
            elif (spec.minimum is not None and value < spec.minimum) or (spec.maximum is not None and value > spec.maximum):
                problems.append(f"{spec.label} must be between {spec.minimum:g} and {spec.maximum:g}.")
        elif spec.kind == "select" and value not in spec.options:
            problems.append(f"{spec.label}: choose one of {', '.join(spec.options)}.")
        elif spec.kind == "tags" and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            problems.append(f"{spec.label} must be a list of words.")
        elif spec.kind == "boolean" and not isinstance(value, bool):
            problems.append(f"{spec.label} must be on or off.")
        elif spec.kind in ("text", "textarea") and not isinstance(value, str):
            problems.append(f"{spec.label} must be text.")
    if node_type.key == "conditional_branch":
        if config.get("field") not in CONDITION_FIELDS or config.get("operator") not in OPERATORS:
            problems.append("Choose what to check and how.")
    if node_type.key == "database_update" and config.get("action") == "set_status" and config.get("value") in (
        "offer_accepted", "offer_declined", "withdrawn",
    ):
        problems.append("That status needs your confirmation, so automation cannot set it.")
    return problems


def _has_cycle(outgoing: dict[str, dict[str, str]]) -> bool:
    state: dict[str, int] = {}

    def visit(node_id: str) -> bool:
        state[node_id] = 1
        for target in outgoing[node_id].values():
            if state.get(target) == 1 or (state.get(target) is None and visit(target)):
                return True
        state[node_id] = 2
        return False

    return any(state.get(node_id) is None and visit(node_id) for node_id in outgoing)


def _reachable(start: str, outgoing: dict[str, dict[str, str]]) -> set[str]:
    seen, stack = set(), [start]
    while stack:
        node_id = stack.pop()
        if node_id not in seen:
            seen.add(node_id)
            stack.extend(outgoing[node_id].values())
    return seen
