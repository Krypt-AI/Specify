"""In-memory stand-ins for Gmail and the AI classifier. Test-only; never used by the application."""
import base64
import re
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.policy import default as default_policy
from itertools import count

from app.services.classification.ai import AIClassification, ClassificationRequest, KeyDate, LabelChoice
from app.services.gmail.client import GmailConflict, GmailNotFound, HistoryExpired
from app.services.google_api import GoogleNotFound
from app.services.recruitment.extraction import (
    ExtractedCompany,
    ExtractedJob,
    ExtractedRecruiter,
    RecruitmentExtraction,
)

_ids = count(1)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(
    message_id: str | None = None,
    *,
    sender: str = "Aisha Rahman <aisha@grab.com>",
    to: str = "Me <me@example.com>",
    subject: str = "Software Engineer opportunity at Grab",
    body: str = "Hi, we have a Software Engineer role that matches your profile.",
    html: str | None = None,
    labels: tuple[str, ...] = ("INBOX", "UNREAD"),
    internal_date: int = 1_761_480_000_000,
    extra_headers: dict[str, str] | None = None,
    attachments: tuple[tuple[str, str, int], ...] = (),
) -> dict:
    message_id = message_id or f"msg{next(_ids)}"
    headers = {"From": sender, "To": to, "Subject": subject, **(extra_headers or {})}
    parts = [{"mimeType": "text/plain", "headers": [], "body": {"data": _b64(body)}}] if body else []
    if html:
        parts.append({"mimeType": "text/html", "headers": [], "body": {"data": _b64(html)}})
    parts += [
        {"mimeType": mime, "filename": name, "headers": [], "body": {"attachmentId": f"att-{name}", "size": size}}
        for name, mime, size in attachments
    ]
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "labelIds": list(labels),
        "snippet": body[:100],
        "internalDate": str(internal_date),
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": k, "value": v} for k, v in headers.items()],
            "parts": parts,
        },
    }


class FakeGmail:
    def __init__(self) -> None:
        self.messages: dict[str, dict] = {}
        self.history: list[dict] = []
        self.history_id = 1000
        self.history_expired = False
        self.labels: dict[str, dict] = {
            "INBOX": {"id": "INBOX", "name": "INBOX", "type": "system"},
            "UNREAD": {"id": "UNREAD", "name": "UNREAD", "type": "system"},
        }
        self.modifications: list[tuple[str, list[str], list[str]]] = []
        self.renamed: list[tuple[str, str]] = []
        self.drafts: dict[str, dict] = {}
        self.watched_topics: list[str] = []

    def __enter__(self) -> "FakeGmail":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    # Test helpers
    def deliver(self, message: dict) -> str:
        """Add a message as if it just arrived, recording a history entry."""
        self.messages[message["id"]] = message
        self.history_id += 1
        self.history.append(
            {
                "id": str(self.history_id),
                "messagesAdded": [
                    {"message": {"id": message["id"], "threadId": message["threadId"], "labelIds": message["labelIds"]}}
                ],
            }
        )
        return message["id"]

    def mark_read(self, message_id: str) -> None:
        message = self.messages[message_id]
        message["labelIds"] = [label for label in message["labelIds"] if label != "UNREAD"]
        self.history_id += 1
        self.history.append(
            {
                "id": str(self.history_id),
                "labelsRemoved": [{"message": {"id": message_id, "labelIds": message["labelIds"]}, "labelIds": ["UNREAD"]}],
            }
        )

    def label_named(self, name: str) -> dict | None:
        return next((label for label in self.labels.values() if label["name"] == name), None)

    # GmailApi
    def get_profile(self) -> dict:
        return {"emailAddress": "me@example.com", "historyId": str(self.history_id)}

    def list_message_ids(self, query: str, page_token: str | None = None, max_results: int = 100):
        ids = [
            m["id"]
            for m in sorted(self.messages.values(), key=lambda m: int(m["internalDate"]), reverse=True)
            if not {"SENT", "DRAFT"} & set(m["labelIds"])
        ]
        start = int(page_token or 0)
        page = ids[start : start + max_results]
        next_token = str(start + max_results) if start + max_results < len(ids) else None
        return page, next_token

    def get_message(self, message_id: str) -> dict:
        if message_id not in self.messages:
            raise GmailNotFound(message_id)
        return self.messages[message_id]

    def list_history(self, start_history_id: str, page_token: str | None = None) -> dict:
        if self.history_expired:
            raise HistoryExpired("expired")
        records = [r for r in self.history if int(r["id"]) > int(start_history_id)]
        return {"history": records, "historyId": str(self.history_id)}

    def list_labels(self) -> list[dict]:
        return list(self.labels.values())

    def create_label(self, name: str) -> dict:
        if any(label["name"].lower() == name.lower() for label in self.labels.values()):
            raise GmailConflict(name)
        label = {"id": f"Label_{len(self.labels)}", "name": name, "type": "user"}
        self.labels[label["id"]] = label
        return label

    def rename_label(self, label_id: str, name: str) -> dict:
        self.labels[label_id]["name"] = name
        self.renamed.append((label_id, name))
        return self.labels[label_id]

    def modify_message(self, message_id: str, add: list[str], remove: list[str]) -> None:
        self.modifications.append((message_id, add, remove))
        message = self.messages.get(message_id)
        if message:
            message["labelIds"] = [l for l in message["labelIds"] if l not in remove] + [l for l in add if l not in message["labelIds"]]


    def create_draft(self, raw: str, thread_id: str | None) -> dict:
        draft_id = f"draft{len(self.drafts) + 1}"
        self.drafts[draft_id] = {"id": draft_id, "message": {"id": f"m-{draft_id}", "threadId": thread_id, "raw": raw}}
        return self.drafts[draft_id]

    def update_draft(self, draft_id: str, raw: str, thread_id: str | None) -> dict:
        if draft_id not in self.drafts:
            raise GmailNotFound(draft_id)
        self.drafts[draft_id]["message"].update(raw=raw, threadId=thread_id)
        return self.drafts[draft_id]

    def delete_draft(self, draft_id: str) -> None:
        if self.drafts.pop(draft_id, None) is None:
            raise GmailNotFound(draft_id)

    def watch(self, topic: str) -> dict:
        self.watched_topics.append(topic)
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        return {"historyId": str(self.history_id), "expiration": str(int(expires.timestamp() * 1000))}

    def draft_message(self, draft_id: str):
        """The draft as a parsed email message, for assertions."""
        raw = self.drafts[draft_id]["message"]["raw"]
        return message_from_bytes(base64.urlsafe_b64decode(raw), policy=default_policy)


