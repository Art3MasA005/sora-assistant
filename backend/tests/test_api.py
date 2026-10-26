"""HTTP API through an in-process ASGI client."""

from __future__ import annotations

import asyncio
import json
from contextlib import aclosing

import httpx
from conftest import FakeLLM, call, reply, run

import sora.agent.runner as runner_module
from sora.agent.runner import Agent
from sora.db import session_scope
from sora.kv import kv_set
from sora.main import create_app
from sora.security import hash_password

PASSWORD = "a-strong-password"


async def _client() -> tuple[httpx.AsyncClient, str]:
    async with session_scope() as session:
        await kv_set(session, "owner_password_hash", hash_password(PASSWORD))
    app = create_app(background=False)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    resp = await client.post("/api/auth/login", json={"password": PASSWORD, "device_name": "Pixel", "device_kind": "android"})
    assert resp.status_code == 200, resp.text
    client.headers["Authorization"] = f"Bearer {resp.json()['token']}"
    return client, resp.json()["device_id"]


def test_auth_required_and_wrong_password():
    async def scenario():
        app = create_app(background=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/api/devices")).status_code == 401
            assert (await c.get("/api/devices", headers={"Authorization": "Bearer nope"})).status_code == 401
            assert (await c.post("/api/auth/login", json={"password": "x", "device_name": "a", "device_kind": "cli"})).status_code == 409
        client, device_id = await _client()
        async with aclosing(client):
            bad = await client.post("/api/auth/login", json={"password": "wrong", "device_name": "a", "device_kind": "cli"})
            assert bad.status_code == 401
            me = (await client.get("/api/auth/me")).json()
            assert me["id"] == device_id and me["kind"] == "android" and me["is_me"]
            assert (await client.put("/api/devices/me/push-token", json={"fcm_token": "tok"})).status_code == 204
            devices = (await client.get("/api/devices")).json()
            assert devices[0]["push_enabled"] is True
            assert (await client.post("/api/auth/logout")).status_code == 204
            assert (await client.get("/api/auth/me")).status_code == 401

    run(scenario())


def test_health_and_connections():
    async def scenario():
        client, _ = await _client()
        async with aclosing(client):
            health = (await client.get("/api/health")).json()
            assert health["database"] is True and health["google_connected"] is False
            assert health["tools"] > 0 and health["name"] == "sora"  # the apps find the server by this
            auto = (await client.get("/api/system/autostart")).json()
            assert set(auto) == {"supported", "enabled"}
            conns = (await client.get("/api/connections")).json()
            assert conns[0]["connected"] is False and conns[0]["configured"] is False
            assert [s["id"] for s in conns[0]["services"]] == [
                "gmail", "calendar", "drive", "docs", "sheets", "slides", "tasks", "contacts"]
            assert not any(s["connected"] for s in conns[0]["services"])
            start = await client.post("/api/connections/google/start")
            assert start.status_code == 400 and "GOOGLE_CLIENT_ID" in start.json()["detail"]
            cb = await client.get("/oauth/google/callback", params={"code": "x", "state": "unknown"})
            assert cb.status_code == 400 and "expired" in cb.text

    run(scenario())


def test_per_service_connect_and_toggle():
    from urllib.parse import parse_qs, urlparse

    from sora.config import get_settings
    from sora.models import Connection

    async def scenario():
        s = get_settings()
        s.google_client_id, s.google_client_secret = "cid.apps.googleusercontent.com", "secret"
        try:
            client, _ = await _client()
            async with aclosing(client):
                url = (await client.post("/api/connections/google/start", json={"services": ["sheets"]})).json()["auth_url"]
                q = parse_qs(urlparse(url).query)
                assert q["scope"][0].split() == ["openid", "https://www.googleapis.com/auth/userinfo.email",
                                                 "https://www.googleapis.com/auth/spreadsheets"]
                assert q["include_granted_scopes"] == ["true"] and q["code_challenge_method"] == ["S256"]
                bad = await client.post("/api/connections/google/start", json={"services": ["youtube"]})
                assert bad.status_code == 400 and "Unknown service" in bad.json()["detail"]

                async with session_scope() as session:  # as if Google granted Gmail + Sheets
                    session.add(Connection(provider="google", account_email="me@gmail.com", status="active", scopes=[
                        "https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/spreadsheets"]))
                svc = {x["id"]: x for x in (await client.get("/api/connections")).json()[0]["services"]}
                assert svc["gmail"]["connected"] and svc["sheets"]["connected"] and not svc["slides"]["connected"]

                off = (await client.patch("/api/connections/google/services/gmail", json={"enabled": False})).json()
                svc = {x["id"]: x for x in off["services"]}
                assert svc["gmail"] == {**svc["gmail"], "granted": True, "enabled": False, "connected": False}
                from sora.google.oauth import enabled_services

                async with session_scope() as session:
                    assert await enabled_services(session) == {"sheets"}
                on = (await client.patch("/api/connections/google/services/gmail", json={"enabled": True})).json()
                assert {x["id"] for x in on["services"] if x["connected"]} == {"gmail", "sheets"}
                assert (await client.patch("/api/connections/google/services/nope", json={"enabled": True})).status_code == 404
        finally:
            s.google_client_id, s.google_client_secret = "", ""

    run(scenario())


def test_chat_json_and_sse_and_conversation_history():
    async def scenario():
        runner_module._agent = Agent(llm=FakeLLM([reply("হ্যালো!"), reply("second")]))
        try:
            client, _ = await _client()
            async with aclosing(client):
                resp = await client.post("/api/chat", json={"message": "hello", "stream": False})
                body = resp.json()
                assert body["reply"] == "হ্যালো!" and body["status"] == "complete"
                conv_id = body["conversation_id"]

                async with client.stream("POST", "/api/chat", json={"message": "again", "conversation_id": conv_id}) as stream:
                    assert stream.headers["content-type"].startswith("text/event-stream")
                    raw = "".join([chunk async for chunk in stream.aiter_text()])
                events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
                assert [e["type"] for e in events] == ["conversation", "delta", "message", "done"]

                convs = (await client.get("/api/conversations")).json()
                assert convs[0]["id"] == conv_id and convs[0]["title"] == "hello"
                assert convs[0]["preview"] == "second" and convs[0]["pinned"] is False  # Sora's latest reply
                assert (await client.patch(f"/api/conversations/{conv_id}", json={"pinned": True})).json()["pinned"] is True
                detail = (await client.get(f"/api/conversations/{conv_id}")).json()
                assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
                assert (await client.patch(f"/api/conversations/{conv_id}", json={"title": "Renamed"})).json()["title"] == "Renamed"
                assert (await client.delete(f"/api/conversations/{conv_id}")).status_code == 204
                assert (await client.get(f"/api/conversations/{conv_id}")).status_code == 404
        finally:
            runner_module._agent = None

    run(scenario())


def test_action_approval_endpoint_with_real_registry():
    async def scenario():
        # knowledge_delete requires confirmation; create a note first through the API.
        client, _ = await _client()
        async with aclosing(client):
            note = (await client.post("/api/knowledge/notes", json={"title": "Wifi", "content": "password is hunter2"})).json()
            runner_module._agent = Agent(llm=FakeLLM([
                call("knowledge_delete", json.dumps({"document_id": note["id"], "title": "Wifi"})),
                reply("Deleted the Wifi note."),
            ]))
            try:
                body = (await client.post("/api/chat", json={"message": "delete wifi note", "stream": False})).json()
                assert body["status"] == "awaiting_confirmation"
                pending = (await client.get("/api/actions/pending")).json()
                assert len(pending) == 1 and "Wifi" in pending[0]["summary"]
                done = (await client.post(f"/api/actions/{pending[0]['action_id']}", json={"approve": True, "stream": False})).json()
                assert done["reply"] == "Deleted the Wifi note." and done["status"] == "complete"
                assert (await client.get(f"/api/knowledge/{note['id']}")).status_code == 404
                assert (await client.get("/api/actions/pending")).json() == []
            finally:
                runner_module._agent = None

    run(scenario())


def test_knowledge_memories_reminders_rules_notifications():
    async def scenario():
        client, _ = await _client()
        async with aclosing(client):
            note = (await client.post("/api/knowledge/notes", json={"title": "Thesis", "content": "ResUNet baseline DSC is 82.75"})).json()
            hits = (await client.get("/api/knowledge/search", params={"q": "ResUNet baseline"})).json()
            assert hits and hits[0]["document_id"] == note["id"]
            upd = (await client.patch(f"/api/knowledge/{note['id']}", json={"append": "New result: 84.1"})).json()
            assert "84.1" in upd["content"]
            assert (await client.get("/api/knowledge/search", params={"q": "84.1"})).json()[0]["document_id"] == note["id"]
            up = await client.post("/api/knowledge/upload", files={"file": ("notes.md", "# Notes\nবাংলা লেখা".encode(), "text/markdown")})
            assert up.status_code == 201 and up.json()["title"] == "notes.md"
            assert len((await client.get("/api/knowledge")).json()) == 2

            mem = (await client.post("/api/memories", json={"content": "Prefers Bangla replies", "category": "preference"})).json()
            assert (await client.patch(f"/api/memories/{mem['id']}", json={"content": "Prefers Bangla"})).json()["content"] == "Prefers Bangla"
            assert len((await client.get("/api/memories")).json()) == 1
            assert (await client.delete(f"/api/memories/{mem['id']}")).status_code == 204

            rem = (await client.post("/api/reminders", json={"text": "Submit paper", "due_at": "2026-10-25T09:00"})).json()
            assert rem["due_at"].startswith("2026-10-25T09:00:00+06:00")
            assert (await client.patch(f"/api/reminders/{rem['id']}", json={"status": "cancelled"})).json()["status"] == "cancelled"
            assert (await client.get("/api/reminders")).json() == []

            rule = (await client.post("/api/email-rules", json={"rule": "University mail is important"})).json()
            assert (await client.get("/api/email-rules")).json() == [rule] and rule["active"] is True
            off = (await client.patch(f"/api/email-rules/{rule['id']}", json={"active": False})).json()
            assert (await client.get("/api/email-rules")).json() == [off] and off["active"] is False  # still listed
            assert (await client.delete(f"/api/email-rules/{rule['id']}")).status_code == 204
            assert (await client.get("/api/email-rules")).json() == []

            assert (await client.get("/api/settings/assistant")).json() == {"instructions": "", "tone": "Warm"}
            saved = {"instructions": "Call me Yeasir.", "tone": "Concise"}
            assert (await client.put("/api/settings/assistant", json=saved)).json() == saved
            assert (await client.get("/api/settings/assistant")).json() == saved

            me = (await client.get("/api/me")).json()
            assert set(me) == {"name", "email", "device"} and me["device"]["kind"]

            from sora.services.notifier import notify

            await notify("system", "Test", "body", push=False)
            items = (await client.get("/api/notifications", params={"unread": True})).json()
            assert items[0]["title"] == "Test"
            assert (await client.post("/api/notifications/read-all")).status_code == 204
            assert (await client.get("/api/notifications", params={"unread": True})).json() == []

    run(scenario())


def test_wake_samples(tmp_path, monkeypatch):
    import io
    import wave

    import sora.api.voice as voice_api

    monkeypatch.setattr(voice_api, "samples_dir", lambda: tmp_path)

    def wav(seconds: float) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\0\1" * int(16000 * seconds))
        return buf.getvalue()

    async def scenario():
        client, _ = await _client()
        async with aclosing(client):
            post = lambda kind, data: client.post(  # noqa: E731
                "/api/voice/wake-samples", data={"kind": kind}, files={"audio": ("s.wav", data, "audio/wav")})
            assert (await post("positive", wav(1.5))).json()["positive"] == {"total": 1, "this_device": 1}
            await post("positive", wav(1.5))
            counts = (await post("negative", wav(2))).json()
            assert counts["positive"]["total"] == 2 and counts["negative"]["this_device"] == 1
            assert (await post("other", wav(1))).status_code == 400
            assert (await post("positive", wav(0.2))).status_code == 400  # too short to learn from
            # undo removes the newest take (the negative one)
            counts = (await client.delete("/api/voice/wake-samples/last")).json()
            assert counts["negative"]["total"] == 0 and counts["positive"]["total"] == 2
            assert sorted(p.parent.name for p in tmp_path.rglob("*.wav")) == ["positive", "positive"]

    run(scenario())


def test_wake_model_files(tmp_path, monkeypatch):
    import sora.api.voice as voice_api

    monkeypatch.setattr(voice_api, "wake_model_dir", lambda: tmp_path)

    async def scenario():
        client, _ = await _client()
        async with aclosing(client):
            assert (await client.get("/api/voice/wake-model")).status_code == 404  # not trained yet
            for i, name in enumerate(voice_api.WAKE_MODEL_FILES):
                (tmp_path / name).write_bytes(bytes([i]) * 10)
            info = (await client.get("/api/voice/wake-model")).json()
            assert info["files"] == list(voice_api.WAKE_MODEL_FILES)
            assert info["threshold"] == voice_api.get_settings().wake_threshold  # WAKE_THRESHOLD
            assert (await client.get("/api/voice/wake-model/hey_sora.onnx")).content == bytes([2]) * 10
            assert (await client.get("/api/voice/wake-model/..%2F.env")).status_code == 404
            (tmp_path / "hey_sora.onnx").write_bytes(b"retrained")
            assert (await client.get("/api/voice/wake-model")).json()["version"] != info["version"]

    run(scenario())


def test_clipboard(tmp_path, monkeypatch):
    import sora.services.clipboard as clip

    monkeypatch.setattr(clip, "folder", lambda: tmp_path)
    clip._history.clear()
    clip._last = ("", 0.0)

    async def scenario():
        client, _ = await _client()  # an android device: what it copies goes to the PC
        async with aclosing(client):
            await client.put("/api/clipboard/settings", json={"enabled": True})
            item = (await client.post("/api/clipboard", json={"text": "hello from the phone"})).json()["item"]
            assert item["kind"] == "text" and item["from"] == "phone" and item["device"] == "Pixel"
            # the same text again right away is the PC echoing it back: not a new item
            assert (await client.post("/api/clipboard", json={"text": "hello from the phone"})).json()["item"] is None
            png = b"\x89PNG\r\n\x1a\n" + b"x" * 100
            shot = (await client.post("/api/clipboard/image", files={"image": ("Screenshot.png", png, "image/png")})).json()["item"]
            listing = (await client.get("/api/clipboard")).json()
            assert listing["enabled"] is True and [i["kind"] for i in listing["items"]] == ["image", "text"]
            assert (await client.get(f"/api/clipboard/{shot['id']}/image")).content == png
            # no PC agent online in the test: copying again says so
            assert (await client.post(f"/api/clipboard/{item['id']}/copy")).status_code == 409
            await client.put("/api/clipboard/settings", json={"enabled": False})
            assert (await client.post("/api/clipboard", json={"text": "secret"})).json()["item"] is None
            assert len((await client.get("/api/clipboard")).json()["items"]) == 2
            await client.put("/api/clipboard/settings", json={"enabled": True})
            # deleting one (its picture goes too), then clearing the rest
            assert (await client.delete(f"/api/clipboard/{shot['id']}")).status_code == 204
            assert (await client.get(f"/api/clipboard/{shot['id']}/image")).status_code == 404
            assert (await client.delete(f"/api/clipboard/{shot['id']}")).status_code == 404
            assert (await client.delete("/api/clipboard")).status_code == 204
            assert (await client.get("/api/clipboard")).json()["items"] == []

    run(scenario())


def test_autostart_switch(monkeypatch):
    """The switch's PUT is parsed and reaches the Startup-folder code (stubbed: the real one edits it)."""
    import sora.services.autostart as autostart

    calls = []
    monkeypatch.setattr(autostart, "supported", lambda: True)
    monkeypatch.setattr(autostart, "set_enabled", lambda on: calls.append(on) or on)

    async def scenario():
        client, _ = await _client()
        async with aclosing(client):
            off = await client.put("/api/system/autostart", json={"enabled": False})
            assert off.status_code == 200 and off.json() == {"supported": True, "enabled": False}
            assert (await client.put("/api/system/autostart", json={"enabled": True})).json()["enabled"] is True
            assert calls == [False, True]

    run(scenario())


def test_turn_off_only_from_windows_app(monkeypatch):
    """Turning Sora off is refused from the phone and reaches the shutdown (stubbed) from the PC app."""
    import sora.services.power as power

    calls = []

    async def fake_stop():
        calls.append(1)
        return {"stopping": True, "agents": 0}

    monkeypatch.setattr(power, "stop", fake_stop)

    async def scenario():
        client, _ = await _client()
        async with aclosing(client):
            assert (await client.post("/api/system/stop")).status_code == 403
            resp = await client.post("/api/auth/login", json={"password": PASSWORD, "device_name": "PC", "device_kind": "windows"})
            client.headers["Authorization"] = f"Bearer {resp.json()['token']}"
            assert (await client.post("/api/system/stop")).json() == {"stopping": True, "agents": 0}
            assert calls == [1]

    run(scenario())


def test_phone_told_when_sora_starts(monkeypatch):
    """The phone's last Wi-Fi address is kept (not loopback); at start it and the broadcast addresses
    hear "Sora is on", and a phone that isn't connected keeps hearing it; a wake-up starts a new epoch."""
    import json as _json
    import socket

    from sora.db import session_scope
    from sora.kv import kv_get
    from sora.services import announce

    sent: list[tuple[set, dict]] = []
    monkeypatch.setattr(announce, "_send", lambda targets, message: sent.append((set(targets), _json.loads(message))))
    monkeypatch.setattr(announce, "BURST", (0.05,))
    monkeypatch.setattr(announce, "TICK", 0.05)
    monkeypatch.setattr(announce, "AWAY_FIRST", 0.1)

    async def scenario():
        await announce.remember("phone-1", "127.0.0.1")
        await announce.remember("phone-1", "192.168.0.57")
        async with session_scope() as session:
            assert (await kv_get(session, announce.KEY))["phone-1"] == "192.168.0.57"
        try:
            await asyncio.wait_for(announce.run_forever(), timeout=0.8)
        except TimeoutError:
            pass
        first_epoch = announce.epoch()
        await announce._woke_up()
        assert announce.epoch() != first_epoch

    run(scenario())
    assert sent[0][0] >= {"192.168.0.57", "255.255.255.255"}  # the start-up burst
    assert sum("192.168.0.57" in targets for targets, _ in sent) >= 3  # and again while it's away
    assert sent[0][1]["name"] == "sora" and sent[0][1]["epoch"]

    monkeypatch.undo()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:  # the real send reaches a socket
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(3)
        monkeypatch.setattr(announce, "PORT", listener.getsockname()[1])
        announce._send({"127.0.0.1"}, b'{"name": "sora"}')
        assert _json.loads(listener.recv(512)) == {"name": "sora"}


def test_phone_that_moved_still_hears_sora(monkeypatch):
    """The router gave the phone a new address and its line is down: its next request (any, over HTTP)
    is where "Sora is on" goes now, and the broadcast goes too, in case the PC moved as well."""
    import json as _json

    from sora.db import session_scope
    from sora.kv import kv_get
    from sora.services import announce

    sent: list[set] = []
    monkeypatch.setattr(announce, "_send", lambda targets, message: sent.append(set(targets)))
    monkeypatch.setattr(announce, "_broadcast_addresses", lambda: {"192.168.0.255"})
    monkeypatch.setattr(announce, "BURST", ())
    monkeypatch.setattr(announce, "TICK", 0.05)
    monkeypatch.setattr(announce, "AWAY_FIRST", 0.1)

    async def scenario():
        client, device_id = await _client()
        async with aclosing(client):
            await announce.remember(device_id, "192.168.0.100")  # where its line last came from
            moved = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(background=False), client=("192.168.0.102", 5000)),
                base_url="http://test",
                headers={"Authorization": client.headers["Authorization"]},
            )
            async with aclosing(moved):
                assert (await moved.get("/api/devices")).status_code == 200
            await announce.remember(device_id, "8.8.8.8")  # not on this network: no use saying hello there
        async with session_scope() as session:
            assert (await kv_get(session, announce.KEY))[device_id] == "192.168.0.102"
        try:
            await asyncio.wait_for(announce.run_forever(), timeout=0.5)
        except TimeoutError:
            pass

    run(scenario())
    assert sent and all(targets == {"192.168.0.102", "192.168.0.255"} for targets in sent)
    assert _json.loads(announce._message())["name"] == "sora"


