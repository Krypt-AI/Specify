from sqlalchemy import select

from app.models import Integration, Opportunity, SheetConflict, SyncJob, SyncJobStatus
from app.services.classification.pipeline import process_email
from app.services.gmail.sync import sync_mailbox
from app.services.google_api import GoogleRetryableError
from tests.conftest import connect_integration, login_as, make_user
from tests.fakes import FakeClassifier, FakeExtractor, ai_output, gmail_message


def _opportunity(db, user, fake_gmail, **message) -> Opportunity:
    fake_gmail.deliver(gmail_message(**message))
    [email_id] = sync_mailbox(db, user.id, fake_gmail).new_email_ids
    process_email(db, email_id, FakeClassifier(ai_output()), extractor=FakeExtractor(), gmail=fake_gmail)
    return db.scalar(select(Opportunity).order_by(Opportunity.created_at.desc()))


def _setup(client, db, user, fake_gmail):
    login_as(client, user)
    opportunity = _opportunity(db, user, fake_gmail)
    assert client.post("/api/sheets/spreadsheet/create", json={"title": "Tracker"}).status_code == 201
    return opportunity


def _sync(client) -> dict:
    job = client.post("/api/sheets/sync").json()
    return client.get("/api/sheets/jobs").json()[0] if job else job


def _set_worksheet(client, entity, **changes):
    settings = client.get("/api/sheets").json()["settings"]
    settings["worksheets"][entity].update(changes)
    response = client.put("/api/sheets/settings", json=settings)
    assert response.status_code == 200, response.text


