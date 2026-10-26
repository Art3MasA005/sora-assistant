"""The corner orb's line from the agent: started with a token, told only what changes, the level throttled."""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest

import corner_orb

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the corner orb is Windows-only")


def _until(check, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_the_orb_hears_what_changes(tmp_path, monkeypatch):
    got = tmp_path / "got.txt"
    script = tmp_path / "orb.py"
    # A stand-in sora.exe --orb: connects with the token and writes down every line it is sent.
    script.write_text(textwrap.dedent(f"""\
        import json, socket, sys
        args = sys.argv[1:]
        port, token = int(args[args.index("--port") + 1]), args[args.index("--token") + 1]
        s = socket.create_connection(("127.0.0.1", port))
        s.sendall((json.dumps({{"token": token}}) + "\\n").encode())
        with open({str(got)!r}, "a", encoding="utf-8") as out:
            for line in s.makefile("r", encoding="utf-8"):
                out.write(line); out.flush()
    """))
    launcher = tmp_path / "sora.cmd"
    launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n')
    monkeypatch.setenv("SORA_APP_EXE", str(launcher))
    monkeypatch.delenv("CORNER_ORB", raising=False)

    orb = corner_orb.CornerOrb()
    assert corner_orb.app_exe() == Path(launcher)
    orb.start()
    assert _until(lambda: orb._conn is not None), "the orb never connected"
    orb.show("listening")
    orb.show("listening")  # unchanged: not sent again
    loud = np.full(512, 0.1, dtype=np.float32)
    orb.level(loud)
    orb.level(loud)  # within 100 ms: not sent
    orb.show("thinking")
    orb.level(loud)  # not listening: no level
    orb.show("speaking")
    orb.hide()
    orb.hide()
    assert _until(lambda: got.exists() and got.read_text().count("\n") >= 5)
    lines = [json.loads(line) for line in got.read_text().splitlines()]
    assert lines == [
        {"state": "listening"},
        {"state": "listening", "level": 0.8},
        {"state": "thinking"},
        {"state": "speaking"},
        {"state": "hide"},
    ]
    orb.stop()
    assert orb._conn is None and orb.state == "hide"


def test_no_app_no_orb(tmp_path, monkeypatch):
    monkeypatch.setenv("SORA_APP_EXE", str(tmp_path / "missing.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(corner_orb, "ROOT", tmp_path)
    assert corner_orb.app_exe() is None
    monkeypatch.setenv("CORNER_ORB", "0")
    orb = corner_orb.CornerOrb()
    orb.start()
    orb.show("listening")  # nothing running, nothing breaks
    assert orb._conn is None
