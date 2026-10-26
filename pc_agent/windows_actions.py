"""Things the PC agent can do on Windows. Standard library + ctypes only.

Every action takes a params dict and returns something JSON-serialisable, or raises ActionError.
"""

from __future__ import annotations

import csv
import ctypes
import difflib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
import zlib
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ActionError(RuntimeError):
    pass


def _run(args: list[str], timeout: float = 30, input_bytes: bytes | None = None,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, input=input_bytes, env=env, creationflags=NO_WINDOW)


# ---------------------------------------------------------------- apps, urls, files

APP_ALIASES = {
    "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
    "chrome": "google chrome", "edge": "microsoft edge", "word": "word", "excel": "excel",
    "powerpoint": "powerpoint", "telegram": "telegram", "whatsapp": "whatsapp", "spotify": "spotify",
}
BUILTIN_APPS = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe", "paint": "mspaint.exe",
    "explorer": "explorer.exe", "file explorer": "explorer.exe", "files": "explorer.exe",
    "task manager": "taskmgr.exe", "cmd": "cmd.exe", "command prompt": "cmd.exe", "powershell": "powershell.exe",
    "terminal": "wt.exe", "settings": "ms-settings:", "control panel": "control.exe", "snipping tool": "snippingtool.exe",
}


def _start_menu_entries() -> dict[str, Path]:
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]
    entries: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() in {".lnk", ".url", ".appref-ms"}:
                name = path.stem.lower()
                if "uninstall" not in name and name not in entries:
                    entries[name] = path
    return entries


def open_app(params: dict) -> str:
    target = (params.get("target") or "").strip().lower()
    if not target:
        raise ActionError("which app?")
    if target in BUILTIN_APPS:
        os.startfile(BUILTIN_APPS[target])
        return f"opened {target}"
    wanted = APP_ALIASES.get(target, target)
    entries = _start_menu_entries()
    exact = [n for n in entries if n == wanted]
    contains = sorted((n for n in entries if wanted in n), key=len)
    fuzzy = difflib.get_close_matches(wanted, list(entries), n=1, cutoff=0.6)
    match = (exact or contains or fuzzy or [None])[0]
    if match is not None:
        os.startfile(str(entries[match]))
        return f"opened {entries[match].stem}"
    store_app = _find_store_app(wanted)
    if store_app is not None:
        name, app_id = store_app
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], creationflags=NO_WINDOW)
        return f"opened {name}"
    exe = shutil.which(target) or shutil.which(target + ".exe")
    if exe:
        subprocess.Popen([exe], creationflags=NO_WINDOW)
        return f"started {exe}"
    raise ActionError(f"could not find an app called '{target}'")


def _find_store_app(wanted: str) -> tuple[str, str] | None:
    """Microsoft Store apps (Telegram, WhatsApp...) have no .lnk; Get-StartApps lists them with launch ids."""
    result = _run(["powershell", "-NoProfile", "-Command",
                   "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"])
    try:
        apps = json.loads(result.stdout.decode("utf-8", errors="replace") or "[]")
    except ValueError:
        return None
    if isinstance(apps, dict):
        apps = [apps]
    by_name = {a["Name"].lower(): (a["Name"], a["AppID"]) for a in apps if a.get("Name") and a.get("AppID")}
    names = [n for n in by_name if "uninstall" not in n]
    exact = [n for n in names if n == wanted]
    contains = sorted((n for n in names if wanted in n), key=len)
    fuzzy = difflib.get_close_matches(wanted, names, n=1, cutoff=0.6)
    match = (exact or contains or fuzzy or [None])[0]
    return by_name[match] if match else None


def open_url(params: dict) -> str:
    url = (params.get("target") or "").strip()
    if not url:
        raise ActionError("which url?")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    webbrowser.open(url)
    return f"opened {url}"


def open_path(params: dict) -> str:
    raw = (params.get("target") or "").strip().strip('"')
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not path.exists():
        raise ActionError(f"{path} does not exist")
    os.startfile(str(path))
    return f"opened {path}"


def _powershell(script: str, *args: str, timeout: float = 30) -> str:
    """Runs [script] with [args] as its parameters — user text never becomes PowerShell code.

    The values travel in environment variables, never on the command line: powershell -Command joins
    everything after it into one command, where "$(…)" in a quoted value would run."""
    names = [f"SORA_ARG{i}" for i in range(len(args))]
    values = "@(" + ",".join(f"$env:{n}" for n in names) + ")"
    wrapped = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $sora_args = " + values + "; & {" + script + "} @sora_args"
    env = {**os.environ, **{n: str(v) for n, v in zip(names, args)}}
    result = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped], timeout=timeout, env=env)
    if result.returncode != 0:
        raise ActionError(result.stderr.decode("utf-8", errors="replace").strip()[-800:] or "PowerShell failed")
    return result.stdout.decode("utf-8", errors="replace").strip()


# App names people say → process names (without .exe).
PROCESS_ALIASES = {
    "vs code": "Code", "vscode": "Code", "visual studio code": "Code", "code": "Code", "chrome": "chrome",
    "google chrome": "chrome", "edge": "msedge", "microsoft edge": "msedge", "firefox": "firefox", "word": "WINWORD",
    "excel": "EXCEL", "powerpoint": "POWERPNT", "outlook": "OUTLOOK", "notepad": "notepad", "paint": "mspaint",
    "calculator": "CalculatorApp", "telegram": "Telegram", "whatsapp": "WhatsApp", "spotify": "Spotify",
    "discord": "Discord", "zoom": "Zoom", "teams": "ms-teams", "vlc": "vlc", "steam": "steam",
    "task manager": "Taskmgr", "store": "WinStore.App", "microsoft store": "WinStore.App", "terminal": "WindowsTerminal",
}
# Never closed: Windows itself, and python (this agent, the Sora server and the owner's training runs).
PROTECTED_PROCESSES = {
    "explorer", "winlogon", "csrss", "lsass", "svchost", "services", "smss", "wininit", "dwm", "system", "python",
    "pythonw", "py", "sora",
}


def close_app(params: dict) -> dict:
    """Closes an app's windows like clicking X (unsaved work prompts stay open); value=1 forces it."""
    target = (params.get("target") or "").strip()
    if not target:
        raise ActionError("which app?")
    name = PROCESS_ALIASES.get(target.lower(), target).removesuffix(".exe")
    if name.lower() in PROTECTED_PROCESSES:
        raise ActionError(f"refusing to close {name}: Windows, Sora and Python jobs are protected")
    force = bool(params.get("value"))
    script = r"""
param($name, $force, $protected)
$prot = $protected -split ','
$procs = @(Get-Process | Where-Object { $prot -notcontains $_.ProcessName.ToLower() -and (
    $_.ProcessName -eq $name -or ($_.MainWindowHandle -ne 0 -and ($_.ProcessName -like "*$name*" -or $_.MainWindowTitle -like "*$name*"))) })
if (-not $procs) { '{"closed":[],"still_open":[]}'; return }
$names = $procs | ForEach-Object { $_.ProcessName } | Select-Object -Unique
foreach ($p in $procs) { if ($p.MainWindowHandle -ne 0) { [void]$p.CloseMainWindow() } }
Start-Sleep -Seconds 4
$left = @(Get-Process -Name $names -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 })
if ($force -eq '1') { Get-Process -Name $names -ErrorAction SilentlyContinue | Stop-Process -Force; $left = @() }
@{ closed = @($names); still_open = @($left | ForEach-Object { $_.ProcessName } | Select-Object -Unique) } | ConvertTo-Json -Compress
"""
    out = _powershell(script, name, "1" if force else "0", ",".join(sorted(PROTECTED_PROCESSES)), timeout=40)
    data = json.loads(out or "{}")
    if not data.get("closed"):
        raise ActionError(f"no open app matches '{target}'")
    if data.get("still_open"):
        data["note"] = "some windows are still open (maybe asking to save); use value=1 to force-close"
    return data


