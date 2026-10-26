"""Knowledge base (documents) and memories: the owner's editable RAG data."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sora.api.deps import current_device
from sora.db import get_session
from sora.models import Chunk, Device, Document, Memory
from sora.services import rag

router = APIRouter(prefix="/api", tags=["knowledge"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _doc_out(d: Document, chunks: int | None = None, full: bool = False) -> dict:
    out = {
        "id": str(d.id),
        "title": d.title,
        "source": d.source,
        "source_ref": d.source_ref,
        "meta": d.meta,
        "characters": len(d.content),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
    if chunks is not None:
        out["chunks"] = chunks
    if full:
        out["content"] = d.content
    else:
        out["preview"] = d.content[:200]
    return out


@router.get("/knowledge")
async def list_documents(q: str | None = None, limit: int = 50, offset: int = 0,
                         device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    stmt = select(Document)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{q}%"))
    rows = (await session.execute(stmt.order_by(Document.updated_at.desc()).limit(min(limit, 200)).offset(offset))).scalars()
    return [_doc_out(d) for d in rows]


@router.get("/knowledge/search")
async def search_documents(q: str, k: int = 6, device: Device = Depends(current_device),
                           session: AsyncSession = Depends(get_session)):
    return await rag.search(session, q, min(k, 20))


@router.get("/knowledge/{doc_id}")
async def get_document(doc_id: uuid.UUID, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "No such document")
    chunks = (await session.execute(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id))).scalar_one()
    return _doc_out(doc, chunks, full=True)


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)


@router.post("/knowledge/notes", status_code=201)
async def add_note(body: NoteIn, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    doc = await rag.add_document(session, body.title, body.content, source="note")
    return _doc_out(doc)


class UrlIn(BaseModel):
    url: str


@router.post("/knowledge/url", status_code=201)
async def add_url(body: UrlIn, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    try:
        title, text = await rag.fetch_url_text(body.url)
    except Exception as exc:
        raise HTTPException(400, f"Could not fetch that page: {exc}") from exc
    doc = await rag.add_document(session, title, text, source="url", source_ref=body.url)
    return _doc_out(doc)


@router.post("/knowledge/upload", status_code=201)
async def upload(file: UploadFile = File(...), title: str | None = Form(None),
                 device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 20 MB")
    try:
        text = rag.extract_text(file.filename or "upload.txt", data)
    except Exception as exc:
        raise HTTPException(400, f"Could not read that file: {exc}") from exc
    if not text.strip():
        raise HTTPException(400, "No text found in that file (scanned PDFs are not supported yet).")
    doc = await rag.add_document(session, title or file.filename or "Upload", text, source="upload",
                                 meta={"filename": file.filename, "content_type": file.content_type})
    return _doc_out(doc)


class DocPatch(BaseModel):
    title: str | None = Field(None, max_length=300)
    content: str | None = None
    append: str | None = None


@router.patch("/knowledge/{doc_id}")
async def update_document(doc_id: uuid.UUID, body: DocPatch, device: Device = Depends(current_device),
                          session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "No such document")
    await rag.update_document(session, doc, body.title, body.content, body.append)
    return _doc_out(doc, full=True)


@router.delete("/knowledge/{doc_id}", status_code=204)
async def delete_document(doc_id: uuid.UUID, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    if not await rag.delete_document(session, doc_id):
        raise HTTPException(404, "No such document")


# ---------------------------------------------------------------- memories


def _memory_out(m: Memory) -> dict:
    return {
        "id": str(m.id),
        "content": m.content,
        "category": m.category,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


@router.get("/memories")
async def list_memories(q: str | None = None, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    if q:
        return [_memory_out(m) for m in await rag.search_memories(session, q, k=30)]
    rows = (await session.execute(select(Memory).order_by(Memory.created_at.desc()))).scalars()
    return [_memory_out(m) for m in rows]


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = "general"


@router.post("/memories", status_code=201)
async def add_memory(body: MemoryIn, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    return _memory_out(await rag.add_memory(session, body.content, body.category))


class MemoryPatch(BaseModel):
    content: str | None = Field(None, min_length=1, max_length=2000)
    category: str | None = None


@router.patch("/memories/{memory_id}")
async def update_memory(memory_id: uuid.UUID, body: MemoryPatch, device: Device = Depends(current_device),
                        session: AsyncSession = Depends(get_session)):
    m = await session.get(Memory, memory_id)
    if m is None:
        raise HTTPException(404, "No such memory")
    if body.category:
        m.category = body.category
    if body.content:
        await rag.update_memory(session, m, body.content)
    return _memory_out(m)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    m = await session.get(Memory, memory_id)
    if m is None:
        raise HTTPException(404, "No such memory")
    await session.delete(m)
