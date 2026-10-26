"""WebSocket for live events (apps) and commands (PC agent, phone).

Connect: ws(s)://<server>/ws  with header `Authorization: Bearer <token>` (or ?token=<token>).

Server → client:  {"type": "hello"} · {"type": "notification", ...} · {"type": "connection_updated", ...}
                  {"type": "command", "id", "action", "params"} · {"type": "ping"}
Client → server:  {"type": "result", "id", "ok", "data" | "error"} · {"type": "pong"} · {"type": "info", ...}
                  {"type": "status", "battery": 0-100, "charging": bool}   the phone, when its battery changes
                  {"type": "phone_notification", "key", "app", "package", "title", "text", "replyable"}   the phone
                  {"type": "pc_event", "event": "download_done" | "training_done", ...}   the PC agent
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from sora.api.deps import authenticate_ws, extract_token
from sora.services import announce, pc_events, phone_notifications, routines
from sora.services.hub import LiveClient, hub

log = logging.getLogger(__name__)
router = APIRouter()

PING_EVERY = 25


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str | None = None):
    device = await authenticate_ws(extract_token(ws.headers.get("authorization"), token))
    await ws.accept()  # accept first so the client receives the 4401 code instead of a bare HTTP 403
    if device is None:
        await ws.close(code=4401, reason="invalid token")
        return
    client = LiveClient(device_id=device.id, name=device.name, kind=device.kind, ws=ws)
    hub.register(client)
    routines.device_connected(device.id, device.kind)
    await client.send({
        "type": "hello", "device_id": str(device.id), "name": device.name,
        "epoch": announce.epoch(), "server": await announce.pc_name(),
    })
    if device.kind == "android" and ws.client is not None:
        with contextlib.suppress(Exception):
            await announce.remember(str(device.id), ws.client.host)  # where to say "Sora is on" next time
    await hub.broadcast({"type": "device_status", "device_id": str(device.id), "name": device.name, "online": True})

    async def pinger() -> None:
        while True:
            await asyncio.sleep(PING_EVERY)
            await client.send({"type": "ping"})

    ping_task = asyncio.create_task(pinger())
    try:
        while True:
            message = await ws.receive_json()
            kind = message.get("type")
            if kind == "result" and message.get("id"):
                hub.resolve(message["id"], message)
            elif kind == "info":
                client.info = {k: v for k, v in message.items() if k != "type"}
            elif kind == "status" and device.kind == "android":
                await routines.phone_status(message.get("battery"), message.get("charging"))
            elif kind == "phone_notification" and device.kind == "android":
                await phone_notifications.add(device, message)
            elif kind == "pc_event" and device.kind == "pc_agent":
                await pc_events.handle(device, message)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.info("websocket for %s closed: %s", device.name, exc)
    finally:
        ping_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ping_task
        hub.unregister(client)
        if not hub.is_online(device.id):
            routines.device_disconnected(device.id, device.kind)
            await hub.broadcast({"type": "device_status", "device_id": str(device.id), "name": device.name, "online": False})
