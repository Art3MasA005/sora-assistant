"""Small web helpers for device actions."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from urllib.parse import quote_plus, urlparse

import httpx

SEARCH_SITES = {
    "google": "https://www.google.com/search?q=",
    "youtube": "https://www.youtube.com/results?search_query=",
    "bing": "https://www.bing.com/search?q=",
    "maps": "https://www.google.com/maps/search/",
    "images": "https://www.google.com/search?tbm=isch&q=",
}


def search_url(query: str, site: str | None = None) -> str:
    return SEARCH_SITES.get((site or "google").lower(), SEARCH_SITES["google"]) + quote_plus(query)


async def youtube_top(query: str) -> tuple[str, str] | None:
    """(title, watch URL) of the top YouTube result, or None (then open the results page instead)."""
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}) as c:
            page = (await c.get(search_url(query, "youtube"))).text
    except httpx.HTTPError:
        return None
    found = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', page)
    if not found:
        return None
    return json.loads(f'"{found.group(2)}"'), f"https://www.youtube.com/watch?v={found.group(1)}"


def is_public_url(url: str) -> bool:
    """Refuse localhost/LAN addresses so a malicious page can't make Sora probe the home network."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True
