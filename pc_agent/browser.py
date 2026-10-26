"""A browser Sora drives step by step on the PC (Playwright): open a page, read it (its text and a
short list of buttons, links and fields with stable ids), click, fill, screenshot, download.

- One worker thread owns Playwright (its objects belong to the thread that made them); every action
  runs there in turn.
- A persistent profile in data/browser-profile, so the owner logs in to a site once (with value=1 the
  window is visible, to log in or watch) and Sora stays logged in.
- The installed Chrome, else Edge (BROWSER_CHANNEL=chrome,msedge); BROWSER_EXECUTABLE points at another one.
- A click that submits, pays, buys, posts or sends is refused until the owner approved it: the server
  sends value=1 only after asking, and the button's text must match. Passwords are never typed.
- The browser closes itself after IDLE_CLOSE seconds unused (Chrome costs memory and some CPU).
"""

from __future__ import annotations

import base64
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from windows_actions import ActionError

PROFILE = Path(__file__).resolve().parents[1] / "data" / "browser-profile"
IDLE_CLOSE = 300.0
MAX_TEXT = 6000
MAX_ELEMENTS = 80
NAV_TIMEOUT = 45_000
# A button or link that does one of these needs the owner's yes first (English and Bangla).
COMMITS = re.compile(
    r"\b(pay|buy|order|checkout|check out|purchase|place order|post|publish|send|submit|confirm|donate|subscribe|"
    r"tweet|reply|comment|share|transfer|delete|remove|book now|sign up|register)\b"
    r"|পাঠান|পাঠাও|কিনুন|অর্ডার|পেমেন্ট|পোস্ট|জমা|নিশ্চিত|মুছুন",
    re.I,
)

# Whether an element sends something off: a form's submit button, or a pay/post/send... label.
SUBMITS_FN = r"""(el, risky) => {
  const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
  if ((tag === 'button' && (type === 'submit' || (type === '' && el.form))) || (tag === 'input' && (type === 'submit' || type === 'image'))) return true;
  return risky.test(el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
}"""
LABEL_FN = r"""(el) => (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
  el.getAttribute('title') || el.getAttribute('name') || '').trim().replace(/\s+/g, ' ').slice(0, 80)"""

# Marks the visible interactive elements with data-sora-id (kept across reads, so ids stay stable on a
# page) and returns the page's text and those elements.
READ_JS = r"""
([maxItems, maxText, commits]) => {
  const submits = """ + SUBMITS_FN + r""", label = """ + LABEL_FN + r""";
  const risky = new RegExp(commits, 'i');
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], ' +
              '[role=checkbox], [role=tab], [role=menuitem], [onclick], [contenteditable=""], [contenteditable=true]';
  let next = window.__soraNext || 1;
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (!el.dataset.soraId) el.dataset.soraId = String(next++);
    const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
    const item = {id: +el.dataset.soraId, kind: tag === 'a' ? 'link' : (tag === 'input' ? (type || 'text') : tag), text: label(el)};
    if (tag === 'a') item.href = el.href.slice(0, 150);
    if (submits(el, risky)) item.submits = true;
    out.push(item);
    if (out.length >= maxItems) break;
  }
  window.__soraNext = next;
  const text = document.body ? document.body.innerText.replace(/\n{3,}/g, '\n\n') : '';
  return {title: document.title, url: location.href, text: text.slice(0, maxText), more_text: text.length > maxText,
          elements: out};
}
"""
INFO_JS = r"""
(el, commits) => {
  const submits = """ + SUBMITS_FN + r""", label = """ + LABEL_FN + r""";
  return {text: label(el), tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
          submits: submits(el, new RegExp(commits, 'i'))};
}
"""


