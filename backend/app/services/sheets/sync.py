"""Two-way spreadsheet sync keyed by record ID.

For every mapped cell Specify remembers the value it last wrote (SheetRowState). Comparing the
sheet, the database and that remembered value tells who changed what:

- sheet unchanged since Specify wrote it → Specify's current value is written
- only the sheet changed → imported when the worksheet is two-way and the column is editable;
  otherwise a conflict, so a manual edit is never silently overwritten
- both changed → a conflict, unless the worksheet names Sheets as its source of truth
"""
import logging
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    ConnectionStatus,
    SheetConflict,
    SheetRowState,
    SheetsConnection,
    SyncJob,
    SyncJobStatus,
    User,
)
from app.services.google_credentials import get_integration
from app.services.sheets import client as sheets_client
from app.services.sheets.client import SheetsApi, column_letter, sheet_range
from app.services.sheets.mapping import (
    ENTITY_ORDER,
    SPECS,
    ImportRejected,
    build_rows,
    cell_text,
    import_value,
)

logger = logging.getLogger(__name__)

LEASE_DURATION = timedelta(minutes=10)
ROW = "__row__"


class SheetsNotReady(Exception):
    """Sheets is not connected or no spreadsheet is selected."""


class LeaseBusy(Exception):
    """Another sync of the same spreadsheet is running."""


@dataclass
class WorksheetResult:
    created: int = 0
    updated: int = 0
    imported: int = 0
    deleted: int = 0
    conflicts: int = 0
    notes: list[str] = field(default_factory=list)


def connected_spreadsheet(db: Session, user_id: uuid.UUID) -> SheetsConnection:
    integration = get_integration(db, user_id, "sheets")
    if integration is None or integration.connection_status != ConnectionStatus.CONNECTED:
        raise SheetsNotReady("Connect Google Sheets first.")
    connection = db.scalar(select(SheetsConnection).where(SheetsConnection.user_id == user_id))
    if connection is None:
        raise SheetsNotReady("Choose or create a spreadsheet first.")
    return connection


def run_sync(db: Session, job: SyncJob, sheets: SheetsApi | None = None) -> SyncJob:
    """Sync every enabled worksheet. Retryable Google errors propagate so the task can retry."""
    connection = connected_spreadsheet(db, job.user_id)
    if not _acquire_lease(db, connection):
        job.status, job.last_error = SyncJobStatus.QUEUED, "Another sync is running; this one will retry."
        db.commit()
        raise LeaseBusy()
    user = db.get(User, job.user_id)
    job.status, job.started_at, job.attempt_count = SyncJobStatus.RUNNING, utcnow(), job.attempt_count + 1
    db.commit()
    try:
        integration = get_integration(db, job.user_id, "sheets")
        with nullcontext(sheets) if sheets else sheets_client.sheets_client_for(db, integration) as api:
            meta = api.get_spreadsheet(connection.spreadsheet_id)
            sheet_ids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
            summary = {}
            for entity in ENTITY_ORDER:
                config = connection.worksheets.get(entity, {})
                if config.get("enabled"):
                    result = sync_worksheet(db, connection, user, entity, api, sheet_ids)
                    summary[entity] = result.__dict__
                    db.commit()
        job.status, job.summary, job.last_error = SyncJobStatus.SUCCEEDED, summary, None
        integration.last_sync_at = utcnow()
    finally:
        connection.lease_expires_at = None
        job.finished_at = utcnow()
        db.commit()
    return job


