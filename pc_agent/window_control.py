"""Windows on the PC: list them, bring one to the front, minimize, maximize, snap it to a half of the
screen; and type text or press a shortcut in whatever is in front. ctypes (user32) only.

A window is named by its title or its app ("chrome", "vs code"); the most recently used match wins.
"""

from __future__ import annotations

import ctypes
import difflib
import os
import re
import time
from ctypes import wintypes

from windows_actions import PROCESS_ALIASES, ActionError

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
GWL_EXSTYLE, WS_EX_TOOLWINDOW = -20, 0x00000080
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
INPUT_KEYBOARD, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 1, 0x1, 0x2, 0x4
# Keys a program could otherwise take for the number pad's (arrows, Home, Delete...), and Win.
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B}
VK_MENU, VK_RETURN = 0x12, 0x0D

MODIFIERS = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B, "cmd": 0x5B}
NAMED_KEYS = {
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "printscreen": 0x2C,
    "prtsc": 0x2C, "capslock": 0x14, "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE, "dot": 0xBE,
    "slash": 0xBF, "backslash": 0xDC, "semicolon": 0xBA, "quote": 0xDE, "backtick": 0xC0, "grave": 0xC0,
    "bracketleft": 0xDB, "bracketright": 0xDD, ",": 0xBC, ".": 0xBE, "/": 0xBF, ";": 0xBA, "-": 0xBD, "=": 0xBB,
}
MAX_TYPED = 5000


# ---------------------------------------------------------------- shortcuts (pure)


def parse_hotkey(keys: str) -> list[int]:
    """"ctrl+shift+s" → virtual-key codes, modifiers first. Raises ActionError for an unknown key."""
    parts = [p for p in re.split(r"\s*\+\s*|\s+", (keys or "").strip().lower()) if p]
    if not parts:
        raise ActionError("which keys? e.g. ctrl+s")
    mods, rest = [], []
    for p in parts:
        if p in MODIFIERS:
            if MODIFIERS[p] not in mods:
                mods.append(MODIFIERS[p])
        elif p in NAMED_KEYS:
            rest.append(NAMED_KEYS[p])
        elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", p):
            rest.append(0x70 + int(p[1:]) - 1)
        elif re.fullmatch(r"[a-z0-9]", p):
            rest.append(ord(p.upper()))
        else:
            raise ActionError(f"unknown key '{p}'")
    if len(rest) > 2:
        raise ActionError("a shortcut has at most two keys besides ctrl/shift/alt/win")
    return mods + rest


# ---------------------------------------------------------------- finding a window (pure)


def pick_window(windows: list[dict], target: str) -> dict:
    """The window [target] names among [windows] (front-most first, as Windows lists them): by app
    ("chrome", "vs code") or by part of the title; failing that, the closest title."""
    want = (target or "").strip().lower()
    if not want:
        raise ActionError("which window?")
    process = PROCESS_ALIASES.get(want, want).lower().removesuffix(".exe")
    for match in (
        lambda w: w["app"].lower() == process,
        lambda w: want in w["title"].lower(),
        lambda w: process in w["app"].lower(),
    ):
        found = [w for w in windows if match(w)]
        if found:
            return found[0]
    titles = [w["title"] for w in windows]
    close = difflib.get_close_matches(target, titles, n=1, cutoff=0.5)
    if close:
        return next(w for w in windows if w["title"] == close[0])
    shown = ", ".join(dict.fromkeys(f"{w['app']}" for w in windows[:12]))
    raise ActionError(f"no open window matches '{target}'" + (f"; open: {shown}" if shown else ""))


# ---------------------------------------------------------------- Windows calls


def _user32():
    return ctypes.windll.user32


