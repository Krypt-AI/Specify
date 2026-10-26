"""Checks that extracted values are actually present in the email. Anything unsupported is dropped,
so the records never carry invented salaries, deadlines or websites."""
import re
from datetime import date, datetime
from urllib.parse import urlsplit

_NUMBER = re.compile(r"(\d{1,3}(?:[,\s]\d{3})+|\d+(?:\.\d+)?)\s*([kK])?\b")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def normalize_space(text: str) -> str:
    return " ".join(text.split()).lower()


def mentions(text: str, phrase: str | None) -> bool:
    return bool(phrase) and normalize_space(phrase) in normalize_space(text)


def numbers_in(text: str) -> set[float]:
    values = set()
    for digits, thousands in _NUMBER.findall(text):
        value = float(re.sub(r"[,\s]", "", digits))
        values.add(value * 1000 if thousands else value)
    return values


def grounded_salary(
    text: str, minimum: float | None, maximum: float | None, currency: str | None, period: str | None
) -> tuple[float | None, float | None, str | None, str | None]:
    """Keep salary figures only when the numbers appear in the email."""
    stated = numbers_in(text)
    minimum = minimum if minimum is not None and minimum in stated else None
    maximum = maximum if maximum is not None and maximum in stated else None
    if minimum is None and maximum is None:
        return None, None, None, None
    currency = currency.upper() if currency and _CURRENCY.match(currency.upper()) else None
    return minimum, maximum, currency, period


def grounded_deadline(text: str, iso_date: str | None, wording: str | None, received_at: datetime) -> tuple[date | None, str | None]:
    """A deadline date counts only when its wording appears in the email and the date parses
    to a plausible year; ambiguous wording is kept as text for the user to read."""
    wording = wording.strip()[:200] if mentions(text, wording) else None
    if not iso_date or not wording:
        return None, wording
    try:
        deadline = date.fromisoformat(iso_date)
    except ValueError:
        return None, wording
    if not received_at.year - 1 <= deadline.year <= received_at.year + 2:
        return None, wording
    return deadline, wording


def grounded_website(text: str, url: str | None, link_domains: list[str]) -> tuple[str | None, str | None]:
    """Return (website, domain) when the site appears in the email text or its links."""
    if not url:
        return None, None
    candidate = url if "://" in url else f"https://{url}"
    try:
        host = (urlsplit(candidate).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return None, None
    if not host or (host not in link_domains and host not in text.lower()):
        return None, None
    return candidate[:500], host
