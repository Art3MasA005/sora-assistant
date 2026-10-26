"""Reminders, email rules, notification history, web search and web fetching."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select

from sora.agent.tools.base import ToolContext, registry
from sora.db import session_scope
from sora.models import EmailRule, Notification, Reminder
from sora.services import rag
from sora.services.web import is_public_url as _is_public
from sora.services.web_search import SearchError
from sora.services.web_search import search as search_web
from sora.textutil import truncate
from sora.timeutil import fmt_local, parse_datetime

# ================================================================ Reminders


class ReminderCreateArgs(BaseModel):
    text: str = Field(description="What to remind about, in the owner's language.")
    due_at: str = Field(description="ISO datetime in local time, e.g. 2026-10-16T09:30")
    repeat: str = Field("none", description="none | daily | weekly")


@registry.tool(ReminderCreateArgs)
async def reminder_create(ctx: ToolContext, a: ReminderCreateArgs):
    """Schedule a reminder; it arrives as a push notification on the phone at that time."""
    due = parse_datetime(a.due_at)
    repeat = a.repeat if a.repeat in {"none", "daily", "weekly"} else "none"
    async with session_scope() as session:
        r = Reminder(text=a.text, due_at=due, repeat=repeat)
        session.add(r)
        await session.flush()
        return {"reminder_id": str(r.id), "due": fmt_local(due), "repeat": repeat}


class ReminderListArgs(BaseModel):
    include_done: bool = False


@registry.tool(ReminderListArgs)
async def reminder_list(ctx: ToolContext, a: ReminderListArgs):
    """List scheduled reminders."""
    async with session_scope() as session:
        stmt = select(Reminder).order_by(Reminder.due_at)
        if not a.include_done:
            stmt = stmt.where(Reminder.status == "scheduled")
        rows = (await session.execute(stmt.limit(50))).scalars()
        return [{"id": str(r.id), "text": r.text, "due": fmt_local(r.due_at), "repeat": r.repeat, "status": r.status} for r in rows]


class ReminderCancelArgs(BaseModel):
    reminder_id: str


@registry.tool(ReminderCancelArgs)
async def reminder_cancel(ctx: ToolContext, a: ReminderCancelArgs):
    """Cancel a reminder."""
    async with session_scope() as session:
        r = await session.get(Reminder, uuid.UUID(a.reminder_id))
        if r is None:
            return "Error: no reminder with that id"
        r.status = "cancelled"
        return {"cancelled": True}


# ================================================================ Email rules


class EmailRuleAddArgs(BaseModel):
    rule: str = Field(description="Plain-language rule, e.g. 'Emails from @gub.edu.bd are always high importance'.")


@registry.tool(EmailRuleAddArgs, taint_guard=True, summary=lambda a: f"Add email rule: {a.rule}")
async def email_rule_add(ctx: ToolContext, a: EmailRuleAddArgs):
    """Add a rule that controls which incoming emails the owner gets notified about."""
    async with session_scope() as session:
        rule = EmailRule(description=a.rule)
        session.add(rule)
        await session.flush()
        return {"rule_id": str(rule.id)}


class EmptyArgs(BaseModel):
    pass


@registry.tool(EmptyArgs)
async def email_rule_list(ctx: ToolContext, a: EmptyArgs):
    """List the email notification rules."""
    async with session_scope() as session:
        rules = (await session.execute(select(EmailRule).where(EmailRule.active).order_by(EmailRule.created_at))).scalars()
        return [{"id": str(r.id), "rule": r.description} for r in rules]


class EmailRuleDeleteArgs(BaseModel):
    rule_id: str


@registry.tool(EmailRuleDeleteArgs, taint_guard=True, summary=lambda a: f"Delete email rule {a.rule_id}")
async def email_rule_delete(ctx: ToolContext, a: EmailRuleDeleteArgs):
    """Remove an email notification rule."""
    async with session_scope() as session:
        r = await session.get(EmailRule, uuid.UUID(a.rule_id))
        if r is None:
            return "Error: no rule with that id"
        await session.delete(r)
        return {"deleted": True}


# ================================================================ Notifications


class NotificationsArgs(BaseModel):
    kind: str | None = Field(None, description="email | reminder | routine | system | device")
    unread_only: bool = False
    limit: int = Field(15, ge=1, le=50)


@registry.tool(NotificationsArgs, untrusted=True)
async def notifications_recent(ctx: ToolContext, a: NotificationsArgs):
    """Recent notifications Sora sent (e.g. 'what important emails came today?')."""
    async with session_scope() as session:
        stmt = select(Notification).order_by(Notification.created_at.desc()).limit(a.limit)
        if a.kind:
            stmt = stmt.where(Notification.kind == a.kind)
        if a.unread_only:
            stmt = stmt.where(Notification.read.is_(False))
        rows = (await session.execute(stmt)).scalars()
        return [
            {"title": n.title, "body": n.body, "importance": n.importance, "at": fmt_local(n.created_at), "data": n.data}
            for n in rows
        ]


# ================================================================ Web


class WebSearchArgs(BaseModel):
    query: str = Field(description="What to look up. English usually finds more; keep Bangla for local Bangla topics.")
    count: int = Field(5, ge=1, le=10, description="How many results.")


@registry.tool(WebSearchArgs, untrusted=True, summary=lambda a: f"Search the web for {a.query}")
async def web_search(ctx: ToolContext, a: WebSearchArgs):
    """Search the web and get the top results (title, URL, snippet) to answer from: news, facts, prices, people,
    places. web_fetch a result's URL to read the whole page. To open a search on the owner's screen instead, use
    pc_action/phone_action web_search."""
    if not a.query.strip():
        return "Error: the search query is empty"
    try:
        source, results = await search_web(a.query, a.count)
    except SearchError as exc:
        return f"Error: web search failed ({exc}). Try again in a minute."
    return {"query": a.query, "source": source, "results": [vars(r) for r in results]}


class WebFetchArgs(BaseModel):
    url: str


@registry.tool(WebFetchArgs, untrusted=True, taint_guard=True, summary=lambda a: f"Open web page {a.url}")
async def web_fetch(ctx: ToolContext, a: WebFetchArgs):
    """Fetch a public web page and return its readable text."""
    if not _is_public(a.url):
        return "Error: only public http(s) URLs can be fetched"
    title, text = await rag.fetch_url_text(a.url)
    return {"title": title, "url": a.url, "text": truncate(text, 10000)}
