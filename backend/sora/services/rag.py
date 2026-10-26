"""Knowledge base and memories: ingest, update, hybrid (vector + full-text) search."""

from __future__ import annotations

import io
import logging
import re
import uuid
import zipfile
from xml.etree import ElementTree

import httpx
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sora.llm.embeddings import EmbeddingError, get_embedder
from sora.models import Chunk, Document, Memory
from sora.textutil import chunk_text, html_to_text

log = logging.getLogger(__name__)

# Memories are injected into every prompt; past this count only the most relevant ones are.
MEMORY_PROMPT_ALL_LIMIT = 40


# ---------------------------------------------------------------- documents


async def _rebuild_chunks(session: AsyncSession, doc: Document) -> int:
    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    pieces = chunk_text(f"{doc.title}\n\n{doc.content}")
    vectors: list[list[float] | None] = [None] * len(pieces)
    embedder = get_embedder()
    if embedder.available and pieces:
        try:
            vectors = await embedder.embed(pieces)
        except (EmbeddingError, httpx.HTTPError) as exc:
            log.warning("embedding failed for %s, stored without vectors: %s", doc.title, exc)
    session.add_all(
        Chunk(document_id=doc.id, idx=i, content=piece, embedding=vec)
        for i, (piece, vec) in enumerate(zip(pieces, vectors, strict=True))
    )
    await session.flush()
    return len(pieces)


async def add_document(
    session: AsyncSession, title: str, content: str, source: str = "note", source_ref: str | None = None,
    meta: dict | None = None,
) -> Document:
    # Re-ingesting the same Drive file or URL updates it instead of duplicating it.
    doc = None
    if source_ref:
        doc = (
            await session.execute(select(Document).where(Document.source == source, Document.source_ref == source_ref))
        ).scalar_one_or_none()
    if doc is None:
        doc = Document(title=title, content=content, source=source, source_ref=source_ref, meta=meta or {})
        session.add(doc)
    else:
        doc.title, doc.content, doc.meta = title, content, meta or doc.meta
    await session.flush()
    await _rebuild_chunks(session, doc)
    return doc


async def update_document(
    session: AsyncSession, doc: Document, title: str | None = None, content: str | None = None, append: str | None = None
) -> Document:
    if title is not None:
        doc.title = title
    if content is not None:
        doc.content = content
    if append:
        doc.content = f"{doc.content.rstrip()}\n\n{append.strip()}"
    await session.flush()
    await _rebuild_chunks(session, doc)
    return doc


async def reindex_all(session: AsyncSession) -> int:
    docs = (await session.execute(select(Document))).scalars().all()
    for doc in docs:
        await _rebuild_chunks(session, doc)
    memories = (await session.execute(select(Memory))).scalars().all()
    embedder = get_embedder()
    if embedder.available and memories:
        vectors = await embedder.embed([m.content for m in memories])
        for m, v in zip(memories, vectors, strict=True):
            m.embedding = v
    return len(docs)


