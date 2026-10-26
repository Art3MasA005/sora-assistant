"""Calendar, Drive, Docs, Sheets, Slides, Tasks and Contacts REST helpers."""

from __future__ import annotations

import io
import re
from datetime import timedelta
from urllib.parse import quote

from sora.config import get_settings
from sora.google.client import GoogleClient
from sora.textutil import truncate
from sora.timeutil import is_date_only, now_local, parse_date, parse_datetime

CAL = "https://www.googleapis.com/calendar/v3/calendars/primary"
DRIVE = "https://www.googleapis.com/drive/v3"
DOCS = "https://docs.googleapis.com/v1/documents"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SLIDES = "https://slides.googleapis.com/v1/presentations"
TASKS = "https://tasks.googleapis.com/tasks/v1/lists/@default/tasks"
PEOPLE = "https://people.googleapis.com/v1"


# ---------------------------------------------------------------- Calendar


def _event_time(value: str) -> dict:
    if is_date_only(value):
        return {"date": parse_date(value).isoformat()}
    return {"dateTime": parse_datetime(value).isoformat(), "timeZone": get_settings().timezone}


def _event_summary(e: dict) -> dict:
    return {
        "id": e["id"],
        "summary": e.get("summary", "(no title)"),
        "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
        "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
        "location": e.get("location"),
        "description": truncate(e.get("description") or "", 500) or None,
        "attendees": [a.get("email") for a in e.get("attendees", [])] or None,
        "meet_link": e.get("hangoutLink"),
        "link": e.get("htmlLink"),
    }


async def calendar_list(
    g: GoogleClient, time_min: str | None = None, time_max: str | None = None, query: str | None = None,
    max_results: int = 20,
) -> list[dict]:
    start = parse_datetime(time_min) if time_min else now_local()
    end = parse_datetime(time_max) if time_max else start + timedelta(days=7)
    params = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max_results,
        "timeZone": get_settings().timezone,
    }
    if query:
        params["q"] = query
    data = await g.get(f"{CAL}/events", params=params)
    return [_event_summary(e) for e in data.get("items", [])]


async def calendar_create(
    g: GoogleClient, summary: str, start: str, end: str | None = None, description: str | None = None,
    location: str | None = None, attendees: list[str] | None = None, add_meet_link: bool = False,
) -> dict:
    if end is None:
        if is_date_only(start):
            end = (parse_date(start) + timedelta(days=1)).isoformat()
        else:
            end = (parse_datetime(start) + timedelta(hours=1)).isoformat()
    body: dict = {"summary": summary, "start": _event_time(start), "end": _event_time(end)}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    params = {"sendUpdates": "all" if attendees else "none"}
    if add_meet_link:
        body["conferenceData"] = {"createRequest": {"requestId": f"sora-{now_local().timestamp():.0f}"}}
        params["conferenceDataVersion"] = 1
    event = await g.post(f"{CAL}/events", json=body, params=params)
    return _event_summary(event)


async def calendar_update(g: GoogleClient, event_id: str, changes: dict) -> dict:
    body: dict = {}
    for key in ("summary", "description", "location"):
        if changes.get(key) is not None:
            body[key] = changes[key]
    if changes.get("start"):
        body["start"] = _event_time(changes["start"])
    if changes.get("end"):
        body["end"] = _event_time(changes["end"])
    if changes.get("attendees") is not None:
        body["attendees"] = [{"email": a} for a in changes["attendees"]]
    event = await g.patch(f"{CAL}/events/{event_id}", json=body, params={"sendUpdates": "all"})
    return _event_summary(event)


async def calendar_delete(g: GoogleClient, event_id: str) -> dict:
    await g.delete(f"{CAL}/events/{event_id}", params={"sendUpdates": "all"})
    return {"deleted": event_id}


# ---------------------------------------------------------------- Drive

_FILE_FIELDS = "id,name,mimeType,modifiedTime,webViewLink,size,owners(displayName)"


def _q_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


async def drive_search(g: GoogleClient, query: str = "", max_results: int = 10, mime_type: str | None = None) -> list[dict]:
    clauses = ["trashed = false"]
    if query:
        q = _q_escape(query)
        clauses.append(f"(name contains '{q}' or fullText contains '{q}')")
    if mime_type:
        clauses.append(f"mimeType = '{_q_escape(mime_type)}'")
    params = {
        "q": " and ".join(clauses),
        "pageSize": max_results,
        "fields": f"files({_FILE_FIELDS})",
        "orderBy": "modifiedTime desc" if not query else None,
    }
    data = await g.get(f"{DRIVE}/files", params={k: v for k, v in params.items() if v is not None})
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "type": f["mimeType"].replace("application/vnd.google-apps.", "google-"),
            "modified": f.get("modifiedTime"),
            "link": f.get("webViewLink"),
        }
        for f in data.get("files", [])
    ]


_EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