def ai_output(
    group: str = "recruitment",
    *,
    existing_label: str | None = None,
    new_label: str | None = "Grab – Software Engineer",
    confidence: float = 0.95,
    secondary: tuple[str, ...] = (),
    suspicious: bool = False,
    reasons: tuple[str, ...] = (),
    dates: tuple[KeyDate, ...] = (),
) -> AIClassification:
    return AIClassification(
        primary_group=group,
        secondary_groups=list(secondary),
        label=LabelChoice(
            existing_label=existing_label,
            new_label_name=None if existing_label else new_label,
            new_label_description=None if existing_label else "Recruiter messages about Grab engineering roles.",
        ),
        confidence=confidence,
        explanation="A recruiter is offering a role.",
        reply_required=True,
        recommended_action="decide",
        suspicious=suspicious,
        suspicious_reasons=list(reasons),
        organization="Grab",
        key_dates=list(dates),
    )


class FakeClassifier:
    def __init__(self, output: AIClassification | None = None, error: Exception | None = None) -> None:
        self.output = output or ai_output()
        self.error = error
        self.requests: list[ClassificationRequest] = []

    def classify(self, request: ClassificationRequest) -> AIClassification:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.output


def extraction_output(
    *,
    email_type: str = "new_opportunity",
    specific: bool = True,
    employer: str | None = "Grab",
    title: str | None = "Software Engineer",
    reference: str | None = None,
    salary: tuple[float | None, float | None] = (None, None),
    currency: str | None = None,
    period: str | None = None,
    deadline: str | None = None,
    deadline_text: str | None = None,
    organization: str | None = "Grab",
    agency: bool = False,
    description: str | None = "Build backend services for payments.",
) -> RecruitmentExtraction:
    return RecruitmentExtraction(
        email_type=email_type,
        is_specific_opportunity=specific,
        employer=ExtractedCompany(name=employer, website=None, industry=None, country=None, location=None),
        recruiter=ExtractedRecruiter(
            name="Aisha Rahman", email=None, phone=None, role="Talent Partner",
            organization=organization, organization_is_agency=agency,
        ),
        job=ExtractedJob(
            title=title, reference=reference, description=description, employment_type="Full-time",
            work_arrangement="hybrid", location="Kuala Lumpur", salary_min=salary[0], salary_max=salary[1],
            salary_currency=currency, salary_period=period, benefits=[], application_deadline=deadline,
            deadline_text=deadline_text,
        ),
        recommended_decision="request_salary",
        recommendation_explanation="No salary is given; ask for the range.",
    )


class FakeExtractor:
    def __init__(self, output: RecruitmentExtraction | None = None, error: Exception | None = None) -> None:
        self.output = output or extraction_output()
        self.error = error
        self.requests: list = []

    def extract(self, request) -> RecruitmentExtraction:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.output