def _winget(args: list[str], timeout: float) -> str:
    exe = shutil.which("winget")
    if not exe:
        raise ActionError("winget is not available on this PC")
    result = _run([exe, *args, "--accept-source-agreements", "--disable-interactivity"], timeout=timeout)
    out = result.stdout.decode("utf-8", errors="replace")
    # winget draws progress spinners with carriage returns; keep the readable lines.
    lines = [ln.split("\r")[-1].strip() for ln in out.splitlines()]
    text = "\n".join(ln for ln in lines if ln and not re.fullmatch(r"[-\\|/]|.*[█▒].*", ln))
    if result.returncode != 0:
        raise ActionError(text[-1500:] or f"winget exited with {result.returncode}")
    return text


def _parse_winget_table(text: str) -> list[dict]:
    """`winget search` prints a fixed-width table: Name  Id  Version ... under a dashed rule."""
    lines = text.splitlines()
    rule = next((i for i, ln in enumerate(lines) if re.fullmatch(r"-{10,}", ln.strip())), None)
    if rule is None or rule == 0:
        return []
    header = lines[rule - 1]
    cols = [m.start() for m in re.finditer(r"\S+", header)]
    names = header.split()
    rows = []
    for ln in lines[rule + 1 :]:
        if not ln.strip():
            continue
        cells = [ln[a:b].strip() for a, b in zip(cols, cols[1:] + [None])]
        rows.append(dict(zip([n.lower() for n in names], cells)))
    return rows


def store_search(params: dict) -> dict:
    """Searches the Microsoft Store (and shows the results in the Store app unless value=0)."""
    query = (params.get("target") or "").strip()
    if not query:
        raise ActionError("search for what?")
    if params.get("value") != 0:
        os.startfile("ms-windows-store://search/?query=" + urllib.parse.quote(query))
    try:
        rows = _parse_winget_table(_winget(["search", query, "--source", "msstore"], timeout=60))
    except ActionError as exc:
        if "No package found" in str(exc):
            rows = []
        else:
            raise
    return {"query": query, "results": [{"name": r.get("name"), "id": r.get("id")} for r in rows[:10]]}


def store_install(params: dict) -> dict:
    """Installs a Microsoft Store app by its Store id (e.g. 9NKSQGP7F2NH) or by name (best match)."""
    target = (params.get("target") or "").strip()
    if not target:
        raise ActionError("install what?")
    app_id, name = target, target
    if not re.fullmatch(r"[0-9A-Z]{12}", target):
        rows = store_search({"target": target, "value": 0})["results"]
        if not rows:
            raise ActionError(f"nothing called '{target}' in the Microsoft Store")
        exact = [r for r in rows if (r["name"] or "").lower() == target.lower()]
        app_id, name = (exact or rows)[0]["id"], (exact or rows)[0]["name"]
    out = _winget(["install", "--id", app_id, "--source", "msstore", "--accept-package-agreements", "--silent"], timeout=900)
    return {"installed": name, "id": app_id, "log": out[-600:]}


def uninstall_app(params: dict) -> dict:
    """Uninstalls an installed app by name (winget). Some uninstallers ask for admin rights on screen."""
    target = (params.get("target") or "").strip()
    if not target:
        raise ActionError("uninstall what?")
    try:
        out = _winget(["uninstall", "--name", target, "--silent"], timeout=600)
    except ActionError as exc:
        if "Multiple" in str(exc) or "multiple" in str(exc):
            listed = _parse_winget_table(_winget(["list", "--name", target], timeout=60))
            raise ActionError(f"several apps match '{target}': " + ", ".join(r.get("name", "") for r in listed[:8])) from None
        raise
    return {"uninstalled": target, "log": out[-600:]}


def installed_apps(params: dict) -> list[dict]:
    """Installed apps whose name contains target (all if empty), from winget."""
    target = (params.get("target") or "").strip()
    args = ["list"] + (["--name", target] if target else [])
    rows = _parse_winget_table(_winget(args, timeout=90))
    return [{"name": r.get("name"), "version": r.get("version")} for r in rows[:40]]


# ---------------------------------------------------------------- browser, YouTube


def _chrome() -> str | None:
    for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("LOCALAPPDATA", "")):
        path = Path(base) / r"Google\Chrome\Application\chrome.exe"
        if base and path.exists():
            return str(path)
    return shutil.which("chrome")


def _open_in_browser(url: str, browser: str = "chrome") -> None:
    exe = _chrome() if browser == "chrome" else None
    if exe:
        subprocess.Popen([exe, url], creationflags=NO_WINDOW)
    else:
        webbrowser.open(url)


