from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    account,
    activity,
    analytics,
    auth,
    companies,
    drafts,
    duplicates,
    emails,
    follow_ups,
    integrations,
    labels,
    notifications,
    opportunities,
    rules,
    settings,
    sheets,
    sync,
    webhooks,
    workflows,
)
from app.core.config import get_settings
from app.core.http import install_http_hardening
from app.core.logging import configure_logging

configure_logging()
config = get_settings()
# The interactive docs are for development; production exposes only the API itself.
docs = {} if not config.is_production else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="Specify", version="0.8.0", **docs)

install_http_hardening(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")
for module in (
    auth, account, integrations, settings, sync, emails, labels, rules, opportunities, companies,
    duplicates, sheets, drafts, workflows, activity, follow_ups, notifications, analytics, webhooks,
):  # fmt: skip
    api_router.include_router(module.router)
app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
