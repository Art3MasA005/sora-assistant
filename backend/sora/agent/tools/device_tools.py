"""Control the owner's PC (through the PC agent) and phone (through the Android app)."""

from __future__ import annotations

import base64
import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from sora.agent.tools.base import ToolContext, registry
from sora.agent.tools.risk import risky_command
from sora.config import get_settings
from sora.db import session_scope
from sora.models import Device, DeviceCommand
from sora.services import phone_notifications
from sora.services.fcm import get_fcm
from sora.services.hub import CommandTimeout, DeviceOffline, hub
from sora.services.web import search_url, youtube_top

# Turning the PC off, ending a process, deleting: always asked. run_command asks only for a risky command (risk.py).
PC_DANGEROUS = {"shutdown", "restart", "sleep", "kill_process", "log_off", "file_delete"}
# These replace an existing file only with value=1, and then the owner is asked first.
PC_OVERWRITES = {"file_copy", "file_move", "file_rename", "file_zip", "file_unzip"}
# Asked about only while third-party content (an email, a web page...) is in the chat, so instructions
# hidden there can't install, remove or close things, type or press keys, or shuffle files on the PC.
PC_TAINT_GUARDED = {
    "open_url", "clipboard_set", "close_app", "uninstall_app", "store_install", "type_text", "hotkey",
    "tidy_downloads", "wifi", "bluetooth", "run_command", *PC_OVERWRITES,
}
# Quick actions: done without a word when they work (the turn ends with no reply).
PC_QUIET = {
    "open_app", "close_app", "open_url", "open_path", "web_search", "youtube_play", "media", "volume", "lock",
    "screenshot", "notify", "clipboard_set", "cancel_shutdown", "window_focus", "window_minimize", "window_maximize",
    "window_snap", "hotkey", "brightness", "dark_mode", "bluetooth",
}
PHONE_QUIET = {
    "open_app", "close_app", "open_url", "web_search", "youtube_play", "media", "volume", "flashlight", "navigate",
    "play_music", "open_settings", "set_alarm", "set_timer", "call", "screenshot", "lock",
}

PHONE_ONLY = {
    "call", "send_sms", "set_alarm", "set_timer", "cancel_alarm", "cancel_timer", "flashlight", "ring", "status",
    "reply_notification", "whatsapp_send",
}
# Sending on the owner's behalf: always asked first.
PHONE_CONFIRM = {"send_sms", "reply_notification", "whatsapp_send"}

_MENTIONS_PC = re.compile(r"\b(pc|computer|laptop|desktop|windows)\b|পিসি|পি\s?সি|কম্পিউটার|ল্যাপটপ|ডেস্কটপ", re.I)
_MENTIONS_PHONE = re.compile(r"\b(phone|mobile|fone|mobail)\b|ফোন|মোবাইল", re.I)


def _wrong_device(ctx: ToolContext, target: str) -> str | None:
    """Things happen on the device the owner is talking from, unless they name the other one."""
    on_phone = ctx.origin_kind == "android"
    on_pc = ctx.origin_kind in {"pc_agent", "windows"}
    if target == "pc" and on_phone and not _MENTIONS_PC.search(ctx.user_text):
        return ("Not done: the owner is talking from their phone, so do it on the phone (phone_action). "
                "Use the PC only when they say PC/computer.")
    if target == "phone" and on_pc and not _MENTIONS_PHONE.search(ctx.user_text):
        return ("Not done: the owner is talking from their PC, so do it on the PC (pc_action). "
                "Use the phone only when they say phone.")
    return None


# Seconds to wait for the PC; installs and uninstalls can take minutes.
PC_TIMEOUTS = {
    "screenshot": 60, "search_files": 60, "run_command": 130, "close_app": 45, "store_search": 70,
    "store_install": 900, "uninstall_app": 600, "installed_apps": 100, "training_status": 60,
    "file_copy": 300, "file_move": 300, "file_zip": 300, "file_unzip": 300, "tidy_downloads": 120, "type_text": 60,
    "wifi": 40, "bluetooth": 40, "brightness": 40,
}

PcActionName = Literal[
    "open_app", "close_app", "open_url", "open_path", "search_files", "web_search", "youtube_play", "media",
    "volume", "lock", "sleep", "shutdown", "restart", "cancel_shutdown", "log_off", "screenshot", "notify",
    "clipboard_get", "clipboard_set", "list_processes", "kill_process", "system_info", "run_command",
    "store_search", "store_install", "installed_apps", "uninstall_app", "training_status", "hey_sora",
    "window_list", "window_focus", "window_minimize", "window_maximize", "window_snap", "type_text", "hotkey",
    "file_copy", "file_move", "file_rename", "file_delete", "file_zip", "file_unzip", "tidy_downloads",
    "brightness", "wifi", "bluetooth", "dark_mode",
]


