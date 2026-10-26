"""Thin Gmail REST client. Errors are typed so callers can tell retryable failures apart."""
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.models import Integration
from app.services.google_api import (
    GoogleApiClient,
    GoogleApiError,
    GoogleConflict,
    GoogleNotFound,
    GoogleRetryableError,
)
from app.services.google_credentials import IntegrationCredentials

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
HISTORY_TYPES = ["messageAdded", "labelAdded", "labelRemoved"]

# Gmail-flavoured names for the shared Google API errors.
GmailError = GoogleApiError
GmailRetryableError = GoogleRetryableError
GmailNotFound = GoogleNotFound
GmailConflict = GoogleConflict


class HistoryExpired(GoogleApiError):
    """The stored history cursor is too old; the mailbox must be resynchronized."""


class GmailApi(Protocol):
    def get_profile(self) -> dict: ...
    def list_message_ids(
        self, query: str, page_token: str | None = None, max_results: int = 100
    ) -> tuple[list[str], str | None]: ...
    def get_message(self, message_id: str) -> dict: ...
    def list_history(self, start_history_id: str, page_token: str | None = None) -> dict: ...
    def list_labels(self) -> list[dict]: ...
    def create_label(self, name: str) -> dict: ...
    def rename_label(self, label_id: str, name: str) -> dict: ...
    def modify_message(self, message_id: str, add: list[str], remove: list[str]) -> None: ...
    def create_draft(self, raw: str, thread_id: str | None) -> dict: ...
    def update_draft(self, draft_id: str, raw: str, thread_id: str | None) -> dict: ...
    def delete_draft(self, draft_id: str) -> None: ...
    def watch(self, topic: str) -> dict: ...


class GmailClient(GoogleApiClient):
    service_name = "Gmail"

    def __init__(self, credentials: IntegrationCredentials, http: httpx.Client | None = None):
        super().__init__(credentials, GMAIL_API, http)

    def get_profile(self) -> dict:
        return self._request("GET", "/profile")

    def list_message_ids(
        self, query: str, page_token: str | None = None, max_results: int = 100
    ) -> tuple[list[str], str | None]:
        params = {"q": query, "maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        data = self._request("GET", "/messages", params=params)
        return [m["id"] for m in data.get("messages", [])], data.get("nextPageToken")

    def get_message(self, message_id: str) -> dict:
        return self._request("GET", f"/messages/{message_id}", params={"format": "full"})

    def list_history(self, start_history_id: str, page_token: str | None = None) -> dict:
        params = {"startHistoryId": start_history_id, "historyTypes": HISTORY_TYPES, "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token
        try:
            return self._request("GET", "/history", params=params)
        except GmailNotFound as exc:
            raise HistoryExpired("The Gmail history cursor has expired.") from exc

    def list_labels(self) -> list[dict]:
        return self._request("GET", "/labels").get("labels", [])

    def create_label(self, name: str) -> dict:
        body = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
        return self._request("POST", "/labels", json=body)

    def rename_label(self, label_id: str, name: str) -> dict:
        return self._request("PATCH", f"/labels/{label_id}", json={"name": name})

    def modify_message(self, message_id: str, add: list[str], remove: list[str]) -> None:
        body = {"addLabelIds": add, "removeLabelIds": remove}
        self._request("POST", f"/messages/{message_id}/modify", json=body)

    def create_draft(self, raw: str, thread_id: str | None) -> dict:
        return self._request("POST", "/drafts", json={"message": _draft_message(raw, thread_id)})

    def update_draft(self, draft_id: str, raw: str, thread_id: str | None) -> dict:
        return self._request("PUT", f"/drafts/{draft_id}", json={"id": draft_id, "message": _draft_message(raw, thread_id)})

    def delete_draft(self, draft_id: str) -> None:
        self._request("DELETE", f"/drafts/{draft_id}")

    def watch(self, topic: str) -> dict:
        """Ask Gmail to publish mailbox changes to a Pub/Sub topic; returns the expiration (ms)."""
        return self._request("POST", "/watch", json={"topicName": topic, "labelFilterBehavior": "exclude", "labelIds": ["SPAM", "TRASH"]})


def _draft_message(raw: str, thread_id: str | None) -> dict:
    return {"raw": raw, "threadId": thread_id} if thread_id else {"raw": raw}


def gmail_client_for(db: Session, integration: Integration) -> GmailClient:
    """Factory used by sync and labeling; tests replace it with an in-memory fake."""
    return GmailClient(IntegrationCredentials(db, integration))