def test_language_preference_and_deleting_notifications(monkeypatch):
    """An app starting up doesn't undo the language chosen elsewhere; Settings does. Notifications can
    be deleted one by one or all at once."""
    from sora.services import app_language
    from sora.services.notifier import notify

    async def no_translation(target):
        return 0

    monkeypatch.setattr(app_language, "translate_recent", no_translation)

    async def scenario():
        client, _ = await _client()
        async with aclosing(client):
            assert (await client.put("/api/preferences/language", json={"language": "en"})).json()["translating"] is True
            started = await client.put("/api/preferences/language", json={"language": "bn", "only_if_unset": True})
            assert started.json() == {"language": "en", "translating": False}
            assert (await client.get("/api/preferences/language")).json() == {"language": "en"}
            assert await app_language.name() == "English"
            first = await notify("email", "One", "body one", push=False)
            await notify("email", "Two", "body two", push=False)
            assert (await client.delete(f"/api/notifications/{first}")).status_code == 204
            assert [n["title"] for n in (await client.get("/api/notifications")).json()] == ["Two"]
            assert (await client.delete(f"/api/notifications/{first}")).status_code == 404
            assert (await client.delete("/api/notifications")).status_code == 204
            assert (await client.get("/api/notifications")).json() == []

    run(scenario())


