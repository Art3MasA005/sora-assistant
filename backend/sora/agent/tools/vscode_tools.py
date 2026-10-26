"""VS Code and Claude Code on the owner's PC (pc_agent/vscode_bridge.py, vscode_ext/, pc_agent/claude_code.py)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from sora.agent.tools.base import ToolContext, registry
from sora.agent.tools.device_tools import _log_command, _pick_device
from sora.agent.tools.risk import risky_command
from sora.services.hub import CommandTimeout, DeviceOffline, hub

MAX_STEPS = 25  # VS Code steps per request
VsOp = Literal[
    "windows", "recent", "open", "new_window", "info", "editor",
    "open_file", "read_file", "write_file", "edit", "rename", "delete", "files", "search", "save", "problems",
    "terminals", "terminal_run", "terminal_read", "terminal_stop", "terminal_new", "terminal_close",
    "git_status", "git_diff", "git_log", "git_commit", "git_push", "git_pull", "git_branch",
    "tasks", "task_run", "debug_start", "debug_stop",
    "commands", "command", "setting", "extensions", "extension_install",
]
# The owner's rule: ordinary work (run the script, commit, change a setting) just happens; only what
# deletes or reaches outside the PC asks, and a terminal command only when it is risky (risk.py).
VS_ALWAYS_ASK = {"delete", "git_push"}
# Change files or what runs: asked once third-party text (an email, a web page) is in the chat, so
# instructions hidden there can't run or change anything.
VS_TAINT_GUARDED = {"open", "new_window", "write_file", "edit", "rename", "git_pull", "git_branch", "git_commit",
                    "terminal_new", "terminal_run", "task_run", "debug_start", "command", "setting", "extension_install"}
# VS Code commands that lose work or reach outside, by their id.
RISKY_COMMAND_ID = re.compile(r"delete|remove|uninstall|push|reset|discard|clean|revert", re.IGNORECASE)
# Settings that change what runs (the terminal's shell and environment, interpreters, trust).
RISKY_SETTING = re.compile(r"\benv\b|shell|executable|automationProfile|security|trust", re.IGNORECASE)
VS_QUIET = {"open", "new_window", "open_file", "save", "terminal_new", "debug_stop"}
# Commands and settings that change only how VS Code looks: no need to ask.
SAFE_COMMANDS = {
    "workbench.action.files.save", "workbench.action.files.saveAll", "editor.action.formatDocument",
    "editor.action.organizeImports", "workbench.action.closeActiveEditor", "workbench.action.closeAllEditors",
    "workbench.action.toggleSidebarVisibility", "workbench.action.togglePanel", "workbench.action.toggleZenMode",
    "workbench.action.toggleFullScreen", "workbench.action.toggleMaximizedPanel", "workbench.action.terminal.toggleTerminal",
    "workbench.action.splitEditor", "workbench.action.reloadWindow", "workbench.actions.view.problems",
    "workbench.view.explorer", "workbench.view.scm", "workbench.view.search", "workbench.view.extensions",
    "workbench.action.zoomIn", "workbench.action.zoomOut", "workbench.action.zoomReset", "editor.foldAll",
    "editor.unfoldAll", "workbench.action.togglePanelPosition",
}
SAFE_SETTINGS = {
    "workbench.colorTheme", "workbench.iconTheme", "editor.fontSize", "editor.fontFamily", "editor.wordWrap",
    "editor.tabSize", "editor.lineNumbers", "editor.minimap.enabled", "editor.formatOnSave", "files.autoSave",
    "window.zoomLevel", "terminal.integrated.fontSize", "breadcrumbs.enabled", "workbench.sideBar.location",
}
SLOW = {"open": 50, "search": 70, "git_push": 130, "git_pull": 130, "git_commit": 70, "extension_install": 130}


class VsCodeArgs(BaseModel):
    action: VsOp = Field(
        description=(
            "windows (open VS Code windows) | recent (recently opened projects) | open (path=project name or folder; "
            "value=1 new window) | new_window | info / editor (open file, selection, unsaved files) | "
            "open_file (path, line) | read_file (path, line, end_line; a folder lists it) | write_file (path, text: "
            "a new file; value=1 replaces an existing one) | edit (path, text=exact old text, new_text; value=1 every "
            "place) | rename (path, text=new path) | delete (to the bin) | files (text=glob, e.g. **/*.py) | "
            "search (text; path=glob; value=1 regex) | save (all) | problems (errors and warnings; path=one file) | "
            "terminals | terminal_run (text=command; name=terminal; wait=seconds, default 30, max 120) | "
            "terminal_read (name) | terminal_stop (Ctrl+C) | terminal_new | terminal_close | git_status | git_diff "
            "(path; value=1 staged) | git_log | git_commit (text=message; commits everything changed if nothing is "
            "staged) | git_push | git_pull | git_branch (name; value=1 create; no name lists) | tasks (tasks and debug "
            "configs) | task_run (name, wait) | debug_start (name) | debug_stop | commands (text=words to find a "
            "command id) | command (name=command id, text=JSON args) | setting (name=key, text=JSON value; no text "
            "reads it) | extensions | extension_install (name=id)"
        )
    )
    path: str | None = Field(None, description="A file or folder, relative to the project (or absolute); open: the project")
    text: str | None = Field(None, description="The command, content, text to find, message or value (see action)")
    new_text: str | None = Field(None, description="edit: the text to put in its place")
    name: str | None = Field(None, description="A terminal, task, debug config, branch, command id, setting or extension")
    line: int | None = Field(None, description="open_file / read_file: the first line")
    end_line: int | None = Field(None, description="read_file: the last line (default: 400 lines)")
    value: int | None = Field(None, description="1 for the action's stronger form (see action)")
    wait: int | None = Field(None, description="terminal_run / task_run: seconds to wait for the end (default 30)")
    window: str | None = Field(None, description="Which VS Code window, by part of its folder name, if several are open")
    device_name: str | None = Field(None, description="Which PC, if the owner has more than one.")


def _vs_asks(a: VsCodeArgs) -> bool:
    if a.action in VS_ALWAYS_ASK:
        return True
    if a.action == "terminal_run":
        return risky_command(a.text)
    if a.action == "command":  # e.g. sendSequence types its text into the terminal
        return a.name not in SAFE_COMMANDS and (bool(RISKY_COMMAND_ID.search(a.name or "")) or risky_command(a.text))
    if a.action == "setting":
        return bool(a.text) and a.name not in SAFE_SETTINGS and bool(RISKY_SETTING.search(a.name or ""))
    return False


def _vs_taint(a: VsCodeArgs) -> bool:
    return a.action in VS_TAINT_GUARDED and not (a.action == "setting" and not a.text)  # reading a setting is fine


def _vs_summary(a: VsCodeArgs) -> str:
    where = f" ({a.window})" if a.window else ""
    if a.action == "terminal_run":
        return f"VS Code{where}: run in the terminal{f' {a.name}' if a.name else ''}: {a.text}"
    if a.action == "task_run":
        return f"VS Code{where}: run the task {a.name}"
    if a.action == "git_commit":
        return f"VS Code{where}: git commit “{a.text}”"
    if a.action == "git_push":
        return f"VS Code{where}: git push"
    if a.action in {"delete", "rename"}:
        return f"VS Code{where}: {a.action} {a.path}" + (f" → {a.text}" if a.action == "rename" else "")
    if a.action in {"write_file", "edit"}:
        return f"VS Code{where}: {'write' if a.action == 'write_file' else 'change'} {a.path}"
    if a.action in {"command", "setting", "extension_install", "debug_start", "terminal_stop", "terminal_close"}:
        return f"VS Code{where}: {a.action.replace('_', ' ')} {a.name or ''} {a.text or ''}".rstrip()
    return f"VS Code{where}: {a.action.replace('_', ' ')} {a.path or a.name or ''}".rstrip()


async def _send(ctx: ToolContext, kind: str, steps_key: str, cap: int, a, action: str, params: dict, timeout: float,
                old_agent: str):
    steps = ctx.extras.get(steps_key, 0) + 1
    ctx.extras[steps_key] = steps
    ctx.extras["max_rounds"] = max(ctx.extras.get("max_rounds", 0), cap + 3)
    if steps > cap:
        return f"Not done: that is {cap} {kind} steps for this request. Tell the owner where you got to and ask whether to go on."
    device = await _pick_device(("pc_agent",), a.device_name)
    if device is None:
        return "Error: no PC agent is set up. Run the Sora PC agent on the computer first."
    try:
        result = await hub.command(device.id, action, params, timeout=timeout)
    except DeviceOffline:
        return f"Error: the PC '{device.name}' is offline (the PC agent is not running or the PC is off)."
    except CommandTimeout as exc:
        await _log_command(device.id, action, {"op": params.get("op")}, "timeout", None)
        return f"Error: {exc}"
    except RuntimeError as exc:
        await _log_command(device.id, action, {"op": params.get("op")}, "error", str(exc)[:300])
        if f"unknown action '{action}'" in str(exc):
            return f"Error: {old_agent}"
        return f"Error from {kind}: {exc}"
    await _log_command(device.id, action, {"op": params.get("op")}, "ok", None)  # file contents aren't kept in the log
    return result


@registry.tool(
    # The owner's own project files and terminal: not third-party text (an email or a web page is).
    VsCodeArgs, needs="pc", summary=_vs_summary, confirm=_vs_asks,
    taint_guard=_vs_taint, quiet=lambda a: a.action in VS_QUIET,
)
async def vscode(ctx: ToolContext, a: VsCodeArgs):
    """VS Code on the owner's PC: open projects, read, write and edit files, search, see problems, run commands
    in its terminal (exit code and output), git, tasks and debugging. Paths are relative to the project. Read a
    file before editing it. For real coding work hand it to claude_code instead of writing the code yourself."""
    params = {"op": a.action, **a.model_dump(exclude={"action", "device_name"}, exclude_none=True)}
    timeout = SLOW.get(a.action, 40) + (min(a.wait if a.wait is not None else 30, 120) if a.action in {"terminal_run", "task_run"} else 0)
    return await _send(ctx, "VS Code", "vscode_steps", MAX_STEPS, a, "vscode", params, timeout,
                       "this PC agent is older and can't use VS Code yet; update Sora on the PC.")


class ClaudeCodeArgs(BaseModel):
    action: Literal["start", "continue", "status", "stop", "open_in_vscode"] = Field(
        description="start (a new job) | continue (the last session in that project: answer it, or retry with more "
                    "allowed) | status (what it is doing, or its last result) | stop | open_in_vscode (the session "
                    "in a VS Code terminal, so the owner carries on at the PC)"
    )
    project: str | None = Field(None, description="The project's name or folder, e.g. 'thesis'")
    prompt: str | None = Field(None, description="start / continue: the job, in the owner's words, complete enough to do alone")
    allow: list[str] | None = Field(
        None, description="What it may also do without asking, as Claude Code rules, e.g. 'Bash(npm test *)', "
                          "'Bash(python -m pytest *)', 'WebFetch'. Only what the owner agreed to; it may always edit "
                          "the project's files.",
    )
    wait: int | None = Field(None, description="start / continue: seconds to wait for the end (default 40, max 100)")
    device_name: str | None = Field(None, description="Which PC, if the owner has more than one.")


def _claude_summary(a: ClaudeCodeArgs) -> str:
    if a.action in {"start", "continue"}:
        also = f"\nAlso allowed: {', '.join(a.allow)}" if a.allow else ""
        verb = "Claude Code" if a.action == "start" else "Claude Code, continuing"
        return f"{verb} in {a.project}: {a.prompt}\nIt may edit the project's files.{also}"
    return f"Claude Code: {a.action.replace('_', ' ')} {a.project or ''}".rstrip()


@registry.tool(
    # A job that only edits the project's files just runs; letting it do more (run commands, read the web)
    # asks, so the owner sees exactly what is allowed. Started while an email or a page is in the chat, it asks.
    ClaudeCodeArgs, needs="pc", summary=_claude_summary,
    confirm=lambda a: a.action in {"start", "continue"} and bool(a.allow),
    taint_guard=lambda a: a.action in {"start", "continue"},
)
async def claude_code(ctx: ToolContext, a: ClaudeCodeArgs):
    """Hand a coding job in one of the owner's projects to Claude Code on their PC. It may edit the project's
    files; anything else it needs (running commands) is refused and listed in 'denied' at the end: then ask the
    owner and continue with exactly that in allow. A long job ends with a notification on the phone."""
    params = {"op": a.action, "target": a.project, "text": a.prompt, "allow": a.allow, "wait": a.wait}
    params = {k: v for k, v in params.items() if v is not None}
    timeout = (min(a.wait or 40, 100) + 30) if a.action in {"start", "continue"} else 40
    return await _send(ctx, "Claude Code", "claude_steps", 10, a, "claude_code", params, timeout,
                       "this PC agent is older and has no Claude Code yet; update Sora on the PC.")
