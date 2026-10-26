"""Gmail, Calendar, Drive, Docs, Sheets, Slides, Tasks, Contacts tools."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select

from sora.agent.tools.base import ToolContext, registry
from sora.db import session_scope
from sora.google import gmail, workspace
from sora.google.client import get_google
from sora.models import Connection


async def _own_email() -> str | None:
    async with session_scope() as session:
        conn = (await session.execute(select(Connection).where(Connection.provider == "google"))).scalar_one_or_none()
        return conn.account_email if conn else None


# ================================================================ Gmail


class GmailSearchArgs(BaseModel):
    query: str = Field(
        "in:inbox",
        description="Gmail search syntax, e.g. 'is:unread', 'from:rahim newer_than:2d', 'subject:invoice', 'has:attachment'.",
    )
    max_results: int = Field(10, ge=1, le=25)


@registry.tool(GmailSearchArgs, needs="gmail", untrusted=True)
async def gmail_search(ctx: ToolContext, a: GmailSearchArgs):
    """Search the owner's Gmail. Returns sender, subject, date, snippet and id for each message."""
    return await gmail.search(get_google(), a.query, a.max_results)


class GmailReadArgs(BaseModel):
    message_id: str


@registry.tool(GmailReadArgs, needs="gmail", untrusted=True)
async def gmail_read(ctx: ToolContext, a: GmailReadArgs):
    """Read the full text of one email by its id."""
    return await gmail.read(get_google(), a.message_id)


class GmailSendArgs(BaseModel):
    to: str = Field(description="Recipient email address(es), comma separated.")
    subject: str
    body: str = Field(description="Plain-text body. Sign off with the owner's name if known.")
    cc: str = ""
    bcc: str = ""


@registry.tool(
    GmailSendArgs, needs="gmail", confirm=True,
    summary=lambda a: f"Send email to {a.to}{f' (cc {a.cc})' if a.cc else ''}\nSubject: {a.subject}\n\n{a.body}",
)
async def gmail_send(ctx: ToolContext, a: GmailSendArgs):
    """Send a new email. The owner is asked to confirm before it goes out."""
    return await gmail.send(get_google(), a.to, a.subject, a.body, a.cc, a.bcc)


class GmailReplyArgs(BaseModel):
    message_id: str = Field(description="Id of the email being answered.")
    body: str
    reply_all: bool = False


@registry.tool(
    GmailReplyArgs, needs="gmail", confirm=True,
    summary=lambda a: f"Reply{' all' if a.reply_all else ''} to email {a.message_id}:\n\n{a.body}",
)
async def gmail_reply(ctx: ToolContext, a: GmailReplyArgs):
    """Reply in the same thread to an email. The owner is asked to confirm first."""
    return await gmail.reply(get_google(), a.message_id, a.body, a.reply_all, await _own_email())


class GmailDraftArgs(BaseModel):
    to: str = ""
    subject: str = ""
    body: str
    cc: str = ""
    reply_to_message_id: str | None = Field(None, description="Set to draft a reply in an existing thread.")


@registry.tool(GmailDraftArgs, needs="gmail")
async def gmail_create_draft(ctx: ToolContext, a: GmailDraftArgs):
    """Save an email as a draft in Gmail without sending it."""
    return await gmail.create_draft(
        get_google(), a.to, a.subject, a.body, a.cc, a.reply_to_message_id, await _own_email()
    )


class GmailModifyArgs(BaseModel):
    message_ids: list[str] = Field(min_length=1, max_length=100)
    mark_read: bool | None = Field(None, description="true = mark read, false = mark unread")
    archive: bool = False
    star: bool | None = None
    trash: bool = Field(False, description="Move to trash (asks the owner first).")


@registry.tool(
    GmailModifyArgs, needs="gmail", confirm=lambda a: a.trash,
    summary=lambda a: f"Move {len(a.message_ids)} email(s) to trash",
)
async def gmail_modify(ctx: ToolContext, a: GmailModifyArgs):
    """Mark emails read/unread, archive, star or trash them."""
    return await gmail.modify(get_google(), a.message_ids, a.mark_read, a.archive, a.star, a.trash)


# ================================================================ Calendar


class CalendarListArgs(BaseModel):
    time_min: str | None = Field(None, description="ISO datetime, local time if no offset. Default: now.")
    time_max: str | None = Field(None, description="ISO datetime. Default: 7 days after time_min.")
    query: str | None = None
    max_results: int = Field(20, ge=1, le=100)


