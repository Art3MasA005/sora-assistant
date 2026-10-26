"""Gmail REST helpers."""

from __future__ import annotations

import asyncio
import base64
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

from sora.google.client import GoogleClient
from sora.textutil import html_to_text, truncate

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
SUMMARY_HEADERS = ["From", "To", "Subject", "Date"]


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _walk(part: dict, plain: list[str], html: list[str], attachments: list[dict]) -> None:
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    if part.get("filename"):
        attachments.append({"filename": part["filename"], "mime_type": mime, "size": body.get("size", 0)})
    elif mime == "text/plain" and body.get("data"):
        plain.append(_decode(body["data"]))
    elif mime == "text/html" and body.get("data"):
        html.append(_decode(body["data"]))
    for sub in part.get("parts", []) or []:
        _walk(sub, plain, html, attachments)


def summarize_message(msg: dict) -> dict:
    h = _headers(msg.get("payload", {}))
    labels = msg.get("labelIds", [])
    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "from": h.get("from", ""),
        "to": h.get("to", ""),
        "subject": h.get("subject", "(no subject)"),
        "date": h.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "unread": "UNREAD" in labels,
        "labels": labels,
    }


async def get_message_summary(g: GoogleClient, message_id: str) -> dict:
    msg = await g.get(
        f"{BASE}/messages/{message_id}",
        params=[("format", "metadata"), *[("metadataHeaders", h) for h in SUMMARY_HEADERS]],
    )
    return summarize_message(msg)


async def search(g: GoogleClient, query: str, max_results: int = 10) -> list[dict]:
    data = await g.get(f"{BASE}/messages", params={"q": query, "maxResults": max_results})
    ids = [m["id"] for m in data.get("messages", [])]
    return list(await asyncio.gather(*(get_message_summary(g, i) for i in ids)))


async def read(g: GoogleClient, message_id: str, max_chars: int = 8000) -> dict:
    msg = await g.get(f"{BASE}/messages/{message_id}", params={"format": "full"})
    plain: list[str] = []
    html: list[str] = []
    attachments: list[dict] = []
    _walk(msg.get("payload", {}), plain, html, attachments)
    body = "\n".join(plain).strip() or html_to_text("\n".join(html))
    out = summarize_message(msg)
    h = _headers(msg.get("payload", {}))
    out.update(
        cc=h.get("cc", ""),
        body=truncate(body, max_chars),
        attachments=attachments,
    )
    return out


def _encode(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def build_message(
    to: str, subject: str, body: str, cc: str = "", bcc: str = "", headers: dict[str, str] | None = None
) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    message["Subject"] = subject
    for k, v in (headers or {}).items():
        message[k] = v
    message.set_content(body)
    return message


async def send(g: GoogleClient, to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    raw = _encode(build_message(to, subject, body, cc, bcc))
    sent = await g.post(f"{BASE}/messages/send", json={"raw": raw})
    return {"id": sent.get("id"), "thread_id": sent.get("threadId")}


async def _reply_context(g: GoogleClient, message_id: str, reply_all: bool, own_email: str | None) -> dict:
    msg = await g.get(
        f"{BASE}/messages/{message_id}",
        params=[
            ("format", "metadata"),
            *[("metadataHeaders", h) for h in ["From", "To", "Cc", "Subject", "Message-ID", "References", "Reply-To"]],
        ],
    )
    h = _headers(msg["payload"])
    to = h.get("reply-to") or h.get("from", "")
    cc = ""
    if reply_all:
        own = (own_email or "").lower()
        to_addr = parseaddr(to)[1].lower()
        others = [
            addr
            for _, addr in getaddresses([h.get("to", ""), h.get("cc", "")])
            if addr and addr.lower() not in {own, to_addr}
        ]
        cc = ", ".join(dict.fromkeys(others))
    subject = h.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    mid = h.get("message-id", "")
    refs = f"{h.get('references', '')} {mid}".strip()
    return {
        "thread_id": msg.get("threadId"),
        "to": to,
        "cc": cc,
        "subject": subject,
        "headers": {"In-Reply-To": mid, "References": refs} if mid else {},
    }


async def reply(g: GoogleClient, message_id: str, body: str, reply_all: bool = False, own_email: str | None = None) -> dict:
    ctx = await _reply_context(g, message_id, reply_all, own_email)
    raw = _encode(build_message(ctx["to"], ctx["subject"], body, ctx["cc"], headers=ctx["headers"]))
    sent = await g.post(f"{BASE}/messages/send", json={"raw": raw, "threadId": ctx["thread_id"]})
    return {"id": sent.get("id"), "thread_id": sent.get("threadId"), "to": ctx["to"], "cc": ctx["cc"]}


async def create_draft(
    g: GoogleClient, to: str, subject: str, body: str, cc: str = "", reply_to_message_id: str | None = None,
    own_email: str | None = None,
) -> dict:
    message: dict = {}
    if reply_to_message_id:
        ctx = await _reply_context(g, reply_to_message_id, False, own_email)
        message["raw"] = _encode(build_message(to or ctx["to"], subject or ctx["subject"], body, cc, headers=ctx["headers"]))
        message["threadId"] = ctx["thread_id"]
    else:
        message["raw"] = _encode(build_message(to, subject, body, cc))
    draft = await g.post(f"{BASE}/drafts", json={"message": message})
    return {"draft_id": draft.get("id"), "message_id": draft.get("message", {}).get("id")}


async def modify(
    g: GoogleClient,
    message_ids: list[str],
    mark_read: bool | None = None,
    archive: bool = False,
    star: bool | None = None,
    trash: bool = False,
) -> dict:
    if trash:
        await asyncio.gather(*(g.post(f"{BASE}/messages/{i}/trash") for i in message_ids))
        return {"trashed": len(message_ids)}
    add, remove = [], []
    if mark_read is True:
        remove.append("UNREAD")
    elif mark_read is False:
        add.append("UNREAD")
    if archive:
        remove.append("INBOX")
    if star is True:
        add.append("STARRED")
    elif star is False:
        remove.append("STARRED")
    if not add and not remove:
        return {"modified": 0}
    await g.post(
        f"{BASE}/messages/batchModify",
        json={"ids": message_ids, "addLabelIds": add, "removeLabelIds": remove},
    )
    return {"modified": len(message_ids), "added": add, "removed": remove}


async def profile(g: GoogleClient) -> dict:
    return await g.get(f"{BASE}/profile")


async def history_new_inbox_ids(g: GoogleClient, start_history_id: str) -> tuple[list[str], str]:
    """New INBOX message ids since start_history_id, plus the latest history id."""
    ids: list[str] = []
    page_token = None
    latest = start_history_id
    while True:
        params = {
            "startHistoryId": start_history_id,
            "historyTypes": "messageAdded",
            "labelId": "INBOX",
            "maxResults": 100,
        }
        if page_token:
            params["pageToken"] = page_token
        data = await g.get(f"{BASE}/history", params=params)
        latest = data.get("historyId", latest)
        for entry in data.get("history", []):
            for added in entry.get("messagesAdded", []):
                mid = added["message"]["id"]
                if mid not in ids:
                    ids.append(mid)
        page_token = data.get("nextPageToken")
        if not page_token:
            return ids, latest
