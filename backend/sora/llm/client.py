"""OpenAI-compatible chat client (OpenRouter, Groq, Gemini's OpenAI endpoint, local servers...).

Swapping providers is a .env change: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from sora.config import get_settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, exactly as the model produced it

    def to_message(self) -> dict:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)


@dataclass
class StreamDelta:
    text: str


class ChatModel(Protocol):
    """What the agent needs from an LLM. Tests plug in a fake."""

    def stream(
        self, messages: list[dict], tools: list[dict] | None = None, *, model: str | None = None
    ) -> AsyncIterator[StreamDelta | ChatResult]: ...

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        model: str | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> ChatResult: ...


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else s.llm_api_key
        self.model = model or s.llm_model
        self.temperature = s.llm_temperature
        self.use_stream = s.llm_stream
        self.reasoning = s.llm_reasoning.strip().lower()
        self.fallbacks = [m.strip() for m in s.llm_fallback_models.split(",") if m.strip()]
        self.data_collection = s.llm_data_collection.strip().lower()
        self.quantizations = [q.strip() for q in s.llm_quantizations.split(",") if q.strip()]
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout or s.llm_timeout_seconds, connect=15))

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not set in .env")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "https://github.com/sora-assistant"
            headers["X-Title"] = "Sora"
        return headers

    def _payload(self, messages, tools, model, temperature, stream, json_mode) -> dict:
        model = model or self.model
        if not model:
            raise LLMError("LLM_MODEL is not set in .env")
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if "openrouter.ai" in self.base_url:
            self._openrouter_options(payload)
        return payload

    def _openrouter_options(self, payload: dict) -> None:
        payload["usage"] = {"include": True}  # report the real cost of each call
        if self.reasoning == "none":
            payload["reasoning"] = {"enabled": False}
        elif self.reasoning in {"low", "medium", "high"}:
            payload["reasoning"] = {"effort": self.reasoning, "exclude": True}
        fallbacks = [m for m in self.fallbacks if m != payload["model"]]
        if fallbacks:
            payload["models"] = [payload["model"], *fallbacks]
        provider: dict[str, Any] = {}
        if self.data_collection in {"allow", "deny"}:
            provider["data_collection"] = self.data_collection
        if self.quantizations:
            provider["quantizations"] = self.quantizations
        if provider:
            payload["provider"] = provider
        if payload["model"].startswith("anthropic/"):
            payload["messages"] = _with_cache_breakpoint(payload["messages"])

    @staticmethod
    def _raise_for_error(status: int, body: str) -> None:
        try:
            detail = json.loads(body).get("error", {})
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except (ValueError, AttributeError):
            message = body[:500]
        raise LLMError(f"LLM request failed ({status}): {message}")

    async def complete(self, messages, tools=None, *, model=None, json_mode=False, temperature=None) -> ChatResult:
        payload = self._payload(messages, tools, model, temperature, False, json_mode)
        resp = await self._client.post(f"{self.base_url}/chat/completions", json=payload, headers=self._headers())
        if resp.status_code >= 400:
            self._raise_for_error(resp.status_code, resp.text)
        data = resp.json()
        if "error" in data:
            self._raise_for_error(resp.status_code, json.dumps(data))
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = [
            ToolCall(
                id=c.get("id") or f"call_{i}",
                name=c["function"]["name"],
                arguments=c["function"].get("arguments") or "{}",
            )
            for i, c in enumerate(msg.get("tool_calls") or [])
        ]
        return ChatResult(
            content=msg.get("content") or "",
            tool_calls=calls,
            model=data.get("model", payload["model"]),
            usage=data.get("usage") or {},
        )

    async def stream(self, messages, tools=None, *, model=None) -> AsyncIterator[StreamDelta | ChatResult]:
        """Yields text deltas as they arrive, then one final ChatResult with the assembled message."""
        if not self.use_stream:
            result = await self.complete(messages, tools, model=model)
            if result.content:
                yield StreamDelta(result.content)
            yield result
            return

        payload = self._payload(messages, tools, model, None, True, False)
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        result_model = payload["model"]
        usage: dict = {}
        async with self._client.stream(
            "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode(errors="replace")
                self._raise_for_error(resp.status_code, body)
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue  # comments like ": OPENROUTER PROCESSING" and blank lines
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if "error" in chunk:
                    self._raise_for_error(resp.status_code, json.dumps(chunk))
                result_model = chunk.get("model", result_model)
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                        yield StreamDelta(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        index = tc.get("index")
                        if index is None:
                            # Some providers omit "index"; a new id means a new call.
                            last = max(calls, default=None)
                            new_call = last is None or (tc.get("id") and tc["id"] != calls[last]["id"])
                            index = (last + 1 if last is not None else 0) if new_call else last
                        slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        tool_calls = [
            ToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"] or "{}")
            for i, c in sorted(calls.items())
            if c["name"]
        ]
        yield ChatResult(content="".join(text_parts), tool_calls=tool_calls, model=result_model, usage=usage)

    async def aclose(self) -> None:
        await self._client.aclose()


_default: OpenAICompatibleClient | None = None


def get_llm() -> OpenAICompatibleClient:
    global _default
    if _default is None:
        _default = OpenAICompatibleClient()
    return _default


CONTEXT_HEADING = "## Current context"


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Anthropic only caches up to an explicit cache_control mark. Put it after the static part of the
    system prompt, so tools + rules (~5k tokens) are cached and the changing context after it is not."""
    if not messages or messages[0].get("role") != "system" or not isinstance(messages[0].get("content"), str):
        return messages
    text = messages[0]["content"]
    static, sep, dynamic = text.partition(CONTEXT_HEADING)
    parts = [{"type": "text", "text": static, "cache_control": {"type": "ephemeral"}}]
    if sep:
        parts.append({"type": "text", "text": sep + dynamic})
    return [{"role": "system", "content": parts}, *messages[1:]]


def parse_json_object(text: str) -> dict:
    """Pull a JSON object out of a model reply, tolerating ```json fences and chatter around it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])
