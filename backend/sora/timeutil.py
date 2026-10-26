"""Time helpers. Everything the owner says is in their local timezone (TIMEZONE in .env)."""

from __future__ import annotations

from datetime import date, datetime

from sora.config import get_settings


def now_local() -> datetime:
    return datetime.now(get_settings().tz)


def parse_datetime(value: str) -> datetime:
    """Parse an ISO 8601 string; naive values are taken as the owner's local time."""
    value = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_settings().tz)
    return dt


def parse_date(value: str) -> date:
    return date.fromisoformat(value.strip()[:10])


def is_date_only(value: str) -> bool:
    return len(value.strip()) == 10


def fmt_local(dt: datetime) -> str:
    return dt.astimezone(get_settings().tz).strftime("%a %d %b %Y, %I:%M %p")
