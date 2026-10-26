"""One clipboard for the phone and the PC.

Copied on the phone (text, or a new screenshot) → put on the PC's clipboard by the PC agent, so
Ctrl+V pastes it. Copied on the PC (text or an image) → put on the phone's clipboard. Every item also lands in a
short history the Windows app shows (Details → Clipboard), with a button to copy it again.

The history (last 20) is kept in memory only — clipboards hold passwords and private messages —
except images, which are files in data/clipboard/ until they drop out of it.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from sora.config import get_settings
from sora.db import session_scope
from sora.kv import kv_get, kv_set
from sora.models import Device
from sora.services.hub import APP_KINDS, hub

log = logging.getLogger(__name__)

KEEP = 20
MAX_TEXT = 20000
PHONE_KINDS = ("android",)
PC_KINDS = ("pc_agent",)

_history: deque[dict] = deque(maxlen=KEEP)
_last: tuple[str, float] = ("", 0.0)  # (what, when) of the newest item, to stop echoes
_image_to_pc_at = 0.0  # when an image was last put on the PC's clipboard (it re-encodes it: no byte match)


def folder() -> Path:
    path = get_settings().data_dir / "clipboard"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def enabled() -> bool:
    async with session_scope() as session:
        return bool(await kv_get(session, "clipboard_sync", True))


async def set_enabled(on: bool) -> None:
    async with session_scope() as session:
        await kv_set(session, "clipboard_sync", bool(on))
    # a phone with the app closed hears it now (its background line keeps the setting)
    for client in hub.online(PHONE_KINDS):
        try:
            await hub.command(client.device_id, "clipboard_sync", {"on": bool(on)}, timeout=10)
        except Exception as exc:
            log.info("clipboard setting to %s failed: %s", client.name, exc)


def history() -> list[dict]:
    return [dict(item) for item in _history]


def get(item_id: str) -> dict | None:
    return next((item for item in _history if item["id"] == item_id), None)


def remove(item_id: str) -> bool:
    """Takes an item out of the history (and its picture off the disk); False if it wasn't there."""
    item = get(item_id)
    if item is None:
        return False
    _history.remove(item)
    if item["kind"] == "image":
        image_path(item).unlink(missing_ok=True)
    return True


def clear() -> None:
    for item in list(_history):
        remove(item["id"])


def image_path(item: dict) -> Path:
    return folder() / f"{item['id']}.png"


def _side(kind: str) -> str:
    return "phone" if kind in PHONE_KINDS else "pc"


async def add(source: Device, *, text: str | None = None, png: bytes | None = None, name: str = "") -> dict | None:
    """Keeps a copied item and puts it on the other side's clipboard. None when it was just the
    echo of an item the other side received a moment ago, or sync is off."""
    global _last
    key = f"text:{text}" if text is not None else f"png:{len(png or b'')}:{hash(png)}"
    if key == _last[0] and time.time() - _last[1] < 10:
        return None  # the PC (or phone) reporting what Sora itself just put on its clipboard
    if png is not None and source.kind in PC_KINDS and time.time() - _image_to_pc_at < 6:
        return None
    if not await enabled():
        return None
    _last = (key, time.time())
    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": "text" if text is not None else "image",
        "from": _side(source.kind),
        "device": source.name,
        "at": datetime.now(UTC).isoformat(),
    }
    if text is not None:
        item["text"] = text[:MAX_TEXT]
    else:
        item["name"] = name or "screenshot.png"
        image_path(item).write_bytes(png or b"")
    if len(_history) == KEEP:
        old = _history[-1]
        if old["kind"] == "image":
            image_path(old).unlink(missing_ok=True)
    _history.appendleft(item)
    asyncio.create_task(_deliver(item), name="clipboard-deliver")
    return item


async def _deliver(item: dict) -> None:
    targets = PC_KINDS if item["from"] == "phone" else PHONE_KINDS
    for client in hub.online(targets):
        try:
            await put_on(client.device_id, item)
        except Exception as exc:  # offline / busy clipboard: the history still has it
            log.info("clipboard to %s failed: %s", client.name, exc)
    await hub.broadcast({"type": "clipboard", "item": item}, kinds=APP_KINDS)


async def put_on(device_id: uuid.UUID, item: dict) -> None:
    """Puts [item] (text or an image) on that device's clipboard, the PC agent's or the phone's."""
    global _last, _image_to_pc_at
    client = hub.clients.get(device_id)
    phone = bool(client and client.kind in PHONE_KINDS)
    if item["kind"] == "text":
        action = "set_clipboard" if phone else "clipboard_set"
        await hub.command(device_id, action, {"text": item["text"]}, timeout=15)
        _last = (f"text:{item['text']}", time.time())
    else:
        png = image_path(item).read_bytes()
        action = "set_clipboard_image" if phone else "clipboard_image"
        if not phone:
            _image_to_pc_at = time.time()
        await hub.command(device_id, action, {"png_base64": base64.b64encode(png).decode()}, timeout=30)


async def pc_ids() -> list[uuid.UUID]:
    return [c.device_id for c in hub.online(PC_KINDS)]
