"""Embeddings through any OpenAI-compatible /embeddings endpoint.

If no key is configured, RAG still works through Postgres full-text search;
embeddings only improve ranking.
"""

from __future__ import annotations

import logging

import httpx

from sora.config import get_settings

log = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


class Embedder:
    def __init__(self) -> None:
        s = get_settings()
        self.base_url = s.embedding_base_url.rstrip("/")
        self.api_key = s.embedding_key
        self.model = s.embedding_model
        self.dim = s.embedding_dim
        self.send_dimensions = s.embedding_send_dimensions
        self.data_collection = s.llm_data_collection.strip().lower()
        self._client = httpx.AsyncClient(timeout=60)

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.available:
            raise EmbeddingError("embeddings are not configured")
        out: list[list[float]] = []
        for start in range(0, len(texts), 64):
            batch = [t[:8000] for t in texts[start : start + 64]]
            payload: dict = {"model": self.model, "input": batch}
            if self.send_dimensions:
                payload["dimensions"] = self.dim
            if "openrouter.ai" in self.base_url and self.data_collection in {"allow", "deny"}:
                payload["provider"] = {"data_collection": self.data_collection}  # notes pass through here too
            resp = await self._client.post(
                f"{self.base_url}/embeddings",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code >= 400:
                raise EmbeddingError(f"embedding request failed ({resp.status_code}): {resp.text[:300]}")
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            for item in data:
                vec = item["embedding"]
                if len(vec) != self.dim:
                    raise EmbeddingError(
                        f"model returned {len(vec)} dims but EMBEDDING_DIM={self.dim}; fix .env"
                    )
                out.append(vec)
        return out

    async def embed_one(self, text: str) -> list[float] | None:
        """Best effort: returns None instead of raising, so callers can fall back to keyword search."""
        if not self.available:
            return None
        try:
            return (await self.embed([text]))[0]
        except (EmbeddingError, httpx.HTTPError) as exc:
            log.warning("embedding failed, using keyword search only: %s", exc)
            return None


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder
