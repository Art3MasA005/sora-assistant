"""VS Code on this PC for Sora, through the Sora Bridge extension (vscode_ext/).

- The agent listens on 127.0.0.1 (a free port) and writes the port and a fresh token to
  vscode-bridge.json (%LOCALAPPDATA%\\Sora). Each VS Code window's extension connects with the token,
  says which folders it has open, and answers requests. Newline-separated JSON; nothing polls.
- The "vscode" action: open a project, a new window and the recent projects are done here with the
  `code` command; everything else goes to a window's extension (see extension.js for each op).
- The extension is installed (or updated) by the agent itself, from vscode_ext/ packed as a .vsix.
- VSCODE_BRIDGE=0 in .env switches all of this off.
"""

from __future__ import annotations

import asyncio
import atexit
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import file_actions
from windows_actions import ActionError

log = logging.getLogger("sora-pc-agent")
EXT_DIR = Path(__file__).resolve().parents[1] / "vscode_ext"
DATA = Path(__file__).resolve().parents[1] / "data"
EXT_ID = "sora.sora-bridge"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_LINE = 16 * 1024 * 1024
OPEN_WAIT = 30.0  # seconds for a window that was just opened to connect
# Ops the agent does itself; the rest are the extension's.
LOCAL_OPS = {"windows", "recent", "open", "new_window"}
# How long an op may take in VS Code (seconds), on top of what it waits for itself.
SLOW_OPS = {"search": 60, "git_push": 120, "git_pull": 120, "git_commit": 60, "extension_install": 120, "files": 30}
# cmd.exe reads these in code.cmd's arguments: refused rather than quoted.
CMD_UNSAFE = re.compile(r'[&|<>^%!"\r\n]')


def bridge_file() -> Path:
    if os.environ.get("SORA_BRIDGE_FILE"):
        return Path(os.environ["SORA_BRIDGE_FILE"])
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Sora" / "vscode-bridge.json"
    return Path.home() / ".sora" / "vscode-bridge.json"


class _Window:
    def __init__(self, writer: asyncio.StreamWriter, info: dict, version: str, ops: list[str]):
        self.writer = writer
        self.version = version
        self.ops = set(ops)
        self.pending: dict[int, asyncio.Future] = {}
        self.focused_at = 0.0
        self.update(info)

    def update(self, info: dict) -> None:
        self.id = str(info.get("id") or "")
        self.name = str(info.get("name") or "")
        self.folders = [f for f in info.get("folders") or [] if isinstance(f, dict)]
        self.remote = info.get("remote")
        self.focused = bool(info.get("focused"))
        if self.focused:
            self.focused_at = time.monotonic()

    def describe(self) -> dict:
        return {"folders": [f.get("name") for f in self.folders] or ["(no folder)"],
                "paths": [f.get("path") for f in self.folders], "focused": self.focused,
                **({"remote": self.remote} if self.remote else {})}


class Bridge:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.windows: dict[asyncio.StreamWriter, _Window] = {}
        self.report = lambda event: None
        self.token = secrets.token_urlsafe(24)
        self.port = 0
        self._next = 0
        self._changed: asyncio.Event | None = None
        self._ready = threading.Event()

    # ------------------------------------------------------------ the server, on its own thread

    def start(self, report) -> None:
        self.report = report
        threading.Thread(target=self._serve, name="vscode-bridge", daemon=True).start()
        self._ready.wait(10)

    def _serve(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._changed = asyncio.Event()
        server = self.loop.run_until_complete(asyncio.start_server(self._client, "127.0.0.1", 0, limit=MAX_LINE))
        self.port = server.sockets[0].getsockname()[1]
        self._write_file()
        self._ready.set()
        self.loop.run_forever()

    def _write_file(self) -> None:
        path = bridge_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"port": self.port, "token": self.token, "pid": os.getpid()}), encoding="utf-8")
        os.replace(tmp, path)  # the extensions watch this file: they connect again when it changes
        atexit.register(self._remove_file, path)

    def _remove_file(self, path: Path) -> None:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                path.unlink()
        except (OSError, ValueError):
            pass

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        window = None
        try:
            hello = json.loads(await asyncio.wait_for(reader.readline(), 10))
            if hello.get("type") != "hello" or not hmac.compare_digest(str(hello.get("token", "")), self.token):
                return
            window = _Window(writer, hello.get("window") or {}, str(hello.get("version") or ""), hello.get("ops") or [])
            self.windows[writer] = window
            self._changed.set()
            log.info("VS Code window connected: %s", ", ".join(window.describe()["folders"]))
            while line := await reader.readline():
                self._received(window, json.loads(line))
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.LimitOverrunError):
            pass
        finally:
            if window is not None:
                self.windows.pop(writer, None)
                for future in window.pending.values():
                    if not future.done():
                        future.set_exception(ActionError("the VS Code window closed"))
            writer.close()

    def _received(self, window: _Window, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "response":
            future = window.pending.pop(msg.get("id"), None)
            if future is not None and not future.done():
                if msg.get("ok"):
                    future.set_result(msg.get("data"))
                else:
                    future.set_exception(ActionError(str(msg.get("error") or "VS Code said no")))
        elif kind == "state":
            window.update(msg.get("window") or {})
            self._changed.set()
        elif kind == "event" and msg.get("event") in {"command_done", "task_done"}:
            fields = {k: v for k, v in msg.items() if k not in {"type", "event"}}
            self.report({"event": f"vscode_{msg['event']}", **fields})

    async def _call(self, window: _Window, op: str, params: dict, timeout: float):
        self._next += 1
        request_id = self._next  # its own: another call may take the next id while this one waits
        future = self.loop.create_future()
        window.pending[request_id] = future
        line = json.dumps({"type": "request", "id": request_id, "action": op, "params": params}, ensure_ascii=False)
        window.writer.write(line.encode() + b"\n")
        await window.writer.drain()
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise ActionError(f"VS Code didn't answer {op} in time") from None
        finally:
            window.pending.pop(request_id, None)

    async def _wait_for(self, folder: Path, timeout: float) -> _Window | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = next((w for w in self.windows.values() if _has_folder(w, folder)), None)
            if found:
                return found
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), deadline - time.monotonic())
            except asyncio.TimeoutError:
                break
        return None

    # ------------------------------------------------------------ called from the agent's threads

    def call(self, op: str, params: dict, window: str | None = None, timeout: float = 30) -> object:
        if self.loop is None:
            raise ActionError("the VS Code bridge is off on this PC (VSCODE_BRIDGE=0)")
        w = self.pick(window)
        if w.ops and op not in w.ops:
            raise ActionError(f"this window's Sora Bridge is older and has no {op}; reload VS Code to update it")
        future = asyncio.run_coroutine_threadsafe(self._call(w, op, params, timeout), self.loop)
        return future.result(timeout + 5)

    def wait_for(self, folder: Path, timeout: float = OPEN_WAIT) -> _Window | None:
        if self.loop is None:
            return None
        return asyncio.run_coroutine_threadsafe(self._wait_for(folder, timeout), self.loop).result(timeout + 5)

    def connected(self) -> list[_Window]:
        return list(self.windows.copy().values())  # the server's thread changes the dict: copy it in one step

    def pick(self, wanted: str | None) -> _Window:
        """The window with [wanted] in a folder's name or path; else the focused one, else the last focused."""
        windows = self.connected()
        if not windows:
            raise ActionError("no VS Code window is connected: VS Code isn't open, or the Sora Bridge extension isn't "
                              "running in it yet (open a project with action=open)")
        if wanted:
            w = wanted.casefold().strip()
            exact = [x for x in windows if any(str(f.get("name", "")).casefold() == w for f in x.folders)]
            near = exact or [x for x in windows if any(w in str(f.get(k, "")).casefold() for f in x.folders
                                                        for k in ("name", "path"))]
            if not near:
                names = "; ".join(", ".join(x.describe()["folders"]) for x in windows)
                raise ActionError(f"no VS Code window has {wanted} open (open: {names})")
            windows = near
        return max(windows, key=lambda x: (x.focused, x.focused_at))


def _has_folder(window: _Window, folder: Path) -> bool:
    want = os.path.normcase(str(folder)).rstrip("\\/")
    return any(os.path.normcase(str(f.get("path", ""))).rstrip("\\/") == want for f in window.folders)


bridge = Bridge()


def start(report) -> None:
    """At agent start: the local server, then (in the background) the extension installed or updated."""
    if os.environ.get("VSCODE_BRIDGE", "1") == "0":
        return
    try:
        bridge.start(report)
    except OSError:
        log.exception("could not start the VS Code bridge")
        return
    threading.Thread(target=ensure_extension, name="vscode-extension", daemon=True).start()


# ---------------------------------------------------------------- the `code` command


