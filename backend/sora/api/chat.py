"""Chat with the agent, approve/decline actions, browse conversations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sora.agent.runner import Origin, get_agent
from sora.api.deps import collect, current_device, sse
from sora.db import get_session
from sora.models import Conversation, Device, Message, PendingAction

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: uuid.UUID | None = None
    voice: bool = Field(False, description="Reply will be spoken: keep it short, no markdown.")
    stream: bool = True


@router.post("/chat")
async def chat(body: ChatIn, device: Device = Depends(current_device)):
    """Send a message. Streams Server-Sent Events by default; `stream: false` returns one JSON object."""
    events = get_agent().chat(
        body.message, body.conversation_id, Origin(device_id=device.id, kind=device.kind, voice=body.voice)
    )
    return sse(events) if body.stream else await collect(events)


class DecisionIn(BaseModel):
    approve: bool
    voice: bool = False
    stream: bool = True


@router.post("/actions/{action_id}")
async def decide_action(action_id: uuid.UUID, body: DecisionIn, device: Device = Depends(current_device),
                        session: AsyncSession = Depends(get_session)):
    """Approve or decline an action the agent asked about; the agent then continues the conversation."""
    if await session.get(PendingAction, action_id) is None:
        raise HTTPException(404, "No such action")
    events = get_agent().resolve(action_id, body.approve, Origin(device_id=device.id, kind=device.kind, voice=body.voice))
    return sse(events) if body.stream else await collect(events)


def _action_out(a: PendingAction) -> dict:
    return {
        "action_id": str(a.id),
        "conversation_id": str(a.conversation_id),
        "tool": a.tool_name,
        "summary": a.summary,
        "args": a.arguments,
        "status": a.status,
        "created_at": a.created_at.isoformat(),
    }


@router.get("/actions/pending")
async def pending_actions(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(select(PendingAction).where(PendingAction.status == "pending").order_by(PendingAction.created_at))
    ).scalars()
    return [_action_out(a) for a in rows]


# ---------------------------------------------------------------- conversations


@router.get("/conversations")
async def list_conversations(
    limit: int = 30, offset: int = 0, archived: bool = False, q: str | None = None,
    device: Device = Depends(current_device), session: AsyncSession = Depends(get_session),
):
    stmt = select(Conversation).where(Conversation.archived.is_(archived))
    if q:
        stmt = stmt.where(Conversation.title.ilike(f"%{q}%"))
    rows = list(
        (await session.execute(stmt.order_by(Conversation.updated_at.desc()).limit(min(limit, 100)).offset(offset))).scalars()
    )
    out = []
    for c in rows:
        # The latest thing Sora said, as the row's second line.
        preview = (
            await session.execute(
                select(Message.content)
                .where(Message.conversation_id == c.id, Message.role == "assistant", Message.content != "")
                .order_by(Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out.append(
            {"id": str(c.id), "title": c.title, "archived": c.archived, "pinned": c.pinned,
             "preview": " ".join((preview or "").split())[:140],
             "updated_at": c.updated_at.isoformat(), "created_at": c.created_at.isoformat()}
        )
    return out


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, include_tools: bool = False,
                           device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "No such conversation")
    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    messages = []
    for m in (await session.execute(stmt)).scalars():
        if not include_tools and (m.role == "tool" or (m.role == "assistant" and not m.content)):
            continue
        item = {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat(), "meta": m.meta}
        if include_tools:
            item.update(tool_calls=m.tool_calls, tool_call_id=m.tool_call_id, name=m.name)
        messages.append(item)
    pending = (
        await session.execute(
            select(PendingAction).where(PendingAction.conversation_id == conversation_id, PendingAction.status == "pending")
        )
    ).scalars()
    return {
        "id": str(conv.id),
        "title": conv.title,
        "archived": conv.archived,
        "pinned": conv.pinned,
        "messages": messages,
        "pending_actions": [_action_out(a) for a in pending],
    }


class ConversationPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    archived: bool | None = None
    pinned: bool | None = None


@router.patch("/conversations/{conversation_id}")
async def update_conversation(conversation_id: uuid.UUID, body: ConversationPatch,
                              device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "No such conversation")
    if body.title is not None:
        conv.title = body.title
    if body.archived is not None:
        conv.archived = body.archived
    if body.pinned is not None:
        conv.pinned = body.pinned
    return {"id": str(conv.id), "title": conv.title, "archived": conv.archived, "pinned": conv.pinned}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, device: Device = Depends(current_device),
                              session: AsyncSession = Depends(get_session)):
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "No such conversation")
    await session.delete(conv)


@router.get("/stats")
async def stats(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    async def count(model) -> int:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()

    return {"conversations": await count(Conversation), "messages": await count(Message)}
