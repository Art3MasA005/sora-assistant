"""What the PC agent reports on its own becomes a notification on the phone: a download finished, a
training run ended (pc_agent/watchers.py), a VS Code terminal command or task ended (vscode_ext/), a
Claude Code job ended (pc_agent/claude_code.py)."""

from __future__ import annotations

from sora.models import Device
from sora.services import app_language
from sora.services.notifier import notify


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


async def handle(device: Device, message: dict) -> None:
    event = message.get("event")
    bangla = await app_language.code() == "bn"
    if event == "download_done":
        name = str(message.get("name") or "")[:200]
        try:
            size = f" ({_size(int(message.get('size') or 0))})"
        except (TypeError, ValueError):
            size = ""
        await notify(kind="device", title="⬇ " + ("ডাউনলোড শেষ" if bangla else "Download finished"),
                     body=name + size, data={"event": event, "name": name, "device": device.name})
    elif event == "training_done":
        command = str(message.get("command") or "")[:150]
        metrics = [str(m)[:200] for m in (message.get("metrics") or [])][-4:]
        await notify(kind="device", title="🎓 " + ("ট্রেনিং শেষ" if bangla else "Training finished"),
                     body="\n".join([command, *metrics]).strip(), importance="high",
                     data={"event": event, "device": device.name})
    elif event in {"vscode_command_done", "vscode_task_done"}:
        what = str(message.get("command") or message.get("task") or "")[:200]
        code = message.get("exit_code")
        failed = code not in (0, None)
        if bangla:
            title = ("❌ কমান্ড ব্যর্থ" if failed else "✅ কমান্ড শেষ") if event == "vscode_command_done" else (
                "❌ টাস্ক ব্যর্থ" if failed else "✅ টাস্ক শেষ")
        else:
            title = ("❌ Command failed" if failed else "✅ Command finished") if event == "vscode_command_done" else (
                "❌ Task failed" if failed else "✅ Task finished")
        if failed:
            title += f" ({code})"
        lines = [f"{message.get('window')}: {what}" if message.get("window") else what,
                 _duration(message.get("seconds"), bangla), str(message.get("tail") or "")[-400:]]
        await notify(kind="device", title=title, body="\n".join(x for x in lines if x).strip(),
                     importance="high" if failed else "normal", data={"event": event, "device": device.name})
    elif event == "claude_done":
        ok = bool(message.get("ok"))
        folder = str(message.get("folder") or "")[:100]
        if bangla:
            title = f"🤖 Claude Code {'শেষ করেছে' if ok else 'থেমে গেছে'}: {folder}"
        else:
            title = f"🤖 Claude Code {'finished' if ok else 'stopped'}: {folder}"
        lines = [str(message.get("summary") or "")[:700]]
        edited = [str(e)[:120] for e in message.get("edited") or []][:8]
        if edited:
            lines.append(("বদলেছে: " if bangla else "Changed: ") + ", ".join(edited))
        denied = [str(d.get("what") or d.get("tool") or "")[:120] for d in message.get("denied") or [] if isinstance(d, dict)][:5]
        if denied:
            lines.append(("অনুমতি ছাড়া করতে পারেনি: " if bangla else "Couldn't, without your yes: ") + "; ".join(denied))
        await notify(kind="device", title=title, body="\n".join(x for x in lines if x), importance="high",
                     data={"event": event, "folder": folder, "device": device.name})


def _duration(seconds, bangla: bool) -> str:
    try:
        minutes = round(int(seconds) / 60)
    except (TypeError, ValueError):
        return ""
    if minutes < 1:
        return ""
    return f"{minutes} মিনিট চলেছে" if bangla else f"ran {minutes} min"
