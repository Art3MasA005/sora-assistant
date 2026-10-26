"""The PC agent's side of VS Code and Claude Code: the bridge's protocol (with a stand-in extension),
choosing a window, VS Code's recent projects, finding a project, installing the extension, and Claude
Code runs (with a stand-in `claude`)."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
import textwrap
import threading
import time
import zipfile
from pathlib import Path

import pytest

import claude_code
import vscode_bridge as vb
from windows_actions import ActionError


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    os.environ["SORA_BRIDGE_FILE"] = str(tmp_path_factory.mktemp("bridge") / "bridge.json")
    events: list[dict] = []
    if vb.bridge.loop is None:
        vb.bridge.start(events.append)
    else:  # another test module started it
        vb.bridge.report = events.append
    return events


_open: list["FakeWindow"] = []


@pytest.fixture(autouse=True)
def _close_windows():
    yield
    while _open:
        _open.pop().close()
    _until(lambda: not vb.bridge.windows)


class FakeWindow:
    """What the extension does on the wire: hello with the token, then answers requests."""

    def __init__(self, folders: list[tuple[str, str]], focused: bool = False, token: str | None = None, ops=("info", "echo", "fail")):
        info = json.loads(Path(os.environ["SORA_BRIDGE_FILE"]).read_text())
        self.sock = socket.create_connection(("127.0.0.1", info["port"]))
        self.file = self.sock.makefile("rwb")
        self.folders = [{"name": n, "path": p} for n, p in folders]
        self.focused = focused
        self.seen: list[dict] = []
        _open.append(self)
        self.send({"type": "hello", "token": token or info["token"], "version": "1.0.0", "ops": list(ops),
                   "window": {"id": os.urandom(3).hex(), "folders": self.folders, "focused": focused}})
        threading.Thread(target=self.serve, daemon=True).start()

    def send(self, msg: dict) -> None:
        self.file.write(json.dumps(msg).encode() + b"\n")
        self.file.flush()

    def serve(self) -> None:
        try:
            for line in self.file:
                msg = json.loads(line)
                self.seen.append(msg)
                if msg["action"] == "fail":
                    self.send({"type": "response", "id": msg["id"], "ok": False, "error": "no such file"})
                elif msg["action"] != "hang":
                    self.send({"type": "response", "id": msg["id"], "ok": True,
                               "data": {"from": self.folders[0]["name"], **msg["params"]}})
        except (OSError, ValueError):
            pass  # closed by the test

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.file.close()
        self.sock.close()


def _until(check, seconds: float = 5) -> None:
    deadline = time.time() + seconds
    while not check():
        assert time.time() < deadline, "timed out"
        time.sleep(0.02)


# ---------------------------------------------------------------- the bridge


def test_only_a_window_with_the_token_gets_in(bridge):
    before = len(vb.bridge.windows)
    FakeWindow([("evil", "/tmp/evil")], token="wrong")
    time.sleep(0.3)
    assert len(vb.bridge.windows) == before


def test_requests_answers_errors_and_choosing_the_window(bridge):
    a = FakeWindow([("thesis", "/home/o/thesis")])
    b = FakeWindow([("website", "/home/o/website")], focused=True)
    _until(lambda: len(vb.bridge.windows) >= 2)
    assert vb.vscode({"op": "info", "text": "hi"})["from"] == "website"  # the focused one
    assert vb.vscode({"op": "info", "window": "thes"})["from"] == "thesis"
    assert vb.vscode({"op": "info", "window": "/home/o/thesis"})["from"] == "thesis"
    assert a.seen[-1]["params"] == {}  # window and op are the agent's, not the extension's
    with pytest.raises(ActionError, match="no VS Code window has photoshop"):
        vb.vscode({"op": "info", "window": "photoshop"})
    with pytest.raises(ActionError, match="no such file"):
        vb.vscode({"op": "fail", "window": "website"})
    with pytest.raises(ActionError, match="older and has no git_push"):
        vb.vscode({"op": "git_push", "window": "website"})

    b.send({"type": "state", "window": {"folders": b.folders, "focused": False}})
    a.send({"type": "state", "window": {"folders": a.folders, "focused": True}})
    _until(lambda: vb.bridge.pick(None).folders[0]["name"] == "thesis")
    listed = vb.vscode({"op": "windows"})
    assert {w["folders"][0] for w in listed} >= {"thesis", "website"}


def test_a_window_that_closes_mid_request_and_events_for_the_phone(bridge):
    w = FakeWindow([("slow", "/home/o/slow")], ops=("hang",))
    _until(lambda: any(x.folders[0]["name"] == "slow" for x in vb.bridge.windows.values()))
    threading.Timer(0.3, w.close).start()
    with pytest.raises(ActionError, match="closed"):
        vb.bridge.call("hang", {}, "slow", timeout=5)

    w2 = FakeWindow([("thesis", "/home/o/thesis")])
    _until(lambda: any(x.folders[0]["name"] == "thesis" for x in vb.bridge.windows.values()))
    w2.send({"type": "event", "event": "command_done", "command": "python train.py", "exit_code": 0, "seconds": 300,
             "tail": "best 0.91", "window": "thesis", "by_sora": True})
    w2.send({"type": "event", "event": "something_else"})
    _until(lambda: bridge)
    assert bridge[-1] == {"event": "vscode_command_done", "command": "python train.py", "exit_code": 0, "seconds": 300,
                          "tail": "best 0.91", "window": "thesis", "by_sora": True}
    assert len([e for e in bridge if e["event"].startswith("vscode_")]) == 1


# ---------------------------------------------------------------- projects


@pytest.fixture
def owner(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for name in ("Desktop", "Documents", "Downloads"):
        (home / name).mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("PROJECT_DIRS", raising=False)
    db = tmp_path / "state.vscdb"
    monkeypatch.setenv("VSCODE_STATE_DB", str(db))
    return home, db


def _recent(db: Path, entries: list[dict]) -> None:
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    con.execute("INSERT INTO ItemTable VALUES (?, ?)", ("history.recentlyOpenedPathsList", json.dumps({"entries": entries})))
    con.commit()
    con.close()


def test_vscodes_recent_list(owner):
    home, db = owner
    _recent(db, [
        {"folderUri": "file:///c%3A/Users/Owner/Thesis%20Code"},
        {"folderUri": (home / "Documents" / "app").as_uri()},
        {"folderUri": "vscode-remote://wsl%2Bubuntu/home/owner/ml"},
        {"workspace": {"id": "1", "configPath": "file:///d%3A/work/site.code-workspace"}},
        {"fileUri": "file:///c%3A/notes.txt"},
        {"folderUri": (home / "Documents" / "app").as_uri()},
    ])
    recent = vb.recent_projects()
    assert [r["name"] for r in recent] == ["Thesis Code", "app", "ml", "site"]
    assert recent[0]["path"].replace("\\", "/") == "c:/Users/Owner/Thesis Code"
    assert recent[2] == {"name": "ml", "path": None, "uri": "vscode-remote://wsl%2Bubuntu/home/owner/ml", "workspace": False}
    assert recent[3]["workspace"] is True


def test_finding_a_project_by_name(owner, monkeypatch):
    home, db = owner
    thesis = home / "Documents" / "thesis"
    (thesis / "src").mkdir(parents=True)
    (home / "Desktop" / "thesis-old").mkdir()
    (home / "Documents" / "website").mkdir()
    elsewhere = home.parent / "D" / "kaggle"
    elsewhere.mkdir(parents=True)
    _recent(db, [{"folderUri": elsewhere.as_uri()}])

    assert vb.resolve_project("thesis")["path"] == str(thesis)  # exact name beats a longer one
    assert vb.resolve_project("WEB")["path"] == str(home / "Documents" / "website")
    assert vb.resolve_project("kaggle")["path"] == str(elsewhere)  # VS Code opened it before
    assert vb.resolve_project(str(elsewhere))["path"] == str(elsewhere)
    with pytest.raises(ActionError, match="several projects"):
        vb.resolve_project("the")  # thesis and thesis-old
    with pytest.raises(ActionError, match="outside your own folders"):
        vb.resolve_project(str(home.parent))  # a folder VS Code never opened, outside the owner's
    with pytest.raises(ActionError, match="no project called photoshop"):
        vb.resolve_project("photoshop")
    monkeypatch.setenv("PROJECT_DIRS", str(home.parent / "D"))
    assert vb.resolve_project("kag")["path"] == str(elsewhere)


# ---------------------------------------------------------------- the `code` command and the extension


def _runnable(script: Path) -> Path:
    """A shebang script as something Windows can start too: a .cmd beside it, like VS Code's own code.cmd."""
    if os.name != "nt":
        return script
    launcher = script.with_suffix(".cmd")
    launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n')
    return launcher


