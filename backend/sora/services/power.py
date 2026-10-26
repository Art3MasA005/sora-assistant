"""Turning Sora off from the Windows app: the PC agents quit (which closes the "Hey Sora" mic), then
the server stops. Opening the app again starts both (core/server_link.dart)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading

from sora.services.hub import hub

log = logging.getLogger(__name__)

PC_KINDS = ("pc_agent",)
_server = None  # the uvicorn.Server running this app, set by `python -m sora serve`


def attach(server) -> None:
    global _server
    _server = server


async def _quit_agents() -> int:
    stopped = 0
    for client in hub.online(PC_KINDS):
        try:
            await hub.command(client.device_id, "quit", {}, timeout=5)
            stopped += 1
        except Exception as exc:  # an older agent without "quit", or already gone
            log.info("could not stop %s: %s", client.name, exc)
    return stopped


def _stop_server() -> None:
    if _server is not None:
        _server.should_exit = True  # finishes open requests and runs the shutdown (database closed)
        # a request or socket that won't finish must not keep Sora running
        timer = threading.Timer(15, os._exit, (0,))
        timer.daemon = True  # a clean exit doesn't wait for it
        timer.start()
    else:  # not started by `serve` (uvicorn run some other way)
        os._exit(0)


async def stop() -> dict:
    """Stops the agents now and the server a moment later, so this reply still reaches the app."""
    agents = await _quit_agents()
    log.info("turning Sora off (stopped %d PC agent(s))", agents)
    asyncio.get_running_loop().call_later(0.5, _stop_server)
    return {"stopping": True, "agents": agents}
