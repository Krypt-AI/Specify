from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

DraftTone = Literal["formal", "friendly", "concise", "enthusiastic"]


def clean_entries(values: list[str]) -> list[str]:
    """Lower-case, trim and de-duplicate list entries such as domains, addresses and keywords."""
    return list(dict.fromkeys(v.strip().lower() for v in values if v.strip()))


class SyncPreferences(BaseModel):
    initial_sync_days: int = Field(30, ge=1, le=365)
    initial_sync_max_messages: int = Field(500, ge=10, le=5000)
    poll_interval_minutes: int = Field(5, ge=1, le=1440)


class ClassificationPreferences(BaseModel):
    # Below this confidence an email goes to the review queue instead of being labeled.
    auto_apply_threshold: float = Field(0.8, ge=0.5, le=1.0)
    apply_gmail_labels: bool = True
    # Specify/Needs Review and Specify/Suspicious status labels in Gmail.
    apply_status_labels: bool = True


class UniversityPreferences(BaseModel):
    domains: list[str] = []
    lecturer_emails: list[str] = []
    department_emails: list[str] = []
    keywords: list[str] = []

    @field_validator("*")
    @classmethod
    def normalize_entries(cls, values: list[str]) -> list[str]:
        return clean_entries(values)


class CertificationProvider(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    domains: list[str] = []

    @field_validator("domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        return clean_entries(values)


# Domains are listed only where they are specific to certification activity; broad senders such
# as microsoft.com would mark every product email. Providers are hints, never a classification.
DEFAULT_CERTIFICATION_PROVIDERS = [
    {"name": "CompTIA", "domains": ["comptia.org"]},
    {"name": "Cisco", "domains": []},
    {"name": "Microsoft", "domains": []},
    {"name": "AWS", "domains": []},
    {"name": "Google Cloud", "domains": []},
    {"name": "Red Hat", "domains": []},
    {"name": "Linux Foundation", "domains": ["linuxfoundation.org"]},
    {"name": "EC-Council", "domains": ["eccouncil.org"]},
    {"name": "JLPT", "domains": ["jlpt.jp"]},
    {"name": "HSK", "domains": ["chinesetest.cn"]},
    {"name": "Pearson VUE", "domains": ["pearsonvue.com"]},
    {"name": "Credly", "domains": ["credly.com"]},
]


class CertificationPreferences(BaseModel):
    providers: list[CertificationProvider] = Field(
        default_factory=lambda: [CertificationProvider(**p) for p in DEFAULT_CERTIFICATION_PROVIDERS]
    )


WorkArrangement = Literal["remote", "hybrid", "onsite"]
SalaryPeriod = Literal["year", "month", "week", "day", "hour"]


class SalaryPreference(BaseModel):
    amount: float | None = Field(None, ge=0)
    currency: str | None = Field(None, pattern=r"^[A-Za-z]{3}$")
    period: SalaryPeriod = "month"

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class RecruitmentPreferences(BaseModel):
    """Used to flag opportunities outside what the user wants. Flags are advisory, never rejections."""

    job_types: list[str] = []
    locations: list[str] = []
    work_arrangements: list[WorkArrangement] = []
    min_salary: SalaryPreference = Field(default_factory=SalaryPreference)

    @field_validator("job_types", "locations")
    @classmethod
    def normalize_entries(cls, values: list[str]) -> list[str]:
        return clean_entries(values)


class DraftingProfile(BaseModel):
    """Personal details the user approves for use in drafts. Nothing else personal is ever added."""

    full_name: str = Field("", max_length=120)
    signature: str = Field("", max_length=500)
    phone: str = Field("", max_length=40)
    linkedin_url: str = Field("", max_length=300)


class DraftingPreferences(BaseModel):
    length: Literal["short", "medium", "long"] = "medium"
    language: str = Field("English", min_length=2, max_length=40)
    profile: DraftingProfile = Field(default_factory=DraftingProfile)


class AutomationPreferences(BaseModel):
    paused: bool = False  # global kill switch: no workflow starts or advances while set
    update_records: bool = True
    generate_drafts: bool = True
    approve_before_drafting: bool = False
    notify_new_opportunities: bool = True
    notify_failures: bool = True


class ReminderPreferences(BaseModel):
    """Reminders are created only by these rules."""

    deadlines: bool = True
    exams: bool = True
    interviews: bool = True
    renewals: bool = True
    reply_needed: bool = False
    deadline_days_before: int = Field(2, ge=0, le=60)
    exam_days_before: int = Field(3, ge=0, le=60)
    interview_days_before: int = Field(1, ge=0, le=30)
    renewal_days_before: int = Field(30, ge=0, le=365)
    recruiter_follow_up_days: int = Field(5, ge=0, le=60)  # 0 turns recruiter follow-ups off


class PrivacyPreferences(BaseModel):
    # Email bodies older than this are removed from Specify; 0 keeps them. Gmail keeps the email.
    email_body_retention_days: int = Field(365, ge=0, le=3650)


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timezone: str | None = None
    draft_tone: DraftTone = "friendly"
    sync: SyncPreferences = Field(default_factory=SyncPreferences)
    classification: ClassificationPreferences = Field(default_factory=ClassificationPreferences)
    university: UniversityPreferences = Field(default_factory=UniversityPreferences)
    certifications: CertificationPreferences = Field(default_factory=CertificationPreferences)
    recruitment: RecruitmentPreferences = Field(default_factory=RecruitmentPreferences)
    drafting: DraftingPreferences = Field(default_factory=DraftingPreferences)
    automation: AutomationPreferences = Field(default_factory=AutomationPreferences)
    reminders: ReminderPreferences = Field(default_factory=ReminderPreferences)
    privacy: PrivacyPreferences = Field(default_factory=PrivacyPreferences)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"Unknown timezone: {value}") from exc
        return value

    @classmethod
    def of(cls, stored: dict | None) -> "UserPreferences":
        return cls.model_validate(stored or {})


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge nested dicts; lists and scalars in the patch replace the base value."""
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