SEARCH_SITES = {
    "google": "https://www.google.com/search?q=", "youtube": "https://www.youtube.com/results?search_query=",
    "bing": "https://www.bing.com/search?q=", "maps": "https://www.google.com/maps/search/",
    "images": "https://www.google.com/search?tbm=isch&q=",
}


def web_search(params: dict) -> str:
    """Searches the web in Chrome. text = google (default) | youtube | bing | maps | images."""
    query = (params.get("target") or "").strip()
    if not query:
        raise ActionError("search for what?")
    site = (params.get("text") or "google").lower()
    _open_in_browser(SEARCH_SITES.get(site, SEARCH_SITES["google"]) + urllib.parse.quote_plus(query))
    return f"searched {site} for {query}"


def youtube_play(params: dict) -> dict:
    """Plays the top YouTube result for target in Chrome."""
    query = (params.get("target") or "").strip()
    if not query:
        raise ActionError("play what?")
    url = SEARCH_SITES["youtube"] + urllib.parse.quote_plus(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"})
        page = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="replace")
    except OSError:
        page = ""
    found = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', page)
    if not found:
        _open_in_browser(url)
        return {"playing": None, "note": "opened the YouTube results page"}
    video_id, title = found.group(1), json.loads(f'"{found.group(2)}"')
    _open_in_browser(f"https://www.youtube.com/watch?v={video_id}")
    return {"playing": title, "url": f"https://www.youtube.com/watch?v={video_id}"}


# ---------------------------------------------------------------- training runs


def _gpu() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    fields = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
    result = _run([exe, f"--query-gpu={fields}", "--format=csv,noheader,nounits"], timeout=15)
    gpus = []
    for line in result.stdout.decode(errors="replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 6:
            gpus.append({"name": parts[0], "util_percent": parts[1], "memory_mb": f"{parts[2]}/{parts[3]}",
                         "temp_c": parts[4], "power_w": parts[5]})
    return gpus


def _training_processes() -> list[dict]:
    script = r"""
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'train|fit|finetune' } |
  ForEach-Object { @{ pid = $_.ProcessId; command = $_.CommandLine; started = $_.CreationDate.ToString('s') } } |
  ConvertTo-Json -Compress
"""
    out = _powershell(script)
    data = json.loads(out) if out else []
    data = data if isinstance(data, list) else [data]
    seen, unique = set(), []
    for p in data:  # a venv launcher and its child share one command line
        key = re.sub(r'^"?[^"]*python[w]?(\.exe)?"?\s*', "", p.get("command") or "", flags=re.I)
        if key not in seen:
            seen.add(key)
            unique.append({"pid": p.get("pid"), "command": key[:300], "started": p.get("started")})
    return unique


SKIP_DIRS = {".venv", "venv", "env", "node_modules", ".git", "__pycache__", "site-packages", "data", "datasets"}


def _latest_logs(roots: list[Path], limit: int = 2) -> list[Path]:
    found: list[tuple[float, Path]] = []
    for root in roots:
        if not root.is_dir():
            continue
        base = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if len(Path(dirpath).parts) - base >= 7:
                dirnames.clear()
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                if f.lower().endswith((".log", "log.txt")):
                    path = Path(dirpath) / f
                    found.append((path.stat().st_mtime, path))
    return [p for _, p in sorted(found, reverse=True)[:limit]]


METRIC_LINE = re.compile(r"dice|hd95|iou|best|accuracy|val[_ ]|epochs done|checkpoint|finished|error|traceback", re.I)


def training_status(params: dict) -> dict:
    """Running training jobs, GPU load and the tail of the newest training log (epoch, loss, Dice...).

    Log folders come from target, else TRAINING_DIRS in .env (separated by ;)."""
    import time

    raw = params.get("target") or os.environ.get("TRAINING_DIRS", "")
    roots = [Path(os.path.expandvars(p.strip())) for p in raw.split(";") if p.strip()]
    logs = []
    newest = _latest_logs(roots)
    # A second log only if it is also current (two runs at once), not last week's run.
    newest = newest[:1] + [p for p in newest[1:] if time.time() - p.stat().st_mtime < 86_400]
    for path in newest:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 24_000))
            tail = fh.read().decode("utf-8", errors="replace").splitlines()[1:]
        lines = [ln for ln in tail if ln.strip()]
        logs.append({
            "file": str(path),
            "updated_minutes_ago": round((time.time() - path.stat().st_mtime) / 60, 1),
            "metrics": [ln.strip() for ln in lines if METRIC_LINE.search(ln)][-12:],
            "tail": "\n".join(lines[-45:])[-4500:],
        })
    return {
        "processes": _training_processes(),
        "gpu": _gpu(),
        "logs": logs,
        "note": None if roots else "no TRAINING_DIRS set in .env, so no log was read",
    }


