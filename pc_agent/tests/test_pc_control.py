"""Item 4's logic on the PC agent: files in the owner's folders, shortcuts, finding a window, typing,
and the download and training watchers. Windows calls (Recycle Bin, SendInput...) are stubbed."""

from __future__ import annotations

import io
import os
import struct
import zipfile
from pathlib import Path

import pytest

import file_actions as fa
import pc_settings
import watchers
import window_control as wc
from windows_actions import ActionError


@pytest.fixture
def recycled(monkeypatch) -> list[Path]:
    """What went to the "Recycle Bin" (here: deleted, and remembered)."""
    sent: list[Path] = []

    def to_bin(path: Path) -> None:
        sent.append(path)
        if path.is_dir():
            import shutil

            shutil.rmtree(path)
        else:
            path.unlink()

    monkeypatch.setattr(fa, "_to_recycle_bin", to_bin)
    return sent


@pytest.fixture
def home(tmp_path, monkeypatch, recycled):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("PROJECT_DIRS", raising=False)
    monkeypatch.delenv("OneDrive", raising=False)
    for name in fa.OWNER_FOLDERS:
        (tmp_path / name).mkdir()
    return tmp_path


# ---------------------------------------------------------------- files


def test_only_the_owners_folders(home, tmp_path, monkeypatch):
    (home / "Downloads" / "a.pdf").write_text("x")
    assert fa.resolve("Downloads/a.pdf") == (home / "Downloads" / "a.pdf").resolve()
    assert fa.resolve("downloads\\a.pdf".replace("\\", os.sep)) == (home / "Downloads" / "a.pdf").resolve()
    assert fa.resolve(str(home / "Downloads" / "a.pdf")) == (home / "Downloads" / "a.pdf").resolve()
    for outside in ("/etc/passwd", str(home / "AppData" / "x"), "Downloads/../../etc"):
        with pytest.raises(ActionError, match="outside your own folders"):
            fa.resolve(outside, must_exist=False)
    with pytest.raises(ActionError, match="does not exist"):
        fa.resolve("Documents/missing.txt")
    project = tmp_path.parent / "proj"
    project.mkdir(exist_ok=True)
    monkeypatch.setenv("PROJECT_DIRS", str(project))
    assert fa.resolve(str(project), must_exist=True) == project.resolve()


def test_nothing_is_replaced_without_value_1(home, recycled):
    src, dst = home / "Downloads" / "a.txt", home / "Documents" / "a.txt"
    src.write_text("new")
    dst.write_text("old")
    with pytest.raises(ActionError, match="value=1"):
        fa.file_copy({"target": "Downloads/a.txt", "text": "Documents"})
    assert dst.read_text() == "old"
    assert "copied" in fa.file_copy({"target": "Downloads/a.txt", "text": "Documents", "value": 1})
    assert dst.read_text() == "new" and recycled == [dst.resolve()]  # the old one went to the bin

    fa.file_move({"target": "Downloads/a.txt", "text": "Pictures/b.txt"})
    assert not src.exists() and (home / "Pictures" / "b.txt").read_text() == "new"

    (home / "Pictures" / "c.txt").write_text("c")
    with pytest.raises(ActionError, match="already exists"):
        fa.file_rename({"target": "Pictures/b.txt", "text": "c.txt"})
    with pytest.raises(ActionError, match="plain file name"):
        fa.file_rename({"target": "Pictures/b.txt", "text": "../evil.txt"})
    fa.file_rename({"target": "Pictures/b.txt", "text": "d.txt"})
    assert (home / "Pictures" / "d.txt").exists()

    with pytest.raises(ActionError, match="whole top folder"):
        fa.file_delete({"target": "Documents"})
    fa.file_delete({"target": "Pictures/d.txt"})
    assert recycled[-1] == (home / "Pictures" / "d.txt").resolve()


