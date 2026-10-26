"""Notifications, reminders, email rules and how Sora should respond."""

from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sora.api.deps import current_device
from sora.db import get_session
from sora.kv import kv_get, kv_set
from sora.config import get_settings
from sora.models import Connection, Device, EmailRule, Notification, Reminder
from sora.services import app_language
from sora.services.notifier import notification_dict
from sora.timeutil import parse_datetime

router = APIRouter(prefix="/api", tags=["notifications, reminders, rules"])


# ---------------------------------------------------------------- notifications


@router.get("/notifications")
async def list_notifications(unread: bool = False, kind: str | None = None, limit: int = 50, offset: int = 0,
                             device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    stmt = select(Notification)
    if unread:
        stmt = stmt.where(Notification.read.is_(False))
    if kind:
        stmt = stmt.where(Notification.kind == kind)
    rows = (await session.execute(stmt.order_by(Notification.created_at.desc()).limit(min(limit, 200)).offset(offset))).scalars()
    return [notification_dict(n) for n in rows]


@router.post("/notifications/{notification_id}/read", status_code=204)
async def mark_read(notification_id: uuid.UUID, device: Device = Depends(current_device),
                    session: AsyncSession = Depends(get_session)):
    n = await session.get(Notification, notification_id)
    if n is None:
        raise HTTPException(404, "No such notification")
    n.read = True


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    await session.execute(update(Notification).where(Notification.read.is_(False)).values(read=True))


@router.delete("/notifications/{notification_id}", status_code=204)
async def delete_notification(notification_id: uuid.UUID, device: Device = Depends(current_device),
                              session: AsyncSession = Depends(get_session)):
    n = await session.get(Notification, notification_id)
    if n is None:
        raise HTTPException(404, "No such notification")
    await session.delete(n)


@router.delete("/notifications", status_code=204)
async def delete_all_notifications(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(Notification))


# ---------------------------------------------------------------- the apps' language


class LanguageIn(BaseModel):
    language: Literal["en", "bn"]
    only_if_unset: bool = False  # an app starting up (vs the owner changing it in Settings)


_translating: set[asyncio.Task] = set()


@router.get("/preferences/language")
async def get_language(device: Device = Depends(current_device)):
    return {"language": await app_language.code()}


@router.put("/preferences/language")
async def put_language(body: LanguageIn, device: Device = Depends(current_device)):
    """The app's language changed (or the app started): email summaries follow it, and recent
    notifications in the other language are translated in the background."""
    if await app_language.set_code(body.language, only_if_unset=body.only_if_unset):
        task = asyncio.create_task(app_language.translate_recent(body.language), name="translate-notifications")
        _translating.add(task)
        task.add_done_callback(_translating.discard)
        return {"language": body.language, "translating": True}
    return {"language": await app_language.code(), "translating": False}


# ---------------------------------------------------------------- reminders


def _reminder_out(r: Reminder) -> dict:
    return {"id": str(r.id), "text": r.text, "due_at": r.due_at.isoformat(), "repeat": r.repeat, "status": r.status}


@router.get("/reminders")
async def list_reminders(include_done: bool = False, device: Device = Depends(current_device),
                         session: AsyncSession = Depends(get_session)):
    stmt = select(Reminder).order_by(Reminder.due_at)
    if not include_done:
        stmt = stmt.where(Reminder.status == "scheduled")
    return [_reminder_out(r) for r in (await session.execute(stmt)).scalars()]


class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    due_at: str = Field(description="ISO datetime; local time if no offset")
    repeat: Literal["none", "daily", "weekly"] = "none"


@router.post("/reminders", status_code=201)
async def create_reminder(body: ReminderIn, device: Device = Depends(current_device),
                          session: AsyncSession = Depends(get_session)):
    try:
        due = parse_datetime(body.due_at)
    except ValueError as exc:
        raise HTTPException(422, "due_at must be an ISO datetime") from exc
    r = Reminder(text=body.text, due_at=due, repeat=body.repeat)
    session.add(r)
    await session.flush()
    return _reminder_out(r)


class ReminderPatch(BaseModel):
    text: str | None = None
    due_at: str | None = None
    repeat: Literal["none", "daily", "weekly"] | None = None
    status: Literal["scheduled", "cancelled", "done"] | None = None


@router.patch("/reminders/{reminder_id}")
async def update_reminder(reminder_id: uuid.UUID, body: ReminderPatch, device: Device = Depends(current_device),
                          session: AsyncSession = Depends(get_session)):
    r = await session.get(Reminder, reminder_id)
    if r is None:
        raise HTTPException(404, "No such reminder")
    if body.text is not None:
        r.text = body.text
    if body.due_at is not None:
        r.due_at = parse_datetime(body.due_at)
    if body.repeat is not None:
        r.repeat = body.repeat
    if body.status is not None:
        r.status = body.status
    return _reminder_out(r)


@router.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder(reminder_id: uuid.UUID, device: Device = Depends(current_device),
                          session: AsyncSession = Depends(get_session)):
    r = await session.get(Reminder, reminder_id)
    if r is None:
        raise HTTPException(404, "No such reminder")
    await session.delete(r)


# ---------------------------------------------------------------- email rules


def _rule_out(r: EmailRule) -> dict:
    return {"id": str(r.id), "rule": r.description, "active": r.active}


@router.get("/email-rules")
async def list_rules(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    """Every rule; the email watcher follows only the ones switched on (`active`)."""
    rows = (await session.execute(select(EmailRule).order_by(EmailRule.created_at))).scalars()
    return [_rule_out(r) for r in rows]


class RuleIn(BaseModel):
    rule: str = Field(min_length=3, max_length=1000)


@router.post("/email-rules", status_code=201)
async def add_rule(body: RuleIn, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    r = EmailRule(description=body.rule, active=True)
    session.add(r)
    await session.flush()
    return _rule_out(r)


class RulePatch(BaseModel):
    active: bool


@router.patch("/email-rules/{rule_id}")
async def switch_rule(rule_id: uuid.UUID, body: RulePatch, device: Device = Depends(current_device),
                      session: AsyncSession = Depends(get_session)):
    r = await session.get(EmailRule, rule_id)
    if r is None:
        raise HTTPException(404, "No such rule")
    r.active = body.active
    return _rule_out(r)


@router.delete("/email-rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: uuid.UUID, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    r = await session.get(EmailRule, rule_id)
    if r is None:
        raise HTTPException(404, "No such rule")
    await session.delete(r)


# ---------------------------------------------------------------- how Sora should respond

class AssistantSettings(BaseModel):
    instructions: str = Field("", max_length=2000)
    tone: Literal["Warm", "Concise", "Formal"] = "Warm"


@router.get("/me")
async def me(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    """Who the apps are signed in for: the owner's name (OWNER_NAME) and their Google account."""
    google = (await session.execute(select(Connection).where(Connection.provider == "google"))).scalar_one_or_none()
    return {"name": get_settings().owner_name or None, "email": google.account_email if google else None,
            "device": {"id": str(device.id), "name": device.name, "kind": device.kind}}


@router.get("/settings/assistant")
async def get_assistant_settings(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    """The owner's custom instructions and reply tone, added to Sora's system prompt."""
    return {
        "instructions": await kv_get(session, "custom_instructions", ""),
        "tone": await kv_get(session, "reply_tone", "Warm"),
    }


@router.put("/settings/assistant")
async def set_assistant_settings(body: AssistantSettings, device: Device = Depends(current_device),
                                 session: AsyncSession = Depends(get_session)):
    await kv_set(session, "custom_instructions", body.instructions.strip())
    await kv_set(session, "reply_tone", body.tone)
    return {"instructions": body.instructions.strip(), "tone": body.tone}
