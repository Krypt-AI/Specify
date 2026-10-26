"""Shared plumbing for Google REST APIs: access tokens, one refresh on 401, and typed errors that
separate retryable failures from permanent ones."""
from typing import Self

import httpx

from app.services.google_credentials import IntegrationCredentials

RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"}
SCOPE_REASONS = {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}


class GoogleApiError(Exception):
    """A Google API failure that retrying will not fix."""


class GoogleRetryableError(GoogleApiError):
    """Rate limiting, a Google server error or a network failure; retry with backoff."""


class GoogleNotFound(GoogleApiError):
    pass


class GoogleConflict(GoogleApiError):
    pass


class GoogleApiClient:
    service_name = "Google"

    def __init__(self, credentials: IntegrationCredentials, base_url: str, http: httpx.Client | None = None):
        self._credentials = credentials
        self._http = http or httpx.Client(base_url=base_url, timeout=30)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in (1, 2):
            token = self._credentials.access_token(force_refresh=attempt == 2)
            try:
                response = self._http.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
            except httpx.HTTPError as exc:
                raise GoogleRetryableError(f"{self.service_name} request failed ({exc.__class__.__name__}).") from exc
            if response.status_code == 401 and attempt == 1:
                continue  # the token may have been revoked early; refresh once and retry
            return self._parse(response)
        raise AssertionError("unreachable")

    def _parse(self, response: httpx.Response) -> dict:
        if response.is_success:
            return response.json() if response.content else {}
        status = response.status_code
        reasons = _error_reasons(response)
        name = self.service_name
        if status == 401:
            self._credentials.reject(f"Google rejected Specify's {name} access. Please reconnect {name}.")
        if status == 403 and reasons & SCOPE_REASONS:
            self._credentials.reject(f"Specify needs updated {name} permissions. Please reconnect {name}.")
        if status == 429 or status >= 500 or (status == 403 and reasons & RATE_LIMIT_REASONS):
            raise GoogleRetryableError(f"{name} is temporarily unavailable (HTTP {status}).")
        if status == 404:
            raise GoogleNotFound(f"{name} resource not found.")
        if status == 409:
            raise GoogleConflict(f"{name} reported a conflict.")
        if status == 403:
            raise GoogleApiError(f"{name} denied access (HTTP 403). Check that your account can open it.")
        raise GoogleApiError(f"{name} request failed (HTTP {status}).")


def _error_reasons(response: httpx.Response) -> set[str]:
    try:
        error = response.json().get("error", {})
    except ValueError:
        return set()
    if not isinstance(error, dict):
        return set()
    reasons = {item.get("reason", "") for item in error.get("errors", [])}
    reasons |= {item.get("reason", "") for item in error.get("details", []) if isinstance(item, dict)}
    return reasons - {""}
