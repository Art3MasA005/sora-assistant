"""FastAPI application: routes plus the background email watcher, reminder loop and routine scheduler."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, text

from sora import __version__
from sora.api import assistant, auth, chat, clipboard, connections, knowledge, voice, ws
from sora.api import people as people_api
from sora.api import phone_notifications as phone_notifications_api
from sora.api import routines as routines_api
from sora.agent.runner import get_agent
from sora.api.deps import current_device
from sora.config import get_settings
from sora.db import dispose_engine, session_scope
from sora.models import Connection, Device
from sora.services import announce, autostart, email_watcher, power, reminders, routines
from sora.services import voice as voice_service
from sora.services.fcm import get_fcm
from sora.services.hub import hub

log = logging.getLogger("sora")


class AutostartIn(BaseModel):
    enabled: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(reminders.run_forever(stop), name="reminders"),
        asyncio.create_task(routines.run_forever(stop), name="routines"),
        asyncio.create_task(voice_service.warm_up(), name="whisper-warm-up"),
        asyncio.create_task(autostart.write_launchers(), name="launch-shortcuts"),
        asyncio.create_task(announce.run_forever(), name="tell-the-phone"),
    ]
    if s.email_watcher_enabled:
        tasks.append(asyncio.create_task(email_watcher.run_forever(stop), name="email-watcher"))
    log.info("Sora %s ready on %s", __version__, s.public_base_url)
    try:
        yield
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await dispose_engine()


def create_app(*, background: bool = True) -> FastAPI:
    app = FastAPI(
        title="Sora",
        version=__version__,
        description="Personal AI assistant backend. Authenticate with `Authorization: Bearer <device token>`.",
        lifespan=lifespan if background else None,
    )
    for module in (auth, chat, connections, knowledge, people_api, assistant, routines_api, phone_notifications_api, voice, clipboard,
                   ws):
        app.include_router(module.router)

    @app.get("/api/health", tags=["system"])
    async def health():
        s = get_settings()
        db_ok = True
        try:
            async with session_scope() as session:
                await session.execute(text("select 1"))
                google = (
                    await session.execute(select(Connection).where(Connection.provider == "google"))
                ).scalar_one_or_none()
        except Exception:
            db_ok, google = False, None
        return {
            "ok": db_ok,
            "name": "sora",  # how the apps recognise this server when they look for it on the network
            "version": __version__,
            "database": db_ok,
            "llm_configured": s.llm_configured,
            "llm_model": s.llm_model or None,
            "google_configured": s.google_configured,
            "google_connected": bool(google and google.status == "active"),
            "push_enabled": get_fcm().enabled,
            "stt_provider": s.stt_provider,
            "stt_ready": voice_service.stt_ready(),
            "devices_online": len(hub.online()),
            "tools": len(get_agent().registry.tools),
        }

    @app.get("/api/system/autostart", tags=["system"])
    async def get_autostart(device: Device = Depends(current_device)):
        """Whether the server and the PC agent start when the owner signs in to Windows."""
        return {"supported": autostart.supported(), "enabled": autostart.enabled()}

    @app.put("/api/system/autostart", tags=["system"])
    async def put_autostart(body: AutostartIn, device: Device = Depends(current_device)):
        if not autostart.supported():
            raise HTTPException(400, "the server isn't running on Windows")
        try:
            on = await asyncio.to_thread(autostart.set_enabled, body.enabled)
        except Exception as exc:
            raise HTTPException(500, f"could not change the Startup shortcuts: {exc}") from exc
        return {"supported": True, "enabled": on}

    @app.post("/api/system/stop", tags=["system"])
    async def stop_sora(device: Device = Depends(current_device)):
        """Turns Sora off on the PC: the PC agent (and its mic) and then this server."""
        if device.kind != "windows":
            raise HTTPException(403, "Sora can only be turned off from the Windows app")
        return await power.stop()

    @app.get("/api/files/{name}", tags=["system"])
    async def get_file(name: str, device: Device = Depends(current_device)):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise HTTPException(400, "bad file name")
        path = get_settings().files_dir / name
        if not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path)

    return app


app = create_app()
