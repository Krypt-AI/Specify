import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ConnectionStatus, SheetConflict, SheetRowState, SheetsConnection, SyncJob, User
from app.schemas.sheets import (
    ConflictOut,
    ConflictResolve,
    FieldInfo,
    SheetsSettings,
    SheetsStatus,
    SpreadsheetCreate,
    SpreadsheetInfo,
    SpreadsheetSelect,
    SyncJobOut,
)
from app.services.audit import record_audit
from app.services.google_api import GoogleApiError, GoogleNotFound
from app.services.google_credentials import ReconnectRequired, get_integration
from app.services.sheets import client as sheets_client
from app.services.sheets.mapping import SPECS, ImportRejected, default_worksheets
from app.services.sheets.sync import ROW, request_sync, resolve_conflict
from app.tasks import enqueue, sync_sheets_task

router = APIRouter(prefix="/sheets", tags=["sheets"])

_SPREADSHEET_ID = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


@router.get("", response_model=SheetsStatus)
def sheets_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SheetsStatus:
    return _status(db, user)


@router.post("/spreadsheet", response_model=SheetsStatus)
def select_spreadsheet(body: SpreadsheetSelect, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SheetsStatus:
    """Use an existing spreadsheet. Its own columns are kept; mapped columns are added if missing."""
    match = _SPREADSHEET_ID.search(body.spreadsheet)
    spreadsheet_id = match.group(1) if match else body.spreadsheet.strip()
    meta = _google_call(db, user, lambda api: api.get_spreadsheet(spreadsheet_id))
    _save_connection(db, user, meta)
    return _status(db, user)


@router.post("/spreadsheet/create", response_model=SheetsStatus, status_code=201)
def create_spreadsheet(body: SpreadsheetCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SheetsStatus:
    worksheets = default_worksheets()
    layout = {w["title"]: list(w["columns"].values()) for w in worksheets.values() if w["enabled"]}
    meta = _google_call(db, user, lambda api: api.create_spreadsheet(body.title.strip(), layout))
    _save_connection(db, user, meta)
    return _status(db, user)


@router.delete("/spreadsheet", status_code=204)
def disconnect_spreadsheet(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """Stop syncing. The spreadsheet itself is left untouched."""
    connection = _connection(db, user)
    db.delete(connection)
    record_audit(db, user, "sheets.spreadsheet_removed")
    db.commit()


@router.put("/settings", response_model=SheetsStatus)
def update_settings(body: SheetsSettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SheetsStatus:
    connection = _connection(db, user)
    connection.worksheets = {key: worksheet.model_dump() for key, worksheet in body.worksheets.items()}
    connection.email_tracker_groups = list(body.email_tracker_groups)
    connection.auto_sync = body.auto_sync
    db.commit()
    return _status(db, user)


@router.post("/sync", response_model=SyncJobOut, status_code=202)
def sync_now(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SyncJob:
    _connection(db, user)
    job = request_sync(db, user.id, "manual")
    if job is None:
        return _latest_job(db, user)  # a sync is already waiting
    if not enqueue(sync_sheets_task, str(job.id)):
        raise HTTPException(503, "The background worker is unavailable. Please try again shortly.")
    return job


@router.get("/jobs", response_model=list[SyncJobOut])
def sync_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SyncJob]:
    return list(
        db.scalars(
            select(SyncJob)
            .where(SyncJob.user_id == user.id, SyncJob.provider == "sheets")
            .order_by(SyncJob.created_at.desc())
            .limit(20)
        )
    )


@router.post("/jobs/{job_id}/retry", response_model=SyncJobOut, status_code=202)
def retry_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SyncJob:
    failed = db.get(SyncJob, job_id)
    if failed is None or failed.user_id != user.id:
        raise HTTPException(404, "Sync not found")
    job = SyncJob(user_id=user.id, provider="sheets", trigger="retry")
    db.add(job)
    db.commit()
    enqueue(sync_sheets_task, str(job.id))
    return job


@router.get("/conflicts", response_model=list[ConflictOut])
def list_conflicts(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ConflictOut]:
    connection = db.scalar(select(SheetsConnection).where(SheetsConnection.user_id == user.id))
    if connection is None:
        return []
    conflicts = db.scalars(
        select(SheetConflict)
        .where(SheetConflict.connection_id == connection.id, SheetConflict.status == "open")
        .order_by(SheetConflict.created_at)
    )
    return [ConflictOut.model_validate(c).model_copy(update={"field_label": _field_label(c)}) for c in conflicts]


@router.post("/conflicts/{conflict_id}/resolve", status_code=204)
def resolve(
    conflict_id: uuid.UUID, body: ConflictResolve, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    connection = _connection(db, user)
    conflict = db.get(SheetConflict, conflict_id)
    if conflict is None or conflict.connection_id != connection.id or conflict.status != "open":
        raise HTTPException(404, "Conflict not found")
    try:
        resolve_conflict(db, user, conflict, body.resolution)
    except ImportRejected as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    job = request_sync(db, user.id, "manual")
    if job:
        enqueue(sync_sheets_task, str(job.id))


def _status(db: Session, user: User) -> SheetsStatus:
    integration = get_integration(db, user.id, "sheets")
    connection = db.scalar(select(SheetsConnection).where(SheetsConnection.user_id == user.id))
    conflicts = 0
    if connection:
        conflicts = db.scalar(
            select(func.count()).select_from(SheetConflict).where(
                SheetConflict.connection_id == connection.id, SheetConflict.status == "open"
            )
        )
    return SheetsStatus(
        connected=integration is not None and integration.connection_status == ConnectionStatus.CONNECTED,
        spreadsheet=SpreadsheetInfo(id=connection.spreadsheet_id, url=connection.spreadsheet_url, title=connection.title)
        if connection
        else None,
        settings=SheetsSettings(
            worksheets=connection.worksheets,
            email_tracker_groups=connection.email_tracker_groups,
            auto_sync=connection.auto_sync,
        )
        if connection
        else None,
        fields={key: [FieldInfo(key=f.key, header=f.header, importable=f.importable) for f in spec.fields] for key, spec in SPECS.items()},
        two_way_capable={key: spec.two_way for key, spec in SPECS.items()},
        open_conflicts=conflicts,
        last_job=_latest_job(db, user),
    )


def _latest_job(db: Session, user: User) -> SyncJob | None:
    return db.scalar(
        select(SyncJob).where(SyncJob.user_id == user.id, SyncJob.provider == "sheets").order_by(SyncJob.created_at.desc())
    )


def _connection(db: Session, user: User) -> SheetsConnection:
    connection = db.scalar(select(SheetsConnection).where(SheetsConnection.user_id == user.id))
    if connection is None:
        raise HTTPException(409, "Choose or create a spreadsheet first.")
    return connection


def _google_call(db: Session, user: User, call):
    integration = get_integration(db, user.id, "sheets")
    if integration is None or integration.connection_status != ConnectionStatus.CONNECTED:
        raise HTTPException(409, "Connect Google Sheets first (Settings → Accounts).")
    try:
        with sheets_client.sheets_client_for(db, integration) as api:
            return call(api)
    except GoogleNotFound as exc:
        raise HTTPException(404, "Spreadsheet not found. Check the link and that your Google account can open it.") from exc
    except (GoogleApiError, ReconnectRequired) as exc:
        raise HTTPException(502, str(exc)) from exc


def _save_connection(db: Session, user: User, meta: dict) -> None:
    spreadsheet_id = meta["spreadsheetId"]
    connection = db.scalar(select(SheetsConnection).where(SheetsConnection.user_id == user.id))
    if connection is None:
        connection = SheetsConnection(user_id=user.id, worksheets=default_worksheets(), email_tracker_groups=["university", "certifications"])
        db.add(connection)
    elif connection.spreadsheet_id != spreadsheet_id:
        # A different spreadsheet: forget what was written to the old one.
        db.execute(delete(SheetRowState).where(SheetRowState.connection_id == connection.id))
        db.execute(delete(SheetConflict).where(SheetConflict.connection_id == connection.id))
    connection.spreadsheet_id = spreadsheet_id
    connection.spreadsheet_url = meta.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    connection.title = meta.get("properties", {}).get("title", "")
    record_audit(db, user, "sheets.spreadsheet_selected", spreadsheet_id=spreadsheet_id)
    db.commit()


def _field_label(conflict: SheetConflict) -> str:
    if conflict.field == ROW:
        return "Whole row"
    spec = SPECS.get(conflict.entity)
    return next((f.header for f in spec.fields if f.key == conflict.field), conflict.field) if spec else conflict.field