def _process_name(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.splitext(os.path.basename(buf.value))[0]
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _cloaked(hwnd: int) -> bool:
    """Hidden by Windows itself (a suspended Store app, another virtual desktop)."""
    value = ctypes.c_int(0)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return bool(value.value)


def _windows() -> list[dict]:
    """The windows on the taskbar, front-most first."""
    user32 = _user32()
    found: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0 or _cloaked(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append({"hwnd": hwnd, "title": buf.value, "app": _process_name(pid.value),
                      "minimized": bool(user32.IsIconic(hwnd))})
        return True

    user32.EnumWindows(each, 0)
    return found


def _front(hwnd: int) -> None:
    """Brings [hwnd] to the front. Windows only lets the app in front do that, so an Alt tap first
    (the usual way around it for a helper the owner asked)."""
    user32 = _user32()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)


def window_list(params: dict) -> list[dict]:
    return [{"title": w["title"], "app": w["app"], "minimized": w["minimized"]} for w in _windows()[:40]]


def window_focus(params: dict) -> str:
    w = pick_window(_windows(), params.get("target") or "")
    _front(w["hwnd"])
    return f"{w['title']} is in front"


def window_minimize(params: dict) -> str:
    w = pick_window(_windows(), params.get("target") or "")
    _user32().ShowWindow(w["hwnd"], SW_MINIMIZE)
    return f"minimized {w['title']}"


def window_maximize(params: dict) -> str:
    w = pick_window(_windows(), params.get("target") or "")
    _user32().ShowWindow(w["hwnd"], SW_MAXIMIZE)
    _front(w["hwnd"])
    return f"maximized {w['title']}"


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def window_snap(params: dict) -> str:
    """target: the window; text: left or right. Fills that half of its screen's work area."""
    side = (params.get("text") or "left").strip().lower()
    if side not in {"left", "right"}:
        raise ActionError("snap to the left or the right?")
    w = pick_window(_windows(), params.get("target") or "")
    user32, hwnd = _user32(), w["hwnd"]
    user32.ShowWindow(hwnd, SW_RESTORE)
    info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))  # MONITOR_DEFAULTTONEAREST
    work = info.rcWork
    half = (work.right - work.left) // 2
    x = work.left if side == "left" else work.left + half
    # Windows 10/11 frames have invisible borders: grow by them so the visible edges meet the screen's.
    outer, visible = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(visible),
                                               ctypes.sizeof(visible))
    left, right = visible.left - outer.left, outer.right - visible.right
    bottom = outer.bottom - visible.bottom
    user32.SetWindowPos(hwnd, 0, x - left, work.top, half + left + right, work.bottom - work.top + bottom, 0x0004)
    _front(hwnd)
    return f"{w['title']} is on the {side} half"


# ---------------------------------------------------------------- typing


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):  # only so the union has its real size
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    return _INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=_KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)))


def _send(events: list[_INPUT]) -> None:
    array = (_INPUT * len(events))(*events)
    if _user32().SendInput(len(events), array, ctypes.sizeof(_INPUT)) != len(events):
        raise ActionError("Windows blocked the keystrokes (an admin window may be in front)")


def text_events(text: str) -> list[tuple[int, int, int]]:
    """(vk, scan, flags) for typing [text]: each UTF-16 unit as a Unicode key (Bangla too), new lines as Enter."""
    events = []
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            events += [(VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP)]
            continue
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            events += [(0, unit, KEYEVENTF_UNICODE), (0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    return events


def type_text(params: dict) -> str:
    """Types [text] into the window in front, as if on the keyboard."""
    text = params.get("text") or params.get("target") or ""
    if not text:
        raise ActionError("type what?")
    if len(text) > MAX_TYPED:
        raise ActionError(f"that is too long to type ({len(text)} characters; at most {MAX_TYPED})")
    events = text_events(text)
    for i in range(0, len(events), 200):  # in pieces, so a slow app keeps up
        _send([_key(*e) for e in events[i:i + 200]])
        time.sleep(0.01)
    return f"typed {len(text)} characters"


def hotkey(params: dict) -> str:
    """Presses a shortcut ("ctrl+s", "alt+tab", "win+d") in the window in front."""
    keys = params.get("target") or params.get("text") or ""
    codes = parse_hotkey(keys)
    ext = {vk: KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0 for vk in codes}
    _send([_key(vk, 0, ext[vk]) for vk in codes] + [_key(vk, 0, ext[vk] | KEYEVENTF_KEYUP) for vk in reversed(codes)])
    return f"pressed {keys}"
