"""Create a notification, show it live in open apps, and push it to phones."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from sora.db import session_scope
from sora.models import Device, Notification
from sora.services.fcm import UnregisteredToken, get_fcm
from sora.services.hub import hub

log = logging.getLogger(__name__)


def notification_dict(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "importance": n.importance,
        "data": n.data,
        "read": n.read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


async def notify(
    kind: str,
    title: str,
    body: str = "",
    importance: str = "normal",
    data: dict | None = None,
    push: bool = True,
) -> uuid.UUID:
    async with session_scope() as session:
        n = Notification(kind=kind, title=title, body=body, importance=importance, data=data or {})
        session.add(n)
        await session.flush()
        await session.refresh(n)
        payload = notification_dict(n)
        devices = (
            (await session.execute(select(Device).where(Device.fcm_token.is_not(None), Device.revoked.is_(False))))
            .scalars()
            .all()
        )
        tokens = [(d.id, d.fcm_token) for d in devices]

    # Open apps get it instantly; they decide whether to speak it aloud.
    await hub.broadcast({"type": "notification", "notification": payload})

    if push and importance != "low":
        fcm = get_fcm()
        for device_id, token in tokens:
            try:
                await fcm.send(
                    token,
                    title,
                    body,
                    data={"notification_id": payload["id"], "kind": kind, "importance": importance},
                    high_priority=importance == "high",
                )
            except UnregisteredToken:
                async with session_scope() as session:
                    device = await session.get(Device, device_id)
                    if device is not None:
                        device.fcm_token = None
            except Exception as exc:
                log.warning("push failed: %s", exc)
    return n.id