def code_cli() -> list[str] | None:
    """How to run VS Code's `code` command here, or None when VS Code isn't installed."""
    if os.environ.get("VSCODE_CLI"):
        return [os.environ["VSCODE_CLI"]]
    found = shutil.which("code")
    if not found and os.name == "nt":  # installed for this user, or for everyone, but not on PATH
        places = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs", Path(os.environ.get("ProgramFiles", ""))]
        found = next((str(p / "Microsoft VS Code" / "bin" / "code.cmd") for p in places
                      if (p / "Microsoft VS Code" / "bin" / "code.cmd").exists()), None)
    return [found] if found else None


def run_code(*args: str, timeout: float = 60) -> str:
    cli = code_cli()
    if cli is None:
        raise ActionError("VS Code isn't installed on this PC (or its `code` command isn't on PATH)")
    if cli[0].lower().endswith((".cmd", ".bat")) and any(CMD_UNSAFE.search(a) for a in args):
        raise ActionError("that path has a character Windows' command line would misread (& | < > ^ % ! \"); rename it")
    done = subprocess.run([*cli, *args], capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise ActionError(f"VS Code said: {(done.stderr or done.stdout).strip()[:300] or done.returncode}")
    return done.stdout


# ---------------------------------------------------------------- projects


def _state_dbs() -> list[Path]:
    if os.environ.get("VSCODE_STATE_DB"):
        return [Path(os.environ["VSCODE_STATE_DB"])]
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return [base / name / "User" / "globalStorage" / "state.vscdb" for name in ("Code", "Code - Insiders")]


def _uri_path(uri: str) -> str | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if re.match(r"^/[a-zA-Z]:", path):  # file:///c%3A/Users/... on Windows
        path = path[1:]
    if parsed.netloc:  # \\server\share
        path = f"//{parsed.netloc}{path}"
    return str(Path(path))


def recent_projects(limit: int = 30) -> list[dict]:
    """The folders VS Code opened lately, newest first (its own "Open Recent" list)."""
    out: list[dict] = []
    for db in _state_dbs():
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
            try:
                row = con.execute("SELECT value FROM ItemTable WHERE key = 'history.recentlyOpenedPathsList'").fetchone()
            finally:
                con.close()
        except sqlite3.Error as exc:
            log.info("can't read VS Code's recent list: %s", exc)
            continue
        if not row:
            continue
        for entry in json.loads(row[0]).get("entries", []):
            uri = entry.get("folderUri") or (entry.get("workspace") or {}).get("configPath")
            if not uri:
                continue
            path = _uri_path(uri)
            name = Path(path).name if path else unquote(uri.rstrip("/").rsplit("/", 1)[-1])
            if name.endswith(".code-workspace"):
                name = name[: -len(".code-workspace")]
            out.append({"name": name, "path": path, "uri": None if path else uri,
                        "workspace": "workspace" in entry})
    seen: set[str] = set()
    unique = []
    for item in out:
        key = (item["path"] or item["uri"] or "").casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:limit]