class _Browser:
    """Lives on the worker thread only."""

    def __init__(self) -> None:
        self.playwright = None
        self.context = None
        self.page = None
        self.visible = False
        self.downloads: list = []
        self.last_used = 0.0

    def ensure(self, visible: bool | None = None):
        """The page, starting the browser (or restarting it to show or hide its window)."""
        want = self.visible if visible is None else visible
        if self.context is not None and want != self.visible:
            self.close()
        if self.context is None:
            from playwright.sync_api import sync_playwright

            PROFILE.mkdir(parents=True, exist_ok=True)
            self.playwright = sync_playwright().start()
            options: dict = {"headless": not want, "accept_downloads": True, "locale": "en-US",
                             "args": ["--disable-blink-features=AutomationControlled"]}
            if os.environ.get("BROWSER_EXECUTABLE"):
                choices = [{"executable_path": os.environ["BROWSER_EXECUTABLE"]}]
            else:  # Edge comes with Windows, so there is always one
                choices = [{"channel": c} for c in (os.environ.get("BROWSER_CHANNEL") or "chrome,msedge").split(",")]
            for i, choice in enumerate(choices):
                try:
                    self.context = self.playwright.chromium.launch_persistent_context(str(PROFILE), **options, **choice)
                    break
                except Exception as exc:
                    if i == len(choices) - 1:
                        self.close()
                        raise ActionError(f"could not start the browser ({str(exc).splitlines()[0][:200]}); "
                                          "is Google Chrome or Microsoft Edge installed?") from exc
            self.visible = want
            self.context.on("page", self._new_page)
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.on("download", self._downloaded)
        if self.page is None or self.page.is_closed():
            self.page = self.context.new_page()
        self.last_used = time.monotonic()
        return self.page

    def _downloaded(self, download) -> None:
        self.downloads.append(download)

    def _new_page(self, page) -> None:
        page.on("download", self._downloaded)
        if page.opener() is not None:  # a link that opened a new tab: carry on there
            self.page = page

    def save_downloads(self) -> list[str]:
        """Saves what the page started downloading into Downloads (the PC's download watcher tells the phone)."""
        saved = []
        folder = Path(os.environ.get("USERPROFILE") or Path.home()) / "Downloads"
        while self.downloads:
            d = self.downloads.pop(0)
            name = re.sub(r'[\\/:*?"<>|]', "_", d.suggested_filename or "download")
            target, n = folder / name, 2
            while target.exists():
                target = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
                n += 1
            folder.mkdir(parents=True, exist_ok=True)
            d.save_as(str(target))
            saved.append(str(target))
        return saved

    def close(self) -> None:
        for step in (lambda: self.context and self.context.close(), lambda: self.playwright and self.playwright.stop()):
            try:
                step()
            except Exception:
                pass
        self.playwright = self.context = self.page = None
        self.downloads.clear()


_browser = _Browser()
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sora-browser")
_idle_timer: threading.Timer | None = None


def _on_worker(fn, timeout: float = 120):
    """Runs fn(browser) on the browser's thread and waits for it; then arms the idle close."""
    global _idle_timer
    try:
        return _worker.submit(fn, _browser).result(timeout)
    finally:
        if _idle_timer is not None:
            _idle_timer.cancel()
        _idle_timer = threading.Timer(IDLE_CLOSE, _close_if_idle)
        _idle_timer.daemon = True
        _idle_timer.start()


def _close_if_idle() -> None:
    def close(b: _Browser) -> None:
        if b.context is not None and time.monotonic() - b.last_used >= IDLE_CLOSE - 1:
            b.close()

    _worker.submit(close, _browser)


