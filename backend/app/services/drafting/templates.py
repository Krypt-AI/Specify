"""Drafting scenarios with built-in guidance and fallback wording. Users can override each one.

The fallback wording is used when no AI is configured, when the AI is unavailable, or when the
user turns AI off for a scenario. Placeholders in {braces} are filled by Specify; anything in
[square brackets] is left for the user to complete.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Decision, DraftTemplate


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    instructions: str
    body: str


_SIGN_OFF = "\n\nBest regards,\n{signature}"

SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        Scenario(
            "interested", "Interested",
            "Thank the sender, say the user is interested in the role and ask about the next steps.",
            "Dear {recipient},\n\nThank you for reaching out about the {role} role{at_company}. I am interested in this "
            "opportunity and would be glad to hear about the next steps." + _SIGN_OFF,
        ),
        Scenario(
            "interested_need_info", "Interested, need more information",
            "Express interest and ask for the missing details listed in the context, as short questions.",
            "Dear {recipient},\n\nThank you for reaching out about the {role} role{at_company}. I am interested and "
            "would appreciate a few more details before moving forward:\n\n{missing_questions}" + _SIGN_OFF,
        ),
        Scenario(
            "request_salary", "Request salary details",
            "Politely ask for the salary range, benefits and overall compensation structure.",
            "Dear {recipient},\n\nThank you for sharing the {role} role{at_company}. Before going further, could you "
            "share the salary range, benefits and overall compensation structure for this position?" + _SIGN_OFF,
        ),
        Scenario(
            "request_job_description", "Request job description",
            "Ask for the full job description: responsibilities, requirements and team.",
            "Dear {recipient},\n\nThank you for getting in touch about the {role} role{at_company}. Could you send me "
            "the full job description, including the main responsibilities and requirements?" + _SIGN_OFF,
        ),
        Scenario(
            "request_interview_details", "Request interview details",
            "Ask about the interview format, possible dates and times, duration and who the user will meet.",
            "Dear {recipient},\n\nThank you for the update on the {role} role{at_company}. Could you share the "
            "interview format, the available dates and times, and who I will be meeting?" + _SIGN_OFF,
        ),
        Scenario(
            "request_more_time", "Request more time",
            "Thank the sender and ask whether an extension is possible. Leave the new date as a placeholder.",
            "Dear {recipient},\n\nThank you for the opportunity regarding the {role} role{at_company}. Would it be "
            "possible to have until [date] to give you my answer?" + _SIGN_OFF,
        ),
        Scenario(
            "decline", "Decline",
            "Thank the sender and politely decline. Do not invent a reason; keep the door open.",
            "Dear {recipient},\n\nThank you for considering me for the {role} role{at_company}. After careful thought, "
            "I have decided not to proceed. I appreciate your time and hope we can stay in touch." + _SIGN_OFF,
        ),
        Scenario(
            "custom", "Custom decision",
            "Write a reply that carries out the user's custom decision described in the context.",
            "Dear {recipient},\n\n[Write your reply: {custom_decision}]" + _SIGN_OFF,
        ),
        Scenario(
            "university_reply", "Reply to a university email",
            "Reply to a lecturer, department or university office. Be respectful and concise, and answer or acknowledge the email.",
            "Dear {recipient},\n\nThank you for your email about {subject}. [Write your reply.]" + _SIGN_OFF,
        ),
        Scenario(
            "certification_reply", "Reply to a certification provider",
            "Reply to a certification provider about registration, scheduling or exam requirements.",
            "Dear {recipient},\n\nThank you for your email about {subject}. [Write your question or reply.]" + _SIGN_OFF,
        ),
        Scenario(
            "general_reply", "General reply",
            "Write a polite, relevant reply to the email.",
            "Dear {recipient},\n\nThank you for your email about {subject}. [Write your reply.]" + _SIGN_OFF,
        ),
    )
}

# Decisions that need a reply. Saving for later, already applied and irrelevant do not.
DRAFT_DECISIONS = {
    Decision.INTERESTED, Decision.INTERESTED_NEED_INFO, Decision.REQUEST_SALARY, Decision.REQUEST_JOB_DESCRIPTION,
    Decision.REQUEST_INTERVIEW_DETAILS, Decision.REQUEST_MORE_TIME, Decision.DECLINE, Decision.CUSTOM,
}

MISSING_QUESTIONS = {
    "salary": "- What is the salary range and benefits package?",
    "job_description": "- Could you share the full job description?",
    "work_arrangement": "- Is the role remote, hybrid or on-site?",
    "location": "- Where is the role based?",
}


@dataclass(frozen=True)
class ResolvedTemplate:
    scenario: Scenario
    instructions: str
    body: str
    use_ai: bool
    customized: bool


def resolve_template(db: Session, user_id: uuid.UUID, scenario: str) -> ResolvedTemplate:
    base = SCENARIOS[scenario]
    custom = db.scalar(select(DraftTemplate).where(DraftTemplate.user_id == user_id, DraftTemplate.scenario == scenario))
    if custom is None:
        return ResolvedTemplate(base, base.instructions, base.body, True, False)
    return ResolvedTemplate(base, custom.instructions or base.instructions, custom.body or base.body, custom.use_ai, True)


def render(body: str, values: dict[str, str]) -> str:
    """Fill {placeholders}; unknown ones are left visible so nothing silently disappears."""

    class _Keep(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return body.format_map(_Keep(values))
