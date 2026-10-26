"""The phone's notifications (WhatsApp, Messenger, SMS...) on the PC.

The phone's notification listener sends each one over its open WebSocket ("phone_notification").
Here they go to the Windows app's Details panel, to a Windows toast through the PC agent (when that
is on), to routines waiting for them, and to Sora ("what came on WhatsApp?", "reply to Ammu").

Kept in memory only (the last 100): they hold private messages, so they are never written to the
database and are gone when the server restarts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from datetime import UTC, datetime

from sora.db import session_scope
from sora.kv import kv_get, kv_set
from sora.models import Device
from sora.services.hub import hub

log = logging.getLogger(__name__)

KEEP = 100
MAX_TEXT = 1000
TOAST_KEY = "phone_notifications_toast"
# Messages that arrive within this many seconds become one toast (a chat sends several at once).
TOAST_GATHER = 2.0
PC_KINDS = ("pc_agent",)

_history: deque[dict] = deque(maxlen=KEEP)
_toast_waiting: list[dict] = []
_toast_task: asyncio.Task | None = None


def history(app: str | None = None, limit: int | None = None) -> list[dict]:
    """Newest first; [app] matches the app's name or package ("whatsapp")."""
    wanted = (app or "").strip().casefold()
    items = [dict(i) for i in _history if not wanted or wanted in i["app"].casefold() or wanted in i["package"]]
    return items[:limit] if limit else items


def clear() -> None:
    _history.clear()


async def toast_enabled() -> bool:
    async with session_scope() as session:
        return bool(await kv_get(session, TOAST_KEY, True))


async def set_toast_enabled(on: bool) -> None:
    async with session_scope() as session:
        await kv_set(session, TOAST_KEY, bool(on))


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


async def add(device: Device, message: dict) -> dict | None:
    """A notification the phone sent. None when it is empty or the same one again."""
    item = {
        "id": uuid.uuid4().hex[:12],
        "key": _text(message.get("key"), 300),
        "app": _text(message.get("app"), 60) or _text(message.get("package"), 60),
        "package": _text(message.get("package"), 120),
        "title": _text(message.get("title"), 200),
        "text": _text(message.get("text"), MAX_TEXT),
        "replyable": bool(message.get("replyable")),
        "device": device.name,
        "at": datetime.now(UTC).isoformat(),
    }
    if not item["title"] and not item["text"]:
        return None
    if any(old["key"] == item["key"] and old["text"] == item["text"] for old in list(_history)[:10]):
        return None  # re-posted unchanged (the phone drops most of these already)
    _history.appendleft(item)
    await hub.broadcast({"type": "phone_notification", "notification": item}, kinds=("windows",))
    if await toast_enabled():
        _queue_toast(item)
    from sora.services import routines  # routines imports the agent, which imports the tools that use this module

    try:
        await routines.phone_notification(item)
    except Exception:
        log.exception("phone notification routines failed")
    return item


# ---------------------------------------------------------------- the Windows toast


def _queue_toast(item: dict) -> None:
    global _toast_task
    _toast_waiting.append(item)
    if _toast_task is None or _toast_task.done():
        _toast_task = asyncio.create_task(_toast_soon(), name="phone-notification-toast")


def toast_for(items: list[dict]) -> tuple[str, str]:
    """(title, text) of one toast for [items]: the message itself, or a count and who sent them."""
    if len(items) == 1:
        one = items[0]
        return (f"{one['app']}: {one['title']}" if one["title"] else one["app"]), one["text"]
    senders: list[str] = []
    for i in items:
        who = f"{i['app']}: {i['title']}" if i["title"] else i["app"]
        if who not in senders:
            senders.append(who)
    return f"{len(items)} new on the phone", ", ".join(senders[:4]) + ("…" if len(senders) > 4 else "")


async def _toast_soon() -> None:
    await asyncio.sleep(TOAST_GATHER)
    items = list(_toast_waiting)
    _toast_waiting.clear()
    if not items:
        return
    title, text = toast_for(items)
    for client in hub.online(PC_KINDS):
        try:
            await hub.command(client.device_id, "toast", {"title": title, "text": text}, timeout=15)
        except Exception as exc:  # an older PC agent has no "toast"
            log.info("phone notification toast on %s failed: %s", client.name, exc)


# ---------------------------------------------------------------- replying


def describe(target: str | None) -> str:
    """"Ammu (WhatsApp)" for a notification key or a name, for approval prompts."""
    found = _find(target)
    if isinstance(found, dict):
        return f"{found['title'] or found['app']} ({found['app']})"
    return target or ""


def reply_key(target: str | None) -> str | None:
    """The key of the notification to reply to: [target] is its key, or the person or chat as its
    title shows (the newest one that can be replied to). Raises ValueError saying what is wrong."""
    found = _find(target)
    if isinstance(found, str):
        raise ValueError(found)
    if not found["replyable"]:
        raise ValueError(f"the {found['app']} notification from {found['title']} has no reply button")
    return found["key"]


def _find(target: str | None) -> dict | str:
    want = (target or "").strip()
    if not want:
        return "reply to which notification? (its key, or the person's name)"
    items = list(_history)
    for i in items:
        if i["key"] == want:
            return i
    folded = want.casefold()
    named = [i for i in items if i["title"].casefold() == folded] or [i for i in items if folded in i["title"].casefold()]
    replyable = [i for i in named if i["replyable"]]
    if replyable:
        return replyable[0]  # the newest
    if named:
        return named[0]
    recent = ", ".join(list(dict.fromkeys(f"{i['title']} ({i['app']})" for i in items if i["replyable"]))[:5])
    return f"no recent phone notification from {want}" + (f"; recent ones to reply to: {recent}" if recent else "")
