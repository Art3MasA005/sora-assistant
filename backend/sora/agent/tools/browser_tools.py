"""The web browser Sora drives on the owner's PC, step by step (pc_agent/browser.py)."""

from __future__ import annotations

import base64
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from sora.agent.tools.base import ToolContext, registry
from sora.agent.tools.device_tools import _log_command, _pick_device
from sora.config import get_settings
from sora.services.hub import CommandTimeout, DeviceOffline, hub

MAX_STEPS = 15  # per request: then Sora says where it got to and asks whether to go on
TIMEOUTS = {"open": 90, "read": 40, "click": 40, "fill": 40, "screenshot": 40, "download": 610, "close": 30}


class BrowserArgs(BaseModel):
    action: Literal["open", "read", "click", "fill", "screenshot", "download", "close"] = Field(
        description=(
            "open (target=web address) | read (the page's text and its buttons, links and fields, each with an id) | "
            "click (target=id) | fill (target=id of a field or list, text=what to type or the option to pick) | "
            "screenshot (shown in the chat) | download (target=file address: saved in Downloads) | close"
        )
    )
    target: str | None = Field(None, description="open/download: the web address; click/fill: the element's id from read")
    text: str | None = Field(None, description="fill: what to type; click with value=1: the button's text as read showed it")
    value: int | None = Field(
        None,
        description="open: 1 shows the window so the owner can log in or watch, 0 hides it. click: 1 only once the owner "
                    "approved pressing a button that submits, pays, buys, posts or sends (read marks those `submits`)",
    )
    device_name: str | None = Field(None, description="Which PC, if the owner has more than one.")


def _summary(a: BrowserArgs) -> str:
    if a.action == "click" and a.value == 1:
        return f"Browser: press “{a.text}” (it submits, pays, posts or sends)"
    if a.action == "fill":
        return f"Browser: type into field {a.target}: {a.text}"
    if a.action in {"open", "download"}:
        return f"Browser: {a.action} {a.target}"
    return f"Browser: {a.action} {a.target or ''}".strip()


@registry.tool(
    BrowserArgs, needs="pc", untrusted=True, summary=_summary,
    confirm=lambda a: a.action == "click" and a.value == 1,
    # A web page's text could steer these to carry data off (an address with it, typing it into a field).
    taint_guard=lambda a: a.action in {"open", "fill", "download"},
)
async def browser(ctx: ToolContext, a: BrowserArgs):
    """A web browser on the owner's PC, used step by step for sites that need clicks, a login or JavaScript.
    Read again after each click. For a plain public page use web_fetch. The owner logs in themselves in the
    visible window (open with value=1); never type passwords. A button that submits, pays, posts or sends is
    refused until the owner approves (see value)."""
    steps = ctx.extras.get("browser_steps", 0) + 1
    ctx.extras["browser_steps"] = steps
    ctx.extras["max_rounds"] = MAX_STEPS + 3  # one step a round, more than a usual request's rounds
    if steps > MAX_STEPS:
        return (f"Not done: that is {MAX_STEPS} browser steps for this request. Tell the owner where you got to "
                "and ask whether to go on.")
    device = await _pick_device(("pc_agent",), a.device_name)
    if device is None:
        return "Error: no PC agent is set up. Run the Sora PC agent on the computer first."
    action = f"browser_{a.action}"
    params = a.model_dump(include={"target", "text", "value"}, exclude_none=True)
    try:
        result = await hub.command(device.id, action, params, timeout=TIMEOUTS[a.action])
    except DeviceOffline:
        return f"Error: the PC '{device.name}' is offline (the PC agent is not running or the PC is off)."
    except CommandTimeout as exc:
        await _log_command(device.id, action, params, "timeout", None)
        return f"Error: {exc}"
    except RuntimeError as exc:
        await _log_command(device.id, action, params, "error", str(exc))
        if "unknown action" in str(exc):
            return "Error: this PC agent is older and has no browser yet; update Sora on the PC."
        return f"Error from the browser: {exc}"
    await _log_command(device.id, action, params, "ok", None)  # page text isn't kept in the log

    if a.action == "screenshot" and isinstance(result, dict) and result.get("png_base64"):
        name = f"browser-{uuid.uuid4().hex[:10]}.png"
        (get_settings().files_dir / name).write_bytes(base64.b64decode(result.pop("png_base64")))
        result["file"] = f"/api/files/{name}"
        if ctx.emit:
            await ctx.emit({"type": "attachment", "kind": "image", "url": f"/api/files/{name}"})
    return result