class PcActionArgs(BaseModel):
    action: PcActionName = Field(
        description=(
            "open_app (target=app name like 'vs code', 'chrome'); close_app (target=app name; value=1 to force-close "
            "windows that ask to save); open_url (target=url); open_path (target=file/folder); "
            "search_files (target=name fragment); web_search (target=query, text=google|youtube|bing|maps|images; "
            "only opens the search in Chrome on the PC, for when the owner asks to open or show it; to answer a "
            "question from the web use the web_search tool instead); "
            "youtube_play (target=what to play: plays the top YouTube result in Chrome); "
            "media (target=play_pause|next|previous|stop: works for YouTube/Spotify playing on the PC); "
            "volume (target=up|down|mute, value=steps); lock; sleep; shutdown (value=delay seconds); restart; "
            "cancel_shutdown; log_off; screenshot; notify (text=message); clipboard_get; clipboard_set (text); "
            "list_processes; kill_process (target=process name); system_info (RAM, disks, battery, uptime); "
            "run_command (text=PowerShell command); store_search (target=query: Microsoft Store results with ids, "
            "also shown in the Store app); store_install (target=Store id from store_search, or app name); "
            "installed_apps (target=name filter); uninstall_app (target=installed app name); "
            "training_status (the owner's model training: running jobs, GPU load, and the newest training log with "
            "epoch, loss and Dice scores; target=log folder, optional); "
            "hey_sora (value=1 turns hands-free \"Hey Sora\" listening on the PC on, value=0 off and frees the mic; "
            "no value: whether it is on); "
            "WINDOWS (target=the window's app like 'chrome' or part of its title): window_list (what is open); "
            "window_focus (bring to the front); window_minimize; window_maximize; window_snap (text=left|right half); "
            "TYPING in the window in front (focus it first): type_text (text=what to type, any language); "
            "hotkey (target=keys like 'ctrl+s', 'alt+tab', 'win+d'); "
            "FILES, only in the owner's Desktop, Documents, Downloads, Pictures, Music, Videos and project folders "
            "(paths like 'Downloads/report.pdf' or absolute): file_copy / file_move (target=from, text=to: a folder "
            "or a new path); file_rename (target=path, text=new name); file_delete (target: goes to the Recycle "
            "Bin); file_zip (target=path(s) separated by ;, text=zip to make); file_unzip (target=zip, text=folder); "
            "these never replace an existing file: if one is in the way the result says so; ask the owner, then call "
            "again with value=1; tidy_downloads (sorts loose files in Downloads into Images, Documents, Archives... "
            "folders); SETTINGS: brightness (value=0-100, or target=up|down; none: current); wifi / bluetooth "
            "(value=1 on, 0 off; none: current); dark_mode (value=1 dark, 0 light; none: current)"
        )
    )
    target: str | None = None
    text: str | None = None
    value: int | None = None
    device_name: str | None = Field(None, description="Which PC, if the owner has more than one.")


async def _pick_device(kinds: tuple[str, ...], name: str | None) -> Device | None:
    async with session_scope() as session:
        devices = list(
            (await session.execute(select(Device).where(Device.kind.in_(kinds), Device.revoked.is_(False)))).scalars()
        )
    if name:
        wanted = name.lower()
        devices = [d for d in devices if wanted in d.name.lower()] or devices
    online = [d for d in devices if hub.is_online(d.id)]
    # The first kind listed wins (the PC agent, not the Sora desktop app on the same PC).
    rank = lambda d: kinds.index(d.kind) if d.kind in kinds else len(kinds)  # noqa: E731
    return (sorted(online, key=rank) or sorted(devices, key=rank) or [None])[0]


async def _log_command(device_id: uuid.UUID | None, action: str, params: dict, status: str, result) -> None:
    async with session_scope() as session:
        session.add(DeviceCommand(device_id=device_id, action=action, params=params, status=status, result=result))


def _pc_summary(a: PcActionArgs) -> str:
    detail = a.target or a.text or (str(a.value) if a.value is not None else "")
    return f"PC: {a.action.replace('_', ' ')} {detail}".strip()


def _pc_confirms(a: PcActionArgs) -> bool:
    # Replacing a file, Wi-Fi off (it can cut the PC off from the phone and from Sora itself), and a
    # PowerShell command that deletes, turns off or kills something; an ordinary one just runs.
    return (a.action in PC_DANGEROUS or (a.action in PC_OVERWRITES and a.value == 1)
            or (a.action == "wifi" and a.value == 0) or (a.action == "run_command" and risky_command(a.text)))


