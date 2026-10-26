"""The phone's notifications on the PC (see services/phone_notifications.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from sora.api.deps import current_device
from sora.models import Device
from sora.services import phone_notifications

router = APIRouter(prefix="/api/phone-notifications", tags=["phone notifications"])


@router.get("")
async def list_phone_notifications(device: Device = Depends(current_device)):
    """Newest first: {id, key, app, package, title, text, replyable, device, at}; new ones also come over
    the WebSocket as {"type": "phone_notification", "notification": ...}."""
    return {"toast": await phone_notifications.toast_enabled(), "items": phone_notifications.history()}


class SettingsIn(BaseModel):
    toast: bool


@router.put("/settings")
async def phone_notification_settings(body: SettingsIn, device: Device = Depends(current_device)):
    """Whether the PC agent shows each one as a Windows toast."""
    await phone_notifications.set_toast_enabled(body.toast)
    return {"toast": body.toast}


@router.delete("", status_code=204)
async def clear_phone_notifications(device: Device = Depends(current_device)):
    phone_notifications.clear()
