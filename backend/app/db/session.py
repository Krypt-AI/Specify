"""Database engines and sessions.

- SessionLocal uses DATABASE_URL (the schema owner). Background work, migrations, sign-in and
  webhooks use it, because they act for the system rather than for one signed-in user.
- Requests from a signed-in user use REQUEST_DATABASE_URL when it is set: a restricted role whose
  PostgreSQL row-level security policies (sql/row_level_security.sql) only reveal that user's
  rows. The user's id is set for every transaction in app.current_user_id. Without it, requests
  use the owner role and isolation rests on the application's own per-user queries.
"""
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.security import decode_signed_token

SESSION_COOKIE = "specify_session"
RLS_SETTING = "app.current_user_id"


def _build_engine(url: str):
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    # SQLite is for tests and local experiments only; in-memory databases need one shared connection.
    in_memory = url in ("sqlite://", "sqlite:///:memory:")
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if in_memory else None,
    )
    # Enforce foreign keys (and their ON DELETE rules) as PostgreSQL does.
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    return engine


_settings = get_settings()
engine = _build_engine(_settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
request_engine = _build_engine(_settings.request_database_url) if _settings.request_database_url else engine
RequestSession = sessionmaker(bind=request_engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def _scope_transaction_to_user(session: Session, transaction, connection) -> None:
    """Tell PostgreSQL whose rows this transaction may see (row-level security)."""
    user_id = session.info.get("rls_user_id")
    if user_id and connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config(:name, :value, true)"), {"name": RLS_SETTING, "value": user_id})


def get_db(request: Request) -> Iterator[Session]:
    """A session for a request, limited to the signed-in user's rows where RLS is configured."""
    with RequestSession() as session:
        claims = decode_signed_token(request.cookies.get(SESSION_COOKIE, ""))
        if claims and claims.get("typ") == "session":
            session.info["rls_user_id"] = claims["sub"]
        yield session


def get_system_db() -> Iterator[Session]:
    """A session acting for the system: sign-in (no user yet) and verified webhooks."""
    with SessionLocal() as session:
        yield session
