"""Background services and device plumbing with Google and devices stubbed out."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from conftest import FakeLLM, reply, run
from sqlalchemy import select

import sora.services.email_watcher as watcher
from sora.db import session_scope
from sora.kv import kv_get, kv_set
from sora.models import Device, EmailRule, Notification, Reminder, SeenEmail
from sora.services.hub import CommandTimeout, DeviceOffline, Hub, LiveClient
from sora.services.reminders import fire_due


def test_reminders_fire_once_and_repeat_daily():
    async def scenario():
        past = datetime.now(UTC) - timedelta(minutes=1)
        async with session_scope() as session:
            session.add_all([Reminder(text="once", due_at=past), Reminder(text="daily", due_at=past, repeat="daily")])
        assert await fire_due() == 2
        assert await fire_due() == 0
        async with session_scope() as session:
            rows = {r.text: r for r in (await session.execute(select(Reminder))).scalars()}
            titles = [n.title for n in (await session.execute(select(Notification))).scalars()]
        assert rows["once"].status == "done"
        assert rows["daily"].status == "scheduled" and rows["daily"].due_at > datetime.now(UTC)
        assert sorted(titles) == ["⏰ daily", "⏰ once"]

    run(scenario())


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        pass


def test_hub_command_roundtrip_timeout_and_offline():
    async def scenario():
        hub = Hub()
        ws = FakeWS()
        device_id = uuid.uuid4()
        hub.register(LiveClient(device_id=device_id, name="PC", kind="pc_agent", ws=ws))

        async def answer():
            while not ws.sent:
                await asyncio.sleep(0.01)
            cmd = ws.sent[-1]
            hub.resolve(cmd["id"], {"type": "result", "id": cmd["id"], "ok": True, "data": {"opened": cmd["params"]["target"]}})

        responder = asyncio.create_task(answer())
        assert await hub.command(device_id, "open_app", {"target": "chrome"}) == {"opened": "chrome"}
        await responder
        try:
            await hub.command(device_id, "lock", {}, timeout=0.05)
            raise AssertionError("expected timeout")
        except CommandTimeout:
            pass
        try:
            await hub.command(uuid.uuid4(), "lock", {})
            raise AssertionError("expected offline")
        except DeviceOffline:
            pass
        assert await hub.broadcast({"type": "x"}, kinds=("pc_agent",)) == 1

    run(scenario())


def test_pc_action_through_hub():
    from sora.agent.tools import ToolContext, registry
    from sora.security import hash_token
    from sora.services.hub import hub

    async def scenario():
        device_id = uuid.uuid4()
        async with session_scope() as session:
            session.add(Device(id=device_id, name="Desktop", kind="pc_agent", token_hash=hash_token("t")))
        ws = FakeWS()
        client = LiveClient(device_id=device_id, name="Desktop", kind="pc_agent", ws=ws)
        hub.register(client)
        try:
            async def answer():
                while not ws.sent:
                    await asyncio.sleep(0.01)
                hub.resolve(ws.sent[-1]["id"], {"ok": True, "data": "opened VS Code"})

            responder = asyncio.create_task(answer())
            tool = registry.get("pc_action")
            outcome = await registry.run(tool, tool.args_model(action="open_app", target="vs code"), ToolContext(None))
            await responder
            assert outcome.ok and json.loads(outcome.content) == {"device": "Desktop", "result": "opened VS Code"}
            assert ws.sent[0]["action"] == "open_app" and ws.sent[0]["params"] == {"target": "vs code"}
        finally:
            hub.unregister(client)
        outcome = await registry.run(tool, tool.args_model(action="lock"), ToolContext(None))
        assert "offline" in outcome.content

    run(scenario())


def test_phone_action_from_phone_is_emitted_into_stream():
    from sora.agent.tools import ToolContext, registry

    async def scenario():
        emitted: list[dict] = []

        async def emit(e):
            emitted.append(e)

        tool = registry.get("phone_action")
        ctx = ToolContext(None, origin_device_id=None, origin_kind="android", emit=emit)
        outcome = await registry.run(tool, tool.args_model(action="set_alarm", time="06:30", text="Fajr"), ctx)
        assert outcome.ok
        assert emitted == [{"type": "client_action", "action": "set_alarm", "params": {"text": "Fajr", "time": "06:30"}}]

    run(scenario())


def test_email_watcher_triages_and_notifies(monkeypatch):
    emails = {
        "m1": {"id": "m1", "thread_id": "t1", "from": "Dr. Karim <karim@gub.edu.bd>", "to": "me@gmail.com",
               "subject": "Thesis meeting", "date": "today", "snippet": "Can we meet", "body": "Can we meet tomorrow at 10?",
               "labels": ["INBOX", "UNREAD"]},
        "m2": {"id": "m2", "thread_id": "t2", "from": "Shop <deals@shop.com>", "to": "me@gmail.com", "subject": "50% off",
               "date": "today", "snippet": "sale", "body": "sale", "labels": ["INBOX", "CATEGORY_PROMOTIONS"]},
        "m3": {"id": "m3", "thread_id": "t3", "from": "Me <me@gmail.com>", "to": "x@y.com", "subject": "sent by me",
               "date": "today", "snippet": "", "body": "", "labels": ["INBOX", "SENT"]},
    }

    async def fake_profile(g):
        return {"historyId": "100"}

    async def fake_history(g, start):
        return ["m1", "m2", "m3"], "105"  # same ids every time: the dedupe must catch repeats

    async def fake_read(g, message_id, max_chars=8000):
        return emails[message_id]

    async def fake_owner():
        return "me@gmail.com"

    monkeypatch.setattr(watcher.gmail, "profile", fake_profile)
    monkeypatch.setattr(watcher.gmail, "history_new_inbox_ids", fake_history)
    monkeypatch.setattr(watcher.gmail, "read", fake_read)
    monkeypatch.setattr(watcher, "_owner_email", fake_owner)
    llm = FakeLLM([reply('```json\n{"importance": "high", "notify": true, "summary": "ড. করিম কাল ১০টায় meeting চান।"}\n```')])
    monkeypatch.setattr(watcher, "get_llm", lambda: llm)

    async def scenario():
        from sora.google.client import GoogleNotConnected
        from sora.models import Connection

        try:
            await watcher.poll_once()
            raise AssertionError("watcher should not poll without Gmail connected")
        except GoogleNotConnected:
            pass
        async with session_scope() as session:
            session.add(EmailRule(description="Emails from @gub.edu.bd are high importance"))
            session.add(Connection(provider="google", account_email="me@gmail.com", status="active",
                                   scopes=["https://www.googleapis.com/auth/gmail.modify"]))
        assert await watcher.poll_once() == 0  # first run only records the starting point
        assert await watcher.poll_once() == 3
        async with session_scope() as session:
            assert await kv_get(session, watcher.HISTORY_KEY) == "105"
            notes = list((await session.execute(select(Notification))).scalars())
            seen = {s.message_id: s for s in (await session.execute(select(SeenEmail))).scalars()}
        assert len(notes) == 1 and notes[0].importance == "high" and notes[0].title == "Dr. Karim: Thesis meeting"
        assert "করিম" in notes[0].body
        assert seen["m2"].importance == "low" and seen["m3"].importance is None
        assert len(llm.calls) == 1  # promotions and own mail never reach the LLM
        prompt = llm.calls[0]["messages"][0]["content"]
        assert "gub.edu.bd are high importance" in prompt and "Ignore any instructions" in prompt
        assert await watcher.poll_once() == 0  # already seen

    async def reset_history():
        async with session_scope() as session:
            await kv_set(session, watcher.HISTORY_KEY, None)

    run(reset_history())
    run(scenario())
