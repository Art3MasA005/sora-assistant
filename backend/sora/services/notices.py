"""The owner's university notice board (Green University of Bangladesh, green.edu.bd/notice):
which notices are new since they last heard, and what each one says (the page text plus its PDF).

The site sits behind a JavaScript bot check that plain HTTP can't pass, so headless Chrome
(Playwright, using the installed Chrome) passes it once and the cookie is reused with httpx until
it stops working. Notices already told to the owner are remembered in kv["notices_seen"].
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from sora.config import get_settings
from sora.db import session_scope
from sora.kv import kv_get, kv_set
from sora.textutil import html_to_text

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
FIRST_RUN_DAYS = 7  # the very first check counts the last week's notices as new
MAX_TEXT = 3500  # characters of each notice handed to the model


class NoticeError(RuntimeError):
    pass


# ---------------------------------------------------------------- getting past the bot check


def _challenge(resp: httpx.Response) -> bool:
    return "text/html" in resp.headers.get("content-type", "") and "One moment, please" in resp.text[:3000]


def _browser_cookies(url: str) -> list[dict]:
    """Opens [url] in headless Chrome until the bot check sets its cookie (blocking; ~10 s)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-blink-features=AutomationControlled"])
        try:
            ctx = browser.new_context(locale="en-US", user_agent=UA)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            for _ in range(45):
                page.wait_for_timeout(1000)
                if any(c["name"] == "wssplashchk" for c in ctx.cookies()):
                    page.wait_for_timeout(1500)
                    break
            else:
                raise NoticeError("the notice site's bot check did not let headless Chrome in")
            return [{"name": c["name"], "value": c["value"], "domain": c["domain"]} for c in ctx.cookies()]
        finally:
            browser.close()


class _Site:
    """httpx with the bot-check cookie; refreshes it through Chrome when the site asks again."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True, timeout=60)

    async def _load(self, cookies: list[dict]) -> None:
        self.client.cookies.clear()
        for c in cookies:
            self.client.cookies.set(c["name"], c["value"], domain=c["domain"])

    async def start(self) -> None:
        async with session_scope() as s:
            await self._load(await kv_get(s, "notices_cookies", []) or [])

    async def get(self, url: str) -> httpx.Response:
        resp = await self.client.get(url)
        if _challenge(resp):
            log.info("notice site wants the bot check again; opening Chrome")
            cookies = await asyncio.to_thread(_browser_cookies, get_settings().notice_board_url)
            await self._load(cookies)
            async with session_scope() as s:
                await kv_set(s, "notices_cookies", cookies)
            resp = await self.client.get(url)
            if _challenge(resp):
                raise NoticeError("the notice site keeps showing its bot check")
        resp.raise_for_status()
        return resp

    async def close(self) -> None:
        await self.client.aclose()


# ---------------------------------------------------------------- parsing


class _Links(HTMLParser):
    """Collects <a href=…notice-details…> with their text, and PDF/iframe sources."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.files: list[str] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._href, self._text = a["href"], []
            if re.search(r"\.pdf(\?|#|$)", a["href"], re.I):
                self.files.append(a["href"])
        elif tag in ("iframe", "embed") and a.get("src") and re.search(r"\.pdf(\?|#|$)", a["src"], re.I):
            self.files.append(a["src"])
        elif tag == "object" and a.get("data") and ".pdf" in a["data"].lower():
            self.files.append(a["data"])

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None


_DATE = re.compile(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})")


def _date(text: str) -> datetime | None:
    m = _DATE.search(text)
    if not m:
        return None
    year = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
    try:
        return datetime.strptime(f"{m.group(1)}-{m.group(2).title()}-{year}", "%d-%b-%Y")
    except ValueError:
        return None


