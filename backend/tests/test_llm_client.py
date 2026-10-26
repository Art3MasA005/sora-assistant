"""OpenAI-compatible client parsing, against a mocked HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import run

from sora.google.workspace import _range
from sora.llm.client import ChatResult, LLMError, OpenAICompatibleClient, StreamDelta, parse_json_object


def _client(handler) -> OpenAICompatibleClient:
    c = OpenAICompatibleClient(base_url="https://llm.test/v1", api_key="k", model="m")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def _sse(chunks: list[dict]) -> bytes:
    lines = [": OPENROUTER PROCESSING", ""]
    for chunk in chunks:
        lines += [f"data: {json.dumps(chunk)}", ""]
    lines += ["data: [DONE]", ""]
    return "\n".join(lines).encode()


def _delta(**delta) -> dict:
    return {"model": "m", "choices": [{"delta": delta}]}


async def _collect(client: OpenAICompatibleClient) -> tuple[str, ChatResult]:
    text, final = "", None
    async for item in client.stream([{"role": "user", "content": "hi"}], tools=[{"type": "function"}]):
        if isinstance(item, StreamDelta):
            text += item.text
        else:
            final = item
    return text, final


def test_stream_text_and_indexed_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True and body["tool_choice"] == "auto"
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, content=_sse([
            _delta(content="আমি "),
            _delta(content="দেখছি"),
            _delta(tool_calls=[{"index": 0, "id": "a", "function": {"name": "gmail_search", "arguments": '{"query"'}}]),
            _delta(tool_calls=[{"index": 0, "function": {"arguments": ': "is:unread"}'}}]),
            _delta(tool_calls=[{"index": 1, "id": "b", "function": {"name": "calendar_list_events", "arguments": "{}"}}]),
        ]))

    text, final = run(_collect(_client(handler)))
    assert text == "আমি দেখছি" and final.content == "আমি দেখছি"
    assert [(c.id, c.name, json.loads(c.arguments)) for c in final.tool_calls] == [
        ("a", "gmail_search", {"query": "is:unread"}),
        ("b", "calendar_list_events", {}),
    ]


def test_stream_tool_calls_without_index_are_kept_apart():
    def handler(request):
        return httpx.Response(200, content=_sse([
            _delta(tool_calls=[{"id": "a", "function": {"name": "tasks_list", "arguments": "{}"}}]),
            _delta(tool_calls=[{"id": "b", "function": {"name": "reminder_list", "arguments": "{}"}}]),
        ]))

    _, final = run(_collect(_client(handler)))
    assert [c.name for c in final.tool_calls] == ["tasks_list", "reminder_list"]


def test_errors_surface_as_llm_error():
    def handler(request):
        return httpx.Response(429, json={"error": {"message": "Rate limit exceeded: free-models-per-day"}})

    with pytest.raises(LLMError, match="429.*free-models-per-day"):
        run(_collect(_client(handler)))

    def handler_in_stream(request):
        return httpx.Response(200, content=_sse([{"error": {"message": "provider down"}}]))

    with pytest.raises(LLMError, match="provider down"):
        run(_collect(_client(handler_in_stream)))


def test_complete_parses_tool_calls():
    def handler(request):
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": None, "tool_calls": [
            {"id": "x", "function": {"name": "tasks_add", "arguments": '{"title": "buy milk"}'}}]}}]})

    result = run(_client(handler).complete([{"role": "user", "content": "add"}]))
    assert result.content == "" and result.tool_calls[0].name == "tasks_add"


def test_openrouter_routing_options(monkeypatch):
    seen: list[dict] = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "ok"}}]})

    c = OpenAICompatibleClient(base_url="https://openrouter.ai/api/v1", api_key="k", model="deepseek/deepseek-v4.1-flash")
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c.reasoning, c.fallbacks = "low", ["anthropic/claude-haiku-5.5"]
    c.data_collection, c.quantizations = "deny", ["fp8", "bf16"]
    system = "Rules...\n\n## Current context\nLocal time: now"
    run(c.complete([{"role": "system", "content": system}, {"role": "user", "content": "hi"}]))
    body = seen[0]
    assert body["models"] == ["deepseek/deepseek-v4.1-flash", "anthropic/claude-haiku-5.5"]
    assert body["provider"] == {"data_collection": "deny", "quantizations": ["fp8", "bf16"]}
    assert body["reasoning"] == {"effort": "low", "exclude": True} and body["usage"] == {"include": True}
    assert body["messages"][0]["content"] == system  # no cache markup for non-Anthropic models

    run(c.complete([{"role": "system", "content": system}, {"role": "user", "content": "hi"}], model="anthropic/claude-haiku-5.5"))
    parts = seen[1]["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Rules...\n\n", "cache_control": {"type": "ephemeral"}}
    assert parts[1]["text"].startswith("## Current context") and "cache_control" not in parts[1]
    assert "models" not in seen[1]  # the fallback is the model itself


def test_non_openrouter_payload_is_plain():
    seen: list[dict] = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    run(_client(handler).complete([{"role": "user", "content": "hi"}]))
    assert not {"provider", "reasoning", "usage", "models"} & set(seen[0])


def test_parse_json_object_tolerates_fences_and_chatter():
    assert parse_json_object('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('{"importance": "high"} hope that helps') == {"importance": "high"}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_sheet_ranges_are_url_safe():
    assert _range("Sheet1!A1:D5") == "Sheet1!A1:D5"
    assert _range("My Budget/2026!A:C") == "My%20Budget%2F2026!A:C"
    assert _range("'খরচ'!A1") == "'%E0%A6%96%E0%A6%B0%E0%A6%9A'!A1"
