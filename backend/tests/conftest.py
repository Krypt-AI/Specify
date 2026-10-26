import os
from datetime import timedelta

from cryptography.fernet import Fernet

# Tests use in-memory SQLite. To run them on PostgreSQL with row-level security, set
# TEST_DATABASE_URL (schema owner) and TEST_REQUEST_DATABASE_URL (the specify_app role).
os.environ.update(
    SESSION_SECRET="test-session-secret-that-is-long-enough-for-hs256",
    TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", "sqlite://"),
    REQUEST_DATABASE_URL=os.environ.get("TEST_REQUEST_DATABASE_URL", ""),
    GOOGLE_CLIENT_ID="test-client",
    GOOGLE_CLIENT_SECRET="test-secret",
    ANTHROPIC_API_KEY="",
    AI_PROVIDER="none",
    CELERY_TASK_ALWAYS_EAGER="true",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import SESSION_COOKIE  # noqa: E402
from app.core.security import create_signed_token, encrypt_secret  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.db.base import Base, utcnow  # noqa: E402
from app.db.rls import apply_row_level_security  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Integration, User  # noqa: E402
from app.services.classification import ai  # noqa: E402
from app.services.gmail import client as gmail_client  # noqa: E402
from app.services.google_oauth import PURPOSES  # noqa: E402
from app.services.recruitment import extraction  # noqa: E402
from app.services.sheets import client as sheets_client  # noqa: E402
from tests.fakes import FakeClassifier, FakeExtractor, FakeGmail, FakeSheets  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(db_session.engine)
    if db_session.request_engine is not db_session.engine:
        apply_row_level_security(db_session.engine)
    yield
    Base.metadata.drop_all(db_session.engine)


@pytest.fixture
def db():
    with db_session.SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_gmail(monkeypatch) -> FakeGmail:
    gmail = FakeGmail()
    monkeypatch.setattr(gmail_client, "gmail_client_for", lambda db, integration: gmail)
    return gmail


@pytest.fixture
def fake_sheets(monkeypatch) -> FakeSheets:
    sheets = FakeSheets()
    monkeypatch.setattr(sheets_client, "sheets_client_for", lambda db, integration: sheets)
    return sheets


@pytest.fixture
def fake_classifier(monkeypatch) -> FakeClassifier:
    classifier = FakeClassifier()
    monkeypatch.setattr(ai, "get_classifier", lambda: classifier)
    return classifier


@pytest.fixture
def fake_extractor(monkeypatch) -> FakeExtractor:
    extractor = FakeExtractor()
    monkeypatch.setattr(extraction, "get_extractor", lambda: extractor)
    return extractor


@pytest.fixture
def user() -> User:
    return make_user("me@example.com", "sub-me")


@pytest.fixture
def gmail_integration(user) -> Integration:
    return connect_gmail(user)


@pytest.fixture
def sheets_integration(user) -> Integration:
    return connect_integration(user, "sheets")


def make_user(email: str, sub: str) -> User:
    with db_session.SessionLocal() as db:
        user = User(email=email, name=email.split("@")[0], google_sub=sub)
        db.add(user)
        db.commit()
        return user


def connect_gmail(user: User) -> Integration:
    return connect_integration(user, "gmail")


def connect_integration(user: User, provider: str) -> Integration:
    with db_session.SessionLocal() as db:
        integration = Integration(
            user_id=user.id,
            provider=provider,
            scopes=list(PURPOSES[provider].scopes),
            access_token_enc=encrypt_secret("access-token"),
            refresh_token_enc=encrypt_secret("refresh-token"),
            token_expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(integration)
        db.commit()
        return integration


def login_as(client: TestClient, user: User) -> None:
    client.cookies.set(
        SESSION_COOKIE,
        create_signed_token({"typ": "session", "sub": str(user.id)}, timedelta(hours=1)),
    )
