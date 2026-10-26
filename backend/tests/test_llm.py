import json

import httpx
import pytest

from app.services.classification.ai import AIClassification
from app.services.llm import AIOutputError, AIUnavailable, OllamaBackend, inline_schema
from tests.fakes import ai_output


def _backend(handler) -> OllamaBackend:
    http = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    return OllamaBackend("http://ollama.test", "llama3.2:3b", timeout=5, http=http)


def test_ollama_returns_a_validated_answer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": ai_output().model_dump_json()}, "done_reason": "stop"})

    result = _backend(handler).structured(["Instructions", "Labels"], "<email>hi</email>", AIClassification)

    assert result.primary_group == "recruitment"
    assert seen["stream"] is False
    assert seen["messages"][0] == {"role": "system", "content": "Instructions\n\nLabels"}
    assert "$ref" not in json.dumps(seen["format"])


def test_ollama_not_running_is_transient():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AIUnavailable, match="Is it running"):
        _backend(handler).structured(["x"], "y", AIClassification)


def test_missing_model_explains_how_to_pull_it():
    with pytest.raises(AIOutputError, match="ollama pull llama3.2:3b"):
        _backend(lambda request: httpx.Response(404, json={"error": "not found"})).structured(["x"], "y", AIClassification)


@pytest.mark.parametrize(
    "payload",
    [
        {"message": {"content": "{\"primary_group\": \"jobs\"}"}, "done_reason": "stop"},
        {"message": {"content": "not json"}, "done_reason": "stop"},
        {"message": {"content": "{"}, "done_reason": "length"},
    ],
)
def test_unusable_local_answers_are_rejected(payload):
    with pytest.raises(AIOutputError):
        _backend(lambda request: httpx.Response(200, json=payload)).structured(["x"], "y", AIClassification)


def test_inline_schema_resolves_nested_models():
    schema = inline_schema(AIClassification.model_json_schema())
    assert "$defs" not in schema
    assert "existing_label" in schema["properties"]["label"]["properties"]
