"""People: matching how the owner names someone, the API, the tools, calls by nickname and birthdays."""

from __future__ import annotations

from contextlib import aclosing
from datetime import date

from conftest import run
from test_api import _client

from sora.agent.tools import ToolContext, registry
from sora.db import session_scope
from sora.models import Person
from sora.services import people

CLEAN, TAINTED = ToolContext(None), ToolContext(None, tainted=True)


def _p(name, relation="", aliases=(), phones=(), birthday=None):
    return Person(name=name, relation=relation, aliases=list(aliases), phones=list(phones), emails=[], notes="",
                  birthday=birthday)


def test_naming_someone_the_owners_way():
    boss = _p("Rahim Uddin", "boss", ["Rahim bhai"])
    mother = _p("Ayesha Begum", "mother", ["Ammu", "আম্মু"])
    for said in ("Rahim Uddin", "rahim", "Rahim bhai", "my boss", "Boss", "rahim-uddin"):
        assert people.score(boss, said) >= people.CLOSE, said
    for said in ("Ammu", "ammu", "আম্মু", "আমার আম্মু", "my mother"):
        assert people.score(mother, said) >= people.CLOSE, said
    assert people.score(boss, "Tasdid") < people.CLOSE
    assert people.score(_p("আদিল"), "আদিল") == 1.0  # Bangla vowel signs and "দি" inside a name stay
    assert people.score(_p("Tasdid Hasan"), "tasdeed") >= people.CLOSE  # a near spelling


def test_birthdays_coming_up():
    today = date(2026, 10, 21)
    soon = people.upcoming_birthdays([
        _p("A", birthday=date(1990, 10, 21)), _p("B", birthday=date(1900, 10, 24)),
        _p("C", birthday=date(1995, 12, 1)), _p("D", birthday=date(2000, 10, 20)),
    ], today)
    assert [(p.name, d) for p, d in soon] == [("A", 0), ("B", 3)]
    leap = people.upcoming_birthdays([_p("E", birthday=date(2000, 2, 29))], date(2027, 2, 25))
    assert [d for _, d in leap] == [4]  # 1 March in a common year


def test_the_people_screen_api():
    async def scenario():
        client, _ = await _client()
        async with aclosing(client):
            made = await client.post("/api/people", json={
                "name": " Rahim Uddin ", "relation": "boss", "phones": ["01711111111", " ", "01711111111"],
                "emails": ["rahim@x.com"], "aliases": ["Rahim bhai"], "birthday": "1980-05-02", "notes": "Office in Gulshan",
            })
            assert made.status_code == 201, made.text
            r = made.json()
            assert r["name"] == "Rahim Uddin" and r["phones"] == ["01711111111"] and r["birthday"] == "1980-05-02"
            await client.post("/api/people", json={"name": "Ayesha Begum", "relation": "mother", "aliases": ["Ammu"]})
            everyone = (await client.get("/api/people")).json()
            assert [p["name"] for p in everyone] == ["Ayesha Begum", "Rahim Uddin"]
            assert [p["name"] for p in (await client.get("/api/people", params={"q": "my boss"})).json()] == ["Rahim Uddin"]
            changed = await client.put(f"/api/people/{r['id']}", json={**r, "phones": ["01722222222"], "birthday": None})
            assert changed.json()["phones"] == ["01722222222"] and changed.json()["birthday"] is None
            assert (await client.delete(f"/api/people/{r['id']}")).status_code == 204
            assert (await client.put(f"/api/people/{r['id']}", json={"name": "x"})).status_code == 404
            assert (await client.post("/api/people", json={"name": ""})).status_code == 422

    run(scenario())


def test_the_tools_save_find_and_ask_before_removing():
    save, find, remove = registry.get("people_save"), registry.get("people_find"), registry.get("people_delete")
    assert not save.needs_confirmation(save.args_model(name="Tasdid"), CLEAN)  # an ordinary thing: no asking
    assert save.needs_confirmation(save.args_model(name="Tasdid"), TAINTED)  # an email can't plant contacts
    assert remove.needs_confirmation(remove.args_model(person="Tasdid"), CLEAN)  # deleting asks

    async def scenario():
        made = await registry.run(save, save.args_model(name="Tasdid Hasan", relation="cousin", phones=["01811111111"],
                                                        aliases=["তাসদিদ"]), CLEAN)
        assert made.ok, made.content
        more = await registry.run(save, save.args_model(person="tasdid", phones=["01822222222"], emails=["t@x.com"],
                                                        notes="Lives in Sylhet"), CLEAN)
        assert more.ok and more.data["saved"]["phones"] == ["01811111111", "01822222222"]  # added, not replaced
        found = await registry.run(find, find.args_model(query="তাসদিদ"), CLEAN)
        assert found.data[0]["emails"] == ["t@x.com"]
        by_note = await registry.run(find, find.args_model(query="Sylhet"), CLEAN)
        assert by_note.data[0]["name"] == "Tasdid Hasan"
        await registry.run(save, save.args_model(name="Tasdid Rahman"), CLEAN)
        which = await registry.run(save, save.args_model(person="Tasdid", phones=["1"]), CLEAN)
        assert not which.ok and "Tasdid Hasan" in which.content and "Tasdid Rahman" in which.content  # asks which
        gone = await registry.run(remove, remove.args_model(person="Tasdid Rahman"), CLEAN)
        assert gone.data == {"removed": "Tasdid Rahman"}

    run(scenario())


def test_calling_a_nickname_uses_the_saved_number(monkeypatch):
    phone_action = registry.get("phone_action")
    emitted: list = []

    async def emit(event):
        emitted.append(event)

    async def no_log(*_a, **_k):
        return None

    async def no_google(_name):
        return None

    monkeypatch.setattr("sora.agent.tools.device_tools._log_command", no_log)
    monkeypatch.setattr("sora.agent.tools.device_tools._google_number", no_google)

    async def scenario():
        async with session_scope() as session:
            session.add(_p("Ayesha Begum", "mother", ["Ammu", "আম্মু"], ["01911111111"]))
        ctx = ToolContext(None, origin_kind="android", emit=emit)
        for said in ("Ammu", "আম্মু", "my mother"):
            outcome = await registry.run(phone_action, phone_action.args_model(action="call", target=said), ctx)
            assert outcome.ok, outcome.content
            assert emitted[-1]["params"]["target"] == "01911111111", said
        await registry.run(phone_action, phone_action.args_model(action="call", target="Karim"), ctx)
        assert emitted[-1]["params"]["target"] == "Karim"  # not saved: the phone's own contacts find it

    run(scenario())


def test_birthdays_reach_the_prompt():
    from sora.agent.runner import Agent, Origin
    from sora.timeutil import now_local

    async def scenario():
        today = now_local().date()
        async with session_scope() as session:
            session.add(_p("Ayesha Begum", "mother", birthday=today.replace(year=1970)))
        lines = await Agent(llm=None)._status_lines(set(), Origin())
        assert any("Ayesha Begum (mother) today" in line for line in lines)

    run(scenario())