async def search(session: AsyncSession, query: str, k: int = 6) -> list[dict]:
    """Hybrid search: reciprocal-rank fusion of vector similarity and full-text matches."""
    scores: dict[int, float] = {}
    rows: dict[int, tuple[Chunk, Document]] = {}
    pool = k * 3

    vec = await get_embedder().embed_one(query)
    if vec is not None:
        result = await session.execute(
            select(Chunk, Document)
            .join(Document)
            .where(Chunk.embedding.is_not(None))
            .order_by(Chunk.embedding.cosine_distance(vec))
            .limit(pool)
        )
        for rank, (chunk, doc) in enumerate(result.all()):
            scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (60 + rank)
            rows[chunk.id] = (chunk, doc)

    tsq = func.websearch_to_tsquery("simple", query)
    result = await session.execute(
        select(Chunk, Document).join(Document).where(Chunk.tsv.op("@@")(tsq))
        .order_by(func.ts_rank(Chunk.tsv, tsq).desc()).limit(pool)
    )
    fts = result.all()
    if not fts and vec is None:
        # Partial-word fallback (full-text needs whole tokens).
        terms = [t for t in re.split(r"\s+", query) if len(t) > 1][:5]
        if terms:
            cond = Chunk.content.ilike(f"%{terms[0]}%")
            for t in terms[1:]:
                cond = cond | Chunk.content.ilike(f"%{t}%")
            fts = (await session.execute(select(Chunk, Document).join(Document).where(cond).limit(pool))).all()
    for rank, (chunk, doc) in enumerate(fts):
        scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (60 + rank)
        rows[chunk.id] = (chunk, doc)

    best = sorted(scores, key=scores.get, reverse=True)[:k]
    return [
        {
            "document_id": str(rows[cid][1].id),
            "title": rows[cid][1].title,
            "source": rows[cid][1].source,
            "source_ref": rows[cid][1].source_ref,
            "content": rows[cid][0].content,
            "score": round(scores[cid], 4),
        }
        for cid in best
    ]


# ---------------------------------------------------------------- extraction


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            root = ElementTree.fromstring(zf.read("word/document.xml"))
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = ["".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p")]
        return "\n".join(paragraphs)
    if name.endswith((".html", ".htm")):
        return html_to_text(data.decode("utf-8", errors="replace"))
    return data.decode("utf-8", errors="replace")


async def fetch_url_text(url: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Sora"}) as c:
        resp = await c.get(url)
        resp.raise_for_status()
    body = resp.text
    if "html" in resp.headers.get("content-type", ""):
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        title = html_to_text(m.group(1)) if m else url
        return title[:300], html_to_text(body)
    return url[:300], body


# ---------------------------------------------------------------- memories


async def add_memory(session: AsyncSession, content: str, category: str = "general") -> Memory:
    memory = Memory(content=content.strip(), category=category, embedding=await get_embedder().embed_one(content))
    session.add(memory)
    await session.flush()
    return memory


async def update_memory(session: AsyncSession, memory: Memory, content: str) -> Memory:
    memory.content = content.strip()
    memory.embedding = await get_embedder().embed_one(content)
    await session.flush()
    return memory


async def search_memories(session: AsyncSession, query: str, k: int = 10) -> list[Memory]:
    vec = await get_embedder().embed_one(query)
    if vec is not None:
        stmt = (
            select(Memory)
            .where(Memory.embedding.is_not(None))
            .order_by(Memory.embedding.cosine_distance(vec))
            .limit(k)
        )
        found = list((await session.execute(stmt)).scalars().all())
        if found:
            return found
    terms = [t for t in re.split(r"\s+", query) if len(t) > 2][:6]
    stmt = select(Memory).order_by(Memory.updated_at.desc()).limit(k)
    if terms:
        cond = Memory.content.ilike(f"%{terms[0]}%")
        for t in terms[1:]:
            cond = cond | Memory.content.ilike(f"%{t}%")
        stmt = select(Memory).where(cond).order_by(Memory.updated_at.desc()).limit(k)
    return list((await session.execute(stmt)).scalars().all())


async def memories_for_prompt(session: AsyncSession, query: str) -> list[Memory]:
    total = (await session.execute(select(func.count()).select_from(Memory))).scalar_one()
    if total <= MEMORY_PROMPT_ALL_LIMIT:
        return list((await session.execute(select(Memory).order_by(Memory.created_at))).scalars().all())
    return await search_memories(session, query, k=15)


async def delete_document(session: AsyncSession, doc_id: uuid.UUID) -> bool:
    doc = await session.get(Document, doc_id)
    if doc is None:
        return False
    await session.delete(doc)
    return True


async def vector_index_ready(session: AsyncSession) -> bool:
    result = await session.execute(text("select 1 from pg_extension where extname = 'vector'"))
    return result.scalar() is not None