@registry.tool(CalendarListArgs, needs="calendar", untrusted=True)
async def calendar_list_events(ctx: ToolContext, a: CalendarListArgs):
    """List events on the owner's primary Google Calendar in a time range."""
    return await workspace.calendar_list(get_google(), a.time_min, a.time_max, a.query, a.max_results)


class CalendarCreateArgs(BaseModel):
    summary: str
    start: str = Field(description="ISO datetime (local time) like 2026-10-20T15:00, or a date 2026-10-20 for all-day.")
    end: str | None = Field(None, description="Defaults to 1 hour after start (or the whole day).")
    description: str | None = None
    location: str | None = None
    attendees: list[str] | None = Field(None, description="Guest emails; they will receive invitations.")
    add_meet_link: bool = False


@registry.tool(
    CalendarCreateArgs, needs="calendar", confirm=lambda a: bool(a.attendees),
    summary=lambda a: f"Create event '{a.summary}' at {a.start} and send invites to {', '.join(a.attendees or [])}",
)
async def calendar_create_event(ctx: ToolContext, a: CalendarCreateArgs):
    """Create a calendar event. Asks the owner first only if guests will be invited."""
    return await workspace.calendar_create(
        get_google(), a.summary, a.start, a.end, a.description, a.location, a.attendees, a.add_meet_link
    )


class CalendarUpdateArgs(BaseModel):
    event_id: str
    summary: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None
    location: str | None = None
    attendees: list[str] | None = None


@registry.tool(
    CalendarUpdateArgs, needs="calendar", confirm=lambda a: a.attendees is not None, taint_guard=True,
    summary=lambda a: f"Update calendar event {a.summary or a.event_id}"
    + (f" and invite {', '.join(a.attendees)}" if a.attendees else ""),
)
async def calendar_update_event(ctx: ToolContext, a: CalendarUpdateArgs):
    """Change fields of an existing event (only the fields given)."""
    return await workspace.calendar_update(get_google(), a.event_id, a.model_dump(exclude={"event_id"}))


class CalendarDeleteArgs(BaseModel):
    event_id: str
    summary: str = Field("", description="Event title, shown to the owner when confirming.")


@registry.tool(
    CalendarDeleteArgs, needs="calendar", confirm=True,
    summary=lambda a: f"Delete calendar event {a.summary or a.event_id}",
)
async def calendar_delete_event(ctx: ToolContext, a: CalendarDeleteArgs):
    """Delete a calendar event (asks the owner first)."""
    return await workspace.calendar_delete(get_google(), a.event_id)


# ================================================================ Drive / Docs / Sheets / Slides


class DriveSearchArgs(BaseModel):
    query: str = Field("", description="Words in the file name or content. Empty = recent files.")
    max_results: int = Field(10, ge=1, le=30)
    file_type: str | None = Field(None, description="Optional: document, spreadsheet, presentation, pdf, folder")


_DRIVE_TYPES = {
    "document": "application/vnd.google-apps.document",
    "spreadsheet": "application/vnd.google-apps.spreadsheet",
    "presentation": "application/vnd.google-apps.presentation",
    "pdf": "application/pdf",
    "folder": "application/vnd.google-apps.folder",
}


@registry.tool(DriveSearchArgs, needs="drive")
async def drive_search(ctx: ToolContext, a: DriveSearchArgs):
    """Find files in the owner's Google Drive."""
    mime = _DRIVE_TYPES.get((a.file_type or "").lower())
    return await workspace.drive_search(get_google(), a.query, a.max_results, mime)


class DriveReadArgs(BaseModel):
    file_id: str


@registry.tool(DriveReadArgs, needs="drive", untrusted=True)
async def drive_read_file(ctx: ToolContext, a: DriveReadArgs):
    """Read the text of a Drive file (Google Doc, Sheet as CSV, Slides, PDF, or text file)."""
    return await workspace.drive_read(get_google(), a.file_id)


class DocsCreateArgs(BaseModel):
    title: str
    content: str = Field("", description="Body text. Supports '# ', '## ', '### ' headings, '- ' bullets, '1. ' lists.")


@registry.tool(DocsCreateArgs, needs="docs")
async def docs_create(ctx: ToolContext, a: DocsCreateArgs):
    """Create a new Google Doc with the given content and return its link."""
    return await workspace.docs_create(get_google(), a.title, a.content)


class DocsAppendArgs(BaseModel):
    document_id: str
    content: str


@registry.tool(
    DocsAppendArgs, needs="docs", taint_guard=True,
    summary=lambda a: f"Add to Google Doc {a.document_id}:\n\n{a.content[:500]}",
)
async def docs_append(ctx: ToolContext, a: DocsAppendArgs):
    """Append text to the end of an existing Google Doc."""
    return await workspace.docs_append(get_google(), a.document_id, a.content)


