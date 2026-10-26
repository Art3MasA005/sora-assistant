"""What the PC tells the phone on its own: a download finished, a training run ended.

Each becomes a {"type": "pc_event", ...} message on the agent's WebSocket; the server turns it into a
notification on the phone. Both are off with DOWNLOAD_WATCH=0 / TRAINING_WATCH=0 in .env.

- Downloads: Windows reports changes in the folder (ReadDirectoryChangesW), so nothing runs while
  nothing changes. A new file counts as finished once it has a real name (no .crdownload / .part),
  no unfinished twin beside it, and has stopped changing for a few seconds.
- Training: a cheap look at the process list once a minute; command lines are read only when a new
  python process appears. A training run that was running and is gone has finished.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("sora-pc-agent")

TEMP_SUFFIXES = (".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload")
SETTLE = 3.0  # seconds a new download must stay unchanged
REPORT_AGAIN_AFTER = 600.0  # the same name and size again within this is the same download
TRAINING_CHECK = 60.0

FILE_ACTION_ADDED, FILE_ACTION_MODIFIED, FILE_ACTION_RENAMED_NEW_NAME = 1, 3, 5


# ---------------------------------------------------------------- downloads (pure)


def parse_notify(data: bytes) -> list[tuple[int, str]]:
    """(action, file name) from ReadDirectoryChangesW's FILE_NOTIFY_INFORMATION records."""
    out, offset = [], 0
    while offset + 12 <= len(data):
        nxt, action, length = struct.unpack_from("<III", data, offset)
        out.append((action, data[offset + 12:offset + 12 + length].decode("utf-16-le", errors="replace")))
        if not nxt:
            break
        offset += nxt
    return out


class DownloadTracker:
    def __init__(self, folder: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self.folder = folder
        self.clock = clock
        self.pending: dict[str, tuple[float, int]] = {}  # name -> (last change, size then)
        self.reported: dict[str, tuple[int, float]] = {}  # name -> (size, when)

    def changed(self, action: int, name: str) -> None:
        if action not in (FILE_ACTION_ADDED, FILE_ACTION_MODIFIED, FILE_ACTION_RENAMED_NEW_NAME):
            return
        if "\\" in name or "/" in name or name.lower().endswith(TEMP_SUFFIXES) or name.lower() == "desktop.ini":
            return
        self.pending[name] = (self.clock(), self._size(name))

    def _size(self, name: str) -> int:
        try:
            return (self.folder / name).stat().st_size
        except OSError:
            return -1

    def due(self) -> list[dict]:
        """The downloads that finished since last asked."""
        now, done = self.clock(), []
        for name, (changed_at, size) in list(self.pending.items()):
            if now - changed_at < SETTLE:
                continue
            path, current = self.folder / name, self._size(name)
            if current <= 0 or not path.is_file():
                del self.pending[name]  # gone, or an empty placeholder (Firefox makes one first)
                continue
            if current != size or any((self.folder / (name + s)).exists() for s in TEMP_SUFFIXES):
                self.pending[name] = (now, current)  # still being written
                continue
            del self.pending[name]
            before = self.reported.get(name)
            if before and before[0] == current and now - before[1] < REPORT_AGAIN_AFTER:
                continue
            self.reported[name] = (current, now)
            done.append({"event": "download_done", "name": name, "size": current})
        for name, (_, at) in list(self.reported.items()):
            if now - at > REPORT_AGAIN_AFTER:
                del self.reported[name]
        return done


# ---------------------------------------------------------------- training runs (pure)


class TrainingWatch:
    def __init__(self) -> None:
        self.running: dict[int, str] = {}  # pid -> command of a training run being watched
        self.python_seen: set[int] = set()

    def step(self, python_pids: set[int], describe: Callable[[], list[dict]]) -> list[dict]:
        """[python_pids]: the python processes now; [describe] reads their command lines (slower:
        only called when a new python process appeared). Returns the runs that have ended."""
        ended = [{"event": "training_done", "pid": pid, "command": cmd}
                 for pid, cmd in self.running.items() if pid not in python_pids]
        for e in ended:
            del self.running[e["pid"]]
        if python_pids - self.python_seen:
            for proc in describe():
                if proc.get("pid") in python_pids:
                    self.running[proc["pid"]] = proc.get("command") or ""
        self.python_seen = set(python_pids)
        return ended


# ---------------------------------------------------------------- Windows


def _watch_folder(folder: Path, on_change: Callable[[int, str], None]) -> None:
    """Blocks, calling on_change for each change Windows reports in [folder] (not its subfolders)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.BOOL,
                                               wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
                                               wintypes.LPVOID]
    # FILE_LIST_DIRECTORY, share everything, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS (needed for a folder)
    handle = kernel32.CreateFileW(str(folder), 0x0001, 0x7, None, 3, 0x02000000, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        log.warning("cannot watch %s for finished downloads", folder)
        return
    buf = ctypes.create_string_buffer(64 * 1024)
    got = wintypes.DWORD()
    try:
        # FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_SIZE
        while kernel32.ReadDirectoryChangesW(handle, buf, len(buf), False, 0x1 | 0x8, ctypes.byref(got), None, None):
            for action, name in parse_notify(buf.raw[:got.value]):  # 0 bytes: too many at once, skipped
                on_change(action, name)
    finally:
        kernel32.CloseHandle(handle)


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def _python_pids() -> set[int]:
    """The python processes, from Windows' process snapshot (a few milliseconds, no PowerShell)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    entry = _PROCESSENTRY32W(dwSize=ctypes.sizeof(_PROCESSENTRY32W))
    pids: set[int] = set()
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() in {"python.exe", "pythonw.exe"} and entry.th32ProcessID != os.getpid():
                pids.add(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return pids


def _last_metrics() -> list[str]:
    from windows_actions import training_status

    try:
        logs = training_status({}).get("logs") or []
        return logs[0]["metrics"][-4:] if logs else []
    except Exception:
        return []


def start(report: Callable[[dict], None]) -> None:
    """Starts the watchers .env allows, in daemon threads; [report] sends an event to the server."""
    if os.environ.get("DOWNLOAD_WATCH", "1") != "0":
        downloads = Path(os.environ.get("USERPROFILE") or Path.home()) / "Downloads"
        if downloads.is_dir():
            tracker, wake, lock = DownloadTracker(downloads), threading.Event(), threading.Lock()

            def on_change(action: int, name: str) -> None:
                with lock:
                    tracker.changed(action, name)
                wake.set()

            def settle() -> None:  # asleep until something changes, then a check a second until it settles
                while True:
                    wake.wait()
                    time.sleep(1)
                    with lock:
                        for event in tracker.due():
                            report(event)
                        if not tracker.pending:
                            wake.clear()

            threading.Thread(target=_watch_folder, args=(downloads, on_change), name="sora-downloads",
                             daemon=True).start()
            threading.Thread(target=settle, name="sora-downloads-settle", daemon=True).start()

    if os.environ.get("TRAINING_WATCH", "1") != "0":
        from windows_actions import _training_processes

        def training() -> None:
            watch = TrainingWatch()
            while True:
                try:
                    for event in watch.step(_python_pids(), _training_processes):
                        event["metrics"] = _last_metrics()
                        report(event)
                except Exception as exc:
                    log.info("training watch: %s", exc)
                time.sleep(TRAINING_CHECK)

        threading.Thread(target=training, name="sora-training-watch", daemon=True).start()