@pytest.fixture
def fake_code(tmp_path, monkeypatch):
    """A `code` that logs its arguments and knows which extensions are installed."""
    log, installed = tmp_path / "code.log", tmp_path / "installed.txt"
    script = tmp_path / "code"
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import sys, pathlib
        args = sys.argv[1:]
        pathlib.Path({str(log)!r}).open("a").write(" ".join(args) + "\\n")
        if "--list-extensions" in args:
            p = pathlib.Path({str(installed)!r})
            print(p.read_text() if p.exists() else "ms-python.python@2026.1.0")
        if "--install-extension" in args:
            pathlib.Path({str(installed)!r}).write_text("sora.sora-bridge@" + {vb.extension_version()!r})
    """))
    script.chmod(0o755)
    monkeypatch.setenv("VSCODE_CLI", str(_runnable(script)))
    monkeypatch.setattr(vb, "DATA", tmp_path / "data")
    return log


def test_the_extension_is_packed_installed_once_and_kept_up_to_date(fake_code, tmp_path):
    vsix = vb.build_vsix(tmp_path / "x.vsix")
    with zipfile.ZipFile(vsix) as z:
        names = set(z.namelist())
        manifest = z.read("extension.vsixmanifest").decode()
        pkg = json.loads(z.read("extension/package.json"))
    assert {"[Content_Types].xml", "extension.vsixmanifest", "extension/package.json", "extension/extension.js"} <= names
    assert f'Id="sora-bridge" Version="{pkg["version"]}" Publisher="sora"' in manifest
    assert vb.ensure_extension() == "installed"
    assert vb.ensure_extension() == "up to date"
    calls = fake_code.read_text().splitlines()
    assert sum("--install-extension" in c for c in calls) == 1


def test_the_code_command_and_windows_cmd_characters(fake_code, monkeypatch, tmp_path):
    assert vb.vscode({"op": "new_window"}) == {"opened": "a new VS Code window"}
    assert fake_code.read_text().splitlines()[-1] == "-n"
    cmd = tmp_path / "code.cmd"
    cmd.write_text("")
    monkeypatch.setenv("VSCODE_CLI", str(cmd))
    with pytest.raises(ActionError, match="misread"):
        vb.run_code("C:\\Users\\o\\a&b")
    monkeypatch.setenv("VSCODE_CLI", str(tmp_path / "missing"))
    monkeypatch.setattr(vb, "code_cli", lambda: None)
    with pytest.raises(ActionError, match="isn't installed"):
        vb.vscode({"op": "new_window"})


def test_opening_a_project_waits_for_its_window(bridge, owner, fake_code, monkeypatch):
    home, db = owner
    project = home / "Documents" / "thesis"
    project.mkdir()
    _recent(db, [])
    monkeypatch.setattr(vb, "OPEN_WAIT", 5.0)
    threading.Timer(0.4, lambda: FakeWindow([("thesis", str(project))])).start()
    opened = vb.vscode({"op": "open", "path": "thesis"})
    assert opened["opened"] == "thesis" and opened["window"]["folders"] == ["thesis"]
    assert fake_code.read_text().splitlines()[-1] == str(project)
    again = vb.vscode({"op": "open", "path": "thesis", "value": 1})  # already open: brought to the front
    assert "window" in again and fake_code.read_text().splitlines()[-1] == str(project)


# ---------------------------------------------------------------- Claude Code


@pytest.fixture
def fake_claude(tmp_path, monkeypatch, owner):
    """A `claude` that logs its arguments and stdin, and streams what a real run would."""
    home, db = owner
    project = home / "Documents" / "thesis"
    project.mkdir()
    _recent(db, [])
    log = tmp_path / "claude.log"
    script = tmp_path / "claude"
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, signal, sys, time, pathlib
        args = sys.argv[1:]
        prompt = sys.stdin.read()
        pathlib.Path({str(log)!r}).open("a").write(json.dumps({{"args": args, "stdin": prompt}}) + "\\n")
        stopped = []
        signal.signal(signal.SIGINT, lambda *a: stopped.append(1))
        def out(m): print(json.dumps(m), flush=True)
        sid = args[args.index("--resume") + 1] if "--resume" in args else "11111111-2222-3333-4444-555555555555"
        out({{"type": "system", "subtype": "init", "session_id": sid}})
        out({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "name": "Edit",
             "input": {{"file_path": {str(project)!r} + "/src/train.py"}}}}]}}}})
        if "slow" in prompt:
            for _ in range(100):
                if stopped: break
                time.sleep(0.05)
        out({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "name": "Bash", "input": {{"command": "npm test"}}}}]}}}})
        denied = [] if "Bash(npm test *)" in " ".join(args) else [{{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {{"command": "npm test"}}}}]
        out({{"type": "result", "subtype": "success", "is_error": bool(stopped), "result": "Fixed the learning rate. Tests not run.",
             "session_id": sid, "total_cost_usd": 0.12, "num_turns": 4, "permission_denials": denied}})
    """))
    script.chmod(0o755)
    monkeypatch.setenv("CLAUDE_CODE_PATH", str(_runnable(script)))
    events: list[dict] = []
    claude_code.start(events.append)
    claude_code._runs.clear()
    return project, log, events


