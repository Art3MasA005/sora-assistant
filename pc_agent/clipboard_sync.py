"""The PC's half of the shared phone/PC clipboard (see backend/sora/services/clipboard.py).

Watches the Windows clipboard; text or an image (a screenshot, Snipping Tool) copied here goes to the
Sora server, which puts it on the phone's clipboard. What the phone copies comes back as the
clipboard_set / clipboard_image actions.
Copies a password manager marks as private (ExcludeClipboardContentFromMonitorProcessing, or
CanIncludeInClipboardHistory = 0) are left alone.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes

log = logging.getLogger("sora-clipboard")

CF_UNICODETEXT = 13
MAX_TEXT = 20000

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

EXCLUDE = user32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
HISTORY_OK = user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")

_put_by_sora = ""  # the text Sora itself last put here (from the phone): not sent back
_image_seq = -1  # the clipboard's sequence number right after Sora put an image there
MAX_PNG = 12 * 1024 * 1024


def remember(text: str) -> None:
    global _put_by_sora
    _put_by_sora = text


def remember_image() -> None:
    global _image_seq
    _image_seq = user32.GetClipboardSequenceNumber()


def read_png() -> bytes | None:
    """The clipboard's image as PNG, or None (no image, or marked private)."""
    if user32.IsClipboardFormatAvailable(EXCLUDE):
        return None
    try:
        import io

        from PIL import Image, ImageGrab

        image = ImageGrab.grabclipboard()
        if not isinstance(image, Image.Image):  # nothing, or files copied in Explorer
            return None
        for _ in range(4):
            buf = io.BytesIO()
            image.save(buf, "PNG")
            if buf.tell() <= MAX_PNG:
                return buf.getvalue()
            image = image.resize((image.width // 2, image.height // 2))
    except Exception as exc:
        log.info("clipboard image not read: %s", exc)
    return None


def read_text() -> str | None:
    """The clipboard's text, or None (no text, private, or busy)."""
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return None
    try:
        if user32.IsClipboardFormatAvailable(EXCLUDE):
            return None
        if user32.IsClipboardFormatAvailable(HISTORY_OK):
            handle = user32.GetClipboardData(HISTORY_OK)
            ptr = kernel32.GlobalLock(handle) if handle else None
            if ptr:
                private = ctypes.c_uint32.from_address(ptr).value == 0
                kernel32.GlobalUnlock(handle)
                if private:
                    return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _watch(server: str, token: str) -> None:
    import httpx

    http = httpx.Client(base_url=server.rstrip("/"), timeout=15, headers={"Authorization": f"Bearer {token}"})
    seen = user32.GetClipboardSequenceNumber()  # what's on it at start-up isn't new
    while True:
        time.sleep(0.5)
        seq = user32.GetClipboardSequenceNumber()
        if seq == seen:
            continue
        seen = seq
        if seq == _image_seq:
            continue  # the image Sora itself just put here
        time.sleep(0.1)  # let the app finish writing every format
        text = read_text()
        try:
            if text is not None:
                if text.strip() and text != _put_by_sora:
                    http.post("/api/clipboard", json={"text": text[:MAX_TEXT]})
            elif (png := read_png()) is not None:
                http.post("/api/clipboard/image", data={"name": "pc-image.png"},
                          files={"image": ("pc-image.png", png, "image/png")}, timeout=60)
        except Exception as exc:
            log.info("clipboard not sent: %s", exc)


def start(server: str, token: str) -> threading.Thread:
    thread = threading.Thread(target=_watch, args=(server, token), name="sora-clipboard", daemon=True)
    thread.start()
    return thread
