from datetime import date

from sqlalchemy import func, select

from app.models import (
    Company,
    CompanyType,
    DuplicateCandidate,
    EmailMessage,
    Opportunity,
    OpportunityStatus,
    RecruiterContact,
)
from app.services.classification.pipeline import process_email
from app.services.gmail.sync import sync_mailbox
from app.services.llm import AIUnavailable
from tests.conftest import connect_gmail, login_as, make_user
from tests.fakes import FakeClassifier, FakeExtractor, ai_output, extraction_output, gmail_message


def _ingest(db, user, fake_gmail, extractor, *, group="recruitment", **message) -> EmailMessage:
    fake_gmail.deliver(gmail_message(**message))
    [email_id] = sync_mailbox(db, user.id, fake_gmail).new_email_ids
    process_email(db, email_id, FakeClassifier(ai_output(group)), extractor=extractor, gmail=fake_gmail)
    email = db.get(EmailMessage, email_id)
    db.refresh(email)
    return email


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_recruitment_email_creates_company_contact_and_opportunity(db, user, gmail_integration, fake_gmail):
    body = "We have a Software Engineer role. The salary is RM 8,000 to RM 10,000 per month."
    extractor = FakeExtractor(extraction_output(salary=(8000, 10000), currency="MYR", period="month"))

    email = _ingest(db, user, fake_gmail, extractor, body=body)

    opportunity = db.get(Opportunity, email.opportunity_id)
    assert opportunity.job_title == "Software Engineer"
    assert opportunity.status == OpportunityStatus.NEW
    assert (float(opportunity.salary_min), float(opportunity.salary_max)) == (8000, 10000)
    assert opportunity.salary_currency == "MYR"
    assert opportunity.company.name == "Grab"
    assert opportunity.company.domain == "grab.com"
    assert opportunity.recruiter.email == "aisha@grab.com"
    assert opportunity.recommendation["decision"] == "request_salary"
    assert email.recruitment_note.startswith("Created the opportunity")


def test_values_missing_from_the_email_are_dropped(db, user, gmail_integration, fake_gmail):
    output = extraction_output(
        salary=(9000, None), currency="MYR", period="month", deadline="2026-11-30", deadline_text="by 30 November 2026"
    )
    email = _ingest(db, user, fake_gmail, FakeExtractor(output), body="A role you may like. Reply if interested.")

    opportunity = db.get(Opportunity, email.opportunity_id)
    assert opportunity.salary_min is None and opportunity.salary_currency is None
    assert opportunity.application_deadline is None and opportunity.deadline_text is None


def test_stated_deadline_is_kept(db, user, gmail_integration, fake_gmail):
    output = extraction_output(deadline="2026-11-30", deadline_text="by 30 November 2026")
    email = _ingest(db, user, fake_gmail, FakeExtractor(output), body="Please apply by 30 November 2026.")
    opportunity = db.get(Opportunity, email.opportunity_id)
    assert opportunity.application_deadline == date(2026, 11, 30)


def test_university_and_certification_emails_never_create_recruitment_records(db, user, gmail_integration, fake_gmail):
    extractor = FakeExtractor()
    _ingest(db, user, fake_gmail, extractor, group="university", sender="Dr Tan <tan@um.edu.my>", subject="Assignment 2")
    _ingest(db, user, fake_gmail, extractor, group="certifications", sender="Pearson VUE <noreply@pearsonvue.com>")

    assert extractor.requests == []
    assert _count(db, Company) == 0 and _count(db, Opportunity) == 0


