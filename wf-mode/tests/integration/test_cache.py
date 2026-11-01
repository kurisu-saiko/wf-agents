import json

import pytest

import tools.cache as cache


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    path = tmp_path / "cache"
    monkeypatch.setenv("WF_CACHE_DIR", str(path))
    monkeypatch.delenv("WF_CACHE_DISABLE", raising=False)
    return path


def test_put_and_get_roundtrip(cache_dir):
    key = cache.make_key("q", 3)
    cache.put("web_search", "tavily", key, {"results": [1]})
    assert cache.get("web_search", "tavily", key) == {"results": [1]}


def test_expired_entry_is_miss(cache_dir, monkeypatch):
    key = cache.make_key("q", 3)
    cache.put("web_search", "tavily", key, {"results": []})
    monkeypatch.setattr(cache, "_ttl", lambda: -1)
    assert cache.get("web_search", "tavily", key) is None


def test_corrupt_entry_is_miss(cache_dir):
    key = cache.make_key("q", 3)
    path = cache._path("web_search", "tavily", key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert cache.get("web_search", "tavily", key) is None


def test_dispatch_marks_cached_in_meta(cache_dir, monkeypatch):
    import importlib.util

    from tools.adapters.web_search import adapter

    root = __file__.rsplit("tests", 1)[0]
    path = __import__("pathlib").Path(root) / "tools" / "wf-tool.py"
    spec = importlib.util.spec_from_file_location("wf_tool_cache_test", path)
    wf_tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wf_tool)

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(
        adapter.http_client,
        "post_json",
        lambda *a, **k: {"results": [{"url": "https://example.com", "title": "t", "content": "c"}]},
    )

    first = wf_tool.dispatch("web_search", "search", {"query": "meta-test", "max_results": 3})
    second = wf_tool.dispatch("web_search", "search", {"query": "meta-test", "max_results": 3})
    assert first["ok"] is True and first["meta"]["cached"] is False
    assert second["meta"]["cached"] is True


def test_adapter_uses_cache_on_second_call(cache_dir, monkeypatch):
    from tools.adapters.web_search import adapter

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    calls = []

    def fake_post(url, body, **kwargs):
        calls.append(body)
        return {"results": [{"url": "https://example.com", "title": "t", "content": "c"}]}

    monkeypatch.setattr(adapter.http_client, "post_json", fake_post)

    first = adapter.execute("search", {"query": "same", "max_results": 3}, provider="tavily")
    second = adapter.execute("search", {"query": "same", "max_results": 3}, provider="tavily")

    assert first["_cached"] is False
    assert second["_cached"] is True
    assert second["results"] == first["results"]
    assert len(calls) == 1
