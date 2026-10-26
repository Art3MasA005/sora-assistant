"""Google "Connect" endpoints: one Connect button per service (Gmail, Sheets, Slides...)."""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sora.api.deps import current_device
from sora.config import get_settings
from sora.db import get_session
from sora.google import oauth
from sora.google.client import get_google
from sora.kv import kv_set
from sora.models import Device
from sora.services.hub import hub

router = APIRouter(tags=["connections"])


async def _connection_out(session: AsyncSession) -> dict:
    s = get_settings()
    conn, granted, disabled = await oauth.service_status(session)
    services = [
        {
            "id": name,
            "label": svc["label"],
            "description": svc["description"],
            "granted": name in granted,  # Google gave permission
            "enabled": name not in disabled,  # the owner hasn't switched it off in the app
            "connected": name in granted and name not in disabled,
        }
        for name, svc in oauth.SERVICES.items()
    ]
    return {
        "provider": "google",
        "configured": s.google_configured,
        "connected": conn is not None and conn.status == "active",
        "status": conn.status if conn else None,
        "account_email": conn.account_email if conn else None,
        "connected_at": conn.created_at.isoformat() if conn and conn.created_at else None,
        "services": services,
    }


@router.get("/api/connections")
async def list_connections(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    return [await _connection_out(session)]


class StartIn(BaseModel):
    services: list[str] | None = None  # e.g. ["sheets"]; empty/None = everything


@router.post("/api/connections/google/start")
async def google_start(body: StartIn | None = None, device: Device = Depends(current_device),
                       session: AsyncSession = Depends(get_session)):
    """Consent URL for the chosen services. The app opens it in a browser; Google redirects to /oauth/google/callback.
    Services connected earlier stay connected."""
    try:
        url = await oauth.build_auth_url(session, (body.services if body else None) or None)
    except oauth.OAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"auth_url": url, "redirect_uri": get_settings().google_redirect}


class ServicePatch(BaseModel):
    enabled: bool


@router.patch("/api/connections/google/services/{service}")
async def toggle_service(service: str, body: ServicePatch, device: Device = Depends(current_device),
                         session: AsyncSession = Depends(get_session)):
    """Switch one service off (Sora stops using it) or back on, without touching Google permissions."""
    if service not in oauth.SERVICES:
        raise HTTPException(404, f"Unknown service. Choose from: {', '.join(oauth.SERVICES)}")
    _, _, disabled = await oauth.service_status(session)
    disabled = (disabled - {service}) if body.enabled else (disabled | {service})
    await kv_set(session, oauth.DISABLED_KEY, sorted(disabled))
    out = await _connection_out(session)
    await hub.broadcast({"type": "connection_updated", "connection": out})
    return out


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sora</title><style>body{{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0;
background:#0f1115;color:#e8e8ea}}main{{max-width:420px;padding:24px;text-align:center}}h1{{font-size:1.4rem}}
p{{color:#a0a3ab;line-height:1.5}}</style></head><body><main><h1>{title}</h1><p>{body}</p></main></body></html>"""


@router.get("/oauth/google/callback", include_in_schema=False)
async def google_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                          session: AsyncSession = Depends(get_session)):
    if error or not code or not state:
        msg = "Google sign-in was cancelled." if error == "access_denied" else f"Google returned an error: {error or 'missing code'}"
        return HTMLResponse(_PAGE.format(title="Not connected", body=escape(msg)), status_code=400)
    try:
        conn = await oauth.handle_callback(session, code, state)
    except oauth.OAuthError as exc:
        return HTMLResponse(_PAGE.format(title="Not connected", body=escape(str(exc))), status_code=400)
    get_google().invalidate()
    await session.commit()
    out = await _connection_out(session)
    await hub.broadcast({"type": "connection_updated", "connection": out})
    names = [svc["label"] for svc in out["services"] if svc["connected"]]
    return HTMLResponse(
        _PAGE.format(
            title="✅ Connected",
            body=f"{escape(conn.account_email or 'Your account')}: {escape(', '.join(names) or 'nothing yet')}. "
                 "You can close this page and go back to Sora.",
        )
    )


@router.delete("/api/connections/google", status_code=204)
async def google_disconnect(device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    """Revoke everything at Google and forget the tokens."""
    if not await oauth.disconnect(session):
        raise HTTPException(404, "Google is not connected")
    get_google().invalidate()
    await session.flush()
    await hub.broadcast({"type": "connection_updated", "connection": await _connection_out(session)})
