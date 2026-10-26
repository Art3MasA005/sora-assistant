"""People for the apps' People screen: the owner adds, edits, finds and removes contacts themselves."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from sora.api.deps import current_device
from sora.db import get_session
from sora.models import Device, Person
from sora.services import people

router = APIRouter(prefix="/api/people", tags=["people"])


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    relation: str = Field("", max_length=80)
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    birthday: date | None = None
    notes: str = Field("", max_length=4000)

    @field_validator("phones", "emails", "aliases")
    @classmethod
    def _tidy(cls, v: list[str]) -> list[str]:
        return people.clean_list(v)


@router.get("")
async def list_people(q: str | None = None, device: Device = Depends(current_device),
                      session: AsyncSession = Depends(get_session)):
    found = await people.find(session, q, limit=50) if q else await people.everyone(session)
    return [people.person_dict(p) for p in found]


@router.post("", status_code=201)
async def add_person(body: PersonIn, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    p = Person(**body.model_dump())
    p.name = p.name.strip()
    session.add(p)
    await session.flush()
    await session.refresh(p)
    return people.person_dict(p)


@router.put("/{person_id}")
async def update_person(person_id: uuid.UUID, body: PersonIn, device: Device = Depends(current_device),
                        session: AsyncSession = Depends(get_session)):
    p = await session.get(Person, person_id)
    if p is None:
        raise HTTPException(404, "No such person")
    for key, value in body.model_dump().items():
        setattr(p, key, value.strip() if isinstance(value, str) else value)
    await session.flush()
    await session.refresh(p)
    return people.person_dict(p)


@router.delete("/{person_id}", status_code=204)
async def delete_person(person_id: uuid.UUID, device: Device = Depends(current_device),
                        session: AsyncSession = Depends(get_session)):
    p = await session.get(Person, person_id)
    if p is None:
        raise HTTPException(404, "No such person")
    await session.delete(p)
