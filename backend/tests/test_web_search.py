"""The web_search tool and its providers, with every HTTP call stubbed."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from conftest import run

import sora.services.web_search as ws
from sora.agent.tools.base import UNTRUSTED_PREFIX, ToolContext, registry

DDG_PAGE = """
<div class="result results_links result--ad">
  <a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_domain=shop.example&amp;u3=x">Buy now</a>
  <a class="result__snippet" href="https://duckduckgo.com/y.js?ad_domain=shop.example">An ad</a>
</div>
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews%3Fid%3D1&amp;rut=abc">
      Dhaka <b>weather</b> &amp; news</a>
  </h2>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews%3Fid%3D1">
    Rain <b>today</b>, 28&deg;C</a>
</div>
<div class="result results_links web-result">
  <a class="result__a" href="https://bn.wikipedia.org/wiki/Dhaka">ঢাকা - উইকিপিডিয়া</a>
  <a class="result__snippet">ঢাকা বাংলাদেশের রাজধানী।</a>
</div>
"""


@pytest.fixture(autouse=True)
def fresh_cache():
    ws._cache.clear()
    yield
    ws._cache.clear()


def _use(monkeypatch, handler, provider="duckduckgo", key=""):
    """Route every search request to [handler] and pick the provider settings."""
    calls: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(ws, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(record)))
    monkeypatch.setattr(ws, "get_settings", lambda: SimpleNamespace(web_search_provider=provider, web_search_api_key=key))
    return calls


def _ddg(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "html.duckduckgo.com"
    return httpx.Response(200, text=DDG_PAGE)


def test_duckduckgo_page_is_parsed_without_ads():
    results = ws.parse_duckduckgo(DDG_PAGE)
    assert [r.url for r in results] == ["https://example.com/news?id=1", "https://bn.wikipedia.org/wiki/Dhaka"]
    assert results[0].title == "Dhaka weather & news"
    assert results[0].snippet == "Rain today, 28°C"
    assert results[1].title == "ঢাকা - উইকিপিডিয়া"


def test_brave_results_with_the_key_and_html_stripped(monkeypatch):
    def brave(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.search.brave.com"
        assert request.headers["X-Subscription-Token"] == "brave-key"
        assert request.url.params["q"] == "dhaka weather" and request.url.params["count"] == "3"
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Weather in <strong>Dhaka</strong>", "url": "https://w.example/dhaka", "description": "Hot &amp; humid"},
            {"title": "no url"},
        ]}})

    _use(monkeypatch, brave, "brave", "brave-key")
    source, results = run(ws.search("  dhaka   weather ", 3))
    assert source == "brave"
    assert [(r.title, r.url, r.snippet) for r in results] == [("Weather in Dhaka", "https://w.example/dhaka", "Hot & humid")]


def test_tavily_results(monkeypatch):
    def tavily(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.tavily.com"
        assert request.headers["Authorization"] == "Bearer tvly-key"
        return httpx.Response(200, json={"results": [{"title": "T", "url": "https://t.example", "content": "c"}]})

    _use(monkeypatch, tavily, "tavily", "tvly-key")
    assert run(ws.search("q")) == ("tavily", [ws.SearchResult("T", "https://t.example", "c")])


def test_falls_back_to_duckduckgo_when_the_provider_fails(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.search.brave.com":
            return httpx.Response(401, json={"error": "bad key"})
        return _ddg(request)

    calls = _use(monkeypatch, handler, "brave", "wrong-key")
    source, results = run(ws.search("dhaka"))
    assert source == "duckduckgo" and len(results) == 2
    assert [c.url.host for c in calls] == ["api.search.brave.com", "html.duckduckgo.com"]


def test_falls_back_on_timeouts_and_bad_json(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.tavily.com":
            raise httpx.ReadTimeout("slow", request=request)
        return _ddg(request)

    _use(monkeypatch, handler, "tavily", "tvly-key")
    assert run(ws.search("a"))[0] == "duckduckgo"

    ws._cache.clear()
    _use(monkeypatch, lambda r: httpx.Response(200, text="<html>not json") if r.url.host != "html.duckduckgo.com"
         else _ddg(r), "brave", "k")
    assert run(ws.search("a"))[0] == "duckduckgo"


def test_provider_without_a_key_uses_duckduckgo(monkeypatch):
    calls = _use(monkeypatch, _ddg, "brave", "")
    assert run(ws.search("x"))[0] == "duckduckgo"
    assert len(calls) == 1


def test_every_provider_failing_is_an_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(202, text="<html>challenge</html>")  # DuckDuckGo rate-limiting
        return httpx.Response(500)

    _use(monkeypatch, handler, "brave", "k")
    with pytest.raises(ws.SearchError) as err:
        run(ws.search("x"))
    assert str(err.value) == "brave: HTTP 500, duckduckgo: rate-limited"


def test_results_are_cached_for_a_few_minutes(monkeypatch):
    calls = _use(monkeypatch, _ddg)
    first = run(ws.search("Dhaka news"))
    assert run(ws.search("dhaka  NEWS")) == first
    assert len(calls) == 1

    # Expired: asked again.
    key = next(iter(ws._cache))
    stamp, source, results = ws._cache[key]
    ws._cache[key] = (stamp - ws.CACHE_SECONDS - 1, source, results)
    run(ws.search("dhaka news"))
    assert len(calls) == 2


def test_empty_results_are_not_cached_and_the_cache_is_capped(monkeypatch):
    calls = _use(monkeypatch, lambda r: httpx.Response(200, text="<html>no results</html>"))
    assert run(ws.search("nothing")) == ("duckduckgo", [])
    run(ws.search("nothing"))
    assert len(calls) == 2

    _use(monkeypatch, _ddg)
    monkeypatch.setattr(ws, "CACHE_MAX", 3)
    for i in range(5):
        run(ws.search(f"q{i}"))
    assert [k[0] for k in ws._cache] == ["q2", "q3", "q4"]


def test_web_search_tool_marks_results_untrusted(monkeypatch):
    _use(monkeypatch, _ddg)
    tool = registry.get("web_search")
    assert tool.untrusted
    # Searching is read-only and goes to a fixed provider, so it never needs the owner's approval.
    assert not tool.needs_confirmation(tool.args_model(query="x"), ToolContext(None, tainted=True))

    outcome = run(registry.run(tool, tool.args_model(query="dhaka weather", count=1), ToolContext(None)))
    assert outcome.ok
    assert outcome.content.startswith(UNTRUSTED_PREFIX)
    assert outcome.data == {
        "query": "dhaka weather",
        "source": "duckduckgo",
        "results": [{"title": "Dhaka weather & news", "url": "https://example.com/news?id=1", "snippet": "Rain today, 28°C"}],
    }


def test_web_search_tool_reports_a_failure(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(503))
    tool = registry.get("web_search")
    outcome = run(registry.run(tool, tool.args_model(query="x"), ToolContext(None)))
    assert not outcome.ok
    assert outcome.content.startswith("Error: web search failed (duckduckgo: HTTP 503)")

    blank = run(registry.run(tool, tool.args_model(query="   "), ToolContext(None)))
    assert not blank.ok


def test_device_web_search_is_described_as_opening_the_browser():
    for name in ("pc_action", "phone_action"):
        description = registry.get(name).schema()["function"]["parameters"]["properties"]["action"]["description"]
        assert "only opens the search" in description and "use the web_search tool instead" in description
