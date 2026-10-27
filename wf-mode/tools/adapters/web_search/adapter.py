"""web_search：Tavily 主，Exa 备。

只做认证、调用和字段归一化；不写文件，不把密钥放进错误或返回值。
"""

from __future__ import annotations

import os
from typing import Any, Callable

from tools import http_client
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "web_search"
ACTIONS = ("search", "health")
PROVIDERS = ("tavily", "exa")


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


def _search_tavily(payload: dict[str, Any]) -> dict[str, Any]:
    key, env_name = first_env("TAVILY_API_KEY", "TAVILY")
    if not key:
        raise ToolError(
            "AUTH_MISSING",
            "TAVILY_API_KEY/TAVILY 未配置",
            details={"provider": "tavily", "env": "TAVILY_API_KEY|TAVILY"},
            allow_fallback=True,
        )
    query = _query(payload)
    limit = _max_results(payload)
    data = http_client.post_json(
        "https://api.tavily.com/search",
        {
            "api_key": key,
            "query": query,
            "max_results": limit,
            "include_answer": False,
        },
        provider="tavily",
    )
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
        result = {
            "title": str(item.get("title") or "").strip(),
            "url": url,
            "snippet": str(item.get("content") or item.get("snippet") or "").strip(),
        }
        published = item.get("published_date") or item.get("publishedDate") or item.get("published_at")
        if published:
            result["publishedAt"] = str(published)
        results.append(result)
    return {"query": query, "results": results}


def _search_exa(payload: dict[str, Any]) -> dict[str, Any]:
    key, env_name = first_env("EXA_API_KEY", "EXA")
    if not key:
        raise ToolError(
            "AUTH_MISSING",
            "EXA_API_KEY/EXA 未配置",
            details={"provider": "exa", "env": "EXA_API_KEY|EXA"},
            allow_fallback=True,
        )
    query = _query(payload)
    limit = _max_results(payload)
    data = http_client.post_json(
        "https://api.exa.ai/search",
        {
            "query": query,
            "numResults": limit,
            "contents": {"text": {"maxCharacters": 600}},
        },
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
        result = {
            "title": str(item.get("title") or "").strip(),
            "url": url,
            "snippet": str(item.get("text") or item.get("summary") or "").strip(),
        }
        published = item.get("publishedDate") or item.get("published_date")
        if published:
            result["publishedAt"] = str(published)
        results.append(result)
    return {"query": query, "results": results}


PROVIDER_FUNCS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "tavily": _search_tavily,
    "exa": _search_exa,
}


def health(provider: str = "tavily") -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    if provider == "tavily":
        key, env_name = first_env("TAVILY_API_KEY", "TAVILY")
    else:
        key, env_name = first_env("EXA_API_KEY", "EXA")
    configured = bool(key)
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