async def drive_read(g: GoogleClient, file_id: str, max_chars: int = 15000) -> dict:
    meta = await g.get(f"{DRIVE}/files/{file_id}", params={"fields": _FILE_FIELDS})
    mime = meta["mimeType"]
    if mime in _EXPORTS:
        raw = await g.raw(f"{DRIVE}/files/{file_id}/export", params={"mimeType": _EXPORTS[mime]})
        text = raw.decode("utf-8", errors="replace")
    elif mime == "application/pdf":
        from pypdf import PdfReader

        raw = await g.raw(f"{DRIVE}/files/{file_id}", params={"alt": "media"})
        reader = PdfReader(io.BytesIO(raw))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    elif mime.startswith("text/") or mime in {"application/json", "application/xml"}:
        raw = await g.raw(f"{DRIVE}/files/{file_id}", params={"alt": "media"})
        text = raw.decode("utf-8", errors="replace")
    else:
        return {"id": file_id, "name": meta["name"], "type": mime, "error": "This file type cannot be read as text."}
    return {
        "id": file_id,
        "name": meta["name"],
        "type": mime,
        "link": meta.get("webViewLink"),
        "content": truncate(text.strip(), max_chars),
        "full_length": len(text),
    }


# ---------------------------------------------------------------- Docs


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _format_requests(content: str, start_index: int) -> tuple[str, list[dict]]:
    """Turn light markdown (#, ##, ###, - bullets, 1. numbered) into Docs text + style requests."""
    lines = content.replace("\r\n", "\n").split("\n")
    out_lines: list[str] = []
    styles: list[tuple[int, int, str]] = []  # (start, end, style)
    index = start_index
    for line in lines:
        kind = None
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            kind = f"HEADING_{len(m.group(1))}"
            line = m.group(2)
        elif re.match(r"^\s*[-*]\s+", line):
            kind = "BULLET"
            line = re.sub(r"^\s*[-*]\s+", "", line)
        elif re.match(r"^\s*\d+[.)]\s+", line):
            kind = "NUMBERED"
            line = re.sub(r"^\s*\d+[.)]\s+", "", line)
        line = line.replace("**", "")
        length = _utf16_len(line) + 1  # + newline
        if kind:
            styles.append((index, index + length, kind))
        out_lines.append(line)
        index += length
    text = "\n".join(out_lines) + "\n"
    requests: list[dict] = [{"insertText": {"location": {"index": start_index}, "text": text}}]
    for s, e, kind in styles:
        rng = {"startIndex": s, "endIndex": e}
        if kind.startswith("HEADING"):
            requests.append(
                {"updateParagraphStyle": {"range": rng, "paragraphStyle": {"namedStyleType": kind}, "fields": "namedStyleType"}}
            )
        else:
            preset = "BULLET_DISC_CIRCLE_SQUARE" if kind == "BULLET" else "NUMBERED_DECIMAL_ALPHA_ROMAN"
            requests.append({"createParagraphBullets": {"range": rng, "bulletPreset": preset}})
    return text, requests


async def docs_create(g: GoogleClient, title: str, content: str = "") -> dict:
    doc = await g.post(DOCS, json={"title": title})
    doc_id = doc["documentId"]
    if content.strip():
        _, requests = _format_requests(content, 1)
        await g.post(f"{DOCS}/{doc_id}:batchUpdate", json={"requests": requests})
    return {"id": doc_id, "title": title, "link": f"https://docs.google.com/document/d/{doc_id}/edit"}


async def docs_append(g: GoogleClient, document_id: str, content: str) -> dict:
    doc = await g.get(f"{DOCS}/{document_id}", params={"fields": "title,body.content(endIndex)"})
    end = doc["body"]["content"][-1]["endIndex"] - 1
    _, requests = _format_requests(content, end)
    await g.post(f"{DOCS}/{document_id}:batchUpdate", json={"requests": requests})
    return {"id": document_id, "title": doc.get("title"), "link": f"https://docs.google.com/document/d/{document_id}/edit"}


# ---------------------------------------------------------------- Sheets


def _range(range_: str) -> str:
    """Sheet names can hold spaces, slashes or Bangla; encode them for the URL path."""
    return quote(range_, safe="!:$'")


async def sheets_info(g: GoogleClient, spreadsheet_id: str) -> dict:
    data = await g.get(f"{SHEETS}/{spreadsheet_id}", params={"fields": "properties.title,sheets.properties(title,gridProperties)"})
    return {
        "title": data["properties"]["title"],
        "sheets": [
            {
                "name": s["properties"]["title"],
                "rows": s["properties"].get("gridProperties", {}).get("rowCount"),
                "columns": s["properties"].get("gridProperties", {}).get("columnCount"),
            }
            for s in data.get("sheets", [])
        ],
    }


async def sheets_read(g: GoogleClient, spreadsheet_id: str, range_: str) -> dict:
    data = await g.get(f"{SHEETS}/{spreadsheet_id}/values/{_range(range_)}")
    values = data.get("values", [])
    return {"range": data.get("range"), "rows": values[:500], "total_rows": len(values)}


async def sheets_append(g: GoogleClient, spreadsheet_id: str, range_: str, rows: list[list]) -> dict:
    data = await g.post(
        f"{SHEETS}/{spreadsheet_id}/values/{_range(range_)}:append",
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json={"values": rows},
    )
    return {"updated_range": data.get("updates", {}).get("updatedRange"), "rows_added": len(rows)}


