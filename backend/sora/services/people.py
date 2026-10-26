"""The owner's people: finding someone by how the owner names them.

"Ammu", "আম্মু", "my boss", "Rahim bhai", "tasdid": each is matched against the names, nicknames and
relations the owner saved, spaces, dots and case aside, with a little room for spelling. The list is
one owner's contacts (tens to a few hundred), so it is read whole and matched here.
"""

from __future__ import annotations

import difflib
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sora.models import Person

CLOSE = 0.82  # how alike two spellings must be to count ("tasdid" / "tasdeed")
# Said around a name or relation, not part of it: "my boss", "Rahim bhai", "আমার আম্মু".
# (Whole words only: Bangla vowel signs aren't \w, so the Bangla ones are bounded by spaces instead.)
FILLER = re.compile(
    r"\b(my|the|mr|mrs|ms|dr|sir|madam|bhai|vai|bhaiya|apu|apa|da|di|uncle|aunty|auntie)\b\.?"
    r"|(?<!\S)(আমার|ভাই|ভাইয়া|আপু|আপা|দা|দি)(?!\S)",
    re.IGNORECASE,
)


def norm(text: str) -> str:
    """Case, spaces and punctuation aside (Bangla vowel signs stay: they are part of the word)."""
    return re.sub(r"[\s.,'\"()\-_/]+", "", text.casefold())


def sound(text: str) -> str:
    """Bangla names in English letters are spelled many ways ("Tasdid", "Tasdeed", "Mahmud", "Mahmood"):
    their consonants, without the h of bh/dh/kh... and doubled letters, are what stays the same."""
    s = norm(text)
    if not s.isascii():
        return s
    s = re.sub(r"(?<=[bcdgkpst])h", "", s)
    s = s[:1] + re.sub(r"[aeiouyw]", "", s[1:])
    return re.sub(r"(.)\1+", r"\1", s)


def _names(p: Person) -> list[str]:
    return [n for n in [p.name, *(p.aliases or [])] if n]


def score(p: Person, query: str) -> float:
    """How well [query] names [p]: 1 for a name, nickname or relation said exactly, less for a near spelling."""
    q, bare = norm(query), norm(FILLER.sub(" ", query))
    if not q:
        return 0.0
    best = 0.0
    for name in _names(p):
        n = norm(name)
        if not n:
            continue
        if n in (q, bare):
            return 1.0
        first = norm(name.split()[0]) if name.split() else n
        if len(first) >= 3 and first in (q, bare):
            best = max(best, 0.95)  # "Rahim" for "Rahim Uddin"
        said = sound(bare or q)
        if len(said) >= 3 and said in (sound(name), sound(name.split()[0])):
            best = max(best, 0.88)  # "Tasdeed" for "Tasdid Hasan"
        best = max(best, difflib.SequenceMatcher(None, n, bare or q).ratio())
    if p.relation and norm(p.relation) in (q, bare):
        best = max(best, 0.9)
    return best


async def everyone(session: AsyncSession) -> list[Person]:
    return list((await session.execute(select(Person).order_by(Person.name))).scalars())


async def find(session: AsyncSession, query: str, limit: int = 5) -> list[Person]:
    """The people [query] could mean, best first; all of them for an empty query."""
    people = await everyone(session)
    if not query.strip():
        return people[:limit]
    ranked = sorted(((score(p, query), p) for p in people), key=lambda sp: -sp[0])
    # also a word of the notes or relation ("who is from Sylhet?")
    words = norm(query)
    loose = [p for p in people if words and (words in norm(p.notes or "") or words in norm(p.relation or ""))]
    out = [p for s, p in ranked if s >= CLOSE]
    out += [p for p in loose if p not in out]
    return out[:limit]


async def resolve(session: AsyncSession, query: str) -> Person | None:
    """The one person [query] means, or None when nobody or several match equally well."""
    people = await everyone(session)
    ranked = sorted(((score(p, query), p) for p in people), key=lambda sp: -sp[0])
    if not ranked or ranked[0][0] < CLOSE:
        return None
    if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] - 0.03:
        return None  # two "Rahim"s, or two friends: ask, don't guess
    return ranked[0][1]


def upcoming_birthdays(people: list[Person], today: date, days: int = 7) -> list[tuple[Person, int]]:
    """(person, days until) for birthdays from today through [days] ahead, soonest first."""
    out = []
    for p in people:
        if p.birthday is None:
            continue
        try:
            next_one = p.birthday.replace(year=today.year)
        except ValueError:  # 29 February in a common year
            next_one = date(today.year, 3, 1)
        if next_one < today:
            try:
                next_one = p.birthday.replace(year=today.year + 1)
            except ValueError:
                next_one = date(today.year + 1, 3, 1)
        ahead = (next_one - today).days
        if ahead <= days:
            out.append((p, ahead))
    return sorted(out, key=lambda pa: pa[1])


def clean_list(values: list[str] | None, limit: int = 10) -> list[str]:
    """Trimmed, without blanks and repeats, in the owner's order."""
    out: list[str] = []
    for v in values or []:
        v = " ".join(str(v).split())
        if v and v.casefold() not in {o.casefold() for o in out}:
            out.append(v[:120])
    return out[:limit]


def person_dict(p: Person) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "relation": p.relation or "",
        "phones": list(p.phones or []),
        "emails": list(p.emails or []),
        "aliases": list(p.aliases or []),
        "birthday": p.birthday.isoformat() if p.birthday else None,
        "notes": p.notes or "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