def test_switching_language_translates_recent_email_notifications(monkeypatch):
    """Only email notifications in the other language go to the model, and come back translated."""
    import types

    from sora.services import app_language
    from sora.services.notifier import notify

    asked = []

    class FakeModel:
        async def complete(self, messages, **_):
            batch = json.loads(messages[1]["content"])
            asked.append(batch)
            return types.SimpleNamespace(content=json.dumps({k: f"EN: {v}" for k, v in batch.items()}))

    monkeypatch.setattr(app_language, "get_llm", lambda: FakeModel())
    monkeypatch.setattr(app_language, "get_settings",
                        lambda: types.SimpleNamespace(llm_configured=True, fast_model="fast", assistant_language="Bangla"))

    async def scenario():
        bangla = await notify("email", "Trip", "ভ্রমণের আমন্ত্রণ", push=False)
        await notify("email", "Code", "Your code is 16971", push=False)
        await notify("reminder", "Call Ammu", "আম্মুকে ফোন", push=False)
        assert await app_language.translate_recent("en") == 1
        async with session_scope() as session:
            from sora.models import Notification
            assert (await session.get(Notification, bangla)).body == "EN: ভ্রমণের আমন্ত্রণ"

    run(scenario())
    assert len(asked) == 1 and list(asked[0].values()) == ["ভ্রমণের আমন্ত্রণ"]
