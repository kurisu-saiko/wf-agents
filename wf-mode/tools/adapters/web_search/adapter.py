"""web_search：Tavily -> Exa -> Brave -> SearXNG -> DuckDuckGo（零密钥兜底）。

只做认证、调用、HTML/JSON 归一化与缓存；不写业务状态，不把密钥放进错误或返回值。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from tools import cache, http_client
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "web_search"
ACTIONS = ("search", "health")
PROVIDERS = ("tavily", "exa", "brave", "searxng", "duckduckgo")


def _query(payload: dict[str, Any]) -> str:
    raw = payload.get("query")
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("INVALID_INPUT", "query 必须是非空字符串")
    return raw.strip()


def _max_results(payload: dict[str, Any]) -> int:
    raw = payload.get("maxResults", payload.get("max_results", 5))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError("INVALID_INPUT", "maxResults 必须是整数") from exc
    if not 1 <= value <= 20:
        raise ToolError("INVALID_INPUT", "maxResults 必须在 1–20 之间")
    return value


def _domain_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def _days(payload: dict[str, Any]) -> int | None:
    raw = payload.get("days")
    if raw is None or raw == "":
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def _search_tavily(payload: dict[str, Any]) -> dict[str, Any]:
    key, _ = first_env("TAVILY_API_KEY", "TAVILY")
    if not key:
        raise ToolError(
            "AUTH_MISSING",
            "TAVILY_API_KEY/TAVILY 未配置",
            details={"provider": "tavily", "env": "TAVILY_API_KEY|TAVILY"},
            allow_fallback=True,
        )
    query = _query(payload)
    limit = _max_results(payload)
    inc = _domain_list(payload.get("includeDomains"))
    exc = _domain_list(payload.get("excludeDomains"))
    days = _days(payload)
    cache_key = cache.make_key(query, limit, ",".join(inc), ",".join(exc), days or "")
    cached = cache.get(SLOT, "tavily", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    body: dict[str, Any] = {
        "api_key": key,
        "query": query,
        "max_results": limit,
        "include_answer": False,
    }
    if inc:
        body["include_domains"] = inc
    if exc:
        body["exclude_domains"] = exc
    if days:
        body["days"] = days

    data = http_client.post_json("https://api.tavily.com/search", body, provider="tavily")
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        raise ToolError(
            "UPSTREAM_ERROR",
            "Tavily 返回缺少 results 数组",
            details={"provider": "tavily"},
            allow_fallback=True,
        )
    results = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        result: dict[str, Any] = {
            "title": str(item.get("title") or "").strip(),
            "url": url,
            "snippet": str(item.get("content") or item.get("snippet") or "").strip(),
        }
        published = item.get("published_date") or item.get("publishedDate") or item.get("published_at")
        if published:
            result["publishedAt"] = str(published)
        results.append(result)
    output = {"query": query, "results": results}
    cache.put(SLOT, "tavily", cache_key, output)
    output["_cached"] = False
    return output


def _search_exa(payload: dict[str, Any]) -> dict[str, Any]:
    key, _ = first_env("EXA_API_KEY", "EXA")
    if not key:
        raise ToolError(
            "AUTH_MISSING",
            "EXA_API_KEY/EXA 未配置",
            details={"provider": "exa", "env": "EXA_API_KEY|EXA"},
            allow_fallback=True,
        )
    query = _query(payload)
    limit = _max_results(payload)
    inc = _domain_list(payload.get("includeDomains"))
    exc = _domain_list(payload.get("excludeDomains"))
    cache_key = cache.make_key(query, limit, ",".join(inc), ",".join(exc))
    cached = cache.get(SLOT, "exa", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    body: dict[str, Any] = {
        "query": query,
        "numResults": limit,
        "contents": {"text": {"maxCharacters": 800}},
    }
    if inc:
        body["includeDomains"] = inc
    if exc:
        body["excludeDomains"] = exc

    data = http_client.post_json(
        "https://api.exa.ai/search",
        body,
        headers={"x-api-key": key},
        provider="exa",
    )
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        raise ToolError(
            "UPSTREAM_ERROR",
            "Exa 返回缺少 results 数组",
            details={"provider": "exa"},
            allow_fallback=True,
        )
    results = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        result: dict[str, Any] = {
            "title": str(item.get("title") or "").strip(),
            "url": url,
            "snippet": str(item.get("text") or item.get("summary") or "").strip(),
        }
        published = item.get("publishedDate") or item.get("published_date")
        if published:
            result["publishedAt"] = str(published)
        results.append(result)
    output = {"query": query, "results": results}
    cache.put(SLOT, "exa", cache_key, output)
    output["_cached"] = False
    return output


def _search_brave(payload: dict[str, Any]) -> dict[str, Any]:
    key, _ = first_env("BRAVE_API_KEY", "BRAVE")
    if not key:
        raise ToolError(
            "AUTH_MISSING",
            "BRAVE_API_KEY/BRAVE 未配置",
            details={"provider": "brave", "env": "BRAVE_API_KEY|BRAVE"},
            allow_fallback=True,
        )
    query = _query(payload)
    limit = _max_results(payload)
    cache_key = cache.make_key(query, limit)
    cached = cache.get(SLOT, "brave", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    data = http_client.get_json(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        params={"q": query, "count": limit},
        provider="brave",
    )
    raw_results = ((data.get("web") or {}).get("results")) if isinstance(data.get("web"), dict) else None
    if not isinstance(raw_results, list):
        raise ToolError(
            "UPSTREAM_ERROR",
            "Brave 返回缺少 web.results 数组",
            details={"provider": "brave"},
            allow_fallback=True,
        )
    results = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        result: dict[str, Any] = {
            "title": str(item.get("title") or "").strip(),
            "url": url,
            "snippet": str(item.get("description") or "").strip(),
        }
        if item.get("page_age"):
            result["publishedAt"] = str(item["page_age"])
        results.append(result)
    output = {"query": query, "results": results}
    cache.put(SLOT, "brave", cache_key, output)
    output["_cached"] = False
    return output


def _search_searxng(payload: dict[str, Any]) -> dict[str, Any]:
    base_url, _ = first_env("SEARXNG_URL")
    if not base_url:
        raise ToolError(
            "AUTH_MISSING",
            "SEARXNG_URL 未配置",
            details={"provider": "searxng", "env": "SEARXNG_URL"},
            allow_fallback=True,
        )
    query = _query(payload)
    limit = _max_results(payload)
    cache_key = cache.make_key(base_url, query, limit)
    cached = cache.get(SLOT, "searxng", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    endpoint = base_url.rstrip("/") + "/search"
    data = http_client.get_json(
        endpoint,
        params={"q": query, "format": "json"},
        provider="searxng",
    )
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        raise ToolError(
            "UPSTREAM_ERROR",
            "SearXNG 返回缺少 results 数组",
            details={"provider": "searxng"},
            allow_fallback=True,
        )
    results = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        result: dict[str, Any] = {
            "title": str(item.get("title") or "").strip(),
            "url": url,
            "snippet": str(item.get("content") or "").strip(),
        }
        if item.get("publishedDate"):
            result["publishedAt"] = str(item["publishedDate"])
        results.append(result)
    output = {"query": query, "results": results}
    cache.put(SLOT, "searxng", cache_key, output)
    output["_cached"] = False
    return output


class _DuckDuckGoParser(HTMLParser):
    """解析 DuckDuckGo HTML 接口搜索结果，不依赖第三方 HTML 解析库。"""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_title = False
        self._in_snippet = False
        self._cur_title: list[str] = []
        self._cur_href = ""
        self._cur_snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        cls = attr_map.get("class") or ""
        classes = set(cls.split())
        if tag == "a" and "result__a" in classes:
            self._flush_current()
            self._in_title = True
            self._cur_href = str(attr_map.get("href") or "")
            self._cur_title = []
            self._cur_snippet = []
        elif tag in {"a", "div", "span"} and "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        elif tag in {"a", "div", "span"} and self._in_snippet:
            self._in_snippet = False
            self._flush_current()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._cur_title.append(data)
        elif self._in_snippet:
            self._cur_snippet.append(data)

    def _flush_current(self) -> None:
        if not self._cur_href:
            return
        url = _unwrap_ddg_url(self._cur_href)
        title = " ".join("".join(self._cur_title).split())
        snippet = " ".join("".join(self._cur_snippet).split())
        if url and title and "duckduckgo.com/y.js" not in url:
            self.results.append({"title": title, "url": url, "snippet": snippet})
        self._cur_href = ""
        self._cur_title = []
        self._cur_snippet = []

    def close(self) -> None:
        super().close()
        self._flush_current()


def _unwrap_ddg_url(href: str) -> str:
    raw = href.strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    parsed = urlparse(raw)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg")
        if uddg and uddg[0]:
            return unquote(uddg[0])
    return raw


def parse_duckduckgo_html(html_text: str, limit: int = 5) -> list[dict[str, str]]:
    parser = _DuckDuckGoParser()
    parser.feed(html_text)
    parser.close()
    return parser.results[:limit]


def _search_duckduckgo(payload: dict[str, Any]) -> dict[str, Any]:
    query = _query(payload)
    limit = _max_results(payload)
    inc = _domain_list(payload.get("includeDomains"))
    effective_query = query
    if inc:
        site_expr = " OR ".join(f"site:{d}" for d in inc[:4])
        effective_query = f"{query} ({site_expr})"

    cache_key = cache.make_key(effective_query, limit)
    cached = cache.get(SLOT, "duckduckgo", cache_key)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    html_text = http_client.get_text(
        "https://html.duckduckgo.com/html/",
        params={"q": effective_query},
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
        },
        provider="duckduckgo",
    )
    if re.search(r"(?:anomaly-modal|If this persists, please|bots use DuckDuckGo)", html_text, re.I):
        raise ToolError(
            "RATE_LIMIT",
            "DuckDuckGo HTML 触发频控",
            retryable=True,
            details={"provider": "duckduckgo"},
            allow_fallback=True,
        )

    results = parse_duckduckgo_html(html_text, limit=limit)
    output = {"query": query, "results": results}
    cache.put(SLOT, "duckduckgo", cache_key, output)
    output["_cached"] = False
    return output


PROVIDER_FUNCS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "tavily": _search_tavily,
    "exa": _search_exa,
    "brave": _search_brave,
    "searxng": _search_searxng,
    "duckduckgo": _search_duckduckgo,
}


def health(provider: str = "tavily") -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    if provider == "tavily":
        key, env_name = first_env("TAVILY_API_KEY", "TAVILY")
        configured = bool(key)
    elif provider == "exa":
        key, env_name = first_env("EXA_API_KEY", "EXA")
        configured = bool(key)
    elif provider == "brave":
        key, env_name = first_env("BRAVE_API_KEY", "BRAVE")
        configured = bool(key)
    elif provider == "searxng":
        key, env_name = first_env("SEARXNG_URL")
        configured = bool(key)
    else:
        env_name = ""
        configured = True
    return {
        "ok": configured,
        "provider": provider,
        "configured": configured,
        "env": env_name,
        "checkedAt": utc_now(),
    }


def execute(action: str, payload: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    if action == "health":
        return health(provider or "tavily")
    if action != "search":
        raise ToolError("UNKNOWN_ACTION", f"web_search 不支持动作: {action}")
    chosen = provider or "tavily"
    func = PROVIDER_FUNCS.get(chosen)
    if func is None:
        raise ToolError("INVALID_INPUT", f"web_search 未知 provider: {chosen}")
    return func(payload)