def search_files(params: dict) -> list[dict]:
    needle = (params.get("target") or "").strip().lower()
    if len(needle) < 2:
        raise ActionError("give at least 2 characters to search for")
    home = Path.home()
    roots = [home / d for d in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")]
    found: list[dict] = []
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if len(Path(dirpath).parts) - base_depth >= 5:
                dirnames.clear()
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {"node_modules", "__pycache__", ".git"}]
            for name in dirnames + filenames:
                if needle in name.lower():
                    found.append({"name": name, "path": str(Path(dirpath) / name)})
                    if len(found) >= 25:
                        return found
    return found


# ---------------------------------------------------------------- keys, media, volume

VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2, "up": 0xAF, "down": 0xAE, "mute": 0xAD}


def _tap(vk: int, times: int = 1) -> None:
    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP


def media(params: dict) -> str:
    key = (params.get("target") or "play_pause").lower().replace(" ", "_").replace("/", "_")
    key = {"play": "play_pause", "pause": "play_pause", "prev": "previous"}.get(key, key)
    if key not in {"play_pause", "next", "previous", "stop"}:
        raise ActionError("media target must be play_pause, next, previous or stop")
    _tap(VK[key])
    return f"media {key}"


def volume(params: dict) -> str:
    direction = (params.get("target") or "up").lower()
    if direction not in {"up", "down", "mute"}:
        raise ActionError("volume target must be up, down or mute")
    steps = 1 if direction == "mute" else max(1, min(50, int(params.get("value") or 5)))
    _tap(VK[direction], steps)
    return f"volume {direction}" + (f" x{steps} (~{steps * 2}%)" if direction != "mute" else "")


# ---------------------------------------------------------------- power / session


def lock(params: dict) -> str:
    ctypes.windll.user32.LockWorkStation()
    return "locked"


def sleep(params: dict) -> str:
    _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], timeout=10)
    return "going to sleep"


def shutdown(params: dict) -> str:
    delay = max(0, min(3600, int(params.get("value") or 60)))
    _run(["shutdown", "/s", "/t", str(delay)])
    return f"shutting down in {delay}s (cancel_shutdown to abort)"


def restart(params: dict) -> str:
    delay = max(0, min(3600, int(params.get("value") or 60)))
    _run(["shutdown", "/r", "/t", str(delay)])
    return f"restarting in {delay}s (cancel_shutdown to abort)"


def cancel_shutdown(params: dict) -> str:
    result = _run(["shutdown", "/a"])
    return "cancelled" if result.returncode == 0 else "nothing to cancel"


def log_off(params: dict) -> str:
    _run(["shutdown", "/l"])
    return "logging off"


# ---------------------------------------------------------------- screen, notifications, clipboard


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


