"""Routines for the apps' Routines screen: list, switch on/off, run now, history, delete.
Creating and editing go through the chat (routine_create / routine_update), where the owner approves them."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sora.api.deps import current_device
from sora.db import get_session, session_scope
from sora.models import Device, Routine, RoutineRun
from sora.services import routines

router = APIRouter(prefix="/api/routines", tags=["routines"])


@router.get("")
async def list_routines(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Routine).order_by(Routine.created_at))).scalars()
    return [routines.routine_dict(r) for r in rows]


class RoutinePatch(BaseModel):
    enabled: bool | None = None
    speak: bool | None = None


@router.patch("/{routine_id}")
async def update_routine(routine_id: uuid.UUID, body: RoutinePatch, device: Device = Depends(current_device)):
    """The owner's own switches in the app (no approval needed, unlike a change asked for in the chat)."""
    async with session_scope() as session:  # committed before the scheduler is woken
        r = await session.get(Routine, routine_id)
        if r is None:
            raise HTTPException(404, "No such routine")
        if body.enabled is not None:
            r.enabled = body.enabled
            routines.schedule(r)
        if body.speak is not None:
            r.speak = body.speak
        out = routines.routine_dict(r)
    routines.poke()
    return out


@router.delete("/{routine_id}", status_code=204)
async def delete_routine(routine_id: uuid.UUID, device: Device = Depends(current_device)):
    async with session_scope() as session:
        r = await session.get(Routine, routine_id)
        if r is None:
            raise HTTPException(404, "No such routine")
        await routines.remove(session, r)
    routines.poke()


@router.post("/{routine_id}/run", status_code=202)
async def run_routine_now(routine_id: uuid.UUID, device: Device = Depends(current_device),
                          session: AsyncSession = Depends(get_session)):
    """Runs it now in the background; the result arrives as a notification like a scheduled run.
    A page watch looks at its page now instead, and runs only if the page changed."""
    r = await session.get(Routine, routine_id)
    if r is None:
        raise HTTPException(404, "No such routine")
    if r.trigger.get("type") == "page_change":
        routines.start_check(r.id, dict(r.trigger))
    else:
        routines.start(routine_id, "run now from the app")
    return {"started": True}


@router.get("/{routine_id}/runs")
async def routine_runs(routine_id: uuid.UUID, device: Device = Depends(current_device),
                       session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(select(RoutineRun).where(RoutineRun.routine_id == routine_id).order_by(RoutineRun.id.desc()))
    ).scalars()
    return [
        {"id": run.id, "reason": run.reason, "status": run.status, "result": run.result,
         "conversation_id": str(run.conversation_id) if run.conversation_id else None,
         "started_at": run.started_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None}
        for run in rows
    ]
