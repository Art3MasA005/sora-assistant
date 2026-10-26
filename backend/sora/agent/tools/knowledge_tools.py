"""Memory and knowledge-base (RAG) tools."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select

from sora.agent.tools.base import ToolContext, registry
from sora.db import session_scope
from sora.google import workspace
from sora.google.client import get_google
from sora.models import Document, Memory
from sora.services import rag
from sora.textutil import truncate

# ================================================================ Memories


class MemorySaveArgs(BaseModel):
    fact: str = Field(description="One self-contained fact, e.g. 'Owner's thesis supervisor is Dr. Karim (karim@gub.edu.bd)'.")
    category: str = Field("general", description="person | preference | work | study | health | general")


@registry.tool(MemorySaveArgs, taint_guard=True, summary=lambda a: f"Remember: {a.fact}")
async def memory_save(ctx: ToolContext, a: MemorySaveArgs):
    """Remember a lasting fact or preference about the owner for future conversations."""
    async with session_scope() as session:
        m = await rag.add_memory(session, a.fact, a.category)
        return {"saved": True, "memory_id": str(m.id)}


class MemorySearchArgs(BaseModel):
    query: str


@registry.tool(MemorySearchArgs)
async def memory_search(ctx: ToolContext, a: MemorySearchArgs):
    """Search saved memories about the owner."""
    async with session_scope() as session:
        found = await rag.search_memories(session, a.query)
        return [{"id": str(m.id), "fact": m.content, "category": m.category} for m in found]


class MemoryUpdateArgs(BaseModel):
    memory_id: str
    fact: str


@registry.tool(MemoryUpdateArgs, taint_guard=True, summary=lambda a: f"Change memory to: {a.fact}")
async def memory_update(ctx: ToolContext, a: MemoryUpdateArgs):
    """Correct a saved memory when the owner says something changed."""
    async with session_scope() as session:
        m = await session.get(Memory, uuid.UUID(a.memory_id))
        if m is None:
            return "Error: no memory with that id"
        await rag.update_memory(session, m, a.fact)
        return {"updated": True}


class MemoryDeleteArgs(BaseModel):
    memory_id: str


@registry.tool(MemoryDeleteArgs, taint_guard=True, summary=lambda a: f"Forget memory {a.memory_id}")
async def memory_delete(ctx: ToolContext, a: MemoryDeleteArgs):
    """Forget a saved memory."""
    async with session_scope() as session:
        m = await session.get(Memory, uuid.UUID(a.memory_id))
        if m is None:
            return "Error: no memory with that id"
        await session.delete(m)
        return {"deleted": True}


# ================================================================ Knowledge base


class KnowledgeSearchArgs(BaseModel):
    query: str
    k: int = Field(6, ge=1, le=15)


@registry.tool(KnowledgeSearchArgs, untrusted=True)
async def knowledge_search(ctx: ToolContext, a: KnowledgeSearchArgs):
    """Search the owner's personal knowledge base (saved notes, uploaded files, saved web pages and Drive files)."""
    async with session_scope() as session:
        return await rag.search(session, a.query, a.k)


class KnowledgeAddNoteArgs(BaseModel):
    title: str
    content: str


@registry.tool(KnowledgeAddNoteArgs)
async def knowledge_add_note(ctx: ToolContext, a: KnowledgeAddNoteArgs):
    """Save a note to the knowledge base so it can be searched later."""
    async with session_scope() as session:
        doc = await rag.add_document(session, a.title, a.content, source="note")
        return {"document_id": str(doc.id), "title": doc.title}


class KnowledgeUpdateArgs(BaseModel):
    document_id: str
    title: str | None = None
    content: str | None = Field(None, description="Replaces the whole content.")
    append: str | None = Field(None, description="Added to the end of the content.")


@registry.tool(KnowledgeUpdateArgs)
async def knowledge_update(ctx: ToolContext, a: KnowledgeUpdateArgs):
    """Update a knowledge-base document: rename it, replace its content, or append to it."""
    async with session_scope() as session:
        doc = await session.get(Document, uuid.UUID(a.document_id))
        if doc is None:
            return "Error: no document with that id"
        await rag.update_document(session, doc, a.title, a.content, a.append)
        return {"updated": True, "document_id": str(doc.id), "length": len(doc.content)}


class KnowledgeReadArgs(BaseModel):
    document_id: str


@registry.tool(KnowledgeReadArgs, untrusted=True)
async def knowledge_read(ctx: ToolContext, a: KnowledgeReadArgs):
    """Read a whole knowledge-base document."""
    async with session_scope() as session:
        doc = await session.get(Document, uuid.UUID(a.document_id))
        if doc is None:
            return "Error: no document with that id"
        return {"id": str(doc.id), "title": doc.title, "source": doc.source, "content": truncate(doc.content, 11000)}


class KnowledgeListArgs(BaseModel):
    limit: int = Field(30, ge=1, le=100)


@registry.tool(KnowledgeListArgs)
async def knowledge_list(ctx: ToolContext, a: KnowledgeListArgs):
    """List documents in the knowledge base, newest first."""
    async with session_scope() as session:
        docs = (await session.execute(select(Document).order_by(Document.updated_at.desc()).limit(a.limit))).scalars()
        return [{"id": str(d.id), "title": d.title, "source": d.source, "updated": d.updated_at.isoformat()} for d in docs]


class KnowledgeAddUrlArgs(BaseModel):
    url: str


@registry.tool(KnowledgeAddUrlArgs, taint_guard=True, summary=lambda a: f"Fetch and save {a.url}")
async def knowledge_add_url(ctx: ToolContext, a: KnowledgeAddUrlArgs):
    """Fetch a web page and save its text to the knowledge base."""
    title, text = await rag.fetch_url_text(a.url)
    async with session_scope() as session:
        doc = await rag.add_document(session, title, text, source="url", source_ref=a.url)
        return {"document_id": str(doc.id), "title": doc.title, "characters": len(text)}


class KnowledgeAddDriveArgs(BaseModel):
    file_id: str


@registry.tool(KnowledgeAddDriveArgs, needs="drive")
async def knowledge_add_drive_file(ctx: ToolContext, a: KnowledgeAddDriveArgs):
    """Copy a Google Drive file's text into the knowledge base (re-running refreshes it)."""
    f = await workspace.drive_read(get_google(), a.file_id, max_chars=2_000_000)
    if "error" in f:
        return f"Error: {f['error']}"
    async with session_scope() as session:
        doc = await rag.add_document(
            session, f["name"], f["content"], source="drive", source_ref=a.file_id, meta={"link": f.get("link")}
        )
        return {"document_id": str(doc.id), "title": doc.title}


class KnowledgeDeleteArgs(BaseModel):
    document_id: str
    title: str = ""


@registry.tool(
    KnowledgeDeleteArgs, confirm=True, summary=lambda a: f"Delete '{a.title or a.document_id}' from the knowledge base"
)
async def knowledge_delete(ctx: ToolContext, a: KnowledgeDeleteArgs):
    """Delete a document from the knowledge base (asks the owner first)."""
    async with session_scope() as session:
        return {"deleted": await rag.delete_document(session, uuid.UUID(a.document_id))}