_RANGE = re.compile(r"^'((?:[^']|'')*)'!([A-Z]+)(\d+)$")


class FakeSheets:
    """An in-memory spreadsheet service mimicking how Google returns values (trailing blanks trimmed)."""

    def __init__(self) -> None:
        self.spreadsheets: dict[str, dict[str, dict]] = {}
        self.fail_with: Exception | None = None
        self._ids = count(1)

    def __enter__(self) -> "FakeSheets":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    # Test helpers
    def add_spreadsheet(self, spreadsheet_id: str, sheets: dict[str, list[list]]) -> None:
        self.spreadsheets[spreadsheet_id] = {t: {"id": next(self._ids), "rows": [list(r) for r in rows]} for t, rows in sheets.items()}

    def rows(self, title: str, spreadsheet_id: str | None = None) -> list[list]:
        book = self.spreadsheets[spreadsheet_id or next(iter(self.spreadsheets))]
        return book[title]["rows"]

    def records(self, title: str, spreadsheet_id: str | None = None) -> dict[str, dict]:
        rows = self.rows(title, spreadsheet_id)
        header = rows[0]
        return {r[0]: dict(zip(header, r + [""] * (len(header) - len(r)))) for r in rows[1:] if r and r[0]}

    def edit(self, title: str, record_id: str, header: str, value) -> None:
        rows = self.rows(title)
        column = rows[0].index(header)
        row = next(r for r in rows[1:] if r and r[0] == record_id)
        row.extend([""] * (column + 1 - len(row)))
        row[column] = value

    def delete_record(self, title: str, record_id: str) -> None:
        rows = self.rows(title)
        rows.remove(next(r for r in rows[1:] if r and r[0] == record_id))

    # SheetsApi
    def get_spreadsheet(self, spreadsheet_id: str) -> dict:
        if self.fail_with:
            raise self.fail_with
        if spreadsheet_id not in self.spreadsheets:
            raise GoogleNotFound(spreadsheet_id)
        return {
            "spreadsheetId": spreadsheet_id,
            "spreadsheetUrl": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
            "properties": {"title": "Tracker"},
            "sheets": [{"properties": {"title": t, "sheetId": s["id"]}} for t, s in self.spreadsheets[spreadsheet_id].items()],
        }

    def create_spreadsheet(self, title: str, sheets: dict[str, list[str]]) -> dict:
        spreadsheet_id = f"created{next(self._ids)}"
        self.add_spreadsheet(spreadsheet_id, {t: [headers] for t, headers in sheets.items()})
        return self.get_spreadsheet(spreadsheet_id)

    def add_sheet(self, spreadsheet_id: str, title: str) -> int:
        sheet = {"id": next(self._ids), "rows": []}
        self.spreadsheets[spreadsheet_id][title] = sheet
        return sheet["id"]

    def read_values(self, spreadsheet_id: str, title: str) -> list[list]:
        rows = [list(r) for r in self.spreadsheets[spreadsheet_id][title]["rows"]]
        for row in rows:
            while row and row[-1] in ("", None):
                row.pop()
        while rows and not rows[-1]:
            rows.pop()
        return rows

    def update_values(self, spreadsheet_id: str, data: list[dict]) -> None:
        for item in data:
            title, letters, number = _RANGE.match(item["range"]).groups()
            rows = self.spreadsheets[spreadsheet_id][title.replace("''", "'")]["rows"]
            column = 0
            for letter in letters:
                column = column * 26 + ord(letter) - 64
            row_index = int(number) - 1
            while len(rows) <= row_index:
                rows.append([])
            for offset, value in enumerate(item["values"][0]):
                row = rows[row_index]
                row.extend([""] * (column + offset - len(row)))
                row[column - 1 + offset] = value

    def append_rows(self, spreadsheet_id: str, title: str, rows: list[list]) -> None:
        self.spreadsheets[spreadsheet_id][title]["rows"].extend([list(r) for r in rows])

    def delete_rows(self, spreadsheet_id: str, sheet_id: int, row_indexes: list[int]) -> None:
        sheet = next(s for s in self.spreadsheets[spreadsheet_id].values() if s["id"] == sheet_id)
        for index in sorted(row_indexes, reverse=True):
            del sheet["rows"][index]


class FakeLLM:
    """A stand-in AI provider: returns prepared answers per output type and records every prompt."""

    def __init__(self, answers: dict | None = None, error: Exception | None = None) -> None:
        self.answers = answers or {}
        self.error = error
        self.calls: list[tuple[list[str], str]] = []

    def structured(self, system, content, output_format):
        self.calls.append((system, content))
        if self.error:
            raise self.error
        return self.answers[output_format.__name__]
