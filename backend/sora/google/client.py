"""Authorized HTTP client for Google REST APIs, with automatic token refresh."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from sora.config import get_settings
from sora.db import session_scope
from sora.google.oauth import PROVIDER, TOKEN_URL
from sora.models import Connection
from sora.security import decrypt, encrypt

log = logging.getLogger(__name__)


class GoogleNotConnected(RuntimeError):
    def __init__(self, message: str = "Google is not connected. Open the app and tap Connect Google.") -> None:
        super().__init__(message)


class GoogleAPIError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Google API error {status}: {message}")
        self.status = status


class GoogleClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15))
        self._lock = asyncio.Lock()
        self._token: str | None = None
        self._expires: datetime | None = None

    def invalidate(self) -> None:
        self._token = None
        self._expires = None

    async def _load_token(self, force_refresh: bool = False) -> str:
        async with self._lock:
            now = datetime.now(UTC)
            if not force_refresh and self._token and self._expires and self._expires - now > timedelta(seconds=90):
                return self._token
            try:
                return await self._refresh_locked(now, force_refresh)
            except GoogleNotConnected:
                self.invalidate()
                raise

    async def _refresh_locked(self, now: datetime, force_refresh: bool) -> str:
        # Errors are returned out of the session block rather than raised inside it, so that a
        # status change to needs_reauth is committed instead of rolled back.
        error: Exception | None = None
        async with session_scope() as session:
            conn = (
                await session.execute(select(Connection).where(Connection.provider == PROVIDER))
            ).scalar_one_or_none()
            if conn is None:
                raise GoogleNotConnected()
            if conn.status == "needs_reauth":
                raise GoogleNotConnected("Google access expired or was revoked. Tap Connect Google again.")
            expires = conn.expires_at
            if not force_refresh and conn.access_token_enc and expires and expires - now > timedelta(seconds=90):
                self._token, self._expires = decrypt(conn.access_token_enc), expires
                return self._token
            refresh = decrypt(conn.refresh_token_enc)
            if not refresh:
                conn.status = "needs_reauth"
                error = GoogleNotConnected("No refresh token stored. Tap Connect Google again.")
            else:
                s = get_settings()
                resp = await self._http.post(
                    TOKEN_URL,
                    data={
                        "client_id": s.google_client_id,
                        "client_secret": s.google_client_secret,
                        "refresh_token": refresh,
                        "grant_type": "refresh_token",
                    },
                )
                if resp.status_code >= 400:
                    if "invalid_grant" in resp.text:
                        conn.status = "needs_reauth"
                        log.warning("Google refresh token rejected; owner must reconnect")
                        error = GoogleNotConnected("Google access expired or was revoked. Tap Connect Google again.")
                    else:
                        raise GoogleAPIError(resp.status_code, resp.text[:300])
                else:
                    data = resp.json()
                    conn.access_token_enc = encrypt(data["access_token"])
                    conn.expires_at = now + timedelta(seconds=int(data.get("expires_in", 3600)))
                    if data.get("refresh_token"):
                        conn.refresh_token_enc = encrypt(data["refresh_token"])
                    self._token, self._expires = data["access_token"], conn.expires_at
        if error is not None:
            raise error
        assert self._token is not None
        return self._token

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        token = await self._load_token()
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}"}
        resp = await self._http.request(method, url, headers=headers, **kwargs)
        if resp.status_code == 401:
            token = await self._load_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            resp = await self._http.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            try:
                message = resp.json().get("error", {}).get("message", resp.text[:300])
            except ValueError:
                message = resp.text[:300]
            raise GoogleAPIError(resp.status_code, message)
        return resp

    async def get(self, url: str, **kwargs: Any) -> Any:
        return (await self.request("GET", url, **kwargs)).json()

    async def post(self, url: str, **kwargs: Any) -> Any:
        resp = await self.request("POST", url, **kwargs)
        return resp.json() if resp.content else {}

    async def patch(self, url: str, **kwargs: Any) -> Any:
        resp = await self.request("PATCH", url, **kwargs)
        return resp.json() if resp.content else {}

    async def put(self, url: str, **kwargs: Any) -> Any:
        resp = await self.request("PUT", url, **kwargs)
        return resp.json() if resp.content else {}

    async def delete(self, url: str, **kwargs: Any) -> None:
        await self.request("DELETE", url, **kwargs)

    async def raw(self, url: str, **kwargs: Any) -> bytes:
        return (await self.request("GET", url, **kwargs)).content


_client: GoogleClient | None = None


def get_google() -> GoogleClient:
    global _client
    if _client is None:
        _client = GoogleClient()
    return _client
