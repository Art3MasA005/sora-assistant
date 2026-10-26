"""Test setup: a separate sora_test database, no real LLM/Google calls, and a scripted fake LLM."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable

import pytest
from dotenv_shim import read_env

_env = read_env()
_base_url = _env.get("DATABASE_URL", "")
os.environ["DATABASE_URL"] = _base_url.rsplit("/", 1)[0] + "/sora_test"
os.environ.update(
    {
        "EMAIL_WATCHER_ENABLED": "false",
        "LLM_API_KEY": "test-key",
        "LLM_MODEL": "fake/model",
        "EMBEDDING_API_KEY": "",
        "EMBEDDING_MODEL": "",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
        "FCM_SERVICE_ACCOUNT_FILE": "",
        "OWNER_NAME": "Tester",
    }
)

from sqlalchemy import text  # noqa: E402

from sora.db import dispose_engine, session_scope  # noqa: E402
from sora.llm.client import ChatResult, StreamDelta, ToolCall  # noqa: E402


def run(coro):
    """Run a coroutine on a fresh selector loop (psycopg needs it on Windows), closing DB connections after."""

    async def wrapper():
        try:
            return await coro
        finally:
            await dispose_engine()

    if sys.platform == "win32":
        return asyncio.run(wrapper(), loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(wrapper())


@pytest.fixture(scope="session", autouse=True)
def database():
    from alembic import command
    from alembic.config import Config

    from sora.config import ROOT_DIR
    from sora.wsl_db import ensure_postgres

    ensure_postgres()
    cfg = Config(str(ROOT_DIR / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT_DIR / "backend" / "alembic"))
    cfg.attributes["skip_logging"] = True
    command.upgrade(cfg, "head")
    yield


TABLES = [
    "chunks", "documents", "memories", "messages", "pending_actions", "conversations", "notifications",
    "reminders", "email_rules", "seen_emails", "device_commands", "devices", "connections", "oauth_states", "kv",
    "routine_runs", "routines", "people",
]


@pytest.fixture(autouse=True)
def clean_db():
    async def truncate():
        async with session_scope() as session:
            await session.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))

    run(truncate())
    from sora.services import announce

    announce._known = None  # the phones' addresses cached from the kv table just emptied
    yield


class FakeLLM:
    """Replays scripted responses. Each script item is a ChatResult or a function(messages) -> ChatResult."""

    def __init__(self, script: list[ChatResult | Callable[[list[dict]], ChatResult]]):
        self.script = list(script)
        self.calls: list[dict] = []

    def _next(self, messages, tools) -> ChatResult:
        self.calls.append({"messages": messages, "tools": tools})
        if not self.script:
            return ChatResult(content="(no more scripted replies)")
        item = self.script.pop(0)
        return item(messages) if callable(item) else item

    async def stream(self, messages, tools=None, *, model=None):
        result = self._next(messages, tools)
        if result.content:
            yield StreamDelta(result.content)
        yield result

    async def complete(self, messages, tools=None, *, model=None, json_mode=False, temperature=None):
        return self._next(messages, tools)


def reply(text: str) -> ChatResult:
    return ChatResult(content=text, model="fake/model")


def call(name: str, arguments: str, call_id: str = "call_1", content: str = "") -> ChatResult:
    return ChatResult(content=content, tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)], model="fake/model")


async def drain(events) -> list[dict]:
    return [e async for e in events]
