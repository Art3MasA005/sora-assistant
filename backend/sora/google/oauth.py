"""Google "Connect" flow: OAuth 2.0 authorization code + PKCE, tokens stored encrypted."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from sora.config import get_settings
from sora.models import Connection, OAuthState
from sora.security import decrypt, encrypt

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

G = "https://www.googleapis.com/auth/"
BASE_SCOPES = ["openid", G + "userinfo.email"]

# Each service has its own Connect button and asks only for its own scopes. Connecting more
# services later adds to what was already granted (include_granted_scopes).
SERVICES: dict[str, dict] = {
    "gmail": {"label": "Gmail", "scopes": [G + "gmail.modify"],
              "description": "Read, search, send and reply to email; notify about important mail"},
    "calendar": {"label": "Google Calendar", "scopes": [G + "calendar"],
                 "description": "See and create events"},
    "drive": {"label": "Google Drive", "scopes": [G + "drive"],
              "description": "Find and read any file (also covers Docs, Sheets and Slides)"},
    "docs": {"label": "Google Docs", "scopes": [G + "documents"], "description": "Create and write documents"},
    "sheets": {"label": "Google Sheets", "scopes": [G + "spreadsheets"], "description": "Read and write spreadsheets"},
    "slides": {"label": "Google Slides", "scopes": [G + "presentations"], "description": "Create presentations"},
    "tasks": {"label": "Google Tasks", "scopes": [G + "tasks"], "description": "To-do list"},
    "contacts": {"label": "Google Contacts", "scopes": [G + "contacts.readonly", G + "contacts.other.readonly"],
                 "description": "Look up email addresses and phone numbers (read-only)"},
}
# Full Drive access also works for the Docs, Sheets and Slides APIs.
_IMPLIED_BY_DRIVE = {"docs", "sheets", "slides"}

SCOPES = BASE_SCOPES + [scope for svc in SERVICES.values() for scope in svc["scopes"]]
DISABLED_KEY = "google_disabled_services"

PROVIDER = "google"


class OAuthError(RuntimeError):
    pass


def granted_services(scopes: list[str] | None) -> set[str]:
    have = set(scopes or [])
    granted = {name for name, svc in SERVICES.items() if all(s in have for s in svc["scopes"])}
    if "drive" in granted:
        granted |= _IMPLIED_BY_DRIVE
    return granted


async def service_status(session: AsyncSession) -> tuple[Connection | None, set[str], set[str]]:
    """(connection, services granted by Google, services the owner switched off in the app)."""
    from sora.kv import kv_get

    conn = (await session.execute(select(Connection).where(Connection.provider == PROVIDER))).scalar_one_or_none()
    disabled = set(await kv_get(session, DISABLED_KEY, []) or [])
    if conn is None or conn.status != "active":
        return conn, set(), disabled
    return conn, granted_services(conn.scopes), disabled


async def enabled_services(session: AsyncSession) -> set[str]:
    _, granted, disabled = await service_status(session)
    return granted - disabled


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def build_auth_url(session: AsyncSession, services: list[str] | None = None) -> str:
    """Consent URL for the given services (all of them when None)."""
    s = get_settings()
    if not s.google_configured:
        raise OAuthError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in .env")
    unknown = [name for name in services or [] if name not in SERVICES]
    if unknown:
        raise OAuthError(f"Unknown service(s): {', '.join(unknown)}. Choose from: {', '.join(SERVICES)}")
    scopes = SCOPES if not services else BASE_SCOPES + [sc for name in services for sc in SERVICES[name]["scopes"]]
    now = datetime.now(UTC)
    await session.execute(delete(OAuthState).where(OAuthState.expires_at < now))
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    session.add(
        OAuthState(state=state, provider=PROVIDER, code_verifier=verifier, expires_at=now + timedelta(minutes=15))
    )
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": s.google_redirect,
        "response_type": "code",
        "scope": " ".join(dict.fromkeys(scopes)),
        "access_type": "offline",
        "prompt": "consent",  # always hand back a refresh token
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def handle_callback(session: AsyncSession, code: str, state: str) -> Connection:
    s = get_settings()
    row = await session.get(OAuthState, state)
    if row is None or row.expires_at < datetime.now(UTC):
        raise OAuthError("This connect link expired. Start again from the app.")
    verifier = row.code_verifier
    await session.delete(row)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": s.google_redirect,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if resp.status_code >= 400:
            raise OAuthError(f"Google refused the code: {resp.text[:300]}")
        tokens = resp.json()
        info = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        email = info.json().get("email") if info.status_code == 200 else None

    conn = (await session.execute(select(Connection).where(Connection.provider == PROVIDER))).scalar_one_or_none()
    if conn is None:
        conn = Connection(provider=PROVIDER, scopes=[], status="new")
        session.add(conn)
    from sora.kv import kv_get, kv_set

    before = granted_services(conn.scopes) if conn.status == "active" else set()
    conn.account_email = email
    # With include_granted_scopes, the response lists everything granted so far, not just this click.
    conn.scopes = tokens.get("scope", "").split()
    newly = granted_services(conn.scopes) - before
    disabled = set(await kv_get(session, DISABLED_KEY, []) or [])
    if newly & disabled:  # connecting a service again switches it back on
        await kv_set(session, DISABLED_KEY, sorted(disabled - newly))
    conn.access_token_enc = encrypt(tokens["access_token"])
    if tokens.get("refresh_token"):
        conn.refresh_token_enc = encrypt(tokens["refresh_token"])
    conn.expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    conn.status = "active"
    await session.flush()
    return conn


async def disconnect(session: AsyncSession) -> bool:
    from sora.kv import kv_delete

    conn = (await session.execute(select(Connection).where(Connection.provider == PROVIDER))).scalar_one_or_none()
    if conn is None:
        return False
    await kv_delete(session, DISABLED_KEY)
    token = decrypt(conn.refresh_token_enc) or decrypt(conn.access_token_enc)
    if token:
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                await client.post(REVOKE_URL, params={"token": token})
            except httpx.HTTPError:
                pass  # deleting locally is what matters
    await session.delete(conn)
    return True
