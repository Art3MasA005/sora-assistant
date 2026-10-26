"""Tiny key/value helpers over the kv table."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sora.models import KeyValue


async def kv_get(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(KeyValue, key)
    return default if row is None else row.value


async def kv_set(session: AsyncSession, key: str, value: Any) -> None:
    stmt = insert(KeyValue).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=[KeyValue.key], set_={"value": value})
    await session.execute(stmt)


async def kv_delete(session: AsyncSession, key: str) -> None:
    row = await session.get(KeyValue, key)
    if row is not None:
        await session.delete(row)