def _png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def screenshot(params: dict) -> dict:
    import base64

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.SetProcessDPIAware()
    for fn in (user32.GetDC, gdi32.CreateCompatibleDC, gdi32.CreateCompatibleBitmap, gdi32.SelectObject):
        fn.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.BitBlt.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    x, y = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    w, h = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(mem, bmp)
    try:
        gdi32.BitBlt(mem, 0, 0, w, h, screen, x, y, 0x00CC0020 | 0x40000000)  # SRCCOPY | CAPTUREBLT
        info = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0):
            raise ActionError("screen capture failed")
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)

    data = buf.raw
    stride = w * 4
    # max_width shrinks the image by whole steps (every k-th pixel and row) — cheap, and plenty for a
    # model to read the screen.
    max_width = int(params.get("max_width") or 0)
    k = -(-w // max_width) if max_width and w > max_width else 1
    out_w, out_h = len(range(0, w, k)), len(range(0, h, k))
    raw = bytearray()
    for row in range(0, h, k):
        line = data[row * stride : (row + 1) * stride]
        rgb = bytearray(out_w * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4 * k], line[1::4 * k], line[0::4 * k]
        raw += b"\x00" + rgb
    return {"png_base64": base64.b64encode(_png(out_w, out_h, bytes(raw))).decode(), "width": out_w, "height": out_h}


def notify(params: dict) -> str:
    text = params.get("text") or params.get("target") or "Hello from Sora"
    # Non-blocking, always-on-top message box.
    threading.Thread(
        target=lambda: ctypes.windll.user32.MessageBoxW(None, text, "Sora", 0x40 | 0x40000), daemon=True
    ).start()
    return "shown"


# A Windows toast (the corner notification) under PowerShell's app id, which every Windows has. The
# text arrives in environment variables: it is someone else's message, so it never becomes code.
TOAST_SCRIPT = (
    "$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime];"
    "$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime];"
    "$t = [Security.SecurityElement]::Escape($env:SORA_TOAST_TITLE);"
    "$b = [Security.SecurityElement]::Escape($env:SORA_TOAST_TEXT);"
    "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
    "$x.LoadXml(\"<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>\");"
    "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
    "[Windows.UI.Notifications.ToastNotification]::new($x))"
)


def toast(params: dict) -> str:
    """A phone notification as a Windows toast (it fades by itself, unlike notify's message box)."""
    env = {**os.environ, "SORA_TOAST_TITLE": str(params.get("title") or "Sora")[:200],
           "SORA_TOAST_TEXT": str(params.get("text") or "")[:600]}
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", TOAST_SCRIPT],
                            capture_output=True, timeout=20, env=env, creationflags=NO_WINDOW)
    if result.returncode != 0:
        raise ActionError(result.stderr.decode("utf-8", errors="replace").strip()[-300:] or "the toast failed")
    return "shown"


def clipboard_get(params: dict) -> str:
    result = _run(["powershell", "-NoProfile", "-Command",
                   "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"])
    return result.stdout.decode("utf-8", errors="replace").strip()[:5000]


def clipboard_set(params: dict) -> str:
    text = params.get("text")
    if text is None:
        raise ActionError("no text given")
    import clipboard_sync

    clipboard_sync.remember(text)  # so the clipboard watcher doesn't send it straight back
    _run(["clip.exe"], input_bytes=text.encode("utf-16-le"))  # clip.exe understands UTF-16 input
    return f"copied {len(text)} characters"


def clipboard_image(params: dict) -> str:
    """Puts a PNG (png_base64) on the clipboard, e.g. a screenshot taken on the phone."""
    import base64
    import tempfile

    data = base64.b64decode(params.get("png_base64") or "")
    if not data:
        raise ActionError("no image given")
    fd, path = tempfile.mkstemp(suffix=".png")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    try:
        script = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                  f"$i = [System.Drawing.Image]::FromFile('{path}'); "
                  "[System.Windows.Forms.Clipboard]::SetImage($i); $i.Dispose()")
        result = _run(["powershell", "-NoProfile", "-STA", "-Command", script], timeout=30)
        if result.returncode != 0:
            raise ActionError(result.stderr.decode(errors="replace").strip()[:300] or "could not set the clipboard")
        import clipboard_sync

        clipboard_sync.remember_image()  # so the clipboard watcher doesn't send it straight back
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return f"copied an image ({len(data) // 1024} KB)"


# ---------------------------------------------------------------- processes and system


def list_processes(params: dict) -> list[dict]:
    result = _run(["tasklist", "/fo", "csv", "/nh"])
    totals: dict[str, dict] = {}
    for row in csv.reader(io.StringIO(result.stdout.decode(errors="replace"))):
        if len(row) < 5:
            continue
        name, mem = row[0], int(re.sub(r"[^\d]", "", row[4]) or 0)
        entry = totals.setdefault(name, {"name": name, "count": 0, "memory_mb": 0.0})
        entry["count"] += 1
        entry["memory_mb"] += mem / 1024
    top = sorted(totals.values(), key=lambda e: e["memory_mb"], reverse=True)[:25]
    for e in top:
        e["memory_mb"] = round(e["memory_mb"])
    return top


