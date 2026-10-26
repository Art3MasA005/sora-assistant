"""Live WebSocket connections to the apps and PC agents, plus request/response commands over them."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)

APP_KINDS = ("android", "windows", "cli")


class DeviceOffline(RuntimeError):
    pass


class CommandTimeout(RuntimeError):
    pass


@dataclass
class LiveClient:
    device_id: uuid.UUID
    name: str
    kind: str
    ws: WebSocket
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    info: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, event: dict) -> None:
        async with self.lock:
            await self.ws.send_json(event)


class Hub:
    def __init__(self) -> None:
        self.clients: dict[uuid.UUID, LiveClient] = {}
        self._pending: dict[str, asyncio.Future] = {}

    def register(self, client: LiveClient) -> None:
        old = self.clients.get(client.device_id)
        if old is not None and old.ws is not client.ws:
            asyncio.create_task(_close_quietly(old.ws))
        self.clients[client.device_id] = client
        log.info("device online: %s (%s)", client.name, client.kind)

    def unregister(self, client: LiveClient) -> None:
        if self.clients.get(client.device_id) is client:
            del self.clients[client.device_id]
            log.info("device offline: %s (%s)", client.name, client.kind)

    def online(self, kinds: tuple[str, ...] | None = None) -> list[LiveClient]:
        return [c for c in self.clients.values() if kinds is None or c.kind in kinds]

    def is_online(self, device_id: uuid.UUID) -> bool:
        return device_id in self.clients

    async def send(self, device_id: uuid.UUID, event: dict) -> bool:
        client = self.clients.get(device_id)
        if client is None:
            return False
        try:
            await client.send(event)
            return True
        except Exception as exc:  # socket died mid-send
            log.info("send to %s failed: %s", client.name, exc)
            self.unregister(client)
            return False

    async def broadcast(self, event: dict, kinds: tuple[str, ...] = APP_KINDS) -> int:
        sent = 0
        for client in self.online(kinds):
            if await self.send(client.device_id, event):
                sent += 1
        return sent

    async def command(self, device_id: uuid.UUID, action: str, params: dict, timeout: float = 30) -> Any:
        """Send a command to a device and wait for its result message."""
        if device_id not in self.clients:
            raise DeviceOffline("That device is not connected right now.")
        command_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[command_id] = future
        try:
            ok = await self.send(device_id, {"type": "command", "id": command_id, "action": action, "params": params})
            if not ok:
                raise DeviceOffline("That device disconnected.")
            return await asyncio.wait_for(future, timeout)
        except TimeoutError as exc:
            raise CommandTimeout(f"The device did not answer within {timeout:.0f}s.") from exc
        finally:
            self._pending.pop(command_id, None)

    def resolve(self, command_id: str, message: dict) -> None:
        future = self._pending.get(command_id)
        if future is None or future.done():
            return
        if message.get("ok", True):
            future.set_result(message.get("data"))
        else:
            future.set_exception(RuntimeError(message.get("error") or "the device reported an error"))


async def _close_quietly(ws: WebSocket) -> None:
    try:
        await ws.close(code=4000, reason="replaced by a newer connection")
    except Exception:
        pass


hub = Hub()
