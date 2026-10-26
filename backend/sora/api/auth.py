"""Owner login (password → per-device token) and device management."""

from __future__ import annotations

import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sora.api.deps import current_device
from sora.db import get_session
from sora.kv import kv_get
from sora.models import Device
from sora.security import hash_token, new_device_token, verify_password
from sora.services.hub import hub

router = APIRouter(prefix="/api", tags=["auth & devices"])

PASSWORD_KEY = "owner_password_hash"

# Brute-force guard: after 5 failures from one address, wait out a growing lockout.
_failures: dict[str, tuple[int, float]] = {}


def _check_lockout(ip: str) -> None:
    count, until = _failures.get(ip, (0, 0.0))
    if until > time.time():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many attempts. Try again in {int(until - time.time())}s.")


def _record_failure(ip: str) -> None:
    count, _ = _failures.get(ip, (0, 0.0))
    count += 1
    lock = 0.0 if count < 5 else min(3600, 30 * 2 ** (count - 5))
    _failures[ip] = (count, time.time() + lock)


class LoginIn(BaseModel):
    password: str
    device_name: str = Field(max_length=100)
    device_kind: Literal["android", "windows", "pc_agent", "cli"]


class LoginOut(BaseModel):
    token: str
    device_id: uuid.UUID


@router.post("/auth/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)):
    ip = request.client.host if request.client else "?"
    _check_lockout(ip)
    stored = await kv_get(session, PASSWORD_KEY)
    if not stored:
        raise HTTPException(status.HTTP_409_CONFLICT, "No password set yet. Run `python -m sora setup` on the server.")
    if not verify_password(body.password, stored):
        _record_failure(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")
    _failures.pop(ip, None)
    token = new_device_token()
    device = Device(name=body.device_name, kind=body.device_kind, token_hash=hash_token(token))
    session.add(device)
    await session.flush()
    return LoginOut(token=token, device_id=device.id)


def _device_out(d: Device, me: Device | None = None) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "kind": d.kind,
        "online": hub.is_online(d.id),
        "push_enabled": bool(d.fcm_token),
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "is_me": me is not None and d.id == me.id,
    }


@router.get("/auth/me")
async def me(device: Device = Depends(current_device)):
    return _device_out(device, device)


@router.post("/auth/logout", status_code=204)
async def logout(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    d = await session.get(Device, device.id)
    d.revoked = True
    d.fcm_token = None


@router.get("/devices")
async def list_devices(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Device).where(Device.revoked.is_(False)).order_by(Device.created_at))).scalars()
    return [_device_out(d, device) for d in rows]


class DevicePatch(BaseModel):
    name: str | None = Field(None, max_length=100)


@router.patch("/devices/{device_id}")
async def rename_device(device_id: uuid.UUID, body: DevicePatch, device: Device = Depends(current_device),
                        session: AsyncSession = Depends(get_session)):
    d = await session.get(Device, device_id)
    if d is None or d.revoked:
        raise HTTPException(404, "No such device")
    if body.name:
        d.name = body.name
    return _device_out(d, device)


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(device_id: uuid.UUID, device: Device = Depends(current_device),
                        session: AsyncSession = Depends(get_session)):
    d = await session.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "No such device")
    d.revoked = True
    d.fcm_token = None
    client = hub.clients.get(device_id)
    if client is not None:
        await client.ws.close(code=4001, reason="revoked")


class PushTokenIn(BaseModel):
    fcm_token: str | None


@router.put("/devices/me/push-token", status_code=204)
async def set_push_token(body: PushTokenIn, device: Device = Depends(current_device),
                         session: AsyncSession = Depends(get_session)):
    d = await session.get(Device, device.id)
    d.fcm_token = body.fcm_token


class CommandIn(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)
    timeout: float = Field(30, ge=1, le=120)


@router.post("/devices/{device_id}/command")
async def direct_command(device_id: uuid.UUID, body: CommandIn, device: Device = Depends(current_device)):
    """Run a device command without the LLM (for buttons in the app's UI)."""
    from sora.services.hub import CommandTimeout, DeviceOffline

    try:
        result = await hub.command(device_id, body.action, body.params, body.timeout)
    except DeviceOffline as exc:
        raise HTTPException(409, str(exc)) from exc
    except CommandTimeout as exc:
        raise HTTPException(504, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "result": result}
