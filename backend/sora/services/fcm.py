"""Firebase Cloud Messaging (HTTP v1) sender. Optional: without a service account, pushes are skipped."""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from sora.config import get_settings

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class UnregisteredToken(RuntimeError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class FCM:
    def __init__(self) -> None:
        self._account: dict | None = None
        self._token: str | None = None
        self._token_exp = 0.0
        path = get_settings().fcm_service_account_file
        if path and Path(path).is_file():
            self._account = json.loads(Path(path).read_text(encoding="utf-8"))
        elif path:
            log.warning("FCM_SERVICE_ACCOUNT_FILE does not exist: %s", path)
        self._http = httpx.AsyncClient(timeout=20)

    @property
    def enabled(self) -> bool:
        return self._account is not None

    def _assertion(self) -> str:
        assert self._account is not None
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": self._account["client_email"],
            "scope": SCOPE,
            "aud": self._account["token_uri"],
            "iat": now,
            "exp": now + 3600,
        }
        signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
        key = serialization.load_pem_private_key(self._account["private_key"].encode(), password=None)
        signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input}.{_b64(signature)}"

    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 120:
            return self._token
        assert self._account is not None
        resp = await self._http.post(
            self._account["token_uri"],
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": self._assertion()},
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    async def send(self, token: str, title: str, body: str, data: dict | None = None, high_priority: bool = False) -> None:
        if not self.enabled:
            return
        assert self._account is not None
        message = {
            "token": token,
            "notification": {"title": title[:200], "body": body[:1000]},
            "data": {k: v if isinstance(v, str) else json.dumps(v) for k, v in (data or {}).items()},
            "android": {"priority": "HIGH" if high_priority else "NORMAL"},
        }
        url = f"https://fcm.googleapis.com/v1/projects/{self._account['project_id']}/messages:send"
        resp = await self._http.post(
            url, json={"message": message}, headers={"Authorization": f"Bearer {await self._access_token()}"}
        )
        if resp.status_code == 404 or "UNREGISTERED" in resp.text:
            raise UnregisteredToken(token)
        if resp.status_code >= 400:
            log.warning("FCM send failed (%s): %s", resp.status_code, resp.text[:300])


_fcm: FCM | None = None


def get_fcm() -> FCM:
    global _fcm
    if _fcm is None:
        _fcm = FCM()
    return _fcm
