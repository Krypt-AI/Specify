"""Explicit date handling for dates found in emails. Ambiguous dates are flagged, never guessed."""
import re
from datetime import date, datetime

from app.services.recruitment.grounding import mentions

# 03/04/2026 could be 3 April or 4 March: numeric dates are ambiguous when both parts could be a month.
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MAX_DATES = 10


def ground_dates(text: str, received_at: datetime, key_dates: list) -> list[dict]:
    """Keep dates whose wording appears in the email; mark the ones a person must check."""
    grounded = []
    for item in key_dates[:MAX_DATES]:
        wording = item.text.strip()[:200]
        if not mentions(text, wording):
            continue  # not in the email: dropped
        parsed = _parse(item.date, received_at)
        numeric = _NUMERIC_DATE.search(wording)
        if numeric and int(numeric.group(1)) <= 12 and int(numeric.group(2)) <= 12 and numeric.group(1) != numeric.group(2):
            parsed = None  # day and month could be swapped
        time = item.time if item.time and _TIME.match(item.time) else None
        grounded.append(
            {
                "kind": item.kind,
                "text": wording,
                "date": parsed.isoformat() if parsed else None,
                "time": time,
                "ambiguous": parsed is None,
            }
        )
    return grounded


def _parse(value: str | None, received_at: datetime) -> date | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if received_at.year - 1 <= parsed.year <= received_at.year + 3 else None
