"""Row-level security: the policy script covers every table, and PostgreSQL enforces it.

The enforcement test needs a disposable PostgreSQL database, given as the schema owner:
  TEST_POSTGRES_URL=postgresql+psycopg://mailup:mailup@localhost:5432/specify_rls_test
"""
import os
import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.rls import SCRIPT, apply_row_level_security
from app.models import EmailMessage, User

APP_ROLE_PASSWORD = "rls-test-password"


def test_policy_script_covers_every_table():
    script = SCRIPT.read_text(encoding="utf-8")
    owned = set(re.findall(r"'(\w+)'", script.split("FOREACH owned_table IN ARRAY ARRAY[")[1].split("]")[0]))
    children = set(re.findall(r"\('(\w+)', '\w+', '\w+'\)", script))

    for table in Base.metadata.sorted_tables:
        if table.name == "users":
            continue
        if "user_id" in table.columns:
            assert table.name in owned, f"{table.name} has user_id but no policy"
        else:
            assert table.name in children, f"{table.name} has no user_id and no parent policy"
    assert owned.isdisjoint(children)


@pytest.fixture
def postgres():
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL is not set")
    owner = create_engine(url)
    Base.metadata.drop_all(owner)
    Base.metadata.create_all(owner)
    apply_row_level_security(owner, APP_ROLE_PASSWORD)
    app_url = make_url(url).set(username="specify_app", password=APP_ROLE_PASSWORD)
    restricted = create_engine(app_url)
    yield owner, restricted
    restricted.dispose()
    Base.metadata.drop_all(owner)
    owner.dispose()


def _seed(owner) -> tuple[str, str]:
    with Session(owner) as db:
        alice = User(email="alice@example.com", google_sub="alice")
        bob = User(email="bob@example.com", google_sub="bob")
        db.add_all([alice, bob])
        db.flush()
        for user in (alice, bob):
            db.add(_email(user.id, f"m-{user.google_sub}"))
        db.commit()
        return str(alice.id), str(bob.id)


def _email(user_id, gmail_id: str) -> EmailMessage:
    return EmailMessage(
        user_id=user_id,
        gmail_message_id=gmail_id,
        gmail_thread_id="t",
        gmail_thread_url="https://mail.google.com/mail/u/0/#all/t",
        sender_email="sender@example.com",
        received_at=datetime.now(UTC),
    )


def _session_for(engine, user_id: str | None) -> Session:
    session = sessionmaker(bind=engine)()
    if user_id:
        session.info["rls_user_id"] = user_id
    return session


def test_restricted_role_only_sees_the_signed_in_users_rows(postgres):
    owner, restricted = postgres
    alice_id, bob_id = _seed(owner)

    with _session_for(restricted, alice_id) as db:
        assert [str(u.id) for u in db.scalars(select(User))] == [alice_id]
        assert [str(e.user_id) for e in db.scalars(select(EmailMessage))] == [alice_id]

    # A new transaction in the same session is scoped again, not left over from the last one.
    with _session_for(restricted, alice_id) as db:
        db.commit()
        assert db.scalar(select(func.count()).select_from(EmailMessage)) == 1

    with _session_for(restricted, None) as db:
        assert db.scalar(select(func.count()).select_from(EmailMessage)) == 0


def test_restricted_role_cannot_write_another_users_rows(postgres):
    owner, restricted = postgres
    alice_id, bob_id = _seed(owner)

    with _session_for(restricted, alice_id) as db:
        db.add(_email(bob_id, "planted"))
        with pytest.raises(ProgrammingError, match="row-level security"):
            db.commit()

    with _session_for(restricted, alice_id) as db:
        bob_email = db.scalar(select(EmailMessage).where(EmailMessage.user_id == bob_id))
        assert bob_email is None  # invisible, so it cannot be updated or deleted either