def test_first_sync_writes_every_worksheet(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    opportunity = _setup(client, db, user, fake_gmail)

    job = _sync(client)

    assert job["status"] == SyncJobStatus.SUCCEEDED
    assert job["summary"]["opportunities"]["created"] == 1
    row = fake_sheets.records("Opportunities")[str(opportunity.id)]
    assert row["Job Title"] == "Software Engineer"
    assert row["Opportunity Status"] == "New"
    assert fake_sheets.records("Companies")[str(opportunity.company_id)]["Company Name"] == "Grab"
    assert str(opportunity.id) in fake_sheets.records("Applications")
    activity = list(fake_sheets.records("Activity Log").values())
    assert activity[0]["Activity Type"] == "opportunity.created"
    assert "Email Tracker" not in fake_sheets.spreadsheets[next(iter(fake_sheets.spreadsheets))]
    assert db.scalar(select(Integration).where(Integration.provider == "sheets")).last_sync_at is not None


def test_changes_in_specify_update_only_their_cells(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    opportunity = _setup(client, db, user, fake_gmail)
    _sync(client)
    fake_sheets.rows("Opportunities")[0].append("My own column")
    fake_sheets.edit("Opportunities", str(opportunity.id), "My own column", "keep me")

    client.patch(f"/api/opportunities/{opportunity.id}", json={"job_title": "Senior Software Engineer"})

    # the edit schedules a sync on its own
    auto = client.get("/api/sheets/jobs").json()[0]
    assert auto["trigger"] == "auto" and auto["summary"]["opportunities"]["updated"] >= 1
    row = fake_sheets.records("Opportunities")[str(opportunity.id)]
    assert row["Job Title"] == "Senior Software Engineer"
    assert row["My own column"] == "keep me"
    assert len(fake_sheets.records("Opportunities")) == 1  # no duplicate rows


def test_manual_edits_are_never_silently_overwritten(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    opportunity = _setup(client, db, user, fake_gmail)
    _sync(client)
    fake_sheets.edit("Opportunities", str(opportunity.id), "Job Title", "Edited by hand")

    job = _sync(client)
    _sync(client)

    assert fake_sheets.records("Opportunities")[str(opportunity.id)]["Job Title"] == "Edited by hand"
    assert job["summary"]["opportunities"]["conflicts"] == 1
    db.refresh(opportunity)
    assert opportunity.job_title == "Software Engineer"
    [conflict] = client.get("/api/sheets/conflicts").json()
    assert conflict["field_label"] == "Job Title" and conflict["sheet_value"] == "Edited by hand"

    assert client.post(f"/api/sheets/conflicts/{conflict['id']}/resolve", json={"resolution": "keep_specify"}).status_code == 204
    assert fake_sheets.records("Opportunities")[str(opportunity.id)]["Job Title"] == "Software Engineer"


def test_two_way_worksheet_imports_edits(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    opportunity = _setup(client, db, user, fake_gmail)
    _set_worksheet(client, "opportunities", direction="two_way")
    _sync(client)
    fake_sheets.edit("Opportunities", str(opportunity.id), "Salary", "8,000 - 10,000")
    fake_sheets.edit("Opportunities", str(opportunity.id), "Currency", "myr")

    job = _sync(client)

    assert job["summary"]["opportunities"]["imported"] == 2
    db.refresh(opportunity)
    assert (float(opportunity.salary_min), float(opportunity.salary_max), opportunity.salary_currency) == (8000, 10000, "MYR")


def test_consequential_status_from_sheets_needs_specify(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    opportunity = _setup(client, db, user, fake_gmail)
    _set_worksheet(client, "opportunities", direction="two_way")
    _sync(client)
    fake_sheets.edit("Opportunities", str(opportunity.id), "Opportunity Status", "Offer accepted")

    _sync(client)

    db.refresh(opportunity)
    assert opportunity.status == "new"
    conflict = db.scalar(select(SheetConflict))
    assert "confirmation" in conflict.reason


def test_edits_on_both_sides_follow_the_source_of_truth(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    opportunity = _setup(client, db, user, fake_gmail)
    _set_worksheet(client, "applications", direction="two_way")
    _sync(client)
    fake_sheets.edit("Applications", str(opportunity.id), "Notes", "from sheet")
    client.patch(f"/api/opportunities/{opportunity.id}", json={"notes": "from specify"})

    _sync(client)
    assert db.scalar(select(SheetConflict).where(SheetConflict.entity == "applications")).field == "notes"

    db.query(SheetConflict).delete()
    db.commit()
    _set_worksheet(client, "applications", direction="two_way", source_of_truth="sheets")
    _sync(client)
    db.refresh(opportunity)
    assert opportunity.notes == "from sheet"


def test_deleted_rows_are_flagged_and_can_be_restored(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    opportunity = _setup(client, db, user, fake_gmail)
    _sync(client)
    fake_sheets.delete_record("Opportunities", str(opportunity.id))

    _sync(client)
    [conflict] = client.get("/api/sheets/conflicts").json()
    assert conflict["field"] == "__row__"
    assert str(opportunity.id) not in fake_sheets.records("Opportunities")

    client.post(f"/api/sheets/conflicts/{conflict['id']}/resolve", json={"resolution": "restore"})
    assert str(opportunity.id) in fake_sheets.records("Opportunities")


def test_rows_of_merged_records_are_removed(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    login_as(client, user)
    _opportunity(db, user, fake_gmail, subject="Role 1")
    _opportunity(db, user, fake_gmail, subject="Role again")
    client.post("/api/sheets/spreadsheet/create", json={"title": "Tracker"})
    _sync(client)
    assert len(fake_sheets.records("Opportunities")) == 2

    [candidate] = client.get("/api/duplicates").json()
    client.post(f"/api/duplicates/{candidate['id']}/merge")
    _sync(client)

    assert len(fake_sheets.records("Opportunities")) == 1


def test_existing_spreadsheet_with_custom_columns(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    login_as(client, user)
    opportunity = _opportunity(db, user, fake_gmail)
    fake_sheets.add_spreadsheet("existing1", {"Jobs": [["Opportunity ID", "Role", "My notes"]]})
    response = client.post("/api/sheets/spreadsheet", json={"spreadsheet": "https://docs.google.com/spreadsheets/d/existing1/edit#gid=0"})
    assert response.json()["spreadsheet"]["id"] == "existing1"

    settings = response.json()["settings"]
    for entity in ("companies", "applications", "activity"):
        settings["worksheets"][entity]["enabled"] = False
    settings["worksheets"]["opportunities"]["title"] = "Jobs"
    settings["worksheets"]["opportunities"]["columns"]["job_title"] = "Role"
    assert client.put("/api/sheets/settings", json=settings).status_code == 200
    _sync(client)

    header, row = fake_sheets.rows("Jobs", "existing1")[:2]
    assert header[:3] == ["Opportunity ID", "Role", "My notes"]
    assert "Opportunity Status" in header  # missing mapped columns are added at the end
    assert row[1] == opportunity.job_title and row[2] == ""


def test_invalid_column_mappings_are_rejected(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    _setup(client, db, user, fake_gmail)
    settings = client.get("/api/sheets").json()["settings"]
    settings["worksheets"]["companies"]["columns"]["company_id"] = ""
    assert client.put("/api/sheets/settings", json=settings).status_code == 422
    settings = client.get("/api/sheets").json()["settings"]
    settings["worksheets"]["companies"]["columns"]["notes"] = "Company Name"
    assert client.put("/api/sheets/settings", json=settings).status_code == 422


def test_temporary_failures_are_retried_then_reported(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    _setup(client, db, user, fake_gmail)
    fake_sheets.fail_with = GoogleRetryableError("Google Sheets is temporarily unavailable (HTTP 503).")

    client.post("/api/sheets/sync")

    job = db.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()))
    assert job.status == SyncJobStatus.FAILED
    assert job.attempt_count == 5 and "temporarily unavailable" in job.last_error

    fake_sheets.fail_with = None
    retried = client.post(f"/api/sheets/jobs/{job.id}/retry").json()
    assert client.get("/api/sheets/jobs").json()[0]["id"] == retried["id"]
    assert client.get("/api/sheets/jobs").json()[0]["status"] == SyncJobStatus.SUCCEEDED


def test_database_changes_survive_sheet_outages(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    opportunity = _setup(client, db, user, fake_gmail)
    fake_sheets.fail_with = GoogleRetryableError("down")
    response = client.patch(f"/api/opportunities/{opportunity.id}", json={"notes": "still saved"})
    assert response.status_code == 200
    db.refresh(opportunity)
    assert opportunity.notes == "still saved"


def test_sheets_settings_are_private(client, db, user, gmail_integration, sheets_integration, fake_gmail, fake_sheets):
    _setup(client, db, user, fake_gmail)
    _sync(client)
    intruder = make_user("intruder@example.com", "sub-x")
    connect_integration(intruder, "sheets")
    login_as(client, intruder)

    assert client.get("/api/sheets").json()["spreadsheet"] is None
    assert client.get("/api/sheets/jobs").json() == []
    assert client.get("/api/sheets/conflicts").json() == []
    assert client.post("/api/sheets/sync").status_code == 409
