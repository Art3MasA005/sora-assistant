"""What starts a routine: a time of day, an interval, or an event. Pure functions, no I/O.

Stored as JSON on the routine:
  {"type": "time", "at": "08:00", "days": ["mon", "wed"]}   days left out = every day
  {"type": "interval", "minutes": 30}
  {"type": "email", "sender": "gub.edu.bd", "subject": "exam", "important_only": false}
  {"type": "battery_below", "percent": 20}
  {"type": "device_online" | "device_offline", "device": "phone" | "pc"}
  {"type": "pc_woke"}
  {"type": "phone_notification", "app": "WhatsApp", "sender": "Ammu"}   both optional
  {"type": "page_change", "url": "https://…", "minutes": 60, "selector": "#price", "contains": "৳", "browser": true}
      checked on its schedule without the LLM; the routine runs only when the watched part changed
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta, tzinfo

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME_TYPES = ("time", "interval", "page_change")
EVENT_TYPES = ("email", "battery_below", "device_online", "device_offline", "pc_woke", "phone_notification")
TYPES = TIME_TYPES + EVENT_TYPES
# Each run is an LLM turn: anything more often than this costs money for little use.
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 7 * 24 * 60
# A time routine found overdue by more than this (the PC was asleep or off) waits for its next time
# instead of running late: "1 am: put the PC to sleep" must not fire when the owner wakes the PC at 3.
MISSED_GRACE = timedelta(minutes=15)


def normalize(raw: dict) -> dict:
    """A clean trigger, or ValueError saying what is wrong (the LLM reads it and retries)."""
    kind = str(raw.get("type") or "").strip().lower()
    if kind == "time":
        at = str(raw.get("at") or "").strip()
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", at)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ValueError("a time trigger needs at=HH:MM (24-hour, local time)")
        out: dict = {"type": "time", "at": f"{int(m.group(1)):02d}:{m.group(2)}"}
        days = raw.get("days") or []
        wanted = {str(d).strip().lower()[:3] for d in days}
        if wanted - set(WEEKDAYS):
            raise ValueError(f"days must be some of {', '.join(WEEKDAYS)}")
        if wanted and wanted != set(WEEKDAYS):
            out["days"] = [d for d in WEEKDAYS if d in wanted]
        return out
    if kind == "interval":
        try:
            minutes = int(raw.get("minutes"))
        except (TypeError, ValueError):
            raise ValueError("an interval trigger needs minutes") from None
        if not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise ValueError(f"minutes must be between {MIN_INTERVAL_MINUTES} and {MAX_INTERVAL_MINUTES}")
        return {"type": "interval", "minutes": minutes}
    if kind == "email":
        out = {"type": "email"}
        for key in ("sender", "subject"):
            if value := str(raw.get(key) or "").strip():
                out[key] = value[:200]
        if raw.get("important_only"):
            out["important_only"] = True
        return out
    if kind == "battery_below":
        try:
            percent = int(raw.get("percent"))
        except (TypeError, ValueError):
            raise ValueError("a battery_below trigger needs percent") from None
        if not 1 <= percent <= 99:
            raise ValueError("percent must be between 1 and 99")
        return {"type": "battery_below", "percent": percent}
    if kind in {"device_online", "device_offline"}:
        device = str(raw.get("device") or "phone").strip().lower()
        if device not in {"phone", "pc"}:
            raise ValueError("device must be phone or pc")
        return {"type": kind, "device": device}
    if kind == "pc_woke":
        return {"type": "pc_woke"}
    if kind == "page_change":
        url = str(raw.get("url") or "").strip()
        if not re.match(r"https?://\S+$", url, re.I):
            raise ValueError("a page_change trigger needs url=https://…")
        try:
            minutes = int(raw.get("minutes") or 60)
        except (TypeError, ValueError):
            raise ValueError("minutes must be a number") from None
        if not MIN_INTERVAL_MINUTES <= minutes <= MAX_INTERVAL_MINUTES:
            raise ValueError(f"minutes must be between {MIN_INTERVAL_MINUTES} and {MAX_INTERVAL_MINUTES}")
        out = {"type": "page_change", "url": url[:500], "minutes": minutes}
        if selector := str(raw.get("selector") or "").strip():
            out["selector"] = selector[:200]
        if contains := str(raw.get("contains") or "").strip():
            out["contains"] = contains[:100]
        if raw.get("browser") or selector:  # a CSS part needs the page as a browser renders it
            out["browser"] = True
        return out
    if kind == "phone_notification":
        out = {"type": "phone_notification"}
        for key in ("app", "sender"):
            if value := str(raw.get(key) or "").strip():
                out[key] = value[:100]
        return out
    raise ValueError(f"type must be one of {', '.join(TYPES)}")


def describe(trigger: dict) -> str:
    """Plain English, for approval prompts and the LLM ("every day at 08:00")."""
    kind = trigger.get("type")
    if kind == "time":
        days = trigger.get("days")
        when = ", ".join(d.capitalize() for d in days) if days else "every day"
        return f"{when} at {trigger['at']}"
    if kind == "interval":
        minutes = trigger["minutes"]
        if minutes % 60:
            return f"every {minutes} minutes"
        return "every hour" if minutes == 60 else f"every {minutes // 60} hours"
    if kind == "email":
        what = "an important email" if trigger.get("important_only") else "an email"
        if trigger.get("sender"):
            what += f" from {trigger['sender']}"
        if trigger.get("subject"):
            what += f" with \"{trigger['subject']}\" in the subject"
        return f"when {what} arrives"
    if kind == "battery_below":
        return f"when the phone battery drops below {trigger['percent']}%"
    if kind == "device_online":
        return f"when the {trigger.get('device', 'phone')} comes online"
    if kind == "device_offline":
        return f"when the {trigger.get('device', 'phone')} goes offline"
    if kind == "pc_woke":
        return "when the PC wakes up"
    if kind == "page_change":
        part = f" ({trigger['selector']})" if trigger.get("selector") else ""
        return f"when {trigger['url']}{part} changes (checked every {trigger['minutes']} minutes)"
    if kind == "phone_notification":
        what = f"a {trigger['app']} notification" if trigger.get("app") else "a phone notification"
        if trigger.get("sender"):
            what += f" from {trigger['sender']}"
        return f"when {what} arrives"
    return str(kind)


def next_run(trigger: dict, after: datetime, tz: tzinfo) -> datetime | None:
    """The first time strictly after [after] (UTC), or None for event triggers."""
    kind = trigger.get("type")
    if kind in {"interval", "page_change"}:
        return after + timedelta(minutes=trigger["minutes"])
    if kind != "time":
        return None
    hour, minute = (int(x) for x in trigger["at"].split(":"))
    days = set(trigger.get("days") or WEEKDAYS)
    start = after.astimezone(tz).date()
    for offset in range(8):
        day = start + timedelta(days=offset)
        if WEEKDAYS[day.weekday()] not in days:
            continue
        # A time that doesn't exist that day (a DST jump) comes out as the same wall time after the jump.
        candidate = datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(UTC)
        if candidate > after:
            return candidate
    return None


def missed(trigger: dict, due: datetime, now: datetime) -> bool:
    """A time routine overdue by too long is skipped (see MISSED_GRACE); an interval one runs once, late."""
    return trigger.get("type") == "time" and now - due > MISSED_GRACE
