"""Keep PostgreSQL inside WSL running while Sora runs (Windows dev setup without Docker).

WSL stops an idle distro after a few seconds, taking Postgres with it. Holding one
`sleep infinity` process attached keeps the distro (and systemd's postgresql service) alive.
Enabled by WSL_DISTRO in .env.
"""

from __future__ import annotations

import atexit
import socket
import subprocess
import sys
import time

from sqlalchemy.engine import make_url

from sora.config import get_settings

_keepalive: subprocess.Popen | None = None


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def ensure_postgres(timeout: float = 60) -> None:
    global _keepalive
    s = get_settings()
    if not s.wsl_distro or sys.platform != "win32" or not s.database_url:
        return
    url = make_url(s.async_database_url)
    host, port = url.host or "127.0.0.1", url.port or 5432
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if _keepalive is None or _keepalive.poll() is not None:
        _keepalive = subprocess.Popen(
            ["wsl.exe", "-d", s.wsl_distro, "--exec", "sleep", "infinity"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
        )
        atexit.register(_stop_keepalive)

    if _port_open(host, port):
        return
    subprocess.run(
        ["wsl.exe", "-d", s.wsl_distro, "-u", "root", "--", "systemctl", "start", "postgresql"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
        timeout=timeout, check=False,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return
        time.sleep(0.5)
    raise RuntimeError(f"PostgreSQL in WSL ({s.wsl_distro}) did not come up on {host}:{port}")


def _stop_keepalive() -> None:
    if _keepalive is not None and _keepalive.poll() is None:
        _keepalive.terminate()