def kill_process(params: dict) -> str:
    name = (params.get("target") or "").strip()
    if not re.fullmatch(r"[\w .\-]+", name):
        raise ActionError("give a process name like chrome.exe")
    if not name.lower().endswith(".exe"):
        name += ".exe"
    if name.lower() in {"explorer.exe", "winlogon.exe", "csrss.exe", "lsass.exe", "svchost.exe", "python.exe", "pythonw.exe"}:
        raise ActionError(f"refusing to kill {name}")
    result = _run(["taskkill", "/im", name, "/f"])
    out = (result.stdout or result.stderr).decode(errors="replace").strip()
    if result.returncode != 0:
        raise ActionError(out or f"could not stop {name}")
    return out


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD)]


def system_info(params: dict) -> dict:
    mem = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    power = SYSTEM_POWER_STATUS()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power))
    ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    uptime_h = ctypes.windll.kernel32.GetTickCount64() / 3_600_000
    disks = {}
    for letter in "CDEFGH":
        root = f"{letter}:\\"
        if os.path.exists(root):
            usage = shutil.disk_usage(root)
            disks[letter] = {"free_gb": round(usage.free / 1e9, 1), "total_gb": round(usage.total / 1e9, 1)}
    return {
        "computer": os.environ.get("COMPUTERNAME"),
        "memory_used_percent": mem.dwMemoryLoad,
        "memory_total_gb": round(mem.ullTotalPhys / 1e9, 1),
        "battery_percent": None if power.BatteryLifePercent == 255 else power.BatteryLifePercent,
        "plugged_in": power.ACLineStatus == 1,
        "uptime_hours": round(uptime_h, 1),
        "disks": disks,
    }


def run_command(params: dict) -> dict:
    command = params.get("text") or ""
    if not command.strip():
        raise ActionError("no command given")
    result = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command], timeout=120)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout.decode("utf-8", errors="replace")[-6000:],
        "stderr": result.stderr.decode("utf-8", errors="replace")[-2000:],
    }


ACTIONS = {
    "open_app": open_app, "open_url": open_url, "open_path": open_path, "search_files": search_files,
    "media": media, "volume": volume, "lock": lock, "sleep": sleep, "shutdown": shutdown, "restart": restart,
    "cancel_shutdown": cancel_shutdown, "log_off": log_off, "screenshot": screenshot, "notify": notify, "toast": toast,
    "clipboard_get": clipboard_get, "clipboard_set": clipboard_set, "clipboard_image": clipboard_image,
    "list_processes": list_processes,
    "kill_process": kill_process, "system_info": system_info, "run_command": run_command,
    "close_app": close_app, "store_search": store_search, "store_install": store_install,
    "uninstall_app": uninstall_app, "installed_apps": installed_apps, "web_search": web_search,
    "youtube_play": youtube_play, "training_status": training_status,
}


def _later(module: str, name: str):
    """An action from one of the modules below, loaded when first used (they import this module)."""

    def action(params: dict):
        import importlib

        return getattr(importlib.import_module(module), name)(params)

    action.__name__ = name
    return action


# Windows and typing, files, settings, the browser, VS Code and Claude Code live in their own modules.
for _module, _names in {
    "window_control": ("window_list", "window_focus", "window_minimize", "window_maximize", "window_snap",
                       "type_text", "hotkey"),
    "file_actions": ("file_copy", "file_move", "file_rename", "file_delete", "file_zip", "file_unzip",
                     "tidy_downloads"),
    "pc_settings": ("brightness", "wifi", "bluetooth", "dark_mode"),
    "browser": ("browser_open", "browser_read", "browser_click", "browser_fill", "browser_screenshot",
                "browser_download", "browser_close", "browser_text"),
    "vscode_bridge": ("vscode",),
    "claude_code": ("claude_code",),
}.items():
    ACTIONS.update({n: _later(_module, n) for n in _names})
