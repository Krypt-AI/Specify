"""Advisory information for the decision panel, computed on read so it follows edits and preferences."""
from app.models import Opportunity
from app.schemas.preferences import RecruitmentPreferences


def missing_information(opportunity: Opportunity) -> list[str]:
    missing = []
    if opportunity.salary_min is None and opportunity.salary_max is None:
        missing.append("salary")
    if not opportunity.job_description.strip():
        missing.append("job_description")
    if not opportunity.work_arrangement:
        missing.append("work_arrangement")
    if not opportunity.location and opportunity.work_arrangement != "remote":
        missing.append("location")
    return missing


def preference_flags(opportunity: Opportunity, preferences: RecruitmentPreferences) -> list[str]:
    """Ways the opportunity differs from the user's preferences. Informational, never a rejection."""
    flags = []
    if preferences.work_arrangements and opportunity.work_arrangement and (
        opportunity.work_arrangement not in preferences.work_arrangements
    ):
        flags.append(f"Work arrangement is {opportunity.work_arrangement}; you prefer {', '.join(preferences.work_arrangements)}.")
    if (
        preferences.locations
        and opportunity.location
        and opportunity.work_arrangement != "remote"
        and not any(place in opportunity.location.lower() for place in preferences.locations)
    ):
        flags.append(f"Location {opportunity.location} is not one of your preferred locations.")
    if preferences.job_types and opportunity.employment_type and not any(
        kind in opportunity.employment_type.lower() for kind in preferences.job_types
    ):
        flags.append(f"Employment type {opportunity.employment_type} is not one you prefer.")
    salary = preferences.min_salary
    top = opportunity.salary_max or opportunity.salary_min
    if (
        salary.amount is not None
        and top is not None
        and opportunity.salary_currency == salary.currency
        and opportunity.salary_period == salary.period
        and float(top) < salary.amount
    ):
        flags.append(f"Salary is below your minimum of {salary.currency} {salary.amount:g} per {salary.period}.")
    return flags


def fallback_recommendation(opportunity: Opportunity) -> dict:
    """Used when no AI recommendation exists (for example, opportunities created manually)."""
    missing = missing_information(opportunity)
    if "job_description" in missing:
        return {"decision": "request_job_description", "explanation": "The role is not described yet; ask for the full job description."}
    if "salary" in missing:
        return {"decision": "request_salary", "explanation": "No salary is mentioned; ask for the range before deciding."}
    return {"decision": "interested", "explanation": "The main details are present; decide whether the role suits you."}