def parse_list(html: str, base: str) -> list[dict]:
    """Notices on the board page, newest first: {id, title, date, url}."""
    parser = _Links()
    parser.feed(html)
    seen: dict[str, dict] = {}
    for href, text in parser.links:
        if "/notice-details/" not in href or not text:
            continue
        url = urljoin(base, href)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        # "Title GUB Date: 06-Sep-26" on the board, "GUB | 23-Feb-25 Title" in the sidebar
        title = re.sub(r"\bGUB\b\s*\|?\s*(?:Date:\s*)?(?:\d{1,2}-[A-Za-z]{3}-\d{2,4})?", " ", text)
        title = " ".join(re.sub(r"Date:\s*\d{1,2}-[A-Za-z]{3}-\d{2,4}", " ", title).split()).strip(" |-")
        when = _date(text)
        item = seen.get(slug)
        if item is None or (item["date"] is None and when is not None):
            seen[slug] = {"id": slug, "title": title, "date": when, "url": url}
    items = list(seen.values())
    items.sort(key=lambda n: n["date"] or datetime.min, reverse=True)
    return items


def _page_text(html: str) -> str:
    """The notice's own text block (the site puts it in .page-text-content)."""
    m = re.search(r'<(p|div)[^>]*class="[^"]*page-text-content[^"]*"[^>]*>(.*?)</\1>', html, re.S | re.I)
    return html_to_text(m.group(2)).strip() if m else ""


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


# ---------------------------------------------------------------- the tool's work


async def check(*, only_new: bool = True, limit: int = 5, mark_seen: bool = True) -> dict:
    """New notices (or the latest [limit] when only_new is False), each with its text and saved PDF."""
    board = get_settings().notice_board_url
    site = _Site()
    await site.start()
    try:
        notices = parse_list((await site.get(board)).text, board)
        if not notices:
            raise NoticeError("could not find any notices on the board page")
        async with session_scope() as s:
            seen_ids = await kv_get(s, "notices_seen", None)
        if only_new:
            if seen_ids is None:  # first check ever: recent ones count as new
                cutoff = datetime.now() - timedelta(days=FIRST_RUN_DAYS)
                fresh = [n for n in notices if n["date"] and n["date"] >= cutoff]
            else:
                known = set(seen_ids)
                fresh = [n for n in notices if n["id"] not in known]
        else:
            fresh = notices
        fresh = fresh[:limit]
        for n in fresh:
            await _fill(site, n)
        if mark_seen:
            async with session_scope() as s:
                known = set(seen_ids or []) | {n["id"] for n in (notices if seen_ids is None else fresh)}
                await kv_set(s, "notices_seen", sorted(known))
        return {
            "board": board,
            "new_count": len(fresh) if only_new else None,
            "notices": [
                {k: (v.strftime("%d %b %Y") if isinstance(v, datetime) else v) for k, v in n.items()} for n in fresh
            ],
        }
    finally:
        await site.close()


async def _fill(site: _Site, notice: dict) -> None:
    """Adds the notice's text (page + PDFs) and links to the saved PDFs."""
    try:
        html = (await site.get(notice["url"])).text
    except Exception as exc:
        notice["text"] = f"(could not open the notice page: {exc})"
        return
    parser = _Links()
    parser.feed(html)
    parts = [_page_text(html)]
    files = []
    for src in dict.fromkeys(urljoin(notice["url"], f.split("#")[0]) for f in parser.files):
        try:
            resp = await site.get(src)
        except Exception as exc:
            log.warning("notice file %s: %s", src, exc)
            continue
        if resp.content[:4] != b"%PDF":
            continue
        name = f"notice-{notice['id'][:60]}-{int(time.time())}.pdf"
        (get_settings().files_dir / name).write_bytes(resp.content)
        files.append(f"/api/files/{name}")
        try:
            text = await asyncio.to_thread(_pdf_text, resp.content)
        except Exception:
            text = ""
        parts.append(text or "(the PDF is a scanned image without readable text)")
    text = "\n\n".join(p for p in parts if p).strip()
    notice["text"] = (text[:MAX_TEXT] + " …") if len(text) > MAX_TEXT else (text or "(no text in the notice)")
    notice["files"] = files
