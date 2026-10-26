"""VS Code and Claude Code on the server side: what asks first, what goes to the PC agent, the step cap,
the phone's notifications, and that the server, the PC agent and the extension agree on the ops."""

from __future__ import annotations

import re
import typing
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import run
from sqlalchemy import select

import sora.agent.tools.vscode_tools as vt
from sora.agent.tools import ToolContext, registry
from sora.db import session_scope
from sora.models import Notification
from sora.services import app_language, pc_events
from sora.services.hub import hub

VS = registry.get("vscode")
CC = registry.get("claude_code")
CLEAN, TAINTED = ToolContext(None), ToolContext(None, tainted=True)
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(("args", "asks", "asks_when_tainted"), [
    ({"action": "read_file", "path": "src/a.py"}, False, False),
    ({"action": "git_status"}, False, False),
    ({"action": "terminal_read"}, False, False),
    ({"action": "problems"}, False, False),
    ({"action": "write_file", "path": "a.py", "text": "x"}, False, True),
    ({"action": "edit", "path": "a.py", "text": "x", "new_text": "y"}, False, True),
    ({"action": "open", "path": "thesis"}, False, True),
    # the owner's rule: ordinary commands just run, only serious ones ask
    ({"action": "terminal_run", "text": "python train.py"}, False, True),
    ({"action": "terminal_run", "text": "python main.py 2>&1 | Select-Object -First 50"}, False, True),
    ({"action": "terminal_run", "text": "rm -rf build"}, True, True),
    ({"action": "terminal_run", "text": "git push origin main"}, True, True),
    ({"action": "task_run", "name": "build"}, False, True),
    ({"action": "terminal_stop", "name": "Sora"}, False, False),
    ({"action": "delete", "path": "old.py"}, True, True),
    ({"action": "git_commit", "text": "fix"}, False, True),
    ({"action": "git_push"}, True, True),
    ({"action": "command", "name": "editor.action.formatDocument"}, False, True),
    ({"action": "command", "name": "workbench.action.terminal.sendSequence", "text": '[{"text": "rm -rf ~\n"}]'}, True, True),
    ({"action": "command", "name": "workbench.action.terminal.sendSequence", "text": '[{"text": "npm test\n"}]'}, False, True),
    ({"action": "command", "name": "git.discardAll"}, True, True),
    ({"action": "setting", "name": "editor.fontSize", "text": "16"}, False, True),
    ({"action": "setting", "name": "terminal.integrated.env.windows", "text": '{"PATH": "x"}'}, True, True),
    ({"action": "setting", "name": "python.defaultInterpreterPath"}, False, False),  # just reading it
    ({"action": "extension_install", "name": "ms-python.python"}, False, True),
])
def test_what_asks_first(args, asks, asks_when_tainted):
    a = registry.parse_args(VS, args)
    assert VS.needs_confirmation(a, CLEAN) is asks
    assert VS.needs_confirmation(a, TAINTED) is asks_when_tainted
    assert not VS.untrusted and not CC.untrusted  # the owner's own files and terminal: they don't taint the chat


def test_the_owner_sees_what_will_run():
    a = registry.parse_args(VS, {"action": "terminal_run", "text": "python train.py --epochs 300", "window": "thesis"})
    assert VS.describe(a) == "VS Code (thesis): run in the terminal: python train.py --epochs 300"
    c = registry.parse_args(CC, {"action": "start", "project": "thesis", "prompt": "fix the failing tests",
                                 "allow": ["Bash(python -m pytest *)"]})
    assert CC.needs_confirmation(c, CLEAN)  # it may run more than edits: the owner sees what
    plain = registry.parse_args(CC, {"action": "start", "project": "thesis", "prompt": "fix the failing tests"})
    assert not CC.needs_confirmation(plain, CLEAN) and CC.needs_confirmation(plain, TAINTED)
    assert CC.describe(c) == ("Claude Code in thesis: fix the failing tests\nIt may edit the project's files.\n"
                              "Also allowed: Bash(python -m pytest *)")
    assert not CC.needs_confirmation(registry.parse_args(CC, {"action": "status"}), TAINTED)
    assert VS.is_quiet(registry.parse_args(VS, {"action": "open", "path": "thesis"}))


def _fake_pc(monkeypatch, answer=lambda action, params: {"ok": True}) -> list:
    sent: list = []
    pc = SimpleNamespace(id=uuid.uuid4(), name="Desk", kind="pc_agent")

    async def pick(kinds, name):
        return pc

    async def command(device_id, action, params, timeout=30):
        sent.append((action, params, timeout))
        return answer(action, params)

    async def log(*args):
        pass

    monkeypatch.setattr(vt, "_pick_device", pick)
    monkeypatch.setattr(vt, "_log_command", log)
    monkeypatch.setattr(hub, "command", command)
    return sent