def test_follow_up_in_the_same_thread_updates_the_opportunity(db, user, gmail_integration, fake_gmail):
    first = _ingest(db, user, fake_gmail, FakeExtractor(), message_id="m1")
    follow_up = gmail_message("m2", subject="Interview invitation")
    follow_up["threadId"] = first.gmail_thread_id
    fake_gmail.deliver(follow_up)
    [email_id] = sync_mailbox(db, user.id, fake_gmail).new_email_ids
    process_email(
        db, email_id, FakeClassifier(ai_output()),
        extractor=FakeExtractor(extraction_output(email_type="interview_invitation")), gmail=fake_gmail,
    )

    assert _count(db, Opportunity) == 1
    opportunity = db.get(Opportunity, first.opportunity_id)
    db.refresh(opportunity)
    assert opportunity.status == OpportunityStatus.INTERVIEW_SCHEDULED
    assert db.get(EmailMessage, email_id).opportunity_id == opportunity.id


def test_same_company_and_title_is_flagged_not_merged(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    first = _ingest(db, user, fake_gmail, FakeExtractor(), subject="Role 1")
    second = _ingest(db, user, fake_gmail, FakeExtractor(), subject="Role again")

    assert first.opportunity_id != second.opportunity_id
    [candidate] = client.get("/api/duplicates").json()
    assert candidate["entity_type"] == "opportunity"
    assert candidate["record_name"] == "Software Engineer at Grab"

    assert client.post(f"/api/duplicates/{candidate['id']}/merge").status_code == 204
    assert _count(db, Opportunity) == 1
    survivor = db.scalar(select(Opportunity))
    emails = client.get(f"/api/opportunities/{survivor.id}").json()["emails"]
    assert len(emails) == 2


def test_similar_company_names_are_flagged(db, user, gmail_integration, fake_gmail):
    _ingest(db, user, fake_gmail, FakeExtractor(extraction_output(employer="Shopee", organization="Shopee")),
            sender="hr@shopee.com")
    _ingest(db, user, fake_gmail, FakeExtractor(extraction_output(employer="Shopee Inc", organization="Shopee Inc")),
            sender="talent@shopee.sg")
    _ingest(db, user, fake_gmail, FakeExtractor(extraction_output(employer="Shoppee", organization="Shoppee")),
            sender="jobs@shoppee.co")

    assert _count(db, Company) == 2  # "Shopee Inc" matches "Shopee" exactly once the suffix is removed
    candidate = db.scalar(select(DuplicateCandidate).where(DuplicateCandidate.entity_type == "company"))
    assert candidate.status == "pending" and candidate.score >= 0.85


def test_agency_recruiter_is_attached_to_the_agency(db, user, gmail_integration, fake_gmail):
    output = extraction_output(employer="Petronas", organization="Hays", agency=True)
    email = _ingest(db, user, fake_gmail, FakeExtractor(output), sender="Lee <lee@hays.com.my>")

    opportunity = db.get(Opportunity, email.opportunity_id)
    assert opportunity.company.name == "Petronas"
    assert opportunity.company.domain is None
    contact = db.scalar(select(RecruiterContact))
    assert contact.company.name == "Hays" and contact.company.company_type == CompanyType.AGENCY


def test_job_alerts_create_no_records(db, user, gmail_integration, fake_gmail):
    email = _ingest(db, user, fake_gmail, FakeExtractor(extraction_output(email_type="job_alert", specific=False)))
    assert _count(db, Opportunity) == 0 and _count(db, Company) == 0
    assert "No specific job opportunity" in email.recruitment_note


def test_unavailable_extraction_is_retried_then_noted(db, user, gmail_integration, fake_gmail):
    fake_gmail.deliver(gmail_message("m1"))
    [email_id] = sync_mailbox(db, user.id, fake_gmail).new_email_ids
    failing = FakeExtractor(error=AIUnavailable("model loading"))
    try:
        process_email(db, email_id, FakeClassifier(), extractor=failing, final_attempt=False, gmail=fake_gmail)
    except AIUnavailable:
        pass
    email = db.get(EmailMessage, email_id)
    db.refresh(email)
    assert email.recruitment_processed_at is None

    process_email(db, email_id, FakeClassifier(), extractor=failing, final_attempt=True, gmail=fake_gmail)
    db.refresh(email)
    assert "temporarily unavailable" in email.recruitment_note


def test_decision_queue_and_confirmed_decline(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    email = _ingest(db, user, fake_gmail, FakeExtractor())
    opportunity_id = str(email.opportunity_id)

    queue = client.get("/api/opportunities", params={"queue": True}).json()
    assert [item["id"] for item in queue["items"]] == [opportunity_id]
    detail = client.get(f"/api/opportunities/{opportunity_id}").json()
    assert detail["missing_information"] == ["salary"]
    assert detail["advice"]["source"] == "ai"

    unconfirmed = client.post(f"/api/opportunities/{opportunity_id}/decision", json={"decision": "decline"})
    assert unconfirmed.status_code == 409
    declined = client.post(
        f"/api/opportunities/{opportunity_id}/decision", json={"decision": "decline", "confirm": True, "notes": "Not now"}
    ).json()
    assert declined["status"] == OpportunityStatus.WITHDRAWN
    assert declined["decisions"][0]["notes"] == "Not now"
    assert client.get("/api/opportunities", params={"queue": True}).json()["total"] == 0


def test_save_for_later_leaves_the_queue_until_revisit(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    email = _ingest(db, user, fake_gmail, FakeExtractor())
    response = client.post(f"/api/opportunities/{email.opportunity_id}/decision", json={"decision": "save_for_later"})
    assert response.json()["next_follow_up_at"] is not None
    assert client.get("/api/opportunities/stats").json()["decision_queue"] == 0


def test_accepting_an_offer_needs_confirmation(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    email = _ingest(db, user, fake_gmail, FakeExtractor(extraction_output(email_type="offer")))
    url = f"/api/opportunities/{email.opportunity_id}"
    assert client.get(url).json()["status"] == OpportunityStatus.OFFER_RECEIVED
    assert client.patch(url, json={"status": "offer_accepted"}).status_code == 409
    assert client.patch(url, json={"status": "offer_accepted", "confirm": True}).json()["status"] == "offer_accepted"


def test_manual_opportunity_from_an_email(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    email = _ingest(db, user, fake_gmail, None)  # no AI configured
    assert "not configured" in email.recruitment_note

    response = client.post(
        "/api/opportunities",
        json={"job_title": "Data Analyst", "company_name": "Grab Sdn Bhd", "from_email_id": str(email.id), "salary_min": 7000},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["company"]["name"] == "Grab Sdn Bhd"
    assert created["recruiter"]["email"] == "aisha@grab.com"
    assert created["advice"]["source"] == "rules"
    assert client.get(f"/api/emails/{email.id}").json()["opportunity"]["job_title"] == "Data Analyst"


def test_correcting_an_email_to_recruitment_extracts_it(client, db, user, gmail_integration, fake_gmail, fake_extractor):
    login_as(client, user)
    email = _ingest(db, user, fake_gmail, fake_extractor, group="other")
    assert email.opportunity_id is None

    client.patch(f"/api/emails/{email.id}/classification", json={"primary_group": "recruitment"})

    db.refresh(email)
    assert email.opportunity_id is not None
    assert len(fake_extractor.requests) == 1


def test_recruitment_records_are_private(client, db, user, gmail_integration, fake_gmail):
    email = _ingest(db, user, fake_gmail, FakeExtractor())
    company = db.scalar(select(Company))
    intruder = make_user("intruder@example.com", "sub-x")
    connect_gmail(intruder)
    login_as(client, intruder)

    assert client.get("/api/opportunities").json()["total"] == 0
    assert client.get(f"/api/opportunities/{email.opportunity_id}").status_code == 404
    assert client.post(f"/api/opportunities/{email.opportunity_id}/decision", json={"decision": "interested"}).status_code == 404
    assert client.get(f"/api/companies/{company.id}").status_code == 404
    assert client.get("/api/companies").json()["total"] == 0
    assert client.get("/api/duplicates").json() == []
