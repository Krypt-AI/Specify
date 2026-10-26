"""Deterministic signals. User rules and configured university senders decide an email's group;
everything else is a hint passed to the AI and never decides on its own."""
import uuid
from dataclasses import dataclass

from app.models import ClassificationRule, EmailMessage, MailGroup
from app.schemas.preferences import UserPreferences
from app.schemas.rule import RuleConditions
from app.services.email_domains import domain_of

RULE_CONFIDENCE = 1.0
UNIVERSITY_CONFIDENCE = 0.95
URL_SHORTENERS = {"bit.ly", "tinyurl.com", "goo.gl", "is.gd", "cutt.ly", "rb.gy", "shorturl.at", "t.ly", "ow.ly"}


@dataclass(frozen=True)
class EmailFeatures:
    sender_email: str
    sender_domain: str
    subject: str
    body: str
    headers: dict
    reply_to: str | None
    link_domains: tuple[str, ...]

    @classmethod
    def of(cls, email: EmailMessage) -> "EmailFeatures":
        return cls(
            sender_email=email.sender_email.lower(),
            sender_domain=domain_of(email.sender_email),
            subject=email.subject.lower(),
            body=email.body_text.lower(),
            headers=email.headers,
            reply_to=email.reply_to,
            link_domains=tuple(email.link_domains),
        )


@dataclass(frozen=True)
class RuleDecision:
    group: str
    label_id: uuid.UUID | None
    rule_id: uuid.UUID | None
    confidence: float
    reason: str


def domain_matches(domain: str, candidates: list[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def match_rules(
    features: EmailFeatures, rules: list[ClassificationRule], prefs: UserPreferences
) -> RuleDecision | None:
    """The user's own rules first (in creation order), then configured university senders."""
    for rule in rules:
        if _conditions_match(features, RuleConditions.model_validate(rule.conditions)):
            return RuleDecision(
                rule.target_group, rule.target_label_id, rule.id, RULE_CONFIDENCE, f'Matched your rule "{rule.name}".'
            )
    return _match_university(features, prefs)


def collect_hints(features: EmailFeatures, prefs: UserPreferences) -> list[str]:
    hints = []
    providers = [
        p.name for p in prefs.certifications.providers if domain_matches(features.sender_domain, p.domains)
    ]
    if providers:
        hints.append(
            f"The sender's domain belongs to certification provider {', '.join(providers)}. Use the "
            "certifications group only if the email is actually about a certification, exam or credential."
        )
    keywords = [k for k in prefs.university.keywords if k in features.subject or k in features.body]
    if keywords:
        hints.append(f"The email mentions university keywords the user configured: {', '.join(keywords)}.")
    if "list-unsubscribe" in features.headers or features.headers.get("precedence", "").lower() in {"bulk", "list"}:
        hints.append("The email is a bulk or mailing-list message.")
    if features.reply_to and domain_of(features.reply_to) != features.sender_domain:
        hints.append(f"Replies go to a different domain ({domain_of(features.reply_to)}) than the sender's.")
    shorteners = sorted(set(features.link_domains) & URL_SHORTENERS)
    if shorteners:
        hints.append(f"The email contains shortened links ({', '.join(shorteners)}).")
    return hints


def _conditions_match(features: EmailFeatures, conditions: RuleConditions) -> bool:
    checks = []
    if conditions.sender_emails:
        checks.append(features.sender_email in conditions.sender_emails)
    if conditions.sender_domains:
        checks.append(domain_matches(features.sender_domain, conditions.sender_domains))
    if conditions.subject_contains:
        checks.append(any(keyword in features.subject for keyword in conditions.subject_contains))
    if conditions.body_contains:
        checks.append(any(keyword in features.body for keyword in conditions.body_contains))
    return bool(checks) and all(checks)


def _match_university(features: EmailFeatures, prefs: UserPreferences) -> RuleDecision | None:
    university = prefs.university
    if features.sender_email in university.lecturer_emails:
        reason = "The sender is one of your lecturers."
    elif features.sender_email in university.department_emails:
        reason = "The sender is a university department you configured."
    elif domain_matches(features.sender_domain, university.domains):
        reason = f"The sender uses your university's domain ({features.sender_domain})."
    else:
        return None
    return RuleDecision(MailGroup.UNIVERSITY, None, None, UNIVERSITY_CONFIDENCE, reason)
