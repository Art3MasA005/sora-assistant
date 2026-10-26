"""The owner's people (contacts with relation, nicknames and birthday) for the LLM."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from sora.agent.tools.base import ToolContext, registry
from sora.db import session_scope
from sora.models import Person
from sora.services import people


class PeopleFindArgs(BaseModel):
    query: str = Field(description="A name, nickname or relation as the owner said it ('Ammu', 'my boss', 'Tasdid'), "
                                   "or a word from their notes. Empty: everyone (first 30).")


@registry.tool(PeopleFindArgs)
async def people_find(ctx: ToolContext, a: PeopleFindArgs):
    """Look up someone in the owner's People: relation, phone numbers, emails, nicknames, birthday, notes.
    Use it for "what is my boss's email?", "when is Ammu's birthday?", or an email to a person by name."""
    async with session_scope() as session:
        found = await people.find(session, a.query, limit=30 if not a.query.strip() else 5)
        if not found:
            return f"Nobody called '{a.query}' in People. Ask the owner, or offer to save them."
        return [people.person_dict(p) for p in found]


class PeopleSaveArgs(BaseModel):
    person: str | None = Field(None, description="To change someone already saved: their name, nickname or relation. "
                                                 "Empty: a new person.")
    name: str | None = Field(None, description="Full name (needed for a new person)")
    relation: str | None = Field(None, description="Who they are to the owner: boss, mother, cousin, friend, supervisor...")
    phones: list[str] | None = Field(None, description="Phone numbers to add (the first is the one called)")
    emails: list[str] | None = Field(None, description="Email addresses to add")
    aliases: list[str] | None = Field(None, description="Other names the owner uses for them, in English and Bangla "
                                                        "letters: 'Ammu', 'আম্মু', 'Rahim bhai'")
    birthday: date | None = Field(None, description="YYYY-MM-DD (use 1900 as the year when it isn't known)")
    notes: str | None = Field(None, description="Anything else worth keeping; added to what is there")


def _save_summary(a: PeopleSaveArgs) -> str:
    bits = [b for b in (a.relation, ", ".join(a.phones or []), ", ".join(a.emails or [])) if b]
    who = a.name or a.person or "?"
    return f"{'Update' if a.person else 'Save'} {who} in People" + (f": {' · '.join(bits)}" if bits else "")


@registry.tool(PeopleSaveArgs, taint_guard=True, summary=_save_summary)
async def people_save(ctx: ToolContext, a: PeopleSaveArgs):
    """Save someone the owner tells you about (family, friends, colleagues, the boss) or add to what is saved:
    a number, an email, a nickname, a birthday. Use this, not memory_save, for people's details."""
    async with session_scope() as session:
        if a.person:
            p = await people.resolve(session, a.person)
            if p is None:
                close = await people.find(session, a.person)
                return (f"Error: '{a.person}' isn't one person in People"
                        + (f" (could be: {', '.join(x.name for x in close)})" if close else "") + ". Ask which one.")
        else:
            if not a.name:
                return "Error: a new person needs a name."
            p = Person(name=a.name.strip(), relation="", phones=[], emails=[], aliases=[], notes="")
            session.add(p)
        if a.name and a.person:
            p.name = a.name.strip()
        if a.relation is not None:
            p.relation = a.relation.strip()[:80]
        # Lists grow: a second number doesn't replace the first.
        p.phones = people.clean_list([*(p.phones or []), *(a.phones or [])])
        p.emails = people.clean_list([*(p.emails or []), *(a.emails or [])])
        p.aliases = people.clean_list([*(p.aliases or []), *(a.aliases or [])])
        if a.birthday is not None:
            p.birthday = a.birthday
        if a.notes:
            p.notes = (f"{p.notes}\n{a.notes}" if p.notes else a.notes).strip()[:4000]
        await session.flush()
        return {"saved": people.person_dict(p)}


class PeopleDeleteArgs(BaseModel):
    person: str = Field(description="Their name, nickname or relation")


@registry.tool(PeopleDeleteArgs, confirm=True, summary=lambda a: f"Remove {a.person} from People")
async def people_delete(ctx: ToolContext, a: PeopleDeleteArgs):
    """Remove someone from the owner's People."""
    async with session_scope() as session:
        p = await people.resolve(session, a.person)
        if p is None:
            return f"Error: '{a.person}' isn't one person in People."
        await session.delete(p)
        return {"removed": p.name}
