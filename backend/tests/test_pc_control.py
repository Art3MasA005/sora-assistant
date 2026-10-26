"""Item 4 on the server side: the new PC actions' safety rules, and the PC's own events reaching the phone."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import run
from sqlalchemy import select

from sora.agent.tools import ToolContext, registry
from sora.db import session_scope
from sora.models import Notification
from sora.services import pc_events

PC = registry.get("pc_action")
CLEAN, TAINTED = ToolContext(None), ToolContext(None, tainted=True)


def _args(**kw):
    return registry.parse_args(PC, kw)


@pytest.mark.parametrize(("args", "asks", "asks_when_tainted"), [
    ({"action": "file_delete", "target": "Downloads/old.zip"}, True, True),  # always: it deletes
    ({"action": "file_copy", "target": "a.txt", "text": "Documents"}, False, True),
    ({"action": "file_copy", "target": "a.txt", "text": "Documents", "value": 1}, True, True),  # replaces a file
    ({"action": "file_unzip", "target": "x.zip", "value": 1}, True, True),
    ({"action": "wifi", "value": 0}, True, True),  # cuts the PC off
    ({"action": "wifi", "value": 1}, False, True),
    ({"action": "type_text", "text": "hello"}, False, True),  # roadmap: asks when the chat is tainted
    ({"action": "hotkey", "target": "ctrl+s"}, False, True),
    ({"action": "window_snap", "target": "chrome", "text": "left"}, False, False),
    ({"action": "brightness", "value": 40}, False, False),
    ({"action": "dark_mode", "value": 1}, False, False),
    ({"action": "run_command", "text": "Get-Date"}, False, True),  # ordinary: runs, unless a page is in the chat
    ({"action": "run_command", "text": r"Remove-Item C:\temp -Recurse"}, True, True),
    ({"action": "run_command", "text": "Stop-Computer"}, True, True),
    ({"action": "shutdown"}, True, True),
    ({"action": "kill_process", "target": "chrome"}, True, True),
])
def test_new_pc_actions_ask_when_they_should(args, asks, asks_when_tainted):
    a = _args(**args)
    assert PC.needs_confirmation(a, CLEAN) is asks
    assert PC.needs_confirmation(a, TAINTED) is asks_when_tainted


def test_quick_ones_end_quietly_and_the_description_explains_overwrites():
    assert PC.is_quiet(_args(action="window_focus", target="chrome"))
    assert not PC.is_quiet(_args(action="window_list"))  # the owner wants to hear what is open
    description = PC.schema()["function"]["parameters"]["properties"]["action"]["description"]
    for name in ("window_snap", "type_text", "hotkey", "file_unzip", "tidy_downloads", "brightness", "dark_mode"):
        assert name in description
    assert "call again with value=1" in description


def test_a_finished_download_and_training_run_reach_the_phone():
    pc = SimpleNamespace(name="Desk", kind="pc_agent")

    async def scenario():
        await pc_events.handle(pc, {"type": "pc_event", "event": "download_done", "name": "thesis.pdf", "size": 2_400_000})
        await pc_events.handle(pc, {"type": "pc_event", "event": "training_done", "command": "train.py --fold 0",
                                    "metrics": ["epoch 300/300", "best Dice 0.912"]})
        await pc_events.handle(pc, {"type": "pc_event", "event": "something_else"})
        async with session_scope() as session:
            rows = list((await session.execute(select(Notification).order_by(Notification.created_at))).scalars())
        assert [(n.kind, n.importance) for n in rows] == [("device", "normal"), ("device", "high")]
        assert rows[0].body == "thesis.pdf (2.3 MB)" and rows[0].title.endswith(("Download finished", "ডাউনলোড শেষ"))
        assert rows[1].body == "train.py --fold 0\nepoch 300/300\nbest Dice 0.912"

    run(scenario())
