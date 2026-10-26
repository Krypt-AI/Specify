"""Logging for the API and workers: one format, the request id, and secrets redacted.

Tokens can reach a log line through an exception message or a logged URL (the OAuth callback
carries the authorization code). Every handler gets RedactingFilter, so they never reach logs.
"""
import logging
import re
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

REDACTED = "[redacted]"
_PATTERNS = [
    (re.compile(r"(?i)\bBearer\s+[\w.~+/-]+=*"), f"Bearer {REDACTED}"),
    (re.compile(r"\bya29\.[\w.-]+"), REDACTED),  # Google access tokens
    (re.compile(r"\b1//[\w.-]+"), REDACTED),  # Google refresh tokens
    (re.compile(r"\bsk-ant-[\w-]+"), REDACTED),  # Anthropic API keys
    (
        re.compile(r"(?i)\b(access_token|refresh_token|id_token|client_secret|code|state)=[^&\s\"']+"),
        rf"\1={REDACTED}",
    ),
    (
        re.compile(r"(?i)([\"'](?:access_token|refresh_token|id_token|client_secret)[\"']\s*:\s*[\"'])[^\"']+"),
        rf"\1{REDACTED}",
    ),
]
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Redacts secrets from the message and traceback, and adds the current request id."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        record.msg, record.args = redact(record.getMessage()), None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def install_redaction(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())


def configure_logging(level: int = logging.INFO) -> None:
    """Give the root logger a handler (if none) and redact on it and on the server's own loggers."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
        root.setLevel(level)
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        install_redaction(logging.getLogger(name))
