from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.models import EmailMessage, FollowUpStatus, FollowUpTask, Notification, User
from app.services.classification.ai import KeyDate
from app.services.dates import ground_dates
from app.services.reminders import notify_due_reminders
from tests.conftest import connect_gmail, login_as, make_user
from tests.fakes import FakeExtractor, ai_output, extraction_output, gmail_message

NEXT_YEAR = utcnow().year + 1


@pytest.fixture
def auto(client, user, gmail_integration, fake_gmail, fake_classifier, fake_extractor):
    login_as(client, user)
    return client


def _deliver(client, fake_gmail, **message):
    fake_gmail.deliver(gmail_message(**message))
    client.post("/api/sync/gmail")


def test_stated_dates_become_reminders_by_the_rules(auto, db, fake_gmail, fake_classifier):
    wording = f"15 December {NEXT_YEAR}"
    fake_classifier.output = ai_output(
        "certifications", new_label="AWS Exam",
        dates=(KeyDate(kind="exam", text=wording, date=f"{NEXT_YEAR}-12-15", time="09:30"),),
    )
    _deliver(auto, fake_gmail, subject="Exam booked", body=f"Your exam is on {wording} at 09:30.")

    task = db.scalar(select(FollowUpTask))
    assert task.kind == "exam" and task.source == "email"
    assert task.due_at.date().isoformat() == f"{NEXT_YEAR}-12-12"  # three days before, by default
    assert db.scalar(select(EmailMessage)).extracted_data["dates"][0]["ambiguous"] is False


def test_unclear_dates_are_flagged_not_guessed(auto, db, fake_gmail, fake_classifier):
    fake_classifier.output = ai_output(
        "university", new_label="CS301",
        dates=(
            KeyDate(kind="deadline", text=f"03/04/{NEXT_YEAR}", date=f"{NEXT_YEAR}-04-03", time=None),
            KeyDate(kind="deadline", text="next Friday", date=None, time=None),
            KeyDate(kind="exam", text="1 May 2099", date="2099-05-01", time=None),  # not in the email
        ),
    )
    _deliver(auto, fake_gmail, subject="Assignment", body=f"Submit by 03/04/{NEXT_YEAR}, or next Friday at the latest.")

    dates = db.scalar(select(EmailMessage)).extracted_data["dates"]
    assert [d["ambiguous"] for d in dates] == [True, True]
    assert db.scalar(select(FollowUpTask)) is None
    assert db.scalar(select(Notification).where(Notification.kind == "date_check")) is not None


def test_reminder_rules_can_be_switched_off(auto, db, fake_gmail, fake_classifier):
    auto.put("/api/settings", json={"preferences": {"reminders": {"exams": False}}})
    fake_classifier.output = ai_output("certifications", dates=(KeyDate(kind="exam", text=f"1 June {NEXT_YEAR}", date=f"{NEXT_YEAR}-06-01", time=None),))
    _deliver(auto, fake_gmail, body=f"Exam on 1 June {NEXT_YEAR}.")
    assert db.scalar(select(FollowUpTask)) is None


def test_decisions_schedule_follow_ups_that_replies_close(auto, db, fake_gmail):
    _deliver(auto, fake_gmail, message_id="first")
    email = db.scalar(select(EmailMessage))
    auto.post(f"/api/opportunities/{email.opportunity_id}/decision", json={"decision": "request_salary"})
    task = db.scalar(select(FollowUpTask).where(FollowUpTask.kind == "recruiter"))
    assert task.status == FollowUpStatus.OPEN and "Aisha Rahman" in task.title

    reply = gmail_message("second", subject="Re: salary")
    reply["threadId"] = email.gmail_thread_id
    fake_extractor_reply = FakeExtractor(extraction_output(email_type="follow_up"))
    from app.services.recruitment import extraction

    extraction.get_extractor = lambda: fake_extractor_reply  # restored by the fixture's monkeypatch
    fake_gmail.deliver(reply)
    auto.post("/api/sync/gmail")

    db.refresh(task)
    assert task.status == FollowUpStatus.DONE