def sync_worksheet(
    db: Session, connection: SheetsConnection, user: User, entity: str, api: SheetsApi, sheet_ids: dict[str, int]
) -> WorksheetResult:
    spec = SPECS[entity]
    config = connection.worksheets[entity]
    title = config["title"]
    columns = {key: header for key, header in config["columns"].items() if header and key in {f.key for f in spec.fields}}
    result = WorksheetResult()

    if title in sheet_ids:
        values = api.read_values(connection.spreadsheet_id, title)
    else:
        sheet_ids[title] = api.add_sheet(connection.spreadsheet_id, title)
        values = []
        result.notes.append(f"Created the {title} worksheet.")
    header = [cell_text(h) for h in (values[0] if values else [])]
    updates: list[dict] = []
    missing = [h for h in columns.values() if h not in header]
    if missing:
        start = column_letter(len(header))
        updates.append({"range": sheet_range(title, f"{start}1"), "values": [missing]})
        header += missing
    index = {key: header.index(h) for key, h in columns.items()}
    id_column = index[spec.id_field]

    sheet_rows: dict[str, tuple[int, dict[str, str]]] = {}
    for row_number, row in enumerate(values[1:], start=2):
        record_id = _cell(row, id_column)
        if record_id and record_id not in sheet_rows:
            sheet_rows[record_id] = (row_number, {key: _cell(row, col) for key, col in index.items()})

    records = build_rows(db, user, entity, connection.email_tracker_groups)
    states = {
        s.record_id: s
        for s in db.scalars(
            select(SheetRowState).where(SheetRowState.connection_id == connection.id, SheetRowState.entity == entity)
        )
    }
    open_conflicts = {
        (c.record_id, c.field)
        for c in db.scalars(
            select(SheetConflict).where(
                SheetConflict.connection_id == connection.id, SheetConflict.entity == entity, SheetConflict.status == "open"
            )
        )
    }
    two_way = spec.two_way and config.get("direction") == "two_way"
    sheets_wins = config.get("source_of_truth") == "sheets"

    def conflict(record_id: str, field_key: str, specify_value: str | None, sheet_value: str | None, reason: str) -> None:
        if (record_id, field_key) not in open_conflicts:
            open_conflicts.add((record_id, field_key))
            db.add(
                SheetConflict(
                    connection_id=connection.id, entity=entity, record_id=record_id, field=field_key,
                    specify_value=specify_value, sheet_value=sheet_value, reason=reason,
                )
            )
            result.conflicts += 1

    appends = []
    for record_id, record in records.items():
        state = states.get(record_id)
        if state is not None and state.excluded:
            continue
        if record_id not in sheet_rows:
            if state is None:
                row = [""] * len(header)
                for key, col in index.items():
                    row[col] = record.get(key, "")
                appends.append(row)
                db.add(SheetRowState(connection_id=connection.id, entity=entity, record_id=record_id, values={k: record.get(k, "") for k in index}))
                result.created += 1
            else:
                conflict(record_id, ROW, None, None, "This row was deleted in Sheets.")
            continue

        row_number, sheet_values = sheet_rows[record_id]
        remembered = dict(state.values) if state else {}
        for key, col in index.items():
            if key == spec.id_field or (record_id, key) in open_conflicts:
                continue
            in_sheet, in_specify = sheet_values.get(key, ""), record.get(key, "")
            last_written = remembered.get(key) if state else None
            if in_sheet == in_specify:
                remembered[key] = in_specify
            elif state is None or in_sheet == last_written:
                updates.append({"range": sheet_range(title, f"{column_letter(col)}{row_number}"), "values": [[in_specify]]})
                remembered[key] = in_specify
                result.updated += 1
            else:
                specify_changed = last_written is not None and in_specify != last_written
                importable = two_way and spec.field(key).importable and (not specify_changed or sheets_wins)
                if not importable:
                    reason = (
                        "Changed in both Sheets and Specify."
                        if specify_changed
                        else "Changed in Sheets, but this column is updated only by Specify."
                    )
                    conflict(record_id, key, in_specify, in_sheet, reason)
                    continue
                try:
                    import_value(db, user, entity, record_id, key, in_sheet)
                except ImportRejected as exc:
                    conflict(record_id, key, in_specify, in_sheet, str(exc))
                    continue
                remembered[key] = in_sheet
                result.imported += 1
        if state is None:
            db.add(SheetRowState(connection_id=connection.id, entity=entity, record_id=record_id, values=remembered))
        else:
            state.values = remembered

    deletes = []
    for record_id, (row_number, sheet_values) in sheet_rows.items():
        state = states.get(record_id)
        if record_id in records or state is None:
            continue  # rows Specify did not write are left alone
        if all(sheet_values.get(k, "") == state.values.get(k, "") for k in index):
            deletes.append(row_number - 1)
            result.deleted += 1
        else:
            result.notes.append(f"Kept row {row_number}: its record was removed in Specify but the row was edited.")
        db.delete(state)

    api.update_values(connection.spreadsheet_id, updates)
    api.append_rows(connection.spreadsheet_id, title, appends)
    api.delete_rows(connection.spreadsheet_id, sheet_ids[title], deletes)
    return result