@registry.tool(
    PcActionArgs, needs="pc", confirm=_pc_confirms, summary=_pc_summary,
    taint_guard=lambda a: a.action in PC_TAINT_GUARDED, quiet=lambda a: a.action in PC_QUIET,
)
async def pc_action(ctx: ToolContext, a: PcActionArgs):
    """Do something on the owner's Windows PC through the Sora PC agent. screenshot only takes and saves it
    (shown in the chat); describe the screen only if asked (pc_look_at_screen)."""
    if problem := _wrong_device(ctx, "pc"):
        return problem
    device = await _pick_device(("pc_agent", "windows"), a.device_name)
    if device is None:
        return "Error: no PC agent is set up. Run the Sora PC agent on the computer first."
    params = a.model_dump(exclude={"action", "device_name"}, exclude_none=True)
    try:
        result = await hub.command(device.id, a.action, params, timeout=PC_TIMEOUTS.get(a.action, 30))
    except DeviceOffline:
        await _log_command(device.id, a.action, params, "error", "offline")
        return f"Error: the PC '{device.name}' is offline (the PC agent is not running or the PC is off)."
    except CommandTimeout as exc:
        await _log_command(device.id, a.action, params, "timeout", None)
        return f"Error: {exc}"
    except RuntimeError as exc:
        await _log_command(device.id, a.action, params, "error", str(exc))
        return f"Error from PC: {exc}"

    if a.action == "screenshot" and isinstance(result, dict) and result.get("png_base64"):
        name = f"screenshot-{uuid.uuid4().hex[:10]}.png"
        (get_settings().files_dir / name).write_bytes(base64.b64decode(result["png_base64"]))
        result = {"saved": True, "file": f"/api/files/{name}", "width": result.get("width"), "height": result.get("height")}
        if ctx.emit:
            await ctx.emit({"type": "attachment", "kind": "image", "url": f"/api/files/{name}"})
    await _log_command(device.id, a.action, params, "ok", result if not isinstance(result, str) else {"text": result})
    return {"device": device.name, "result": result}


class LookAtScreenArgs(BaseModel):
    question: str | None = Field(
        None, description="What to look for, e.g. 'how is the training run in VS Code doing?'. Empty = describe the screen."
    )
    device_name: str | None = Field(None, description="Which PC, if the owner has more than one.")


VISION_PROMPT = (
    "This is a screenshot of the owner's Windows PC. {ask} Read the important text exactly (numbers, file names, "
    "errors, metrics such as loss, Dice or accuracy). Be brief and factual; do not guess at what you cannot read."
)


@registry.tool(LookAtScreenArgs, needs="pc", untrusted=True, summary=lambda a: "PC: look at the screen")
async def pc_look_at_screen(ctx: ToolContext, a: LookAtScreenArgs):
    """Look at the PC's screen and describe it or answer a question about it — only when the owner asks what is
    on the screen or to explain/read it (for "take a screenshot" use pc_action screenshot instead)."""
    from sora.llm.client import get_llm

    if problem := _wrong_device(ctx, "pc"):
        return problem

    device = await _pick_device(("pc_agent", "windows"), a.device_name)
    if device is None:
        return "Error: no PC agent is set up. Run the Sora PC agent on the computer first."
    try:
        shot = await hub.command(device.id, "screenshot", {"max_width": 2000}, timeout=60)
    except DeviceOffline:
        return f"Error: the PC '{device.name}' is offline (the PC agent is not running or the PC is off)."
    except (CommandTimeout, RuntimeError) as exc:
        return f"Error: {exc}"
    png = shot.get("png_base64") if isinstance(shot, dict) else None
    if not png:
        return "Error: the PC did not send a screenshot."
    name = f"screenshot-{uuid.uuid4().hex[:10]}.png"
    (get_settings().files_dir / name).write_bytes(base64.b64decode(png))
    if ctx.emit:
        await ctx.emit({"type": "attachment", "kind": "image", "url": f"/api/files/{name}"})
    ask = f"Answer this: {a.question}" if a.question else "Describe what is on the screen."
    messages = [{"role": "user", "content": [
        {"type": "text", "text": VISION_PROMPT.format(ask=ask)},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
    ]}]
    try:
        result = await get_llm().complete(messages, model=get_settings().vision_model_name, temperature=0.1)
    except Exception as exc:  # the screenshot is still in the chat
        return f"Error: could not read the screenshot ({exc}). It is shown in the chat."
    await _log_command(device.id, "look_at_screen", {"question": a.question}, "ok", {"file": name})
    return {"device": device.name, "screen": result.content.strip(), "screenshot": f"/api/files/{name}"}


