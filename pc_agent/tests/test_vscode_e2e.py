"""The Sora Bridge extension in a real VS Code: code-server (VS Code in a browser) with headless Chromium,
connected to the PC agent's bridge. Skipped unless CODE_SERVER points at a code-server binary:

    npm install code-server@4.104.0      # VS Code 1.104; runs on Node 22
    CODE_SERVER=node_modules/.bin/code-server .venv/bin/python -m pytest -q pc_agent/tests/test_vscode_e2e.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

CODE_SERVER = os.environ.get("CODE_SERVER", "")
if not CODE_SERVER or not Path(CODE_SERVER).exists():
    pytest.skip("set CODE_SERVER to a code-server binary to run these", allow_module_level=True)
playwright = pytest.importorskip("playwright.sync_api")
CHROMIUM = os.environ.get("BROWSER_EXECUTABLE") or "/opt/pw-browsers/chromium"

import vscode_bridge as vb  # noqa: E402
from windows_actions import ActionError  # noqa: E402

SETTINGS = {
    "security.workspace.trust.enabled": False,
    "terminal.integrated.defaultProfile.linux": "bash",
    "git.openRepositoryInParentFolders": "always",
    "workbench.startupEditor": "none",
    "sora.longCommandMinutes": 0,
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def vscode(tmp_path_factory):
    root = tmp_path_factory.mktemp("vscode")
    events: list[dict] = []
    os.environ["SORA_BRIDGE_FILE"] = str(root / "bridge.json")
    vb.bridge.start(events.append)

    data, exts = root / "data", root / "ext"
    (data / "User").mkdir(parents=True)
    (data / "User" / "settings.json").write_text(json.dumps(SETTINGS))
    vsix = vb.build_vsix(root / "sora-bridge.vsix")
    subprocess.run([CODE_SERVER, "--user-data-dir", str(data), "--extensions-dir", str(exts),
                    "--install-extension", str(vsix)], check=True, capture_output=True, timeout=120)

    ws = root / "thesis"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "train.py").write_text("def train(epochs):\n    return epochs * 2\n\nprint(train(3))\n")
    (ws / "README.md").write_text("# Thesis\n")
    (ws / ".vscode").mkdir()
    (ws / ".vscode" / "tasks.json").write_text(json.dumps({"version": "2.0.0", "tasks": [
        {"label": "build", "type": "shell", "command": "echo built"},
        {"label": "broken", "type": "shell", "command": "exit 3"},
    ]}))
    _git(ws, "init", "-q", "-b", "main")
    _git(ws, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(ws, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "start")
    _git(ws, "config", "user.email", "owner@example.com")
    _git(ws, "config", "user.name", "Owner")

    port = _free_port()
    server = subprocess.Popen(
        [CODE_SERVER, "--auth", "none", "--bind-addr", f"127.0.0.1:{port}", "--user-data-dir", str(data),
         "--extensions-dir", str(exts), "--disable-telemetry", "--disable-update-check", str(ws)],
        env={**os.environ, "SORA_BRIDGE_FILE": str(root / "bridge.json")},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    pw = playwright.sync_playwright().start()
    browser = pw.chromium.launch(executable_path=CHROMIUM)
    page = browser.new_page()
    for _ in range(60):
        try:
            page.goto(f"http://127.0.0.1:{port}/?folder={ws}", timeout=5000)
            break
        except Exception:
            time.sleep(0.5)
    deadline = time.time() + 90
    while not vb.bridge.windows and time.time() < deadline:
        time.sleep(0.25)
    assert vb.bridge.windows, "the extension never connected"
    yield {"ws": ws, "events": events, "page": page}
    browser.close()
    pw.stop()
    server.terminate()
    server.wait(10)


def call(op: str, **params):
    return vb.vscode({"op": op, **params})


def test_the_window_says_what_it_has_open(vscode):
    [window] = call("windows")
    assert window["folders"] == ["thesis"] and window["paths"] == [str(vscode["ws"])]
    info = call("info")
    assert info["folders"][0]["name"] == "thesis"


def test_files_read_write_edit_rename_delete(vscode):
    ws = vscode["ws"]
    page = call("read_file", path="src/train.py")
    assert page["lines"] == 5 and "    2|     return epochs * 2" in page["text"]
    assert call("write_file", path="src/util.py", text="X = 1\n")["created"] == "src/util.py"
    assert (ws / "src" / "util.py").read_text() == "X = 1\n"
    with pytest.raises(ActionError, match="value=1"):
        call("write_file", path="src/util.py", text="X = 2\n")
    call("write_file", path="src/util.py", text="X = 2\n", value=1)
    assert (ws / "src" / "util.py").read_text() == "X = 2\n"

    assert call("edit", path="src/train.py", text="epochs * 2", new_text="epochs * 3")["places"] == 1
    assert "epochs * 3" in (ws / "src" / "train.py").read_text()
    with pytest.raises(ActionError, match="not in"):
        call("edit", path="src/train.py", text="no such text", new_text="x")

    call("rename", path="src/util.py", text="src/helpers.py")
    assert (ws / "src" / "helpers.py").exists() and not (ws / "src" / "util.py").exists()
    for outside in ("../evil.py", "/etc/passwd", str(ws.parent / "other.py")):
        with pytest.raises(ActionError, match="outside this window"):
            call("write_file", path=outside, text="x")
    with pytest.raises(ActionError, match="whole project"):
        call("delete", path=".")
    try:
        call("delete", path="src/helpers.py")
        assert not (ws / "src" / "helpers.py").exists()
    except ActionError as exc:  # code-server's folders have no bin: nothing goes for good
        assert "no Recycle Bin" in str(exc) and (ws / "src" / "helpers.py").exists()


def test_finding_files_and_text_and_the_editor(vscode):
    files = call("files", text="**/*.py")["files"]
    assert "src/train.py" in files
    hits = call("search", text="def train")["matches"]
    assert hits[0]["path"] == "src/train.py" and hits[0]["line"] == 1
    call("open_file", path="src/train.py", line=4)
    editor = call("editor")
    assert editor["active"]["path"] == "src/train.py" and editor["active"]["line"] == 4


def test_a_terminal_command_with_its_exit_code_and_output(vscode):
    done = call("terminal_run", text="python3 src/train.py && echo done-ok", wait=60)
    assert done.get("exit_code") == 0 and "done-ok" in done["output"] and "9" in done["output"], done
    failed = call("terminal_run", text="ls /no/such/folder", wait=30)
    assert failed["exit_code"] not in (0, None)
    read = call("terminal_read")
    assert read["command"] == "ls /no/such/folder" and not read["running"]
    assert any(t["name"].startswith("Sora") for t in call("terminals"))


def test_a_long_command_reports_when_it_ends(vscode):
    started = call("terminal_run", text="sleep 3; echo finished-late", wait=1)
    assert started["running"] is True
    deadline = time.time() + 30
    while not vscode["events"] and time.time() < deadline:
        time.sleep(0.25)
    [event] = [e for e in vscode["events"] if e["event"] == "vscode_command_done"]
    assert event["exit_code"] == 0 and "finished-late" in event["tail"] and event["by_sora"]
    stop = call("terminal_run", text="sleep 30", wait=1)
    assert stop["running"]
    call("terminal_stop", name=stop["terminal"])
    time.sleep(1.5)
    assert call("terminal_read", name=stop["terminal"])["running"] is False


def test_problems_list(vscode):
    result = call("problems")
    assert set(result) == {"errors", "warnings", "items"}


def test_git_status_diff_commit_and_branches(vscode):
    ws = vscode["ws"]
    deadline = time.time() + 30
    while time.time() < deadline:  # the Git extension finds the repository on its own time
        try:
            status = call("git_status")
            break
        except ActionError:
            time.sleep(0.5)
    assert status["branch"] == "main"
    (ws / "notes.md").write_text("new\n")
    time.sleep(2)
    status = call("git_status")
    assert any(c["path"] == "src/train.py" for c in status["changed"])
    assert "epochs * 3" in call("git_diff")["diff"]
    committed = call("git_commit", text="Train for longer")
    assert committed["committed"] >= 2
    assert _git(ws, "log", "-1", "--format=%s").strip() == "Train for longer"
    assert "notes.md" in _git(ws, "show", "--stat", "--format=", "HEAD")
    call("git_branch", name="try-lr", value=1)
    assert _git(ws, "branch", "--show-current").strip() == "try-lr"
    assert call("git_log")[0]["message"] == "Train for longer"


def test_settings_commands_and_extensions(vscode):
    call("setting", name="editor.fontSize", text="17")
    assert call("setting", name="editor.fontSize")["value"] == 17
    assert "workbench.action.files.saveAll" in call("commands", text="files saveall")["commands"]
    call("command", name="workbench.action.files.saveAll")
    assert any(e["id"] == "sora.sora-bridge" for e in call("extensions"))
    assert "tasks" in call("tasks")


def test_picking_the_window_by_name(vscode):
    with pytest.raises(ActionError, match="no VS Code window has"):
        call("info", window="photoshop")
    assert call("info", window="thes")["folders"][0]["name"] == "thesis"


def test_tasks_and_terminals_opened_and_closed(vscode):
    names = [t["name"] for t in call("tasks")["tasks"]]
    assert {"build", "broken"} <= set(names)
    assert call("task_run", name="build", wait=60)["exit_code"] == 0
    assert call("task_run", name="broken", wait=60)["exit_code"] == 3
    with pytest.raises(ActionError, match="no task named"):
        call("task_run", name="deploy")
    opened = call("terminal_new", name="scratch")["terminal"]
    assert any(t["name"] == opened for t in call("terminals"))
    call("terminal_close", name="scratch")
    time.sleep(0.5)
    assert not any(t["name"] == "scratch" for t in call("terminals"))
    assert "saved" in call("save")

