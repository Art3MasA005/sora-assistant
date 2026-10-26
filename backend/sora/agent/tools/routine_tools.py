"""Routines: what Sora does on its own, on a schedule or when something happens (services/routines.py)."""

from __future__ import annotations

import typing
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select

from sora.agent.tools.base import ToolContext, registry
from sora.db import session_scope
from sora.models import Routine
from sora.services import routine_triggers as triggers
from sora.services import routines
from sora.textutil import truncate
from sora.timeutil import fmt_local

# A routine may not make or change routines without asking, whatever it lists.
NEVER_ALLOWED = {"routine_create", "routine_update"}

ALLOWED_HELP = (
    "Steps that normally ask the owner first but may run without asking in this routine: a tool name "
    "('gmail_send', 'calendar_create_event') or 'pc_action:<action>' / 'phone_action:<action>' "
    "('pc_action:sleep', 'phone_action:send_sms'). Only what the owner clearly agreed to; anything not listed "
    "waits for their approval in a notification."
)


class TriggerArgs(BaseModel):
    type: typing.Literal[
        "time", "interval", "email", "battery_below", "device_online", "device_offline", "pc_woke", "phone_notification",
        "page_change",
    ] = Field(
        description=(
            "time (at HH:MM, on some days or every day) | interval (every N minutes) | email (an email arrives, "
            "optionally from someone or about something) | battery_below (the phone's battery drops below percent) | "
            "device_online / device_offline (the phone or the PC connects to Sora or drops off; the phone coming "
            "online usually means it is back on the home Wi-Fi) | pc_woke (the PC wakes from sleep) | "
            "phone_notification (a notification arrives on the phone, optionally from an app and a person or chat) | "
            "page_change (a web page changes: a price, a notice, a result; checked every N minutes without costing "
            "a run, and the routine runs with what changed only when it did)"
        )
    )
    at: str | None = Field(None, description="time: HH:MM, 24-hour, local time")
    days: list[str] | None = Field(None, description="time: weekdays like ['mon', 'fri']; leave out for every day")
    minutes: int | None = Field(
        None, description=f"interval: every N minutes (at least {triggers.MIN_INTERVAL_MINUTES}); page_change: how often "
                          "to look (default 60)"
    )
    sender: str | None = Field(
        None, description="email: part of the sender's name or address; phone_notification: the person or chat"
    )
    app: str | None = Field(None, description="phone_notification: the app, e.g. WhatsApp, Messenger, Messages")
    subject: str | None = Field(None, description="email: a word or phrase in the subject")
    important_only: bool | None = Field(None, description="email: only emails Sora rates as important")
    percent: int | None = Field(None, description="battery_below: the battery level, e.g. 20")
    device: typing.Literal["phone", "pc"] | None = Field(None, description="device_online / device_offline")
    url: str | None = Field(None, description="page_change: the page's web address")
    selector: str | None = Field(
        None, description="page_change: a CSS selector for just the part to watch, e.g. '#price' (read with the PC's "
                          "browser, so the PC must be on)"
    )
    contains: str | None = Field(
        None, description="page_change: watch only the lines with this word, e.g. '৳' or 'Result' (ignores ads and clocks)"
    )
    browser: bool | None = Field(
        None, description="page_change: read the page with the PC's browser (for pages built by JavaScript or behind "
                          "the owner's login)"
    )

    @model_validator(mode="after")
    def _valid(self):
        triggers.normalize(self.model_dump(exclude_none=True))  # a ValueError says what is missing
        return self

    def clean(self) -> dict:
        return triggers.normalize(self.model_dump(exclude_none=True))


def _check_allowed(entries: list[str]) -> list[str]:
    out: list[str] = []
    for entry in entries:
        entry = entry.strip()
        name, _, action = entry.partition(":")
        if name in NEVER_ALLOWED:
            raise ValueError(f"'{entry}' can't run without asking")
        tool = registry.get(name)
        if tool is None:
            raise ValueError(f"'{entry}': there is no tool named {name}")
        field = tool.args_model.model_fields.get("action")
        choices = typing.get_args(field.annotation) if field is not None else ()
        if choices and action not in choices:
            raise ValueError(f"'{entry}': name the action too, e.g. '{name}:{choices[0]}'")
        if not choices and action:
            raise ValueError(f"'{entry}': {name} has no actions, so list just '{name}'")
        if entry not in out:
            out.append(entry)
    return out


def _summary(verb: str, name: str, trigger: TriggerArgs | None, prompt: str | None,
             allowed: list[str] | None, speak: bool | None, enabled: bool | None = None) -> str:
    """What the owner approves: the trigger, the prompt and what may run without asking."""
    lines = [f"{verb} routine: {name}"]
    if trigger is not None:
        lines.append(f"When: {triggers.describe(trigger.clean())}")
    if prompt is not None:
        lines.append(f"Does: {prompt}")
    if allowed is not None:
        lines.append("Runs without asking: " + (", ".join(allowed) if allowed else "nothing (steps that need approval ask)"))
    if speak is not None:
        lines.append("Says the result aloud" if speak else "Notification only (silent)")
    if enabled is not None:
        lines.append("Switched on" if enabled else "Switched off")
    return "\n".join(lines)