PhoneActionName = Literal[
    "open_app", "close_app", "open_url", "web_search", "youtube_play", "media", "volume", "screenshot", "lock",
    "call", "send_sms", "set_alarm", "set_timer", "cancel_alarm", "cancel_timer", "flashlight", "navigate",
    "play_music", "open_settings", "ring", "status", "reply_notification", "whatsapp_send",
]


class PhoneActionArgs(BaseModel):
    action: PhoneActionName = Field(
        description=(
            "open_app (target=app name); close_app (target=app name; leaves it and stops it in the background); "
            "open_url (target); web_search (target=query, text=google|youtube|maps|images; only opens the search in "
            "the phone's browser, for when the owner asks to open or show it; to answer a question from the web use "
            "the web_search tool instead); "
            "youtube_play (target=what to play: opens the top YouTube result); "
            "media (target=play_pause|next|previous|stop); volume (target=up|down|mute, seconds=steps); "
            "screenshot (takes and saves it on the phone); lock; "
            "call (target=number or contact name as the owner said it, in English letters; calls right away — "
            "don't look the name up first: the phone finds the contact by sound, with Google contacts as the fallback), "
            "send_sms (target=number or contact name, text; sent straight away once the owner approves), "
            "set_alarm (time=HH:MM 24h, text=label); cancel_alarm (turn an alarm off or stop one ringing: "
            "time=HH:MM 24h for that alarm, text='all' for every alarm, neither for the next one; the Clock app "
            "may ask the owner to pick); set_timer (seconds); cancel_timer (stop a timer); flashlight (on=true/false), "
            "navigate (target=place), play_music (target=song/artist), open_settings (target=wifi|bluetooth|...); "
            "ring (find my phone: rings at full volume even in silent mode, seconds=how long, default 30; "
            "target='stop' stops it); status (battery %, charging, network, free storage, ringer mode, model); "
            "reply_notification (target=the notification's key from phone_notifications_recent, or the person or "
            "chat as it shows there; text=the reply: sent through the notification's own reply, once the owner "
            "approves); whatsapp_send (target=contact name or number, text: opens the WhatsApp chat with the text "
            "and taps Send, once the owner approves)"
        )
    )
    target: str | None = None
    text: str | None = None
    time: str | None = None
    seconds: int | None = None
    on: bool | None = None
    sim: str | None = Field(
        None,
        description="call / send_sms only, when the owner names a SIM: '1' or '2' (\"SIM 2\", \"সিম ২\"), or the carrier "
                    "(e.g. 'Grameenphone', 'Robi'). Leave empty otherwise: the phone's default SIM is used.",
    )


def _phone_summary(a: PhoneActionArgs) -> str:
    if a.action == "send_sms":
        return f"Phone: send SMS to {a.target}{f' from SIM {a.sim}' if a.sim else ''}: {a.text}"
    if a.action == "reply_notification":
        return f"Phone: reply to {phone_notifications.describe(a.target)}: {a.text}"
    if a.action == "whatsapp_send":
        return f"Phone: WhatsApp {a.target}: {a.text}"
    return f"Phone: {a.action} {a.target or ''}{f' (SIM {a.sim})' if a.sim else ''}"