def _url(params: dict) -> str:
    url = (params.get("target") or "").strip()
    if not re.match(r"https?://", url, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", url, re.I):
            url = "https://" + url
        else:
            raise ActionError("give a web address (https://…)")
    return url


def _element(page, raw):
    try:
        element_id = int(str(raw).strip().lstrip("#"))
    except ValueError:
        raise ActionError("which element? give its id from browser_read") from None
    loc = page.locator(f'[data-sora-id="{element_id}"]')
    if loc.count() == 0:
        raise ActionError(f"no element {element_id} on this page now; read the page again")
    return loc.first


def _where(page) -> dict:
    return {"url": page.url, "title": page.title()}


def _settle(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    page.wait_for_timeout(400)  # a single-page app updates a moment later


# ---------------------------------------------------------------- the actions


def browser_open(params: dict) -> dict:
    """target=url; value=1 shows the window (to log in or watch), value=0 hides it."""
    url = _url(params)
    visible = None if params.get("value") is None else str(params["value"]) == "1"

    def go(b: _Browser) -> dict:
        page = b.ensure(visible)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        except Exception as exc:
            if "Download is starting" not in str(exc):
                raise ActionError(f"could not open {url}: {str(exc).splitlines()[0][:200]}") from exc
        _settle(page)
        out = _where(page)
        if saved := b.save_downloads():
            out["downloaded"] = saved
        return out

    return _on_worker(go)


def browser_read(params: dict) -> dict:
    """The page's text (the first part) and its buttons, links and fields with ids for click/fill."""

    def read(b: _Browser) -> dict:
        page = b.ensure()
        if page.url in ("", "about:blank"):
            raise ActionError("no page is open; browser_open one first")
        return page.evaluate(READ_JS, [MAX_ELEMENTS, MAX_TEXT, COMMITS.pattern])

    return _on_worker(read)


def browser_click(params: dict) -> dict:
    """target=element id. A button that submits, pays or posts needs value=1 (the owner said yes) and
    text=its label as browser_read showed it."""

    def click(b: _Browser) -> dict:
        page = b.ensure()
        el = _element(page, params.get("target"))
        info = el.evaluate(INFO_JS, COMMITS.pattern)
        if info["submits"]:
            label = info["text"] or info["tag"]
            if str(params.get("value") or "0") != "1":
                raise ActionError(f"“{label}” submits, pays, posts or sends something: ask the owner first, then call "
                                  f"again with value=1 and text=\"{label}\"")
            said = (params.get("text") or "").strip().casefold()
            if not said or said not in label.casefold():
                raise ActionError(f"the approved button was “{params.get('text')}”, but element {params.get('target')} "
                                  f"is “{label}”: read the page again")
        el.click(timeout=10_000)
        _settle(page)
        out = {"clicked": info["text"], **_where(page)}
        if saved := b.save_downloads():
            out["downloaded"] = saved
        return out

    return _on_worker(click)


def browser_fill(params: dict) -> dict:
    """target=element id, text=what to put in it (a list: the option's label). Never a password."""
    text = params.get("text") or ""

    def fill(b: _Browser) -> dict:
        page = b.ensure()
        el = _element(page, params.get("target"))
        info = el.evaluate(INFO_JS, COMMITS.pattern)
        if info["type"] == "password":
            raise ActionError("Sora doesn't type passwords: show the window (browser_open with value=1) and let "
                              "the owner log in; the profile remembers it")
        if info["tag"] == "select":
            el.select_option(label=text, timeout=10_000)
        else:
            el.fill(text, timeout=10_000)
        return {"filled": info["text"] or info["tag"]}

    return _on_worker(fill)


def browser_screenshot(params: dict) -> dict:
    def shot(b: _Browser) -> dict:
        page = b.ensure()
        png = page.screenshot(timeout=20_000)
        return {"png_base64": base64.b64encode(png).decode(), **_where(page)}

    return _on_worker(shot)


def browser_download(params: dict) -> dict:
    """target=url of a file: saved into Downloads."""
    url = _url(params)

    def download(b: _Browser) -> dict:
        page = b.ensure()
        try:
            with page.expect_download(timeout=NAV_TIMEOUT) as info:
                try:
                    page.goto(url, timeout=NAV_TIMEOUT)
                except Exception as exc:
                    if "Download is starting" not in str(exc):
                        raise
            if info.value not in b.downloads:  # the page's own download handler may have it already
                b.downloads.append(info.value)
        except Exception as exc:
            raise ActionError(f"{url} didn't start a download: {str(exc).splitlines()[0][:200]}") from exc
        return {"downloaded": b.save_downloads()}

    return _on_worker(download, timeout=600)


def browser_close(params: dict) -> str:
    _on_worker(lambda b: b.close())
    return "closed the browser"


def browser_text(params: dict) -> dict:
    """For page watching: target=url, text=CSS selector (optional). Its own tab, closed after: the page
    the owner is working on is left alone."""
    url = _url(params)
    selector = (params.get("text") or "").strip()

    def text(b: _Browser) -> dict:
        b.ensure()
        page = b.context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            if selector:
                page.wait_for_selector(selector, timeout=20_000)
                content = "\n".join(page.locator(selector).all_inner_texts())
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass
                content = page.inner_text("body")
            return {"url": page.url, "text": content[:20_000]}
        except ActionError:
            raise
        except Exception as exc:
            raise ActionError(f"could not read {url}: {str(exc).splitlines()[0][:200]}") from exc
        finally:
            page.close()

    return _on_worker(text)
