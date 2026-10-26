from sqlalchemy import select

from app.models import ClassificationFeedback, EmailMessage, Label, ProcessingStatus
from app.services.classification.pipeline import process_email
from app.services.gmail.sync import sync_mailbox
from tests.conftest import connect_gmail, login_as, make_user
from tests.fakes import FakeClassifier, ai_output, gmail_message


def _ingest(db, user, fake_gmail, classifier, **message) -> EmailMessage:
    fake_gmail.deliver(gmail_message(**message))
    [email_id] = sync_mailbox(db, user.id, fake_gmail).new_email_ids
    process_email(db, email_id, classifier, gmail=fake_gmail)
    return db.get(EmailMessage, email_id)


def test_folders_include_secondary_groups(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    _ingest(db, user, fake_gmail, FakeClassifier(ai_output("recruitment")), subject="Grab role")
    _ingest(
        db, user, fake_gmail,
        FakeClassifier(ai_output("university", secondary=("recruitment",), new_label="UM Internships")),
        subject="Internship fair",
    )
    _ingest(db, user, fake_gmail, FakeClassifier(ai_output("other", new_label="Newsletters")), subject="Weekly digest")

    recruitment = client.get("/api/emails", params={"folder": "recruitment"}).json()
    assert {item["subject"] for item in recruitment["items"]} == {"Grab role", "Internship fair"}
    university = client.get("/api/emails", params={"folder": "university"}).json()
    assert [item["subject"] for item in university["items"]] == ["Internship fair"]
    assert client.get("/api/emails", params={"q": "digest"}).json()["total"] == 1
    assert client.get("/api/emails", params={"q": "100%"}).json()["total"] == 0


def test_review_queue_and_pagination(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    for index in range(3):
        _ingest(db, user, fake_gmail, FakeClassifier(ai_output(confidence=0.4)), subject=f"Unclear {index}")

    page = client.get("/api/emails", params={"status": "review_required", "page_size": 2}).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["items"][0]["label_suggestion"]["name"] == "Grab – Software Engineer"


def test_correction_records_feedback_and_relabels_in_gmail(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    email = _ingest(db, user, fake_gmail, FakeClassifier(ai_output(confidence=0.4)))

    response = client.patch(
        f"/api/emails/{email.id}/classification",
        json={"primary_group": "recruitment", "new_label_name": "Grab Careers"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["processing_status"] == ProcessingStatus.CLASSIFIED
    assert body["label"]["name"] == "Grab Careers"
    assert body["classification_source"] == "user"
    careers = fake_gmail.label_named("Specify/Grab Careers")
    review = fake_gmail.label_named("Specify/Needs Review")
    assert fake_gmail.modifications[-1] == (email.gmail_message_id, [careers["id"]], [review["id"]])
    feedback = db.scalar(select(ClassificationFeedback))
    assert feedback.corrected_group == "recruitment"
    assert feedback.sender_domain == "grab.com"


def test_rule_suggested_after_repeated_corrections(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    for index in range(2):
        email = _ingest(db, user, fake_gmail, FakeClassifier(ai_output("other", new_label=f"Misc {index}")))
        client.patch(f"/api/emails/{email.id}/classification", json={"primary_group": "recruitment"})

    [suggestion] = client.get("/api/rules/suggestions").json()
    assert suggestion["rule"]["conditions"]["sender_emails"] == ["aisha@grab.com"]
    assert suggestion["rule"]["target_group"] == "recruitment"

    assert client.post("/api/rules", json=suggestion["rule"]).status_code == 201
    assert client.get("/api/rules/suggestions").json() == []


def test_rules_require_a_condition(client, user):
    login_as(client, user)
    response = client.post(
        "/api/rules", json={"name": "Empty", "conditions": {}, "target_group": "recruitment"}
    )
    assert response.status_code == 422


def test_stats_count_real_data(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    _ingest(db, user, fake_gmail, FakeClassifier(ai_output("recruitment")))
    _ingest(db, user, fake_gmail, FakeClassifier(ai_output("certifications", new_label="AWS Exam", confidence=0.3)))

    stats = client.get("/api/emails/stats").json()
    assert stats["total"] == 2
    assert stats["needs_review"] == 1
    assert stats["by_group"] == {"recruitment": 1, "university": 0, "certifications": 1, "other": 0}


def test_label_rename_is_mirrored_in_gmail(client, db, user, gmail_integration, fake_gmail):
    login_as(client, user)
    email = _ingest(db, user, fake_gmail, FakeClassifier())

    labels = client.get("/api/labels").json()
    [context] = [label for label in labels if label["system_key"] is None]
    assert context["email_count"] == 1

    response = client.patch(f"/api/labels/{context['id']}", json={"name": "Grab Engineering"})
    assert response.status_code == 200
    assert fake_gmail.renamed[-1][1] == "Specify/Grab Engineering"
    db.expire_all()  # the API changed the label in its own session
    assert db.get(Label, email.label_id).name == "Grab Engineering"

    duplicate = client.post("/api/labels", json={"name": "Grab engineering"})
    assert duplicate.status_code == 409


def test_users_cannot_see_each_others_emails(client, db, user, gmail_integration, fake_gmail):
    email = _ingest(db, user, fake_gmail, FakeClassifier())
    intruder = make_user("intruder@example.com", "sub-x")
    connect_gmail(intruder)
    login_as(client, intruder)

    assert client.get("/api/emails").json()["total"] == 0
    assert client.get(f"/api/emails/{email.id}").status_code == 404
    patch = client.patch(f"/api/emails/{email.id}/classification", json={"primary_group": "other"})
    assert patch.status_code == 404
    assert client.get("/api/labels").json() == []


def test_manual_sync_requires_gmail(client, user):
    login_as(client, user)
    assert client.post("/api/sync/gmail").status_code == 409
    assert client.get("/api/sync/gmail").json()["connected"] is False


def test_manual_sync_runs_pipeline(client, db, user, gmail_integration, fake_gmail, fake_classifier):
    login_as(client, user)
    fake_gmail.deliver(gmail_message("fresh"))

    assert client.post("/api/sync/gmail").status_code == 202

    email = db.scalar(select(EmailMessage).where(EmailMessage.gmail_message_id == "fresh"))
    assert email.processing_status == ProcessingStatus.CLASSIFIED
    assert client.get("/api/sync/gmail").json()["queued_emails"] == 0