def resolve_conflict(db: Session, user: User, conflict: SheetConflict, resolution: str) -> None:
    """keep_specify / keep_sheet for cells; restore / stop_syncing for deleted rows."""
    state = db.scalar(
        select(SheetRowState).where(
            SheetRowState.connection_id == conflict.connection_id,
            SheetRowState.entity == conflict.entity,
            SheetRowState.record_id == conflict.record_id,
        )
    )
    if conflict.field == ROW:
        if resolution not in ("restore", "stop_syncing"):
            raise ImportRejected("Choose restore or stop_syncing.")
        if state is not None:
            if resolution == "restore":
                db.delete(state)  # the next sync writes the row again
            else:
                state.excluded = True
    else:
        if resolution not in ("keep_specify", "keep_sheet"):
            raise ImportRejected("Choose keep_specify or keep_sheet.")
        if resolution == "keep_sheet":
            import_value(db, user, conflict.entity, conflict.record_id, conflict.field, conflict.sheet_value or "")
        if state is not None:
            # Remember the sheet's value as last written: the next sync sees the sheet as untouched
            # and writes Specify's value (which now equals the sheet's after keep_sheet).
            state.values = {**state.values, conflict.field: conflict.sheet_value or ""}
    conflict.status, conflict.resolution = "resolved", resolution


def request_sync(db: Session, user_id: uuid.UUID, trigger: str) -> SyncJob | None:
    """Queue a sync unless one is already waiting. Returns the new job, or None."""
    try:
        connection = connected_spreadsheet(db, user_id)
    except SheetsNotReady:
        return None
    if trigger != "manual" and not connection.auto_sync:
        return None
    waiting = db.scalar(
        select(SyncJob).where(
            SyncJob.user_id == user_id,
            SyncJob.provider == "sheets",
            SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING]),
            SyncJob.created_at > utcnow() - LEASE_DURATION,
        )
    )
    if waiting:
        return None
    job = SyncJob(user_id=user_id, provider="sheets", trigger=trigger)
    db.add(job)
    db.commit()
    return job


def due_sheet_syncs(db: Session, every: timedelta = timedelta(minutes=15)) -> list[uuid.UUID]:
    """Users whose spreadsheet has not synced recently, so edits made in Sheets are picked up."""
    cutoff = utcnow() - every
    recent = select(SyncJob.user_id).where(SyncJob.provider == "sheets", SyncJob.created_at > cutoff)
    return list(
        db.scalars(
            select(SheetsConnection.user_id).where(
                SheetsConnection.auto_sync.is_(True), SheetsConnection.user_id.not_in(recent)
            )
        )
    )


def _acquire_lease(db: Session, connection: SheetsConnection) -> bool:
    now = utcnow()
    result = db.execute(
        update(SheetsConnection)
        .where(
            SheetsConnection.id == connection.id,
            or_(SheetsConnection.lease_expires_at.is_(None), SheetsConnection.lease_expires_at < now),
        )
        .values(lease_expires_at=now + LEASE_DURATION)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(connection)
    return result.rowcount == 1


def _cell(row: list, index: int) -> str:
    return cell_text(row[index]) if index < len(row) else ""
