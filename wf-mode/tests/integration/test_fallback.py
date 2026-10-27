import importlib
import importlib.util
from pathlib import Path

from tools.errors import ToolError

ROOT = Path(__file__).resolve().parents[2]


def load_wf_tool():
    path = ROOT / "tools" / "wf-tool.py"
    spec = importlib.util.spec_from_file_location("wf_tool_fallback_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wf_tool = load_wf_tool()


def test_primary_failure_falls_back_to_alternate(monkeypatch):
    adapter = importlib.import_module("tools.adapters.web_search.adapter")

    def primary_fails(payload):
        raise ToolError("AUTH_MISSING", "primary missing", allow_fallback=True)

    def alternate_works(payload):
        return {
            "query": payload["query"],
            "results": [{"title": "ok", "url": "https://example.com", "snippet": "ok"}],
        }

    monkeypatch.setitem(adapter.PROVIDER_FUNCS, "tavily", primary_fails)
    monkeypatch.setitem(adapter.PROVIDER_FUNCS, "exa", alternate_works)

    env = wf_tool.dispatch("web_search", "search", {"query": "x"})
    assert env["ok"] is True
    assert env["adapter"] == "exa"
    assert env["degradation"][0]["from"] == "tavily"
    assert env["degradation"][0]["to"] == "exa"


def test_both_fail_returns_fallback_exhausted(monkeypatch):
    adapter = importlib.import_module("tools.adapters.web_search.adapter")

    def always_fails(payload):
        raise ToolError("UPSTREAM_ERROR", "boom", allow_fallback=True)

    monkeypatch.setitem(adapter.PROVIDER_FUNCS, "tavily", always_fails)
    monkeypatch.setitem(adapter.PROVIDER_FUNCS, "exa", always_fails)

    env = wf_tool.dispatch("web_search", "search", {"query": "x"})
    assert env["ok"] is False
    assert env["error"]["code"] == "FALLBACK_EXHAUSTED"
    assert len(env["error"]["details"]["attempts"]) == 2


def test_web_extract_falls_back_to_jina(monkeypatch):
    adapter = importlib.import_module("tools.adapters.web_extract.adapter")

    def primary_missing(payload):
        raise ToolError("AUTH_MISSING", "firecrawl missing", allow_fallback=True)

    def jina_works(payload):
        return {
            "url": payload["url"],
            "title": "Example",
            "text": "body",
            "metadata": {"provider": "jina", "fetchedAt": "x", "publishedTime": "2026-10-01"},
        }

    monkeypatch.setitem(adapter.PROVIDER_FUNCS, "firecrawl", primary_missing)
    monkeypatch.setitem(adapter.PROVIDER_FUNCS, "jina", jina_works)

    env = wf_tool.dispatch("web_extract", "extract", {"url": "https://example.com"})
    assert env["ok"] is True
    assert env["adapter"] == "jina"
    assert env["degradation"][0]["to"] == "jina"


def test_project_search_normalizes_github(monkeypatch):
    adapter = importlib.import_module("tools.adapters.project_search.adapter")

    def fake_get_json(url, *, provider, headers=None, params=None):
        assert "api.github.com" in url
        return {
            "items": [
                {
                    "name": "searxng",
                    "full_name": "searxng/searxng",
                    "html_url": "https://github.com/searxng/searxng",
                    "description": "meta search",
                    "stargazers_count": 38911,
                    "updated_at": "2026-10-27T12:50:12Z",
                    "license": {"spdx_id": "AGPL-3.0"},
                    "archived": False,
                    "language": "Python",
                }
            ]
        }

    monkeypatch.setattr(adapter.http_client, "get_json", fake_get_json)
    env = wf_tool.dispatch("project_search", "search", {"query": "searxng", "maxResults": 1})
    assert env["ok"] is True
    candidate = env["data"]["candidates"][0]
    assert candidate["fullName"] == "searxng/searxng"
    assert candidate["license"] == "AGPL-3.0"