class RoutineCreateArgs(BaseModel):
    name: str = Field(description="A short name in the owner's language, e.g. 'Morning brief'.")
    trigger: TriggerArgs
    prompt: str = Field(
        description="What Sora does each time, in the owner's own words and language, complete enough to do alone, "
                    "e.g. 'Tell me today's calendar and the important emails from last night.'"
    )
    allowed_actions: list[str] = Field(default_factory=list, description=ALLOWED_HELP)
    speak: bool = Field(True, description="Also say the result aloud. False for night-time or silent routines.")

    @field_validator("allowed_actions")
    @classmethod
    def _allowed(cls, value: list[str]) -> list[str]:
        return _check_allowed(value)


@registry.tool(
    RoutineCreateArgs, confirm=True,
    summary=lambda a: _summary("New", a.name, a.trigger, a.prompt, a.allowed_actions, a.speak),
)
async def routine_create(ctx: ToolContext, a: RoutineCreateArgs):
    """Create a routine: something Sora does on its own on a schedule (every day at 8, on weekdays, every 30
    minutes) or when something happens (an email arrives, the phone battery runs low, the phone or PC comes online
    or goes offline, the PC wakes up, a web page changes). Each result arrives as a notification and can be said aloud. For a one-off
    reminder use reminder_create instead."""
    async with session_scope() as session:
        r = Routine(name=a.name.strip()[:100], trigger=a.trigger.clean(), prompt=a.prompt.strip(),
                    allowed_actions=a.allowed_actions, speak=a.speak, enabled=True)
        routines.schedule(r)
        session.add(r)
        await session.flush()
        out = {"routine_id": str(r.id), "when": triggers.describe(r.trigger)}
        if r.next_run_at:
            out["next_run"] = fmt_local(r.next_run_at)
    routines.poke()
    return out


class RoutineListArgs(BaseModel):
    pass


# Last results can quote the emails or pages a run read.
@registry.tool(RoutineListArgs, untrusted=True)
async def routine_list(ctx: ToolContext, a: RoutineListArgs):
    """List the owner's routines: when each runs, what it does, and how its last run went."""
    async with session_scope() as session:
        rows = (await session.execute(select(Routine).order_by(Routine.created_at))).scalars().all()
        return [
            {"id": str(r.id), "name": r.name, "enabled": r.enabled, "when": triggers.describe(r.trigger),
             "does": r.prompt, "runs_without_asking": r.allowed_actions, "speaks": r.speak,
             "next_run": fmt_local(r.next_run_at) if r.next_run_at else None,
             "last_run": fmt_local(r.last_run_at) if r.last_run_at else None,
             "last_status": r.last_status, "last_result": truncate(r.last_result or "", 300) or None}
            for r in rows
        ]


async def _find(session, ref: str) -> Routine | str:
    """A routine by id or by name; or the error to return."""
    try:
        found = await session.get(Routine, uuid.UUID(ref))
        if found is not None:
            return found
    except ValueError:
        pass
    rows = (await session.execute(select(Routine))).scalars().all()
    named = [r for r in rows if r.name.casefold() == ref.strip().casefold()] or [
        r for r in rows if ref.strip().casefold() in r.name.casefold()
    ]
    if len(named) == 1:
        return named[0]
    if not named:
        return "Error: no routine with that id or name (routine_list shows them)"
    return f"Error: several routines match: {', '.join(r.name for r in named)}. Use the id."


class RoutineUpdateArgs(BaseModel):
    routine: str = Field(description="The routine's id or name.")
    name: str | None = None
    trigger: TriggerArgs | None = None
    prompt: str | None = None
    allowed_actions: list[str] | None = Field(None, description="Replaces the list. " + ALLOWED_HELP)
    speak: bool | None = None
    enabled: bool | None = Field(None, description="Switch it on or off.")

    @field_validator("allowed_actions")
    @classmethod
    def _allowed(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _check_allowed(value)


@registry.tool(
    RoutineUpdateArgs, confirm=True,
    summary=lambda a: _summary("Change", a.name or a.routine, a.trigger, a.prompt, a.allowed_actions, a.speak, a.enabled),
)
async def routine_update(ctx: ToolContext, a: RoutineUpdateArgs):
    """Change a routine: its name, trigger, what it does, what runs without asking, speaking, or switch it on/off."""
    async with session_scope() as session:
        r = await _find(session, a.routine)
        if isinstance(r, str):
            return r
        if a.name is not None:
            r.name = a.name.strip()[:100]
        if a.trigger is not None:
            r.trigger = a.trigger.clean()
        if a.prompt is not None:
            r.prompt = a.prompt.strip()
        if a.allowed_actions is not None:
            r.allowed_actions = a.allowed_actions
        if a.speak is not None:
            r.speak = a.speak
        if a.enabled is not None:
            r.enabled = a.enabled
        routines.schedule(r)
        out = {"routine_id": str(r.id), "name": r.name, "enabled": r.enabled, "when": triggers.describe(r.trigger),
               "next_run": fmt_local(r.next_run_at) if r.next_run_at else None}
    routines.poke()
    return out


class RoutineDeleteArgs(BaseModel):
    routine: str = Field(description="The routine's id or name.")


@registry.tool(RoutineDeleteArgs, taint_guard=True, summary=lambda a: f"Delete routine: {a.routine}")
async def routine_delete(ctx: ToolContext, a: RoutineDeleteArgs):
    """Delete a routine and its run history."""
    async with session_scope() as session:
        r = await _find(session, a.routine)
        if isinstance(r, str):
            return r
        name = r.name
        await routines.remove(session, r)
    routines.poke()
    return {"deleted": name}
