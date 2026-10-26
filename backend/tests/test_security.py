"""Phase 8 hardening: every endpoint requires a session, headers, CSRF origin check, errors, logs."""
import logging
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import account
from app.core.config import get_settings
from app.core.logging import RedactingFilter, redact
from app.main import app
from tests.conftest import login_as

# Endpoints that work without a session, and why.
PUBLIC_ENDPOINTS = {
    ("GET", "/health"),  # liveness probe
    ("GET", "/api/auth/google/start"),  # starts sign-in (integrations still check the session)
    ("GET", "/api/auth/google/callback"),  # finishes sign-in; protected by the signed state cookie
    ("POST", "/api/auth/logout"),  # only clears the cookie
    ("POST", "/api/webhooks/gmail"),  # authenticated by Google's signed token instead
}


def _api_routes() -> list[tuple[str, str]]:
    """Every operation the app serves, read from its OpenAPI schema (no endpoint is hidden from it)."""
    return sorted((method.upper(), path) for path, operations in app.openapi()["paths"].items() for method in operations)


def test_the_audit_sees_every_router():
    paths = {path for _, path in _api_routes()}
    assert {"/api/emails", "/api/workflows", "/api/account/export", "/api/webhooks/gmail"} <= paths


@pytest.mark.parametrize(("method", "path"), [r for r in _api_routes() if r not in PUBLIC_ENDPOINTS])
def test_every_endpoint_requires_a_session(client, method, path):
    url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
    response = client.request(method, url, json={})
    assert response.status_code == 401, f"{method} {path} answered {response.status_code} without a session"


def test_public_endpoint_list_matches_the_app():
    assert PUBLIC_ENDPOINTS <= set(_api_routes())


def test_responses_carry_security_headers_and_a_request_id(client, user):
    login_as(client, user)
    response = client.get("/api/auth/me")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert response.headers["Cache-Control"] == "no-store"
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])

    echoed = client.get("/health", headers={"X-Request-ID": "trace-1234abcd"})
    assert echoed.headers["X-Request-ID"] == "trace-1234abcd"
    rejected = client.get("/health", headers={"X-Request-ID": "bad id\r\nSet-Cookie: x"})
    assert rejected.headers["X-Request-ID"] != "bad id\r\nSet-Cookie: x"


def test_cross_site_writes_are_blocked(client, user):
    login_as(client, user)
    blocked = client.put("/api/settings", json={"preferences": {}}, headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403

    same_site = client.put("/api/settings", json={"preferences": {}}, headers={"Origin": get_settings().frontend_url})
    assert same_site.status_code == 200
    # Reads are never blocked, and clients that send no Origin cannot carry a browser's cookie.
    assert client.get("/api/auth/me", headers={"Origin": "https://evil.example"}).status_code == 200


def test_unexpected_errors_reveal_nothing_but_a_request_id(user, monkeypatch):
    def explode(db, user):
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr(account, "export_user_data", explode)
    client = TestClient(app, raise_server_exceptions=False)
    login_as(client, user)
    response = client.get("/api/account/export")
    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer ya29.a0AfH6SMBx-secret",
        "token ya29.a0AfH6SMBx-secret expired",
        "refresh 1//0gLx-secret failed",
        "key sk-ant-api03-secret",
        "GET /api/auth/google/callback?code=4/0secret&state=abc123",
        '{"access_token": "secret-value", "expires_in": 3599}',
    ],
)
def test_secrets_are_redacted_from_logs(secret):
    assert "secret" not in redact(secret).replace("[redacted]", "")


def test_log_filter_redacts_arguments_and_tracebacks():
    try:
        raise ValueError("refresh with 1//0gLx-secret failed")
    except ValueError:
        import sys

        record = logging.LogRecord("app", logging.ERROR, __file__, 1, "token %s", ("ya29.secret",), sys.exc_info())
    RedactingFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert "secret" not in record.exc_text
    assert record.request_id == "-"
