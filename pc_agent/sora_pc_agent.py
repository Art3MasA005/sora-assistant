"""Sora PC agent: keeps a WebSocket open to the Sora backend and runs commands on this PC.

    python pc_agent/sora_pc_agent.py                 # uses SORA_SERVER_URL and PC_AGENT_TOKEN from .env
    python pc_agent/sora_pc_agent.py --allow-shell   # also allow run_command (PowerShell)

Get a token on the server with:  python -m sora create-device --name "My PC" --kind pc_agent --save-as PC_AGENT_TOKEN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import sys
import threading
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

import claude_code
import clipboard_sync
import voice_wake
import vscode_bridge
import watchers
from windows_actions import ACTIONS, ActionError

__version__ = "0.1.0"
log = logging.getLogger("sora-pc-agent")
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
SLOW_ACTIONS = {"clipboard_image": 40, "screenshot": 60, "search_files": 60, "run_command": 130, "close_app": 45, "store_search": 70,
                "store_install": 910, "uninstall_app": 610, "installed_apps": 100, "youtube_play": 30,
                "training_status": 60, "say": 120, "file_copy": 300, "file_move": 300, "file_zip": 300,
                "file_unzip": 300, "tidy_downloads": 120, "type_text": 60, "wifi": 40, "bluetooth": 40, "brightness": 40,
                "browser_open": 90, "browser_read": 40, "browser_click": 40, "browser_fill": 40, "browser_screenshot": 40,
                "browser_download": 610, "browser_text": 90, "vscode": 160, "claude_code": 135}


def hey_sora(params: dict) -> dict:
    """value=1 / 0 switches "Hey Sora" on / off on this PC (off closes the mic); no value: just its state."""
    value = params.get("value", params.get("enabled"))
    if value is None:
        return voice_wake.status()
    return voice_wake.set_enabled(str(value).strip().lower() in {"1", "true", "on", "yes"})


def quit_agent(params: dict) -> dict:
    """Sora is being turned off (from the Windows app): exit just after this reply goes out, which
    also closes the "Hey Sora" mic."""
    threading.Timer(1.0, os._exit, (0,)).start()
    return {"quitting": True}


LOCAL_ACTIONS = {"hey_sora": hey_sora, "quit": quit_agent, "say": voice_wake.say}


# Settings the agent's modules read from the environment, also taken from .env: folders training_status
# reads logs from (separated by ;); WAKE_WORD=0 makes hands-free voice off by default; WAKE_ENGINE=whisper
# skips the on-device "Hey Sora" model; WAKE_THRESHOLD is its sensitivity; PROJECT_DIRS are more folders
# the file actions may touch; DOWNLOAD_WATCH / TRAINING_WATCH=0 switch the watchers off; BROWSER_CHANNEL /
# BROWSER_EXECUTABLE choose the browser Sora drives; VSCODE_BRIDGE=0 switches the VS Code bridge off;
# VSCODE_CLI / CLAUDE_CODE_PATH point at `code` / `claude` when they aren't on PATH; SORA_BRIDGE_FILE and
# VSCODE_STATE_DB move the bridge's file and VS Code's recent list (tests use them).
ENV_KEYS = ("TRAINING_DIRS", "WAKE_WORD", "WAKE_ENGINE", "WAKE_THRESHOLD", "PROJECT_DIRS", "DOWNLOAD_WATCH",
            "TRAINING_WATCH", "BROWSER_CHANNEL", "BROWSER_EXECUTABLE", "VSCODE_BRIDGE", "VSCODE_CLI",
            "CLAUDE_CODE_PATH", "SORA_BRIDGE_FILE", "VSCODE_STATE_DB", "CORNER_ORB", "SORA_APP_EXE")


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k in {"SORA_SERVER_URL", "PC_AGENT_TOKEN"}})
    for key in ENV_KEYS:
        if values.get(key):
            os.environ.setdefault(key, values[key])
    return values


def ws_url(server: str) -> str:
    server = server.rstrip("/")
    if server.startswith("http://"):
        server = "ws://" + server[7:]
    elif server.startswith("https://"):
        server = "wss://" + server[8:]
    return server if server.endswith("/ws") else server + "/ws"


async def handle(ws, message: dict, allow_shell: bool) -> None:
    command_id, action, params = message.get("id"), message.get("action"), message.get("params") or {}
    log.info("command: %s %s", action, {k: v for k, v in params.items() if k != "text"})
    try:
        if action == "run_command" and not allow_shell:
            raise ActionError("run_command is disabled on this PC (start the agent with --allow-shell to enable it)")
        fn = ACTIONS.get(action) or LOCAL_ACTIONS.get(action)
        if fn is None:
            raise ActionError(f"unknown action '{action}'")
        data = await asyncio.wait_for(asyncio.to_thread(fn, params), timeout=SLOW_ACTIONS.get(action, 30))
        reply = {"type": "result", "id": command_id, "ok": True, "data": data}
    except TimeoutError:
        reply = {"type": "result", "id": command_id, "ok": False, "error": f"{action} took too long"}
    except Exception as exc:
        reply = {"type": "result", "id": command_id, "ok": False, "error": str(exc) or type(exc).__name__}
    await ws.send(json.dumps(reply, ensure_ascii=False))


async def run(server: str, token: str, allow_shell: bool) -> None:
    url = ws_url(server)
    backoff = 1
    tasks: set[asyncio.Task] = set()
    # What this PC tells the phone on its own (a download finished...): kept while the line is down.
    outbox: asyncio.Queue[dict] = asyncio.Queue(maxsize=50)
    loop = asyncio.get_running_loop()

    def offer(event: dict) -> None:
        if not outbox.full():
            outbox.put_nowait(event)

    def report(event: dict) -> None:
        loop.call_soon_threadsafe(offer, event)

    watchers.start(report)
    vscode_bridge.start(report)  # VS Code windows connect to this PC agent
    claude_code.start(report)

    async def send_events(ws) -> None:
        while True:
            event = await outbox.get()
            await ws.send(json.dumps({"type": "pc_event", **event}, ensure_ascii=False))

    while True:
        sender: asyncio.Task | None = None
        try:
            async with websockets.connect(
                url, additional_headers={"Authorization": f"Bearer {token}"}, max_size=None, ping_interval=20
            ) as ws:
                backoff = 1
                await ws.send(json.dumps({
                    "type": "info", "hostname": platform.node(), "platform": platform.platform(),
                    "agent_version": __version__, "allow_shell": allow_shell,
                }))
                sender = asyncio.create_task(send_events(ws))
                async for raw in ws:
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "hello":
                        log.info("connected to %s as %s", url, message.get("name"))
                    elif kind == "command":
                        task = asyncio.create_task(handle(ws, message, allow_shell))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                    elif kind == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
        except ConnectionClosed as exc:
            if exc.rcvd is not None and exc.rcvd.code in (4401, 4001):
                sys.exit(f"Server rejected this agent ({exc.rcvd.reason}). Create a new token.")
            log.warning("connection closed: %s", exc)
        except (OSError, InvalidStatus, TimeoutError) as exc:
            log.warning("cannot reach %s: %s", url, exc)
        finally:
            if sender is not None:
                sender.cancel()
        await asyncio.sleep(backoff)
        backoff = min(60, backoff * 2)


def main() -> None:
    env = load_env()
    parser = argparse.ArgumentParser(description="Sora PC agent")
    parser.add_argument("--server", default=env.get("SORA_SERVER_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=env.get("PC_AGENT_TOKEN"))
    parser.add_argument("--allow-shell", action="store_true", help="allow the run_command action")
    args = parser.parse_args()
    if not args.token:
        sys.exit("No token. Run on the server: python -m sora create-device --name \"My PC\" --kind pc_agent --save-as PC_AGENT_TOKEN")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    voice_wake.start(args.server, args.token)  # "Hey Sora" on this PC's mic
    clipboard_sync.start(args.server, args.token)  # what's copied here goes to the phone
    try:
        asyncio.run(run(args.server, args.token, args.allow_shell))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
