"""Telling the phone Sora is on, so it connects at once instead of at its next retry, like Phone
Link does when the PC comes on.

The phone's accessibility service listens on UDP port 48765 (app/packages/sora_phone SoraLink) for
{"name": "sora", "port": <port>, "epoch": <id>}. The server sends it
- right after it starts, a few times, to each phone's last address (phones' Wi-Fi drops broadcasts
  while the screen is off) and to the Wi-Fi broadcast addresses;
- after the PC wakes from sleep, with a new epoch: the phones' connections from before are dead,
  so they are closed here and the phones (which compare the epoch with their connection's) reconnect;
- now and then to a phone that isn't connected: often at first, then less (every 2 min at most), to
  its last address and to the Wi-Fi broadcast addresses too, so it still hears when either side got a
  new address from the router.
A phone's address is taken from any request it makes, not only its WebSocket: a phone whose line is
down still asks things over HTTP while the app is open, and that is its new address.
The phone then checks /api/health and its token as usual, so a stray packet can't send it anywhere.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import platform
import socket
import time
import uuid

from sqlalchemy import select

from sora.config import get_settings
from sora.db import session_scope
from sora.kv import kv_get, kv_set
from sora.models import Device
from sora.services import routines
from sora.services.hub import hub

log = logging.getLogger(__name__)

PORT = 48765
KEY = "phone_addresses"  # {device id: last IP it connected from}
PHONE_KINDS = ("android",)
BURST = (0.3, 1, 2, 4, 8, 15)  # seconds after start / wake-up
AWAY_FIRST, AWAY_MAX = 3.0, 120.0  # the pause between hellos to a phone that isn't connected
TICK = 0.5
BROADCAST_REFRESH = 300.0  # seconds: the PC's own addresses can change too (DHCP, Wi-Fi to cable)

_known: dict[str, str] | None = None  # {device id: last IP}, as saved under KEY; loaded once

_epoch = uuid.uuid4().hex[:12]


_pc_name: str | None = None


async def pc_name() -> str:
    """What the phone calls this PC ("Connected to Yeasir's PC"): the PC agent's name, else the host's."""
    global _pc_name
    if _pc_name is None:
        name = ""
        try:
            async with session_scope() as session:
                name = (await session.execute(
                    select(Device.name).where(Device.kind == "pc_agent").order_by(Device.created_at).limit(1)
                )).scalar_one_or_none() or ""
        except Exception:
            pass
        _pc_name = name or platform.node()
    return _pc_name


def epoch() -> str:
    """This run of the server (new after the PC slept): sent in the WebSocket hello too."""
    return _epoch


async def remember(device_id: str, host: str | None) -> None:
    """A phone was heard from [host]: tell it there next time. Called on every phone request, so an
    unchanged address costs a dict lookup; only a new one is written."""
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return
    if ip.is_loopback or ip.version != 4 or not ip.is_private:
        return  # a hello only reaches a phone on this network
    known = await _phones()
    if known.get(device_id) == str(ip):
        return
    known[device_id] = str(ip)
    try:
        async with session_scope() as session:
            await kv_set(session, KEY, dict(known))
    except Exception:
        log.warning("could not save the phone's new address", exc_info=True)


async def _phones() -> dict[str, str]:
    """The phones' last addresses: the same dict each time, which [remember] updates in place."""
    global _known
    if _known is None:
        try:
            async with session_scope() as session:
                _known = dict(await kv_get(session, KEY, {}) or {})
        except Exception:
            return {}
    return _known


def _broadcast_addresses() -> set[str]:
    """x.y.z.255 for each of this PC's private IPv4 addresses (/24, as home routers use), plus the
    plain broadcast address."""
    found = {"255.255.255.255"}
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return found
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private and not ip.is_loopback:
            found.add(str(ipaddress.ip_network(f"{ip}/24", strict=False).broadcast_address))
    return found


def _message() -> bytes:
    return json.dumps({"name": "sora", "port": get_settings().port, "epoch": _epoch}).encode()


def _send(targets: set[str], message: bytes) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in targets:
            try:
                s.sendto(message, (target, PORT))
            except OSError:
                pass  # that network isn't up


async def _woke_up() -> None:
    """The PC slept: every phone connection is from before and dead (the phone may not know)."""
    global _epoch
    _epoch = uuid.uuid4().hex[:12]
    for client in hub.online(PHONE_KINDS):
        with contextlib.suppress(Exception):
            await client.ws.close(code=1012, reason="the PC woke up")
        hub.unregister(client)


async def run_forever() -> None:
    """Hello bursts at start and after sleep, and hellos to phones that aren't connected."""
    phones = await _phones()  # kept up to date by remember()
    broadcast = await asyncio.to_thread(_broadcast_addresses)
    broadcast_at = time.monotonic()
    burst = [time.monotonic() + at for at in BURST]
    pause: dict[str, float] = {}  # device id -> current pause while away
    next_at: dict[str, float] = {}
    wall = time.time()
    while True:
        await asyncio.sleep(TICK)
        now = time.monotonic()
        if time.time() - wall > 30:  # the loop didn't run for a while: the PC was asleep
            log.info("the PC woke up: telling the phone(s)")
            await _woke_up()
            routines.pc_woke()
            broadcast_at = float("-inf")  # it may have woken on another network
            burst = [now + at for at in BURST]
            pause.clear()
            next_at.clear()
        wall = time.time()
        targets: set[str] = set()
        to_all = False  # the broadcast addresses too
        if burst and now >= burst[0]:
            burst.pop(0)
            targets |= set(phones.values())
            to_all = True
        online = {str(c.device_id) for c in hub.online(PHONE_KINDS)}
        for device_id, ip in list(phones.items()):
            if device_id in online:
                pause[device_id] = AWAY_FIRST  # quick again once it drops
                next_at[device_id] = now + AWAY_FIRST
            elif now >= next_at.setdefault(device_id, now + AWAY_FIRST):
                # its last address, and the broadcast in case the phone (or this PC) moved since
                targets.add(ip)
                to_all = True
                pause[device_id] = min(AWAY_MAX, pause.get(device_id, AWAY_FIRST) * 1.6)
                next_at[device_id] = now + pause[device_id]
        if to_all:
            if now - broadcast_at > BROADCAST_REFRESH:
                broadcast, broadcast_at = await asyncio.to_thread(_broadcast_addresses), now
            targets |= broadcast
        if targets:
            await asyncio.to_thread(_send, targets, _message())
