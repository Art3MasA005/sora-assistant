"""File operations in the owner's own folders: copy, move, rename, delete (to the Recycle Bin), zip,
unzip and tidying Downloads.

Only Desktop, Documents, Downloads, Pictures, Music, Videos and the folders in PROJECT_DIRS (.env,
separated by ;) are touched; system folders and everything else are refused. Nothing is overwritten
unless value=1, which the server only sends after the owner approved it (deleting always asks too).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

from windows_actions import ActionError

OWNER_FOLDERS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
# Still being written by a browser: never moved or reported.
TEMP_SUFFIXES = (".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload")
TIDY_GROUPS = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic", ".ico", ".tif", ".tiff"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".csv", ".odt", ".rtf",
                  ".epub"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Installers": {".exe", ".msi", ".msix", ".appx", ".apk"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"},
    "Music": {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"},
    "Code": {".py", ".ipynb", ".js", ".ts", ".dart", ".java", ".c", ".cpp", ".json", ".yaml", ".yml", ".html", ".css"},
}
TIDY_SKIP_RECENT = 120  # seconds: a file this new may still be in use


def home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def allowed_roots() -> list[Path]:
    roots = [home() / name for name in OWNER_FOLDERS]
    roots += [Path(os.path.expandvars(p.strip())) for p in os.environ.get("PROJECT_DIRS", "").split(";") if p.strip()]
    # OneDrive may hold Desktop/Documents instead
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        roots += [Path(onedrive) / name for name in OWNER_FOLDERS]
    return [r.resolve() for r in roots]


def resolve(raw: str | None, *, must_exist: bool = True) -> Path:
    """[raw] as a path inside the owner's folders: absolute, "~/…", or starting with a folder name
    ("Downloads/report.pdf"). Anything else is refused."""
    text = (raw or "").strip().strip('"')
    if not text:
        raise ActionError("which file or folder?")
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if not path.is_absolute():
        first, *rest = path.parts
        named = next((home() / f for f in OWNER_FOLDERS if f.lower() == first.lower()), None)
        path = named.joinpath(*rest) if named else home() / path
    path = path.resolve()
    if not any(path == root or root in path.parents for root in allowed_roots()):
        raise ActionError(f"{path} is outside your own folders (Desktop, Documents, Downloads, Pictures, Music, "
                          "Videos, PROJECT_DIRS), so Sora won't touch it")
    if must_exist and not path.exists():
        raise ActionError(f"{path} does not exist")
    return path


def _destination(src: Path, raw: str | None, overwrite: bool) -> Path:
    """Where [src] goes: into [raw] if it is a folder, else to [raw] itself."""
    dst = resolve(raw, must_exist=False)
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists() and not overwrite:
        raise ActionError(f"{dst} already exists; to replace it, ask the owner and call again with value=1")
    if dst == src:
        raise ActionError("that is the same place")
    return dst


def _overwrite(params: dict) -> bool:
    return str(params.get("value") or "0") == "1"


def file_copy(params: dict) -> str:
    src = resolve(params.get("target"))
    dst = _destination(src, params.get("text"), _overwrite(params))
    if dst.exists():
        _to_recycle_bin(dst)  # replaced (the owner approved): the old one can still be restored
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return f"copied to {dst}"


def file_move(params: dict) -> str:
    src = resolve(params.get("target"))
    dst = _destination(src, params.get("text"), _overwrite(params))
    if dst.exists():
        _to_recycle_bin(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"moved to {dst}"


def file_rename(params: dict) -> str:
    src = resolve(params.get("target"))
    name = (params.get("text") or "").strip()
    if not name or any(c in name for c in '\\/:*?"<>|'):
        raise ActionError("the new name must be a plain file name")
    dst = src.with_name(name)
    if dst.exists() and not _overwrite(params):
        raise ActionError(f"{dst.name} already exists there; to replace it, ask the owner and call again with value=1")
    if dst.exists():
        _to_recycle_bin(dst)
    src.rename(dst)
    return f"renamed to {dst.name}"


def file_delete(params: dict) -> str:
    path = resolve(params.get("target"))
    if path in allowed_roots():
        raise ActionError("refusing to delete a whole top folder")
    _to_recycle_bin(path)
    return f"moved {path.name} to the Recycle Bin"


def file_zip(params: dict) -> str:
    """target: a file or folder (or several, separated by ;); text: the zip to make (default: next to the first)."""
    sources = [resolve(p) for p in (params.get("target") or "").split(";") if p.strip()]
    if not sources:
        raise ActionError("zip what?")
    raw = params.get("text") or str(sources[0].with_suffix(".zip"))
    zip_path = resolve(raw if raw.lower().endswith(".zip") else raw + ".zip", must_exist=False)
    if zip_path.exists() and not _overwrite(params):
        raise ActionError(f"{zip_path} already exists; to replace it, ask the owner and call again with value=1")
    if zip_path.exists():
        _to_recycle_bin(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for src in sources:
            if src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file() and f != zip_path:
                        z.write(f, f.relative_to(src.parent))
                        count += 1
            else:
                z.write(src, src.name)
                count += 1
    return f"zipped {count} file(s) into {zip_path}"


def file_unzip(params: dict) -> str:
    """target: the zip; text: the folder to unpack into (default: a folder named after the zip)."""
    zip_path = resolve(params.get("target"))
    dst = resolve(params.get("text") or str(zip_path.with_suffix("")), must_exist=False)
    overwrite = _overwrite(params)
    with zipfile.ZipFile(zip_path) as z:
        members = z.infolist()
        replaced = []
        for m in members:
            out = (dst / m.filename).resolve()
            if dst not in out.parents and out != dst:
                raise ActionError(f"refusing {zip_path.name}: it would write outside {dst} ({m.filename})")
            if out.exists() and not out.is_dir():
                if not overwrite:
                    raise ActionError(f"{out} already exists; to replace files, ask the owner and call again with value=1")
                replaced.append(out)
        for old in replaced:
            _to_recycle_bin(old)
        dst.mkdir(parents=True, exist_ok=True)
        z.extractall(dst)
    return f"unpacked {len(members)} item(s) into {dst}"


def _group(path: Path) -> str:
    ext = path.suffix.lower()
    return next((group for group, exts in TIDY_GROUPS.items() if ext in exts), "Other")


def tidy_downloads(params: dict) -> dict:
    """Sorts the loose files in Downloads into Images, Documents, Archives… folders. Files still
    downloading or used in the last two minutes stay; a name already taken gets " (2)"."""
    downloads = home() / "Downloads"
    if not downloads.is_dir():
        raise ActionError("there is no Downloads folder")
    moved: dict[str, int] = {}
    now = time.time()
    for f in downloads.iterdir():
        if not f.is_file() or f.name.startswith(".") or f.name.lower() == "desktop.ini" \
                or f.name.lower().endswith(TEMP_SUFFIXES):
            continue
        if now - f.stat().st_mtime < TIDY_SKIP_RECENT:
            continue
        group = _group(f)
        folder = downloads / group
        folder.mkdir(exist_ok=True)
        target, n = folder / f.name, 2
        while target.exists():
            target = folder / f"{f.stem} ({n}){f.suffix}"
            n += 1
        shutil.move(str(f), str(target))
        moved[group] = moved.get(group, 0) + 1
    return {"moved": moved, "total": sum(moved.values())}


# ---------------------------------------------------------------- the Recycle Bin


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int), ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def _to_recycle_bin(path: Path) -> None:
    """Deletes [path] the way Explorer does, so it can be restored (no extra package needed)."""
    if sys.platform != "win32":
        raise ActionError("the Recycle Bin is only on Windows")
    FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 3, 0x40, 0x10, 0x4, 0x400
    op = _SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=str(path) + "\0",  # double-NUL-terminated list
                          fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0 or op.fAnyOperationsAborted:
        raise ActionError(f"could not move {path.name} to the Recycle Bin")
