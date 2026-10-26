"""Sora's orb in the screen's bottom-right corner while the owner talks to it with "Hey Sora" on this PC,
so it is clear at once that Sora heard, even when the answer takes a while. Talking in the app shows
the app's own orb instead.

- The orb is the Windows app in its corner mode (`sora.exe --orb`, app/lib/desktop/orb_overlay.dart):
  a small transparent window that never takes the focus and lets clicks through.
- Started while "Hey Sora" is on and kept running: hidden, it draws nothing and uses no CPU (only
  some memory), so it can appear the moment the name is heard. It ends with the agent.
- One JSON line per change over 127.0.0.1, after a token: {"state": "listening" | "thinking" |
  "speaking" | "hide", "level": 0..1}; the mic's level at most 10 times a second.
- Without the app installed (or with CORNER_ORB=0 in .env) nothing happens. SORA_APP_EXE points at
  another sora.exe (a build of your own).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("sora-voice")

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LEVEL_EVERY = 0.1  # seconds between level updates


def app_exe() -> Path | None:
    """The Windows app's sora.exe: SORA_APP_EXE, the installed one, or a build in this folder."""
    places = [
        os.environ.get("SORA_APP_EXE"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Sora" / "sora.exe"),
        str(ROOT / "app" / "build" / "windows" / "x64" / "runner" / "Release" / "sora.exe"),
    ]
    return next((Path(p) for p in places if p and Path(p).is_file()), None)


class CornerOrb:
    def __init__(self):
        self._lock = threading.Lock()
        self._conn: socket.socket | None = None
        self._proc: subprocess.Popen | None = None
        self._starting = False
        self.state = "hide"
        self._level_at = 0.0

    # ------------------------------------------------------------ the orb's process

    def start(self) -> None:
        """Starts the orb in the background (if it isn't running already)."""
        if os.name != "nt" or os.environ.get("CORNER_ORB", "1") == "0":
            return
        with self._lock:
            if self._starting or (self._proc is not None and self._proc.poll() is None):
                return
            self._starting = True
        threading.Thread(target=self._launch, name="corner-orb", daemon=True).start()

    def _launch(self) -> None:
        try:
            exe = app_exe()
            if exe is None:
                log.info("no Sora app found for the corner orb (install it, or set SORA_APP_EXE)")
                return
            token = secrets.token_urlsafe(16)
            with socket.create_server(("127.0.0.1", 0)) as server:
                server.settimeout(30)
                port = server.getsockname()[1]
                proc = subprocess.Popen([str(exe), "--orb", "--port", str(port), "--token", token], creationflags=NO_WINDOW)
                conn, _ = server.accept()
            conn.settimeout(5)
            hello = conn.makefile("r", encoding="utf-8").readline()
            if json.loads(hello or "{}").get("token") != token:
                conn.close()
                proc.terminate()
                return
            conn.settimeout(None)
            with self._lock:
                self._proc, self._conn = proc, conn
            log.info("corner orb ready")
        except (OSError, ValueError) as exc:
            log.warning("corner orb not started: %s", exc)
        finally:
            self._starting = False

    def stop(self) -> None:
        with self._lock:
            conn, proc = self._conn, self._proc
            self._conn = self._proc = None
        if conn is not None:
            conn.close()  # the orb ends when its line does
        if proc is not None:
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                proc.terminate()
        self.state = "hide"

    # ------------------------------------------------------------ what it shows

    def _send(self, msg: dict) -> None:
        conn = self._conn
        if conn is None:
            if msg.get("state") != "hide":
                self.start()  # not running (closed meanwhile): back for the next time
            return
        try:
            conn.sendall((json.dumps(msg) + "\n").encode())
        except OSError:
            with self._lock:
                self._conn = None

    def show(self, state: str) -> None:
        """"listening", "thinking" or "speaking"."""
        if state != self.state:
            self.state = state
            self._send({"state": state})

    def hide(self) -> None:
        if self.state != "hide":
            self.state = "hide"
            self._send({"state": "hide"})

    def level(self, samples) -> None:
        """The mic's loudness while listening (a chunk of float samples)."""
        now = time.monotonic()
        if self.state != "listening" or now - self._level_at < LEVEL_EVERY or not len(samples):
            return
        self._level_at = now
        rms = float((samples * samples).mean()) ** 0.5
        self._send({"state": "listening", "level": round(min(1.0, rms * 8), 3)})


orb = CornerOrb()
