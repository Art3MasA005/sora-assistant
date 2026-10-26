"""Start with Windows: shortcuts that run the server and the PC agent without console windows
(scripts/run_hidden.py), under .venv\\Scripts\\Sora.exe so Windows calls them "Sora" (pythonw.exe
if that isn't built — scripts/sora_host/build.ps1).

- Startup folder: "Sora server" / "Sora PC agent" while "Start with Windows" is on.
- %LOCALAPPDATA%\\Sora\\backend.json: how to start them, written whenever the server starts, so the
  Windows app can start Sora when it opens and finds it off. run_hidden.py makes sure only one of
  each runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
ITEMS = {"Sora server": "server", "Sora PC agent": "agent"}


def supported() -> bool:
    return sys.platform == "win32"


def startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def launch_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Sora" / "backend.json"


def interpreter() -> Path:
    scripts = ROOT / ".venv" / "Scripts"
    host = scripts / "Sora.exe"
    return host if host.exists() else scripts / "pythonw.exe"


def enabled() -> bool:
    return supported() and all((startup_dir() / f"{name}.lnk").exists() for name in ITEMS)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_shortcuts(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    exe, script = interpreter(), ROOT / "scripts" / "run_hidden.py"
    lines = ["$sh = New-Object -ComObject WScript.Shell"]
    for name, target in ITEMS.items():
        link, args = str(folder / f"{name}.lnk"), f'"{script}" {target}'
        lines += [
            f"$s = $sh.CreateShortcut({_ps_quote(link)})",
            f"$s.TargetPath = {_ps_quote(str(exe))}",
            f"$s.Arguments = {_ps_quote(args)}",
            f"$s.WorkingDirectory = {_ps_quote(str(ROOT))}",
            f"$s.IconLocation = {_ps_quote(f'{exe},0')}",
            f"$s.Description = {_ps_quote(f'Sora ({target})')}",
            "$s.Save()",
        ]
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", "; ".join(lines)],
        check=True, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
    )


def set_enabled(on: bool) -> bool:
    if not supported():
        return False
    if on:
        _write_shortcuts(startup_dir())
    else:
        for name in ITEMS:
            (startup_dir() / f"{name}.lnk").unlink(missing_ok=True)
    return enabled()


def _write_launch_file() -> None:
    path = launch_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    script = ROOT / "scripts" / "run_hidden.py"
    path.write_text(json.dumps({
        "exe": str(interpreter()), "cwd": str(ROOT),
        "server": [str(script), "server"], "agent": [str(script), "agent"],
    }, indent=2), encoding="utf-8")


async def write_launchers() -> None:
    """Tells the Windows app how to start Sora (and refreshes the Startup shortcuts if on, in case
    the project folder moved)."""
    if not supported():
        return
    try:
        await asyncio.to_thread(_write_launch_file)
        if enabled():
            await asyncio.to_thread(_write_shortcuts, startup_dir())
    except Exception as exc:  # odd profile, no PowerShell: the app just can't start Sora itself
        log.warning("could not write the launch details: %s", exc)