class SheetsInfoArgs(BaseModel):
    spreadsheet_id: str


@registry.tool(SheetsInfoArgs, needs="sheets")
async def sheets_info(ctx: ToolContext, a: SheetsInfoArgs):
    """List the tabs (sheet names) and sizes of a spreadsheet."""
    return await workspace.sheets_info(get_google(), a.spreadsheet_id)


class SheetsReadArgs(BaseModel):
    spreadsheet_id: str
    range: str = Field("A1:Z200", description="A1 notation, optionally with a tab: 'Sheet1!A1:D50'.")


@registry.tool(SheetsReadArgs, needs="sheets", untrusted=True)
async def sheets_read(ctx: ToolContext, a: SheetsReadArgs):
    """Read cell values from a Google Sheet."""
    return await workspace.sheets_read(get_google(), a.spreadsheet_id, a.range)


class SheetsWriteArgs(BaseModel):
    spreadsheet_id: str
    range: str = Field(description="A1 notation, e.g. 'Sheet1!A1' or 'Expenses!A:D'.")
    rows: list[list[str | int | float | bool | None]]
    mode: str = Field("append", description="'append' adds rows after existing data; 'overwrite' writes at range.")


@registry.tool(
    SheetsWriteArgs, needs="sheets", confirm=lambda a: a.mode == "overwrite", taint_guard=True,
    summary=lambda a: f"{'Overwrite' if a.mode == 'overwrite' else 'Add'} {len(a.rows)} row(s) in sheet "
    f"{a.spreadsheet_id} at {a.range}",
)
async def sheets_write(ctx: ToolContext, a: SheetsWriteArgs):
    """Append rows to, or overwrite cells in, a Google Sheet."""
    if a.mode == "overwrite":
        return await workspace.sheets_update(get_google(), a.spreadsheet_id, a.range, a.rows)
    return await workspace.sheets_append(get_google(), a.spreadsheet_id, a.range, a.rows)


class SheetsCreateArgs(BaseModel):
    title: str
    rows: list[list[str | int | float | bool | None]] | None = Field(None, description="Optional initial rows (first row = header).")


@registry.tool(SheetsCreateArgs, needs="sheets")
async def sheets_create(ctx: ToolContext, a: SheetsCreateArgs):
    """Create a new Google Sheet, optionally filled with rows."""
    return await workspace.sheets_create(get_google(), a.title, a.rows)


class SlideSpec(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)


class SlidesCreateArgs(BaseModel):
    title: str
    subtitle: str = ""
    slides: list[SlideSpec] = Field(description="Content slides after the title slide.", min_length=1, max_length=40)


@registry.tool(SlidesCreateArgs, needs="slides")
async def slides_create(ctx: ToolContext, a: SlidesCreateArgs):
    """Create a Google Slides presentation: a title slide plus one slide per entry with bullet points."""
    return await workspace.slides_create(get_google(), a.title, a.subtitle, [s.model_dump() for s in a.slides])


# ================================================================ Tasks / Contacts


class TasksListArgs(BaseModel):
    show_completed: bool = False


@registry.tool(TasksListArgs, needs="tasks")
async def tasks_list(ctx: ToolContext, a: TasksListArgs):
    """List the owner's Google Tasks (to-do list)."""
    return await workspace.tasks_list(get_google(), a.show_completed)


class TasksAddArgs(BaseModel):
    title: str
    notes: str | None = None
    due: str | None = Field(None, description="Due date YYYY-MM-DD.")


@registry.tool(TasksAddArgs, needs="tasks")
async def tasks_add(ctx: ToolContext, a: TasksAddArgs):
    """Add a to-do item to Google Tasks."""
    return await workspace.tasks_add(get_google(), a.title, a.notes, a.due)


class TasksCompleteArgs(BaseModel):
    task_id: str


@registry.tool(TasksCompleteArgs, needs="tasks")
async def tasks_complete(ctx: ToolContext, a: TasksCompleteArgs):
    """Mark a Google Task as done."""
    return await workspace.tasks_complete(get_google(), a.task_id)


class ContactsSearchArgs(BaseModel):
    query: str = Field(description="Name, email or phone fragment.")


@registry.tool(ContactsSearchArgs, needs="contacts")
async def contacts_search(ctx: ToolContext, a: ContactsSearchArgs):
    """Look up a person's email address or phone number in the owner's Google contacts. Not needed to call or text
    someone from the phone: phone_action finds the contact itself."""
    return await workspace.contacts_search(get_google(), a.query)
