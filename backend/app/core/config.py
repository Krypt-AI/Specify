from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # The repo-root .env is shared with docker compose; a backend/.env overrides it locally.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./specify.db"
    # Optional restricted PostgreSQL role for user requests; enables row-level security.
    request_database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    session_secret: str
    token_encryption_key: str
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    google_client_id: str = ""
    google_client_secret: str = ""
    session_ttl_hours: int = 24 * 7

    # AI provider: "ollama" keeps email content on your machine; "anthropic" uses the Claude API;
    # "none" runs on rules and manual review only. Anthropic without a key also means none.
    ai_provider: Literal["ollama", "anthropic", "none"] = "anthropic"
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ollama_url: str = "http://localhost:11434"
    # Small enough for a laptop CPU; larger models classify better if your hardware allows.
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: float = 180.0

    # Gmail push notifications through Google Cloud Pub/Sub (optional; polling is the fallback).
    gmail_pubsub_topic: str = ""  # projects/<project>/topics/<topic>
    gmail_push_audience: str = ""  # the push endpoint URL set on the subscription
    gmail_push_service_account: str = ""  # the service account that signs push requests

    # Runs background tasks inline; for tests and single-process debugging only.
    celery_task_always_eager: bool = False

    @field_validator("session_secret")
    @classmethod
    def _strong_session_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters; generate one as shown in .env.example.")
        return value

    @field_validator("token_encryption_key")
    @classmethod
    def _valid_fernet_key(cls, value: str) -> str:
        try:
            Fernet(value.encode())
        except ValueError as exc:
            raise ValueError("TOKEN_ENCRYPTION_KEY is not a valid key; generate one as shown in .env.example.") from exc
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.backend_url}/api/auth/google/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
