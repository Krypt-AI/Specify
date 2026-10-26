"""Checks run on every draft before it reaches Gmail. They warn; the user decides what to send."""
import re

_ATTACHMENT = re.compile(r"\b(attached|attachment|enclosed|please find)\b", re.IGNORECASE)
_COMMITMENT = re.compile(
    r"\b(i (?:hereby )?accept|i am pleased to accept|i agree to (?:the|your) (?:offer|salary|terms)|i confirm my acceptance|i (?:will|can) start on)\b",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,60}\]")
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")
_ID_NUMBER = re.compile(r"\b\d{6}-\d{2}-\d{4}\b|\b\d{3}-\d{2}-\d{4}\b")


def check_draft(body: str, *, decision: str | None, known_text: str, approved_values: list[str]) -> list[str]:
    """Return human-readable warnings. known_text is everything the draft may draw facts from."""
    warnings = []
    if _ATTACHMENT.search(body):
        warnings.append("Mentions an attachment. Specify never attaches files; add it in Gmail or remove the mention.")
    if _COMMITMENT.search(body):
        warnings.append("Contains a commitment such as accepting an offer. Check it carefully before sending.")
    placeholders = sorted(set(_PLACEHOLDER.findall(body)))
    if placeholders:
        warnings.append(f"Fill in before sending: {', '.join(placeholders)}.")
    if _ID_NUMBER.search(body):
        warnings.append("Contains what looks like an identity number. Remove it unless you meant to share it.")

    known_numbers = {_digits(n) for n in _NUMBER.findall(known_text + " " + " ".join(approved_values))}
    unknown = sorted({n for n in _NUMBER.findall(body) if len(_digits(n)) >= 3 and _digits(n) not in known_numbers})
    if unknown:
        warnings.append(f"Mentions {', '.join(unknown)}, which is not in the conversation. Make sure it is correct.")
    if decision == "decline" and re.search(r"\b(salary|offer) (?:was|is) too low\b", body, re.IGNORECASE):
        warnings.append("Gives a reason for declining that you did not provide.")
    return warnings


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)