def _log(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_a_quick_run_answers_in_the_chat(fake_claude):
    project, log, events = fake_claude
    done = claude_code.claude_code({"op": "start", "target": "thesis", "text": "fix the lr & run tests | now"})
    assert done["running"] is False and done["ok"] is True
    assert done["summary"] == "Fixed the learning rate. Tests not run."
    assert done["edited"] == ["src/train.py"] and done["denied"] == [{"tool": "Bash", "what": "npm test"}]
    assert done["session_id"] == "11111111-2222-3333-4444-555555555555" and done["cost_usd"] == 0.12
    [run] = _log(log)
    assert run["stdin"] == "fix the lr & run tests | now"  # the prompt never goes on the command line
    assert "fix the lr" not in " ".join(run["args"])
    assert run["args"][:7] == ["-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
                               "--append-system-prompt"]
    assert events == []  # the chat already has it

    more = claude_code.claude_code({"op": "continue", "target": "thesis", "text": "run the tests now",
                                    "allow": ["Bash(npm test *)"]})
    assert more["denied"] == []
    second = _log(log)[1]["args"]
    assert second[second.index("--resume") + 1] == done["session_id"]
    assert second[second.index("--allowedTools") + 1] == "Bash(npm test *)"
    with pytest.raises(ActionError, match="not a tool rule"):
        claude_code.claude_code({"op": "start", "target": "thesis", "text": "x", "allow": ["Bash(rm -rf /) & calc"]})


def test_a_long_run_tells_the_phone_and_can_be_stopped(fake_claude):
    project, log, events = fake_claude
    started = claude_code.claude_code({"op": "start", "target": "thesis", "text": "slow job", "wait": 0.3})
    assert started["running"] is True and started["now"].startswith("Edit")
    with pytest.raises(ActionError, match="already working"):
        claude_code.claude_code({"op": "start", "target": "thesis", "text": "another"})
    assert claude_code.claude_code({"op": "status"})["running"] is True
    assert claude_code.claude_code({"op": "stop"})["stopped"] is True
    _until(lambda: events, 10)
    [event] = events
    assert event["event"] == "claude_done" and event["folder"] == "thesis" and event["ok"] is False
    assert claude_code.claude_code({"op": "status", "target": "thesis"})["running"] is False


def test_claude_code_missing_or_a_strange_project(fake_claude, monkeypatch):
    with pytest.raises(ActionError, match="no project called photoshop"):
        claude_code.claude_code({"op": "start", "target": "photoshop", "text": "x"})
    with pytest.raises(ActionError, match="no earlier Claude Code session"):
        claude_code.claude_code({"op": "continue", "target": "thesis", "text": "x"})
    monkeypatch.setenv("CLAUDE_CODE_PATH", "")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    monkeypatch.setattr(claude_code.Path, "home", lambda: Path("/nonexistent"))
    with pytest.raises(ActionError, match="isn't installed"):
        claude_code.claude_code({"op": "start", "target": "thesis", "text": "x"})