@registry.tool(
    PhoneActionArgs, needs="phone", confirm=lambda a: a.action in PHONE_CONFIRM,
    taint_guard=lambda a: a.action in {"open_url", "call"}, quiet=lambda a: a.action in PHONE_QUIET,
    summary=_phone_summary,
)
async def phone_action(ctx: ToolContext, a: PhoneActionArgs):
    """Do something on the owner's Android phone (open/close apps, search, YouTube, media, volume, screenshot,
    lock, call, SMS, alarms, timers, flashlight, maps)."""
    # Calls, texts, alarms, timers and the torch exist only on the phone: no need to say "phone" for them.
    if a.action not in PHONE_ONLY and (problem := _wrong_device(ctx, "phone")):
        return problem
    action = a.action
    params = a.model_dump(exclude={"action"}, exclude_none=True)
    # Searches become plain links the phone opens (the YouTube app plays a watch link).
    if action == "web_search" and a.target:
        action, params = "open_url", {"target": search_url(a.target, a.text)}
    elif action == "reply_notification":
        try:
            params["target"] = phone_notifications.reply_key(a.target)
        except ValueError as exc:
            return f"Error: {exc}"
        if not a.text:
            return "Error: reply with what? (text)"
    elif action in {"call", "send_sms", "whatsapp_send"} and a.target and not re.search(r"\d{3}", a.target):
        # A name, nickname or relation the owner saved in People ("Ammu", "my boss"): its number. Else the
        # phone looks in its own contacts, with a Google contact as the fallback.
        if saved := await _people_number(a.target):
            params["target"] = saved[1]
        elif fallback := await _google_number(a.target):
            params["fallback_name"], params["fallback_number"] = fallback
    elif action == "youtube_play" and a.target:
        top = await youtube_top(a.target)
        action, params = "open_url", {"target": top[1] if top else search_url(a.target, "youtube")}
        if top:
            params["title"] = top[0]
    # Request came from the phone itself: it executes the action from the response stream.
    if ctx.origin_kind == "android" and ctx.emit is not None:
        await ctx.emit({"type": "client_action", "action": action, "params": params})
        await _log_command(ctx.origin_device_id, action, params, "sent", None)
        return {"sent_to": "this phone", "status": "the phone app is carrying it out"}
    device = await _pick_device(("android",), None)
    if device is None:
        return "Error: no Android phone is registered with Sora."
    if hub.is_online(device.id):
        try:
            result = await hub.command(device.id, action, params, timeout=20)
            await _log_command(device.id, action, params, "ok", result)
            return {"device": device.name, "result": result}
        except (DeviceOffline, CommandTimeout, RuntimeError) as exc:
            await _log_command(device.id, action, params, "error", str(exc))
            return f"Error from phone: {exc}"
    fcm = get_fcm()
    if device.fcm_token and fcm.enabled:
        await fcm.send(device.fcm_token, "Sora", f"{action.replace('_', ' ')} {a.target or ''}",
                       data={"client_action": action, "params": params}, high_priority=True)
        await _log_command(device.id, action, params, "sent", "push")
        return {"device": device.name, "status": "sent as a push notification; the phone app will run it"}
    return ("Error: the phone isn't connected right now. It is connected while the Sora app is open on it, or "
            "all the time with \"Hey Sora\" on (phone app: Settings → Voice); it must be on the home Wi-Fi.")


async def _people_number(name: str) -> tuple[str, str] | None:
    """(name, number) of the one person in People that [name] means, if they have a number."""
    from sora.services import people

    async with session_scope() as session:
        p = await people.resolve(session, name)
    return (p.name, p.phones[0]) if p is not None and p.phones else None


async def _google_number(name: str) -> tuple[str, str] | None:
    """(name, number) when exactly one Google contact with a phone number matches [name]."""
    from sora.google import workspace
    from sora.google.client import get_google

    try:
        found = await workspace.contacts_search(get_google(), name, max_results=5)
    except Exception:  # Google not connected / contacts not allowed
        return None
    people = {(p["name"] or name): p["phones"][0] for p in found if p.get("phones")}
    return next(iter(people.items())) if len(people) == 1 else None


class PhoneNotificationsArgs(BaseModel):
    app: str | None = Field(None, description="Only this app, e.g. WhatsApp, Messenger, Messages. Empty: all apps.")
    limit: int = Field(10, ge=1, le=50)


@registry.tool(PhoneNotificationsArgs, needs="phone", untrusted=True)
async def phone_notifications_recent(ctx: ToolContext, a: PhoneNotificationsArgs):
    """Recent notifications that came on the owner's phone (WhatsApp, Messenger, SMS...), newest first:
    "what came on WhatsApp?", "did Ammu text me?". Each has a key to answer it with phone_action
    reply_notification when replyable."""
    from sora.timeutil import fmt_local, parse_datetime

    items = phone_notifications.history(a.app, a.limit)
    if not items:
        return ("No phone notifications" + (f" from {a.app}" if a.app else "") + " since Sora started. They come only "
                "with notification mirroring on in the phone app's Settings, and are kept in memory only.")
    return [
        {"app": i["app"], "from": i["title"], "text": i["text"], "at": fmt_local(parse_datetime(i["at"])),
         "key": i["key"], "replyable": i["replyable"]}
        for i in items
    ]


class DevicesStatusArgs(BaseModel):
    pass


@registry.tool(DevicesStatusArgs)
async def devices_status(ctx: ToolContext, a: DevicesStatusArgs):
    """Which of the owner's devices (phone, PC agent, apps) are online right now."""
    async with session_scope() as session:
        devices = (await session.execute(select(Device).where(Device.revoked.is_(False)))).scalars().all()
    return [
        {"name": d.name, "kind": d.kind, "online": hub.is_online(d.id),
         "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None}
        for d in devices
    ]
