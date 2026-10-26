"""Web search for the web_search tool: Brave or Tavily with an API key, DuckDuckGo's HTML page without one."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import httpx

from sora.config import get_settings
from sora.textutil import html_to_text

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
CACHE_SECONDS = 300
CACHE_MAX = 100


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    async def search(self, client: httpx.AsyncClient, query: str, count: int) -> list[SearchResult]: ...


def _result(title: str, url: str, snippet: str) -> SearchResult:
    # Brave marks the matched words with <strong>, DuckDuckGo with <b>: plain text for the LLM.
    return SearchResult(html_to_text(title or url)[:200], url, html_to_text(snippet or "")[:400])


class BraveSearch:
    name = "brave"

    def __init__(self, key: str) -> None:
        self.key = key

    async def search(self, client: httpx.AsyncClient, query: str, count: int) -> list[SearchResult]:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": count},
            headers={"Accept": "application/json", "X-Subscription-Token": self.key},
        )
        resp.raise_for_status()
        items = (resp.json().get("web") or {}).get("results") or []
        return [_result(i.get("title", ""), i["url"], i.get("description", "")) for i in items if i.get("url")]


class TavilySearch:
    name = "tavily"

    def __init__(self, key: str) -> None:
        self.key = key

    async def search(self, client: httpx.AsyncClient, query: str, count: int) -> list[SearchResult]:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"query": query, "max_results": count, "search_depth": "basic"},
            headers={"Authorization": f"Bearer {self.key}"},
        )
        resp.raise_for_status()
        items = resp.json().get("results") or []
        return [_result(i.get("title", ""), i["url"], i.get("content", "")) for i in items if i.get("url")]


class _DuckDuckGoParser(HTMLParser):
    """Results on html.duckduckgo.com: an <a class="result__a"> title, then an <a class="result__snippet">."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._field: str | None = None
        self._tag = ""
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if self._field is not None:
            self._depth += tag == self._tag
            return
        classes = (dict(attrs).get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self.results.append({"title": "", "url": dict(attrs).get("href") or "", "snippet": ""})
            self._field = "title"
        elif "result__snippet" in classes and self.results:
            self._field = "snippet"
        else:
            return
        self._tag, self._depth = tag, 0

    def handle_endtag(self, tag):
        if self._field is None or tag != self._tag:
            return
        if self._depth:
            self._depth -= 1
        else:
            self._field = None

    def handle_data(self, data):
        if self._field is not None:
            self.results[-1][self._field] += data


def _ddg_url(href: str) -> str:
    """DuckDuckGo links go through its redirect (//duckduckgo.com/l/?uddg=<the real URL>)."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        return (parse_qs(parsed.query).get("uddg") or [""])[0]
    return href


def parse_duckduckgo(page: str) -> list[SearchResult]:
    parser = _DuckDuckGoParser()
    parser.feed(page)
    parser.close()
    results = []
    for r in parser.results:
        url = _ddg_url(r["url"])
        # Ads link to duckduckgo.com/y.js, which has no uddg target.
        if url.startswith(("http://", "https://")):
            results.append(SearchResult(" ".join(r["title"].split())[:200], url, " ".join(r["snippet"].split())[:400]))
    return results


class DuckDuckGoSearch:
    name = "duckduckgo"

    async def search(self, client: httpx.AsyncClient, query: str, count: int) -> list[SearchResult]:
        resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
        resp.raise_for_status()
        if resp.status_code == 202:  # DuckDuckGo's answer when it rate-limits: a challenge page, no results
            raise ValueError("rate-limited")
        # The page is ~30 KB of HTML: parse it off the event loop.
        return (await asyncio.to_thread(parse_duckduckgo, resp.text))[:count]


def providers() -> list[Provider]:
    """The configured provider first, then DuckDuckGo, which needs no key, if that one fails."""
    s = get_settings()
    name, key = s.web_search_provider.strip().lower(), s.web_search_api_key.strip()
    chosen: list[Provider] = []
    if key and name == "brave":
        chosen.append(BraveSearch(key))
    elif key and name == "tavily":
        chosen.append(TavilySearch(key))
    elif name not in {"", "duckduckgo"}:
        log.warning("WEB_SEARCH_PROVIDER=%s needs WEB_SEARCH_API_KEY (brave or tavily); using DuckDuckGo", name)
    return [*chosen, DuckDuckGoSearch()]


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Sora"})


def _reason(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timed out"
    return str(exc) if isinstance(exc, ValueError) and str(exc) else type(exc).__name__


# The same question is often asked twice in a row (voice retries, "and the second one?"): keep answers briefly.
_cache: OrderedDict[tuple[str, int], tuple[float, str, list[SearchResult]]] = OrderedDict()


async def search(query: str, count: int = 5) -> tuple[str, list[SearchResult]]:
    """(provider name, results). Raises SearchError when every provider failed."""
    query = " ".join(query.split())
    key = (query.casefold(), count)
    now = time.monotonic()
    if (hit := _cache.get(key)) and now - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2]
    errors = []
    async with _client() as client:
        for provider in providers():
            try:
                results = await provider.search(client, query, count)
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
                log.warning("web search with %s failed: %s", provider.name, exc)
                errors.append(f"{provider.name}: {_reason(exc)}")
                continue
            if results:  # an empty page may be a hiccup: ask again next time
                _cache[key] = (now, provider.name, results)
                _cache.move_to_end(key)
                while len(_cache) > CACHE_MAX:
                    _cache.popitem(last=False)
            return provider.name, results
    raise SearchError(", ".join(errors))
