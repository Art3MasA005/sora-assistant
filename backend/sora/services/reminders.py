"""Fires due reminders as notifications."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from sora.config import get_settings
from sora.db import session_scope
from sora.models import Reminder
from sora.services.notifier import notify
from sora.timeutil import fmt_local

log = logging.getLogger(__name__)

REPEAT_STEP = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1)}


async def fire_due() -> int:
    now = datetime.now(UTC)
    async with session_scope() as session:
        due = (
            await session.execute(
                select(Reminder).where(Reminder.status == "scheduled", Reminder.due_at <= now).with_for_update(skip_locked=True)
            )
        ).scalars().all()
        fired = [(r.id, r.text, r.due_at) for r in due]
        for r in due:
            step = REPEAT_STEP.get(r.repeat)
            if step:
                while r.due_at <= now:
                    r.due_at += step
            else:
                r.status = "done"
    for rid, text, due_at in fired:
        await notify(
            kind="reminder",
            title="⏰ " + text[:200],
            body=f"Reminder for {fmt_local(due_at)}",
            importance="high",
            data={"reminder_id": str(rid)},
        )
    return len(fired)


async def run_forever(stop: asyncio.Event) -> None:
    interval = max(5, get_settings().reminder_poll_seconds)
    while not stop.is_set():
        try:
            await fire_due()
        except Exception:
            log.exception("reminder round failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
