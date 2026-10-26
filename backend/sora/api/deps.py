"""Shared API dependencies: device-token auth and SSE helpers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sora.db import get_session, session_scope
from sora.models import Device
from sora.security import hash_token
from sora.services import announce

SEEN_UPDATE_EVERY = timedelta(minutes=2)


def extract_token(authorization: str | None, query_token: str | None = None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return query_token


async def device_for_token(session: AsyncSession, token: str | None) -> Device | None:
    if not token:
        return None
    device = (
        await session.execute(select(Device).where(Device.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if device is None or device.revoked:
        return None
    now = datetime.now(UTC)
    if device.last_seen_at is None or now - device.last_seen_at > SEEN_UPDATE_EVERY:
        device.last_seen_at = now
    return device


async def current_device(request: Request, session: AsyncSession = Depends(get_session)) -> Device:
    token = extract_token(request.headers.get("authorization"))
    device = await device_for_token(session, token)
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing device token", headers={"WWW-Authenticate": "Bearer"})
    if device.kind == "android" and request.client:
        # The phone's address now, even while its line is down: "Sora is on" goes there.
        await announce.remember(str(device.id), request.client.host)
    return device


async def authenticate_ws(token: str | None) -> Device | None:
    async with session_scope() as session:
        return await device_for_token(session, token)


def sse(events: AsyncIterator[dict]) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        async for event in events:
            payload = json.dumps(event, ensure_ascii=False, default=str)
            yield f"event: {event.get('type', 'message')}\ndata: {payload}\n\n".encode()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def collect(events: AsyncIterator[dict]) -> dict:
    """Non-streaming variant: run the turn and return the final reply plus every event."""
    all_events: list[dict] = []
    reply_parts: list[str] = []
    conversation_id = None
    state = "complete"
    async for event in events:
        if event["type"] == "delta":
            continue
        all_events.append(event)
        if event["type"] == "conversation":
            conversation_id = event["id"]
        elif event["type"] == "message":
            reply_parts.append(event["content"])
        elif event["type"] == "done":
            state = event["status"]
    return {
        "conversation_id": conversation_id,
        "reply": "\n\n".join(reply_parts),
        "status": state,
        "events": all_events,
    }
