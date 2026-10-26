"""Start a Sora process without a console window (for Windows sign-in), logging to data/logs.

    .venv\Scripts\Sora.exe scripts/run_hidden.py server   # the backend (python -m sora serve)
    .venv\Scripts\Sora.exe scripts/run_hidden.py agent    # the PC agent (with PowerShell commands allowed)

Sora.exe (scripts/sora_host) is Python under Sora's name; pythonw.exe works too. Neither has a
stdout/stderr, so both go to a log file instead. Only one of each runs: a second start exits at once
(the Startup shortcut and the Windows app may both start it). The Startup shortcuts come from the
app's "Start with Windows" setting or scripts/install_autostart.ps1.
"""

from __future__ import annotations

import ctypes
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "server": (ROOT / "backend", "sora", ["serve"]),
    "agent": (ROOT / "pc_agent", "sora_pc_agent", ["--allow-shell"]),
}


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in TARGETS:
        sys.exit(f"usage: run_hidden.py {'|'.join(TARGETS)}")
    folder, module, args = TARGETS[name]
    if sys.platform == "win32":
        # Kept open for the life of the process; Windows closes it on exit.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW(None, False, f"Local\\sora-{name}")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS: already running
            sys.exit(0)
    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = open(logs / f"{name}.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the process
    sys.stdout = sys.stderr = log
    sys.path.insert(0, str(folder))
    os.chdir(folder)
    sys.argv = [module, *args]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