def test_zip_and_a_zip_that_would_escape(home):
    folder = home / "Documents" / "thesis"
    folder.mkdir()
    (folder / "ch1.md").write_text("one")
    (folder / "ch2.md").write_text("two")
    assert "2 file(s)" in fa.file_zip({"target": "Documents/thesis"})
    zip_path = home / "Documents" / "thesis.zip"
    with zipfile.ZipFile(zip_path) as z:
        assert sorted(z.namelist()) == ["thesis/ch1.md", "thesis/ch2.md"]
    fa.file_unzip({"target": "Documents/thesis.zip", "text": "Downloads/out"})
    assert (home / "Downloads" / "out" / "thesis" / "ch1.md").read_text() == "one"
    with pytest.raises(ActionError, match="value=1"):
        fa.file_unzip({"target": "Documents/thesis.zip", "text": "Downloads/out"})

    evil = home / "Downloads" / "evil.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../escaped.txt", "gotcha")
    evil.write_bytes(buf.getvalue())
    with pytest.raises(ActionError, match="outside"):
        fa.file_unzip({"target": "Downloads/evil.zip"})
    assert not (home / "escaped.txt").exists()


def test_tidy_downloads_leaves_unfinished_and_new_files(home):
    d = home / "Downloads"
    old = os.path.getmtime(d) - 3600
    for name in ("photo.JPG", "notes.pdf", "setup.exe", "data.zip", "weird.xyz", "photo (1).jpg", "desktop.ini",
                 "movie.mp4.crdownload"):
        (d / name).write_text(name)
        os.utime(d / name, (old, old))
    (d / "Images").mkdir()
    (d / "Images" / "notes.pdf").write_text("unrelated")  # a name already taken elsewhere is fine
    (d / "just-now.pdf").write_text("fresh")
    result = fa.tidy_downloads({})
    assert result["moved"] == {"Images": 2, "Documents": 1, "Installers": 1, "Archives": 1, "Other": 1}
    assert (d / "Images" / "photo.JPG").exists() and (d / "Other" / "weird.xyz").exists()
    for stays in ("desktop.ini", "movie.mp4.crdownload", "just-now.pdf"):
        assert (d / stays).exists()


# ---------------------------------------------------------------- shortcuts, windows, typing


def test_shortcuts():
    assert wc.parse_hotkey("ctrl+s") == [0x11, ord("S")]
    assert wc.parse_hotkey("Ctrl + Shift + T") == [0x11, 0x10, ord("T")]
    assert wc.parse_hotkey("alt f4") == [0x12, 0x73]
    assert wc.parse_hotkey("win+left") == [0x5B, 0x25]
    for bad in ("", "ctrl+banana", "a+b+c"):
        with pytest.raises(ActionError):
            wc.parse_hotkey(bad)


def test_finding_a_window():
    windows = [
        {"hwnd": 1, "title": "Inbox - Gmail - Google Chrome", "app": "chrome", "minimized": False},
        {"hwnd": 2, "title": "train.py - sora - Visual Studio Code", "app": "Code", "minimized": False},
        {"hwnd": 3, "title": "Untitled - Notepad", "app": "notepad", "minimized": True},
    ]
    assert wc.pick_window(windows, "vs code")["hwnd"] == 2  # the app's alias
    assert wc.pick_window(windows, "gmail")["hwnd"] == 1  # part of the title
    assert wc.pick_window(windows, "Notepad")["hwnd"] == 3
    with pytest.raises(ActionError, match="open: chrome, Code, notepad"):
        wc.pick_window(windows, "photoshop")


def test_typing_any_language():
    events = wc.text_events("আমি\nok")
    units = [scan for _, scan, flags in events if flags == wc.KEYEVENTF_UNICODE]
    assert "".join(map(chr, units)) == "আমিok"
    assert (wc.VK_RETURN, 0, 0) in events
    assert len(wc.text_events("😀")) == 4  # a surrogate pair: two units, down and up each


# ---------------------------------------------------------------- settings


def test_brightness_and_switch_values():
    assert pc_settings.brightness_level({"value": 130}, 50) == 100
    assert pc_settings.brightness_level({"target": "down"}, 5) == 0
    assert pc_settings.brightness_level({"target": "up"}, None) is None
    assert pc_settings.brightness_level({}, 70) is None  # just tell
    assert pc_settings._on_off({"value": 0}) == "Off" and pc_settings._on_off({"target": "on"}) == "On"
    assert pc_settings._on_off({}) == ""


# ---------------------------------------------------------------- watchers


