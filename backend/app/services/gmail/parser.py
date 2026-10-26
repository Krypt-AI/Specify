"""Turns Gmail API message resources into plain data. HTML is reduced to text and never stored."""
import base64
import html
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from urllib.parse import urlsplit

MAX_BODY_CHARS = 20_000
MAX_LINK_DOMAINS = 50
STORED_HEADERS = ("message-id", "in-reply-to", "references", "list-id", "list-unsubscribe", "precedence", "auto-submitted")

_CHARSET = re.compile(r'charset="?([\w.:-]+)"?', re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedMessage:
    gmail_message_id: str
    gmail_thread_id: str
    label_ids: list[str]
    received_at: datetime
    sender_name: str
    sender_email: str
    reply_to: str | None
    recipients: list[dict]
    subject: str
    snippet: str
    body_text: str
    body_truncated: bool
    attachments: list[dict]
    headers: dict[str, str]
    link_domains: list[str]


def parse_message(raw: dict) -> ParsedMessage:
    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    reply_to = parseaddr(headers.get("reply-to", ""))[1].lower() or None
    recipients = [
        {"type": kind, "name": name, "email": address.lower()}
        for kind in ("to", "cc")
        for name, address in getaddresses([headers.get(kind, "")])
        if address
    ]
    body, link_domains = _extract_body(payload)
    return ParsedMessage(
        gmail_message_id=raw["id"],
        gmail_thread_id=raw["threadId"],
        label_ids=list(raw.get("labelIds", [])),
        received_at=datetime.fromtimestamp(int(raw.get("internalDate", "0")) / 1000, tz=timezone.utc),
        sender_name=sender_name,
        sender_email=sender_email.lower(),
        reply_to=reply_to if reply_to != sender_email.lower() else None,
        recipients=recipients,
        subject=headers.get("subject", ""),
        snippet=html.unescape(raw.get("snippet", "")),
        body_text=body[:MAX_BODY_CHARS],
        body_truncated=len(body) > MAX_BODY_CHARS,
        attachments=[_attachment(part) for part in _walk(payload) if _is_attachment(part)],
        headers={name: headers[name] for name in STORED_HEADERS if name in headers},
        link_domains=link_domains,
    )


def html_to_text(markup: str) -> tuple[str, list[str]]:
    """Return readable text and the link targets of an HTML document."""
    extractor = _TextExtractor()
    extractor.feed(markup)
    extractor.close()
    return _normalize_whitespace(extractor.text()), extractor.links


def _extract_body(payload: dict) -> tuple[str, list[str]]:
    plain, markup = [], []
    for part in _walk(payload):
        if _is_attachment(part) or not part.get("body", {}).get("data"):
            continue
        if part.get("mimeType") == "text/plain":
            plain.append(_decode(part))
        elif part.get("mimeType") == "text/html":
            markup.append(_decode(part))

    links: list[str] = []
    html_text = ""
    if markup:
        html_text, links = html_to_text("\n".join(markup))
    text = _normalize_whitespace("\n".join(plain)) if plain else html_text
    links += _URL.findall(text)
    return text, _domains(links)


def _walk(part: dict) -> Iterator[dict]:
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk(child)


def _is_attachment(part: dict) -> bool:
    return bool(part.get("filename")) and bool(part.get("body", {}).get("attachmentId"))


def _attachment(part: dict) -> dict:
    return {
        "filename": part["filename"],
        "mime_type": part.get("mimeType", ""),
        "size": part.get("body", {}).get("size", 0),
    }


def _decode(part: dict) -> str:
    data = part["body"]["data"]
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    content_type = next(
        (h["value"] for h in part.get("headers", []) if h["name"].lower() == "content-type"), ""
    )
    match = _CHARSET.search(content_type)
    try:
        return raw.decode(match.group(1) if match else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _domains(urls: list[str]) -> list[str]:
    domains: dict[str, None] = {}
    for url in urls:
        try:
            host = urlsplit(url.strip()).hostname
        except ValueError:
            continue
        if host:
            domains[host.lower().removeprefix("www.")] = None
    return list(domains)[:MAX_LINK_DOMAINS]


def _normalize_whitespace(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class _TextExtractor(HTMLParser):
    _SKIPPED = {"script", "style", "head", "noscript", "template"}
    _BLOCKS = {
        "p", "div", "br", "li", "tr", "table", "section", "article", "header", "footer",
        "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIPPED:
            self._skip_depth += 1
        elif tag in self._BLOCKS:
            self._parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)
