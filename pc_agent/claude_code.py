"""Claude Code working on one of the owner's projects for Sora: `claude -p` in the project's folder.

- The owner approves each run on the phone first (the server asks). The run may edit files in the
  project (--permission-mode acceptEdits); a shell command or anything else that would need a yes is
  refused by Claude Code itself, and listed when the run ends, so Sora can ask the owner and continue
  the same session with exactly that allowed (op=continue, allow=["Bash(npm test *)"]).
- The prompt goes in on stdin, never on the command line: npm's claude.cmd passes its arguments
  through cmd.exe, which would read & | < > in them.
- A run that outlives the request ends with a "claude_done" event: a notification on the phone with
  Claude Code's own summary.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import vscode_bridge
from windows_actions import ActionError

log = logging.getLogger("sora-pc-agent")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
MAX_PROMPT = 20_000
SUMMARY = 3000
KEPT_RUNS = 10
# Tool rules the owner can allow for a run: Read, Bash(npm test *), Bash(python -m pytest *), WebFetch...
RULE = re.compile(r"^[A-Za-z][\w-]*(\([\w .,:/=*@+~\-\[\]]{1,120}\))?$")
UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
REMOTE_NOTE = ("The owner is away from this PC and reads only your final message, on their phone. End with a short "
               "summary of what you changed and what is left. Ask nothing in between: no one can answer.")

_runs: dict[str, "_Run"] = {}  # by folder: the current or the last run there
_lock = threading.Lock()
_report = lambda event: None  # noqa: E731


def start(report) -> None:
    global _report
    _report = report


def claude_exe() -> str | None:
    if os.environ.get("CLAUDE_CODE_PATH"):
        return os.environ["CLAUDE_CODE_PATH"]
    native = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(native) if native.exists() else shutil.which("claude")


class _Run:
    def __init__(self, folder: Path, prompt: str, allow: list[str], resume: str | None):
        self.folder, self.prompt, self.allow, self.resume = folder, prompt, allow, resume
        self.proc: subprocess.Popen | None = None
        self.session_id = resume
        self.started = time.time()
        self.ended = 0.0
        self.step = "starting"
        self.steps = 0
        self.edited: list[str] = []
        self.result: dict | None = None
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.waiting = True  # the request that started it is still waiting: it shows the result itself
        self.stopped = False

    def command(self) -> list[str]:
        args = [claude_exe(), "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
                "--append-system-prompt", REMOTE_NOTE]
        if self.allow:
            args += ["--allowedTools", ",".join(self.allow)]
        if self.resume:
            args += ["--resume", self.resume]
        return args

    def run(self) -> None:
        try:
            self.proc = subprocess.Popen(
                self.command(), cwd=self.folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=NO_WINDOW | NEW_GROUP,
            )
        except OSError as exc:
            self._finish({"ok": False, "summary": f"Claude Code didn't start: {exc}"})
            return
        threading.Thread(target=self._feed, daemon=True).start()
        errors: deque[bytes] = deque(maxlen=20)  # the last lines only
        drain = threading.Thread(target=lambda: errors.extend(self.proc.stderr), daemon=True)  # a full pipe would stall it
        drain.start()
        last: dict = {}
        for raw in self.proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            self._seen(msg)
            if msg.get("type") == "result":
                last = msg
        self.proc.wait()
        drain.join(5)
        err = b"".join(errors).decode("utf-8", "replace").strip()[-500:]
        if last:
            self._finish({
                "ok": not last.get("is_error") and not self.stopped,
                "summary": str(last.get("result") or "")[:SUMMARY],
                "cost_usd": last.get("total_cost_usd"),
                "turns": last.get("num_turns"),
                "denied": [_denial(d) for d in last.get("permission_denials") or []][:10],
            })
        else:
            self._finish({"ok": False, "summary": "stopped" if self.stopped else (err or f"Claude Code exited ({self.proc.returncode})")})

    def _feed(self) -> None:
        try:
            self.proc.stdin.write(self.prompt.encode("utf-8"))
            self.proc.stdin.close()
        except OSError:
            pass

    def _seen(self, msg: dict) -> None:
        if msg.get("session_id"):
            self.session_id = msg["session_id"]
        if msg.get("type") != "assistant":
            return
        for block in (msg.get("message") or {}).get("content") or []:
            if block.get("type") != "tool_use":
                continue
            name, data = block.get("name", ""), block.get("input") or {}
            self.steps += 1
            self.step = f"{name} {_short(data)}".strip()
            path = data.get("file_path") or data.get("notebook_path")
            if name in EDIT_TOOLS and path:
                shown = _relative(path, self.folder)
                if shown not in self.edited:
                    self.edited.append(shown)

    def _finish(self, outcome: dict) -> None:
        self.ended = time.time()
        with self.lock:
            self.result = {**outcome, "folder": self.folder.name, "path": str(self.folder), "session_id": self.session_id,
                           "edited": self.edited[:30], "seconds": round(self.ended - self.started)}
            tell = not self.waiting
        self.done.set()
        if tell:
            _report({"event": "claude_done", **self.result})

    def status(self) -> dict:
        if self.result is not None:
            return {"running": False, **self.result}
        return {"running": True, "folder": self.folder.name, "path": str(self.folder), "now": self.step,
                "steps": self.steps, "edited": self.edited[:30], "seconds": round(time.time() - self.started),
                "session_id": self.session_id}

    def stop(self) -> None:
        self.stopped = True
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            # Like Ctrl+C: Claude Code ends the turn it is in.
            proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            proc.wait(10)
        except (OSError, subprocess.TimeoutExpired):
            if os.name == "nt":  # the whole tree: a test run it started goes too
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
            else:
                proc.kill()


def _short(data: dict) -> str:
    for key in ("command", "file_path", "pattern", "url", "description", "path"):
        if data.get(key):
            return str(data[key]).splitlines()[0][:120]
    return ""


def _relative(path: str, folder: Path) -> str:
    try:
        return Path(path).resolve().relative_to(folder.resolve()).as_posix()  # one spelling, whichever slashes it came with
    except ValueError:
        return path


def _denial(d: dict) -> dict:
    data = d.get("tool_input") or {}
    return {"tool": d.get("tool_name"), "what": _short(data) or json.dumps(data, ensure_ascii=False)[:150]}


def _folder(params: dict) -> Path:
    project = vscode_bridge.resolve_project(params.get("target"))
    if not project.get("path"):
        raise ActionError("Claude Code runs on this PC's own folders, not WSL or SSH ones")
    return Path(project["path"])


def _start(params: dict, resume: str | None) -> dict:
    if not claude_exe():
        raise ActionError("Claude Code isn't installed on this PC (or `claude` isn't on PATH)")
    folder = _folder(params)
    prompt = str(params.get("text") or "").strip()
    if not prompt:
        raise ActionError("what should Claude Code do? (text=)")
    if len(prompt) > MAX_PROMPT:
        raise ActionError("that request is too long")
    allow = [str(a).strip() for a in params.get("allow") or [] if str(a).strip()]
    bad = [a for a in allow if not RULE.match(a)]
    if bad:
        raise ActionError(f"not a tool rule Claude Code knows: {bad[0]} (like Bash(npm test *) or WebFetch)")
    with _lock:
        current = _runs.get(str(folder))
        if current is not None and current.result is None:
            raise ActionError(f"Claude Code is already working in {folder.name} ({current.step}): wait, or stop it")
        run = _Run(folder, prompt, allow, resume)
        _runs.pop(str(folder), None)
        _runs[str(folder)] = run  # newest last
        finished = [k for k, r in _runs.items() if r.result is not None]
        while len(_runs) > KEPT_RUNS and finished:
            _runs.pop(finished.pop(0))
    threading.Thread(target=run.run, name="claude-code", daemon=True).start()
    run.done.wait(max(0.0, min(float(params.get("wait") or 40), 100)))
    with run.lock:
        run.waiting = False  # from now on the end goes to the phone
        if run.result is not None:
            return {"running": False, **run.result}
    return {**run.status(), "note": "still working: the owner gets a notification with its summary when it ends"}


def _find(params: dict) -> "_Run":
    if params.get("target"):
        run = _runs.get(str(_folder(params)))
    else:
        live = [r for r in _runs.values() if r.result is None]
        run = live[-1] if live else (list(_runs.values())[-1] if _runs else None)
    if run is None:
        raise ActionError("Claude Code hasn't run in that project since the PC agent started")
    return run


def claude_code(params: dict) -> dict:
    """op: start (target=project, text=what to do, allow=extra tool rules) | continue (the same session
    in that project, with text and allow) | status | stop | open_in_vscode (the session in a VS Code
    terminal, to carry on at the PC)."""
    op = str(params.get("op") or "start")
    if op == "start":
        return _start(params, None)
    if op == "continue":
        last = _runs.get(str(_folder(params)))
        if last is None or not last.session_id:
            raise ActionError("no earlier Claude Code session in that project to continue: start one")
        if last.result is None:
            raise ActionError("it is still working: wait for it to end, or stop it")
        return _start(params, last.session_id)
    if op == "status":
        return _find(params).status()
    if op == "stop":
        run = _find(params)
        if run.result is not None:
            return {"stopped": False, "note": "it had already finished"}
        run.stop()
        return {"stopped": True, "folder": run.folder.name}
    if op == "open_in_vscode":
        run = _find(params)
        if not run.session_id or not UUID.match(run.session_id):
            raise ActionError("that run has no session to open")
        return vscode_bridge.bridge.call("terminal_run", {"text": f"claude --resume {run.session_id}", "name": "Claude Code",
                                                          "wait": 0}, run.folder.name, timeout=20)
    raise ActionError(f"unknown Claude Code op {op}")