def test_saving_for_later_brings_it_back(auto, db, fake_gmail):
    _deliver(auto, fake_gmail)
    email = db.scalar(select(EmailMessage))
    auto.post(f"/api/opportunities/{email.opportunity_id}/decision", json={"decision": "save_for_later"})
    task = db.scalar(select(FollowUpTask))
    assert task.kind == "decision" and task.due_at > utcnow() + timedelta(days=6)


def test_due_reminders_notify_once(auto, db):
    user = db.scalar(select(User))
    task = FollowUpTask(user_id=user.id, title="Call Grab", due_at=utcnow() - timedelta(minutes=5))
    db.add(task)
    db.commit()

    assert notify_due_reminders(db) == 1
    assert notify_due_reminders(db) == 0
    notifications = auto.get("/api/notifications").json()
    assert notifications["unread"] == 1 and notifications["items"][0]["title"] == "Reminder: Call Grab"

    auto.post("/api/notifications/read-all")
    assert auto.get("/api/notifications").json()["unread"] == 0


def test_follow_up_lifecycle(auto, db):
    due = (utcnow() - timedelta(hours=1)).isoformat()
    created = auto.post("/api/follow-ups", json={"title": "Email the recruiter", "due_at": due}).json()
    assert created["overdue"] is True

    later = (utcnow() + timedelta(days=2)).isoformat()
    snoozed = auto.post(f"/api/follow-ups/{created['id']}/snooze", json={"until": later}).json()
    assert snoozed["overdue"] is False and snoozed["snoozed_until"]

    done = auto.post(f"/api/follow-ups/{created['id']}/complete").json()
    assert done["status"] == "done"
    assert auto.get("/api/follow-ups").json() == []
    assert len(auto.get("/api/follow-ups", params={"status": "done"}).json()) == 1
    assert auto.post("/api/follow-ups", json={"title": "x", "due_at": "2026-01-01T09:00:00"}).status_code == 422  # no timezone


def test_analytics_use_real_data(auto, db, fake_gmail):
    _deliver(auto, fake_gmail, internal_date=int(utcnow().timestamp() * 1000))
    email = db.scalar(select(EmailMessage))
    auto.post(f"/api/opportunities/{email.opportunity_id}/decision", json={"decision": "interested"})

    data = auto.get("/api/analytics").json()
    assert data["emails_by_group"]["recruitment"] == 1
    assert data["opportunities_by_status"] == {"interested": 1}
    assert data["decisions_by_outcome"] == {"interested": 1}
    assert sum(w["recruitment_emails"] for w in data["activity_by_week"]) == 1
    assert data["workflow_runs"].get("completed") == 1

    summary = auto.get("/api/analytics/summary").json()
    assert summary["drafts_ready"] == 1 and summary["workflows_failed"] == 0


def test_numeric_dates_with_swappable_day_and_month_are_ambiguous():
    received = utcnow()
    dates = ground_dates(
        "Due 25/04/2026 and 03/04/2026",
        received,
        [KeyDate(kind="deadline", text="25/04/2026", date="2026-04-25", time=None),
         KeyDate(kind="deadline", text="03/04/2026", date="2026-04-03", time=None)],
    )
    assert [d["ambiguous"] for d in dates] == [False, True]


def test_reminders_are_private(auto, db):
    created = auto.post("/api/follow-ups", json={"title": "Mine", "due_at": utcnow().isoformat()}).json()
    intruder = make_user("intruder@example.com", "sub-x")
    connect_gmail(intruder)
    login_as(auto, intruder)
    assert auto.get("/api/follow-ups").json() == []
    assert auto.post(f"/api/follow-ups/{created['id']}/complete").status_code == 404
    assert auto.get("/api/notifications").json()["items"] == []
    assert auto.get("/api/analytics").json()["opportunities_by_status"] == {}