async def sheets_update(g: GoogleClient, spreadsheet_id: str, range_: str, rows: list[list]) -> dict:
    data = await g.put(
        f"{SHEETS}/{spreadsheet_id}/values/{_range(range_)}",
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": rows},
    )
    return {"updated_range": data.get("updatedRange"), "updated_cells": data.get("updatedCells")}


async def sheets_create(g: GoogleClient, title: str, rows: list[list] | None = None) -> dict:
    data = await g.post(SHEETS, json={"properties": {"title": title}})
    sid = data["spreadsheetId"]
    if rows:
        await sheets_update(g, sid, "A1", rows)
    return {"id": sid, "title": title, "link": data.get("spreadsheetUrl")}


# ---------------------------------------------------------------- Slides


async def slides_create(g: GoogleClient, title: str, subtitle: str, slides: list[dict]) -> dict:
    pres = await g.post(SLIDES, json={"title": title})
    pid = pres["presentationId"]
    requests: list[dict] = []
    first = pres["slides"][0]
    for element in first.get("pageElements", []):
        ph = element.get("shape", {}).get("placeholder", {}).get("type")
        if ph in {"CENTERED_TITLE", "TITLE"}:
            requests.append({"insertText": {"objectId": element["objectId"], "text": title}})
        elif ph == "SUBTITLE" and subtitle:
            requests.append({"insertText": {"objectId": element["objectId"], "text": subtitle}})
    for i, slide in enumerate(slides, start=1):
        sid, tid, bid = f"sora_slide_{i}", f"sora_title_{i}", f"sora_body_{i}"
        requests.append(
            {
                "createSlide": {
                    "objectId": sid,
                    "insertionIndex": i,
                    "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                    "placeholderIdMappings": [
                        {"layoutPlaceholder": {"type": "TITLE"}, "objectId": tid},
                        {"layoutPlaceholder": {"type": "BODY"}, "objectId": bid},
                    ],
                }
            }
        )
        requests.append({"insertText": {"objectId": tid, "text": slide.get("title", "")}})
        bullets = [b for b in slide.get("bullets", []) if b.strip()]
        if bullets:
            requests.append({"insertText": {"objectId": bid, "text": "\n".join(bullets)}})
            requests.append(
                {
                    "createParagraphBullets": {
                        "objectId": bid,
                        "textRange": {"type": "ALL"},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                }
            )
    if requests:
        await g.post(f"{SLIDES}/{pid}:batchUpdate", json={"requests": requests})
    return {"id": pid, "title": title, "slides": len(slides) + 1, "link": f"https://docs.google.com/presentation/d/{pid}/edit"}


# ---------------------------------------------------------------- Tasks


async def tasks_list(g: GoogleClient, show_completed: bool = False, max_results: int = 50) -> list[dict]:
    data = await g.get(
        TASKS, params={"showCompleted": str(show_completed).lower(), "showHidden": "false", "maxResults": max_results}
    )
    return [
        {"id": t["id"], "title": t.get("title"), "notes": t.get("notes"), "due": t.get("due"), "status": t.get("status")}
        for t in data.get("items", [])
    ]


async def tasks_add(g: GoogleClient, title: str, notes: str | None = None, due: str | None = None) -> dict:
    body: dict = {"title": title}
    if notes:
        body["notes"] = notes
    if due:
        body["due"] = f"{parse_date(due).isoformat()}T00:00:00.000Z"
    t = await g.post(TASKS, json=body)
    return {"id": t["id"], "title": t.get("title"), "due": t.get("due")}


async def tasks_complete(g: GoogleClient, task_id: str) -> dict:
    t = await g.patch(f"{TASKS}/{task_id}", json={"status": "completed"})
    return {"id": t["id"], "title": t.get("title"), "status": t.get("status")}


# ---------------------------------------------------------------- Contacts

_warmed_up = False


async def contacts_search(g: GoogleClient, query: str, max_results: int = 10) -> list[dict]:
    global _warmed_up
    if not _warmed_up:  # the People API wants an empty warm-up search to fill its cache
        await g.get(f"{PEOPLE}/people:searchContacts", params={"query": "", "readMask": "names"})
        await g.get(f"{PEOPLE}/otherContacts:search", params={"query": "", "readMask": "names"})
        _warmed_up = True
    results: list[dict] = []
    saved = await g.get(
        f"{PEOPLE}/people:searchContacts",
        params={"query": query, "readMask": "names,emailAddresses,phoneNumbers", "pageSize": max_results},
    )
    other = await g.get(
        f"{PEOPLE}/otherContacts:search",
        params={"query": query, "readMask": "names,emailAddresses,phoneNumbers", "pageSize": max_results},
    )
    for source, data in (("contacts", saved), ("other", other)):
        for r in data.get("results", []):
            p = r.get("person", {})
            results.append(
                {
                    "name": (p.get("names") or [{}])[0].get("displayName"),
                    "emails": [e["value"] for e in p.get("emailAddresses", [])],
                    "phones": [n["value"] for n in p.get("phoneNumbers", [])],
                    "source": source,
                }
            )
    return results[:max_results]