def _project_dirs() -> list[Path]:
    """Folders one level inside PROJECT_DIRS, Desktop and Documents: where projects usually are."""
    out: list[Path] = []
    roots = [Path(os.path.expandvars(p.strip())) for p in os.environ.get("PROJECT_DIRS", "").split(";") if p.strip()]
    roots += [file_actions.home() / "Desktop", file_actions.home() / "Documents"]
    for root in roots:
        out.append(root)
        try:
            out += [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        except OSError:
            continue
    return out


def resolve_project(raw: str | None) -> dict:
    """A project the owner named ("thesis", or a path) as {name, path} (or {name, uri} for a remote one).
    Only folders VS Code opened before, open windows' folders, or folders inside the owner's own ones."""
    text = (raw or "").strip().strip('"')
    if not text:
        raise ActionError("which project? give its name or folder")
    recent = recent_projects(60)
    open_folders = [{"name": f.get("name"), "path": f.get("path")} for w in bridge.connected() for f in w.folders]
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if path.is_absolute():
        if not path.is_dir():
            raise ActionError(f"{path} is not a folder")
        known = {os.path.normcase(str(p["path"])) for p in recent + open_folders if p.get("path")}
        if os.path.normcase(str(path)) not in known:
            file_actions.resolve(str(path))  # refuses anything outside the owner's folders
        return {"name": path.name, "path": str(path)}
    want = text.casefold()
    candidates = open_folders + recent + [{"name": p.name, "path": str(p)} for p in _project_dirs()]
    for test in (lambda n: n == want, lambda n: n.startswith(want), lambda n: want in n):
        found = [c for c in candidates if c.get("name") and test(str(c["name"]).casefold())]
        unique = {(c.get("path") or c.get("uri") or "").casefold(): c for c in found}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            listed = ", ".join(str(c.get("path") or c.get("uri")) for c in list(unique.values())[:6])
            raise ActionError(f"several projects match {text}: {listed}. Say which (give the path)")
    raise ActionError(f"no project called {text} (recent: {', '.join(p['name'] for p in recent[:10]) or 'none'})")


# ---------------------------------------------------------------- the action


def vscode(params: dict) -> object:
    """params: op (see LOCAL_OPS and extension.js), window (part of a window's folder name), and the
    op's own fields (path, text, new_text, name, line, end_line, value, wait)."""
    op = str(params.get("op") or "").strip()
    if not op:
        raise ActionError("which VS Code op?")
    if op == "windows":
        return [w.describe() for w in bridge.connected()] or {"note": "no VS Code window is connected"}
    if op == "recent":
        return recent_projects()
    if op == "new_window":
        run_code("-n")
        return {"opened": "a new VS Code window"}
    if op == "open":
        return open_project(params)
    fields = {k: v for k, v in params.items() if k not in {"op", "window"} and v is not None}
    timeout = SLOW_OPS.get(op, 30) + min(float(params.get("wait") or 30), 120) * (op in {"terminal_run", "task_run"})
    return bridge.call(op, fields, params.get("window"), timeout=timeout)


def open_project(params: dict) -> dict:
    project = resolve_project(params.get("path") or params.get("text"))
    new = int(params.get("value") or 0) == 1
    if project.get("uri"):  # a WSL or SSH folder: VS Code opens it by its address
        run_code(*(["-n"] if new else []), "--folder-uri", project["uri"])
        return {"opened": project["name"], "remote": True}
    folder = Path(project["path"])
    window = next((w for w in bridge.connected() if _has_folder(w, folder)), None)
    run_code(*(["-n"] if new and window is None else []), str(folder))  # an open one comes to the front
    window = window or bridge.wait_for(folder)
    if window is None:
        return {"opened": project["name"], "path": str(folder),
                "note": "VS Code opened it, but the Sora Bridge extension hasn't connected (yet): only open and "
                        "recent work until it does"}
    return {"opened": project["name"], "path": str(folder), "window": window.describe()}


# ---------------------------------------------------------------- the extension itself


def extension_version() -> str:
    return json.loads((EXT_DIR / "package.json").read_text(encoding="utf-8"))["version"]


def build_vsix(out: Path) -> Path:
    """vscode_ext/ packed the way `vsce package` does: a zip with the manifest VS Code reads on install."""
    pkg = json.loads((EXT_DIR / "package.json").read_text(encoding="utf-8"))
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{pkg['name']}" Version="{pkg['version']}" Publisher="{pkg['publisher']}" />
    <DisplayName>{pkg['displayName']}</DisplayName>
    <Description xml:space="preserve">{pkg['description']}</Description>
    <Categories>Other</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg['engines']['vscode']}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="{','.join(pkg.get('extensionKind', ['workspace']))}" />
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="" />
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
"""
    types = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension=".json" ContentType="application/json" />
  <Default Extension=".js" ContentType="application/javascript" />
  <Default Extension=".md" ContentType="text/markdown" />
  <Default Extension=".vsixmanifest" ContentType="text/xml" />
</Types>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("extension.vsixmanifest", manifest)
        for name in ("package.json", "extension.js", "README.md"):
            if (EXT_DIR / name).exists():
                z.write(EXT_DIR / name, f"extension/{name}")
    return out


def ensure_extension() -> str:
    """Installs Sora Bridge into VS Code when it's missing or older. Once per agent start, in the background."""
    if code_cli() is None:
        return "no VS Code"
    version = extension_version()
    try:
        installed = run_code("--list-extensions", "--show-versions", timeout=90)
        if f"{EXT_ID}@{version}".casefold() in installed.casefold():
            return "up to date"
        vsix = build_vsix(DATA / f"sora-bridge-{version}.vsix")
        run_code("--install-extension", str(vsix), "--force", timeout=180)
        log.info("installed the Sora Bridge %s extension in VS Code", version)
        return "installed"
    except (ActionError, OSError, subprocess.SubprocessError) as exc:
        log.warning("could not install the Sora Bridge extension: %s", exc)
        return f"failed: {exc}"
