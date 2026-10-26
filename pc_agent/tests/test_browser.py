"""The PC agent's browser against local pages, with a real (headless) Chromium. Skipped where there is
no browser to drive (set BROWSER_EXECUTABLE, or have Playwright's own Chromium)."""

from __future__ import annotations

import base64
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright")
CHROMIUM = os.environ.get("BROWSER_EXECUTABLE") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else "")
if not CHROMIUM:
    pytest.skip("no Chromium to drive here", allow_module_level=True)

import browser  # noqa: E402
from windows_actions import ActionError  # noqa: E402

PAGES = {
    "/": ("text/html", """<html><head><title>Shop</title></head><body>
      <h1>Welcome to the shop</h1>
      <a href="/details">Details</a> <a href="/details" target="_blank">Open in a tab</a>
      <a href="/report.pdf">Download report</a>
      <form action="/search"><input name="q" placeholder="Search"><input type="password" name="pw">
        <select name="size"><option>Small</option><option>Large</option></select>
        <button type="button">Search</button></form>
      <form action="/order" method="get"><button>Place order</button></form>
      <a href="/pay">পেমেন্ট করুন</a>
      <div id="price"></div>
      <script>setTimeout(() => document.getElementById('price').innerText = 'Price: ৳ 1,200', 300)</script>
    </body></html>"""),
    "/details": ("text/html", "<html><head><title>Details</title></head><body><p>Details page</p></body></html>"),
    "/order": ("text/html", "<html><head><title>Ordered</title></head><body><p>Thank you</p></body></html>"),
    "/report.pdf": ("application/pdf", "%PDF-1.4 fake"),
}


class _Pages(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        kind, body = PAGES.get(self.path.split("?")[0], ("text/plain", "not here"))
        data = body.encode()
        self.send_response(200 if self.path.split("?")[0] in PAGES else 404)
        self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith("text") else ""))
        if kind == "application/pdf":
            self.send_header("Content-Disposition", 'attachment; filename="report.pdf"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    (home / "Downloads").mkdir()
    old = {k: os.environ.get(k) for k in ("BROWSER_EXECUTABLE", "USERPROFILE")}
    os.environ.update(BROWSER_EXECUTABLE=CHROMIUM, USERPROFILE=str(home))
    profile, browser.PROFILE = browser.PROFILE, home / "profile"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", home
    browser.browser_close({})
    server.shutdown()
    browser.PROFILE = profile
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _by_text(page: dict, text: str, kind: str | None = None) -> dict:
    return next(e for e in page["elements"] if e["text"] == text and (kind is None or e["kind"] == kind))


def test_reading_a_page_gives_stable_ids_and_marks_what_commits(site):
    url, _ = site
    assert browser.browser_open({"target": url})["title"] == "Shop"
    page = browser.browser_read({})
    assert "Welcome to the shop" in page["text"]
    assert _by_text(page, "Details")["kind"] == "link"
    assert "submits" not in _by_text(page, "Search", "button")  # type=button: just a button
    assert _by_text(page, "Place order").get("submits") is True  # a form's submit button
    assert _by_text(page, "পেমেন্ট করুন").get("submits") is True  # "pay", in Bangla
    assert any(e["kind"] == "password" for e in page["elements"])
    again = browser.browser_read({})
    assert [e["id"] for e in again["elements"]] == [e["id"] for e in page["elements"]]


def test_filling_but_never_a_password(site):
    url, _ = site
    browser.browser_open({"target": url})
    page = browser.browser_read({})
    search = next(e for e in page["elements"] if e["text"] == "Search" and e["kind"] == "text")
    browser.browser_fill({"target": search["id"], "text": "রবি ফোন"})
    size = next(e for e in page["elements"] if e["kind"] == "select")
    browser.browser_fill({"target": size["id"], "text": "Large"})
    pw = next(e for e in page["elements"] if e["kind"] == "password")
    with pytest.raises(ActionError, match="doesn't type passwords"):
        browser.browser_fill({"target": pw["id"], "text": "hunter2"})
    with pytest.raises(ActionError, match="no element 999"):
        browser.browser_fill({"target": 999, "text": "x"})


def test_a_click_that_commits_needs_the_owners_yes(site):
    url, _ = site
    browser.browser_open({"target": url})
    order = _by_text(browser.browser_read({}), "Place order")["id"]
    with pytest.raises(ActionError, match="ask the owner first"):
        browser.browser_click({"target": order})
    with pytest.raises(ActionError, match="read the page again"):
        browser.browser_click({"target": order, "value": 1, "text": "Search"})  # approved something else
    done = browser.browser_click({"target": order, "value": 1, "text": "Place order"})
    assert done["title"] == "Ordered"


def test_links_new_tabs_downloads_and_screenshots(site):
    url, home = site
    browser.browser_open({"target": url})
    page = browser.browser_read({})
    assert browser.browser_click({"target": _by_text(page, "Details")["id"]})["title"] == "Details"

    browser.browser_open({"target": url})
    page = browser.browser_read({})
    assert browser.browser_click({"target": _by_text(page, "Open in a tab")["id"]})["clicked"] == "Open in a tab"
    assert "Details page" in browser.browser_read({})["text"]  # carried on in the new tab

    saved = browser.browser_download({"target": url + "/report.pdf"})["downloaded"]
    assert saved == [str(home / "Downloads" / "report.pdf")]
    assert (home / "Downloads" / "report.pdf").read_bytes() == b"%PDF-1.4 fake"
    browser.browser_open({"target": url})
    clicked = browser.browser_click({"target": _by_text(browser.browser_read({}), "Download report")["id"]})
    assert clicked["downloaded"] == [str(home / "Downloads" / "report (2).pdf")]

    shot = browser.browser_screenshot({})
    assert base64.b64decode(shot["png_base64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_page_watching_reads_a_part_rendered_by_javascript(site):
    url, _ = site
    browser.browser_open({"target": url + "/details"})
    assert browser.browser_text({"target": url, "text": "#price"})["text"] == "Price: ৳ 1,200"
    assert "Details page" in browser.browser_read({})["text"]  # the owner's page was left alone
    with pytest.raises(ActionError, match="give a web address"):
        browser.browser_text({"target": "not a url"})


def test_it_closes_itself_when_idle(site, monkeypatch):
    url, _ = site
    monkeypatch.setattr(browser, "IDLE_CLOSE", 0.5)
    browser.browser_open({"target": url})
    import time

    time.sleep(1.5)
    assert browser._worker.submit(lambda: browser._browser.context).result() is None