def _notify(*records: tuple[int, str]) -> bytes:
    out = b""
    for i, (action, name) in enumerate(records):
        data = name.encode("utf-16-le")
        body = struct.pack("<III", 0, action, len(data)) + data
        body += b"\0" * (-len(body) % 4)
        if i < len(records) - 1:
            body = struct.pack("<I", len(body)) + body[4:]
        out += body
    return out


def test_reading_windows_change_records():
    assert watchers.parse_notify(_notify((1, "a.pdf"), (5, "রিপোর্ট.pdf"))) == [(1, "a.pdf"), (5, "রিপোর্ট.pdf")]
    assert watchers.parse_notify(b"") == []


def test_a_download_counts_once_it_has_settled(tmp_path):
    now = [0.0]
    t = watchers.DownloadTracker(tmp_path, clock=lambda: now[0])
    (tmp_path / "big.iso.crdownload").write_text("x")
    t.changed(watchers.FILE_ACTION_ADDED, "big.iso.crdownload")  # still downloading: ignored
    assert not t.pending

    (tmp_path / "big.iso.crdownload").rename(tmp_path / "big.iso")  # Chrome renames it when done
    t.changed(watchers.FILE_ACTION_RENAMED_NEW_NAME, "big.iso")
    assert t.due() == []  # not settled yet
    now[0] = 4
    assert t.due() == [{"event": "download_done", "name": "big.iso", "size": 1}]
    t.changed(watchers.FILE_ACTION_MODIFIED, "big.iso")
    now[0] = 8
    assert t.due() == []  # the same file again: reported once

    (tmp_path / "f.zip").write_text("")  # Firefox's empty placeholder, with the real data in .part
    (tmp_path / "f.zip.part").write_text("abc")
    t.changed(watchers.FILE_ACTION_ADDED, "f.zip")
    now[0] = 12
    assert t.due() == [] and "f.zip" not in t.pending  # empty: not a download yet
    (tmp_path / "g.pdf").write_text("abc")
    (tmp_path / "g.pdf.part").write_text("more")
    t.changed(watchers.FILE_ACTION_ADDED, "g.pdf")
    now[0] = 16
    assert t.due() == [] and "g.pdf" in t.pending  # its unfinished twin is still there
    (tmp_path / "g.pdf.part").unlink()
    now[0] = 20
    assert [e["name"] for e in t.due()] == ["g.pdf"]


def test_a_training_run_that_ends_is_reported():
    w = watchers.TrainingWatch()
    looked: list[int] = []

    def describe():
        looked.append(1)
        return [{"pid": 10, "command": "train.py --fold 0"}]

    assert w.step({10, 20}, describe) == [] and len(looked) == 1
    assert w.step({10, 20}, describe) == [] and len(looked) == 1  # no new python: no slow look
    assert w.step({20}, describe) == [{"event": "training_done", "pid": 10, "command": "train.py --fold 0"}]
    assert w.step({20}, describe) == []


def test_every_pc_action_the_server_knows_exists_here():
    import re
    import sys
    import typing

    import windows_actions

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from sora.agent.tools.device_tools import PcActionName

    agent = (Path(__file__).resolve().parents[1] / "sora_pc_agent.py").read_text(encoding="utf-8")
    local = set(re.findall(r'"(\w+)":', re.search(r"LOCAL_ACTIONS = \{(.*?)\}", agent, re.S).group(1)))
    missing = set(typing.get_args(PcActionName)) - set(windows_actions.ACTIONS) - local
    assert not missing, missing
    assert windows_actions.ACTIONS["tidy_downloads"].__name__ == "tidy_downloads"  # loaded on first use


def test_every_setting_the_agent_reads_can_come_from_env():
    import re

    root = Path(__file__).resolve().parents[1]
    agent = (root / "sora_pc_agent.py").read_text(encoding="utf-8")
    from_env = set(re.findall(r'"(\w+)"', re.search(r"ENV_KEYS = \((.*?)\)", agent, re.S).group(1)))
    read = {key for f in root.glob("*.py") for key in re.findall(r'os\.environ\.get\("([A-Z_]+)"', f.read_text(encoding="utf-8"))}
    windows_own = {"APPDATA", "COMPUTERNAME", "LOCALAPPDATA", "PUBLIC", "USERPROFILE"}
    assert read - windows_own <= from_env, read - windows_own - from_env
