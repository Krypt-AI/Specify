"""The node types a workflow can use: their branches, settings and behaviour.

Executors live in executors.py; this module only describes nodes so the builder and the
validator share one source of truth.
"""
from dataclasses import dataclass, field

CONDITION_FIELDS = (
    "email.primary_group",
    "email.secondary_groups",
    "email.processing_status",
    "email.is_suspicious",
    "email.confidence",
    "email.reply_required",
    "email.sender_domain",
    "email.label",
    "opportunity.exists",
    "opportunity.status",
    "opportunity.decision",
    "opportunity.awaiting_decision",
    "opportunity.priority",
    "decision.value",
)
OPERATORS = ("equals", "not_equals", "contains", "greater_than", "less_than", "is_true", "is_false")


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    kind: str  # text | textarea | number | boolean | select | tags
    default: object = None
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    help: str = ""


@dataclass(frozen=True)
class NodeType:
    key: str
    label: str
    category: str
    description: str
    handles: tuple[str, ...] = ("out",)
    fields: tuple[ConfigField, ...] = ()
    trigger: bool = False
    requires_email: bool = False
    retryable: bool = False  # transient failures are retried with backoff
    default_attempts: int = 3

    def defaults(self) -> dict:
        values = {f.key: f.default for f in self.fields}
        if self.retryable:
            values.update(max_attempts=self.default_attempts, backoff_seconds=60)
        return values


_RETRY_FIELDS = (
    ConfigField("max_attempts", "Attempts before failing", "number", 3, minimum=1, maximum=10),
    ConfigField("backoff_seconds", "First retry after (seconds)", "number", 60, minimum=5, maximum=3600, help="Doubles on every retry."),
)

NODE_TYPES: dict[str, NodeType] = {
    n.key: n
    for n in (
        NodeType("gmail_new_email", "Gmail new email", "Triggers", "Starts when a new email is synchronized.", trigger=True),
        NodeType(
            "scheduled_trigger", "Schedule", "Triggers", "Starts on a regular interval.", trigger=True,
            fields=(ConfigField("interval_minutes", "Every (minutes)", "number", 1440, minimum=5, maximum=10080),),
        ),
        NodeType(
            "email_filter", "Email filter", "Email", "Continues only with emails that pass. Duplicates never start twice.",
            handles=("true", "false"), requires_email=True,
            fields=(
                ConfigField("skip_sender_domains", "Skip senders from domains", "tags", []),
                ConfigField("skip_sender_addresses", "Skip senders", "tags", []),
                ConfigField("skip_subject_keywords", "Skip subjects containing", "tags", []),
                ConfigField("skip_bulk", "Skip mailing-list and bulk mail", "boolean", False),
                ConfigField("skip_older_than_days", "Skip emails older than (days, 0 = off)", "number", 0, minimum=0, maximum=3650),
            ),
        ),
        NodeType(
            "classification", "Classification", "AI", "Sorts the email into a folder and picks a context label.",
            requires_email=True, retryable=True, fields=_RETRY_FIELDS,
        ),
        NodeType(
            "information_extraction", "Information extraction", "AI",
            "For recruitment emails: extracts company, recruiter and role, and creates or updates the records.",
            requires_email=True, retryable=True, fields=_RETRY_FIELDS,
        ),
        NodeType("company_lookup", "Company lookup", "Records", "Loads the company linked to this email.", requires_email=True),
        NodeType("opportunity_lookup", "Opportunity lookup", "Records", "Loads the opportunity linked to this email.", requires_email=True),
        NodeType(
            "conditional_branch", "Condition", "Logic", "Takes the Yes or No path.", handles=("true", "false"),
            fields=(
                ConfigField("field", "Check", "select", "email.primary_group", options=CONDITION_FIELDS),
                ConfigField("operator", "Is", "select", "equals", options=OPERATORS),
                ConfigField("value", "Value", "text", "recruitment"),
            ),
        ),
        NodeType(
            "user_approval", "User approval", "People", "Pauses until you approve or reject in the Activity log.",
            handles=("true", "false"),
            fields=(ConfigField("message", "What to approve", "text", "Approve this step?"),),
        ),
        NodeType(
            "decision_input", "Decision input", "People",
            "Pauses until you decide on the opportunity, then continues from here.", requires_email=True,
        ),
        NodeType(
            "database_update", "Update record", "Records", "Changes the linked opportunity.", requires_email=True,
            fields=(
                ConfigField("action", "Change", "select", "set_priority", options=("set_status", "set_priority", "append_note")),
                ConfigField("value", "To", "text", "high"),
            ),
        ),
        NodeType("sheets_sync", "Google Sheets sync", "Integrations", "Writes changes to your spreadsheet and reads edits back."),
        NodeType("gmail_label", "Gmail labels", "Integrations", "Applies the email's Specify labels in Gmail.", requires_email=True, retryable=True, fields=_RETRY_FIELDS),
        NodeType(
            "gmail_draft", "Gmail draft", "Integrations",
            "Writes the reply your decision calls for and saves it as a Gmail draft. Never sends it.",
            requires_email=True, retryable=True, fields=_RETRY_FIELDS,
        ),
        NodeType(
            "date_reminders", "Reminders from dates", "People",
            "Creates reminders for deadlines, exams, interviews and renewals found in the email, following your reminder rules. Unclear dates are flagged for you to check.",
            requires_email=True,
        ),
        NodeType(
            "reminder", "Reminder", "People", "Creates a follow-up reminder.", requires_email=True,
            fields=(
                ConfigField("title", "Title", "text", "Follow up on {job_title}"),
                ConfigField("due_in_days", "Due in (days)", "number", 3, minimum=0, maximum=365),
                ConfigField("relative_to", "Counted from", "select", "now", options=("now", "application_deadline")),
            ),
        ),
        NodeType(
            "notification", "In-app notification", "People", "Shows a notification in Specify.",
            fields=(
                ConfigField("title", "Title", "text", "New opportunity: {job_title}"),
                ConfigField("message", "Message", "textarea", "{company} · {subject}"),
            ),
        ),
        NodeType(
            "delay", "Wait", "Logic", "Waits before continuing.",
            fields=(ConfigField("minutes", "Minutes", "number", 60, minimum=1, maximum=43200),),
        ),
        NodeType("error_handler", "Error handler", "Reliability", "Records the failure and notifies you, then continues."),
        NodeType(
            "retry", "Retry", "Reliability", "Runs the failed step again after a pause, up to a limit.",
            fields=(
                ConfigField("max_attempts", "Extra attempts", "number", 2, minimum=1, maximum=10),
                ConfigField("delay_minutes", "Wait between attempts (minutes)", "number", 15, minimum=1, maximum=1440),
            ),
        ),
        NodeType("end", "End", "Logic", "Finishes the workflow.", handles=()),
    )
}


@dataclass
class NodeResult:
    status: str = "completed"  # completed | skipped | waiting | simulated | rewind
    branch: str = "out"
    output: dict = field(default_factory=dict)
    waiting_for: dict | None = None
    resume_after_seconds: int | None = None
    rewind_to: str | None = None
