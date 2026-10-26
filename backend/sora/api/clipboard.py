"""The shared phone/PC clipboard (see services/clipboard.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sora.api.deps import current_device
from sora.models import Device
from sora.services import clipboard

router = APIRouter(prefix="/api/clipboard", tags=["clipboard"])

MAX_IMAGE = 15 * 1024 * 1024


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=clipboard.MAX_TEXT)


class SyncIn(BaseModel):
    enabled: bool


@router.get("")
async def list_clipboard(device: Device = Depends(current_device)):
    """Newest first: {id, kind: text|image, text | name, from: phone|pc, device, at}."""
    return {"enabled": await clipboard.enabled(), "items": clipboard.history()}


@router.post("")
async def copied_text(body: TextIn, device: Device = Depends(current_device)):
    """Something was copied on this device: put it on the other one's clipboard."""
    return {"item": await clipboard.add(device, text=body.text)}


@router.post("/image")
async def copied_image(image: UploadFile = File(...), name: str = Form(""), device: Device = Depends(current_device)):
    """A new screenshot (or image) on the phone: put it on the PC's clipboard."""
    data = await image.read(MAX_IMAGE + 1)
    if not data or len(data) > MAX_IMAGE:
        raise HTTPException(413 if data else 400, "the image is empty or larger than 15 MB")
    return {"item": await clipboard.add(device, png=data, name=name or image.filename or "")}


@router.delete("", status_code=204)
async def clear_clipboard(device: Device = Depends(current_device)):
    """Empties the history (what is on the clipboards themselves stays)."""
    clipboard.clear()


@router.delete("/{item_id}", status_code=204)
async def delete_clipboard_item(item_id: str, device: Device = Depends(current_device)):
    if not clipboard.remove(item_id):
        raise HTTPException(404, "that item is no longer in the history")


@router.get("/{item_id}/image")
async def clipboard_image(item_id: str, device: Device = Depends(current_device)):
    item = clipboard.get(item_id)
    if item is None or item["kind"] != "image" or not clipboard.image_path(item).is_file():
        raise HTTPException(404, "not found")
    return FileResponse(clipboard.image_path(item), media_type="image/png")


@router.post("/{item_id}/copy")
async def copy_again(item_id: str, device: Device = Depends(current_device)):
    """Puts an item from the history on the PC's clipboard again (the Windows app's copy button)."""
    item = clipboard.get(item_id)
    if item is None:
        raise HTTPException(404, "that item is no longer in the history")
    pcs = await clipboard.pc_ids()
    if not pcs:
        raise HTTPException(409, "the PC agent isn't running")
    try:
        await clipboard.put_on(pcs[0], item)
    except Exception as exc:
        raise HTTPException(502, f"couldn't copy it: {exc}") from exc
    return {"ok": True}


@router.get("/settings")
async def clipboard_settings(device: Device = Depends(current_device)):
    return {"enabled": await clipboard.enabled()}


@router.put("/settings")
async def set_clipboard_settings(body: SyncIn, device: Device = Depends(current_device)):
    await clipboard.set_enabled(body.enabled)
    return {"enabled": body.enabled}