def test_what_goes_to_the_pc_agent(monkeypatch):
    sent = _fake_pc(monkeypatch)

    async def scenario():
        await registry.run(VS, registry.parse_args(VS, {"action": "terminal_run", "text": "npm test", "wait": 90,
                                                        "window": "site"}), ToolContext(None))
        await registry.run(VS, registry.parse_args(VS, {"action": "read_file", "path": "a.py", "line": 10}), ToolContext(None))
        await registry.run(CC, registry.parse_args(CC, {"action": "start", "project": "thesis", "prompt": "add tests",
                                                        "allow": ["WebFetch"]}), ToolContext(None))

    run(scenario())
    assert sent[0] == ("vscode", {"op": "terminal_run", "text": "npm test", "wait": 90, "window": "site"}, 130)
    assert sent[1] == ("vscode", {"op": "read_file", "path": "a.py", "line": 10}, 40)
    assert sent[2] == ("claude_code", {"op": "start", "target": "thesis", "text": "add tests", "allow": ["WebFetch"]}, 70)


def test_steps_are_capped_and_an_older_agent_says_so(monkeypatch):
    def answer(action, params):
        if params["op"] == "git_push":
            raise RuntimeError("unknown action 'vscode'")
        return {"ok": True}

    _fake_pc(monkeypatch, answer)
    ctx = ToolContext(None)

    async def scenario():
        read = registry.parse_args(VS, {"action": "git_status"})
        for _ in range(vt.MAX_STEPS - 1):
            assert (await registry.run(VS, read, ctx)).ok
        old = await registry.run(VS, registry.parse_args(VS, {"action": "git_push"}), ctx)
        assert not old.ok and "update Sora on the PC" in old.content
        stopped = await registry.run(VS, read, ctx)
        assert not stopped.ok and "ask whether to go on" in stopped.content
        assert ctx.extras["max_rounds"] == vt.MAX_STEPS + 3

    run(scenario())


def test_the_server_the_agent_and_the_extension_agree():
    ops = set(typing.get_args(vt.VsOp))
    extension = (ROOT / "vscode_ext" / "extension.js").read_text(encoding="utf-8")
    table = re.search(r"const OPS = \{(.*?)\n\};", extension, re.S).group(1)
    in_extension = set(re.findall(r"^\s+(\w+)[:,]", table, re.M))
    agent = (ROOT / "pc_agent" / "vscode_bridge.py").read_text(encoding="utf-8")
    local = set(re.findall(r'"(\w+)"', re.search(r"LOCAL_OPS = \{(.*?)\}", agent).group(1)))
    assert ops <= in_extension | local, ops - in_extension - local
    assert in_extension <= ops, in_extension - ops  # nothing the extension can do is out of reach

    claude = (ROOT / "pc_agent" / "claude_code.py").read_text(encoding="utf-8")
    for op in typing.get_args(vt.ClaudeCodeArgs.model_fields["action"].annotation):
        assert f'op == "{op}"' in claude
    actions = (ROOT / "pc_agent" / "windows_actions.py").read_text(encoding="utf-8")
    assert '"vscode_bridge": ("vscode",)' in actions and '"claude_code": ("claude_code",)' in actions


async def _notifications() -> list[Notification]:
    async with session_scope() as session:
        return list((await session.execute(select(Notification).order_by(Notification.created_at))).scalars())


def test_the_phone_hears_when_a_command_or_claude_code_ends(monkeypatch):
    pc = SimpleNamespace(name="Desk", kind="pc_agent")

    async def english():
        return "en"

    monkeypatch.setattr(app_language, "code", english)

    async def scenario():
        await pc_events.handle(pc, {"type": "pc_event", "event": "vscode_command_done", "command": "python train.py",
                                    "exit_code": 0, "seconds": 3600, "tail": "best Dice 0.91", "window": "thesis"})
        await pc_events.handle(pc, {"type": "pc_event", "event": "vscode_task_done", "task": "build", "exit_code": 2,
                                    "seconds": 20})
        await pc_events.handle(pc, {"type": "pc_event", "event": "claude_done", "ok": True, "folder": "thesis",
                                    "summary": "Fixed the lr. Tests not run.", "edited": ["src/train.py"],
                                    "denied": [{"tool": "Bash", "what": "npm test"}]})
        return await _notifications()

    done, task, claude = run(scenario())
    assert (done.title, done.importance) == ("✅ Command finished", "normal")
    assert done.body == "thesis: python train.py\nran 60 min\nbest Dice 0.91"
    assert (task.title, task.importance) == ("❌ Task failed (2)", "high")
    assert claude.title == "🤖 Claude Code finished: thesis"
    assert claude.body == "Fixed the lr. Tests not run.\nChanged: src/train.py\nCouldn't, without your yes: npm test"


def test_the_notifications_in_bangla(monkeypatch):
    pc = SimpleNamespace(name="Desk", kind="pc_agent")

    async def bangla():
        return "bn"

    monkeypatch.setattr(app_language, "code", bangla)

    async def scenario():
        await pc_events.handle(pc, {"type": "pc_event", "event": "vscode_command_done", "command": "npm test",
                                    "exit_code": 1, "seconds": 5})
        await pc_events.handle(pc, {"type": "pc_event", "event": "claude_done", "ok": False, "folder": "site",
                                    "summary": "stopped", "denied": [{"what": "git push"}]})
        return await _notifications()

    failed, claude = run(scenario())
    assert failed.title == "❌ কমান্ড ব্যর্থ (1)" and failed.body == "npm test"
    assert claude.title == "🤖 Claude Code থেমে গেছে: site" and "অনুমতি ছাড়া করতে পারেনি: git push" in claude.body
