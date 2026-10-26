"""AI providers behind one interface: a system prompt and untrusted content in, a validated
Pydantic object out. The model never gets tools, so it can only answer, never act.

Two providers:
- ollama: a local model; email content never leaves your machine.
- anthropic: Claude through the Anthropic API.

Callers get either the validated object or one of two errors: AIUnavailable (transient, retry
later) or AIOutputError (the answer cannot be used).
"""
import json
import logging
import re
from functools import lru_cache
from typing import Any, Protocol, TypeVar

import anthropic
import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

OutputT = TypeVar("OutputT", bound=BaseModel)


class AIUnavailable(Exception):
    """A transient provider failure (rate limit, overload, network, model loading). Retry later."""


class AIOutputError(Exception):
    """The provider answered, but the result cannot be used (refusal, invalid or truncated output)."""


class LLMBackend(Protocol):
    def structured(self, system: list[str], content: str, output_format: type[OutputT]) -> OutputT:
        """system holds stable prompt blocks (cacheable); content holds the per-request text."""
        ...


def neutralize(text: str) -> str:
    """Stop an email's sender from closing the <email> block early and forging Specify's signals."""
    return re.sub(r"<(?=\s*/?\s*email)", "‹", text, flags=re.IGNORECASE)


class AnthropicBackend:
    def __init__(self, client: anthropic.Anthropic, model: str):
        self._client = client
        self._model = model

    def structured(self, system: list[str], content: str, output_format: type[OutputT]) -> OutputT:
        # Server-side fallback re-runs a declined request on another model; Haiku has none.
        fallback = {} if self._model.startswith("claude-haiku") else {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = self._client.beta.messages.parse(
                model=self._model,
                max_tokens=4096,
                output_config={"effort": "low"},
                output_format=output_format,
                system=[{"type": "text", "text": block, "cache_control": {"type": "ephemeral"}} for block in system],
                messages=[{"role": "user", "content": content}],
                **fallback,
            )
        except anthropic.RateLimitError as exc:
            raise AIUnavailable("The AI provider is rate limiting requests.") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code in (408, 409):
                raise AIUnavailable(f"The AI provider is unavailable (HTTP {exc.status_code}).") from exc
            logger.error("AI request rejected with HTTP %s (request id %s)", exc.status_code, exc.request_id)
            raise AIOutputError(f"The AI provider rejected the request (HTTP {exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise AIUnavailable("Could not reach the AI provider.") from exc
        except ValidationError as exc:
            raise AIOutputError("The AI returned an invalid answer.") from exc

        if response.stop_reason == "refusal":
            raise AIOutputError("The AI declined to process this email.")
        if response.parsed_output is None:
            raise AIOutputError(f"The AI returned no answer (stop reason: {response.stop_reason}).")
        return response.parsed_output


class OllamaBackend:
    """A local model served by Ollama, constrained to the output's JSON schema."""

    def __init__(self, base_url: str, model: str, timeout: float, http: httpx.Client | None = None):
        self._model = model
        self._http = http or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def structured(self, system: list[str], content: str, output_format: type[OutputT]) -> OutputT:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "\n\n".join(system)},
                {"role": "user", "content": content},
            ],
            "format": inline_schema(output_format.model_json_schema()),
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            response = self._http.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise AIUnavailable(f"Could not reach Ollama ({exc.__class__.__name__}). Is it running?") from exc
        if response.status_code == 404:
            raise AIOutputError(f"Ollama has no model named {self._model}. Run: ollama pull {self._model}")
        if response.status_code >= 500 or response.status_code == 429:
            raise AIUnavailable(f"Ollama is unavailable (HTTP {response.status_code}).")
        if not response.is_success:
            raise AIOutputError(f"Ollama rejected the request (HTTP {response.status_code}).")

        data = response.json()
        if data.get("done_reason") == "length":
            raise AIOutputError("The local model's answer was cut off.")
        try:
            return output_format.model_validate_json(data.get("message", {}).get("content", ""))
        except ValidationError as exc:
            raise AIOutputError("The local model returned an invalid answer.") from exc


def inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve $ref/$defs so the schema is self-contained for constrained decoding."""
    definitions = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(definitions[node["$ref"].rsplit("/", 1)[-1]])
            return {key: resolve(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return json.loads(json.dumps(resolve(schema)))


@lru_cache
def get_backend() -> LLMBackend | None:
    """The configured AI provider, or None to run on rules and manual review only."""
    settings = get_settings()
    if settings.ai_provider == "ollama":
        return OllamaBackend(settings.ollama_url, settings.ollama_model, settings.ollama_timeout_seconds)
    if settings.ai_provider == "anthropic" and settings.anthropic_api_key:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=2)
        return AnthropicBackend(client, settings.ai_model)
    return None
