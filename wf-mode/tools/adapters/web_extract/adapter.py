"""web_extract：Firecrawl 主，Jina Reader 备。"""

from __future__ import annotations

import os
from typing import Any, Callable

from tools import cache, http_client
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "web_extract"
ACTIONS = ("extract", "health")
PROVIDERS = ("firecrawl", "jina")


def _url(payload: dict[str, Any]) -> str:
    raw = payload.get("url")
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("INVALID_INPUT", "url 必须是非空字符串")
    url = raw.strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ToolError("INVALID_INPUT", "url 必须是 http/https 地址")
    return url


def _extract_firecrawl(payload: dict[str, Any]) -> dict[str, Any]:
    key, env_name = first_env("FIRECRAWL_API_KEY", "FIRECRAWL")
    if not key:
        raise ToolError(
            "AUTH_MISSING",
            "FIRECRAWL_API_KEY/FIRECRAWL 未配置",
            details={"provider": "firecrawl", "env": "FIRECRAWL_API_KEY|FIRECRAWL"},
            allow_fallback=True,
        )
    url = _url(payload)
    cache_key = cache.make_key(url)
    cached = cache.get(SLOT, "firecrawl", cache_key)
    if cached is not None:
        cached["_cached"] = True
        return cached
    data = http_client.post_json(
        "https://api.firecrawl.dev/v1/scrape",
        {"url": url, "formats": ["markdown"], "onlyMainContent": True},
        headers={"Authorization": f"Bearer {key}"},
        provider="firecrawl",
    )
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    text = str(body.get("markdown") or body.get("content") or "")
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    published = (
        metadata.get("publishedTime")
        or metadata.get("modifiedTime")
        or metadata.get("og:published_time")
        or metadata.get("article:published_time")
        or metadata.get("date")
        or ""
    )
    output = {
        "url": url,
        "title": str(metadata.get("title") or ""),
        "text": text[:20000],
        "metadata": {
            "provider": "firecrawl",
            "fetchedAt": utc_now(),
            "publishedTime": str(published),
        },
    }
    cache.put(SLOT, "firecrawl", cache_key, output)
    output["_cached"] = False
    return output


def _extract_jina(payload: dict[str, Any]) -> dict[str, Any]:
    url = _url(payload)
    cache_key = cache.make_key(url)
    cached = cache.get(SLOT, "jina", cache_key)
    if cached is not None:
        cached["_cached"] = True
        return cached
    headers = {"Accept": "text/plain"}
    key, _ = first_env("JINA_API_KEY", "JINA")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    text = http_client.get_text(f"https://r.jina.ai/{url}", headers=headers, provider="jina")
    output = {
        "url": url,
        "title": "",
        "text": text[:20000],
        "metadata": {
            "provider": "jina",
            "fetchedAt": utc_now(),
            "publishedTime": "",
        },
    }
    cache.put(SLOT, "jina", cache_key, output)
    output["_cached"] = False
    return output


PROVIDER_FUNCS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "firecrawl": _extract_firecrawl,
    "jina": _extract_jina,
}


def health(provider: str = "firecrawl") -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    if provider == "firecrawl":
        key, env_name = first_env("FIRECRAWL_API_KEY", "FIRECRAWL")
        configured = bool(key)
    else:
        # Jina Reader 可以无密钥使用；配置密钥只是提高额度。
        _, env_name = first_env("JINA_API_KEY", "JINA")
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
        return health(provider or "firecrawl")
    if action != "extract":
        raise ToolError("UNKNOWN_ACTION", f"web_extract 不支持动作: {action}")
    chosen = provider or "firecrawl"
    func = PROVIDER_FUNCS.get(chosen)
    if func is None:
        raise ToolError("INVALID_INPUT", f"web_extract 未知 provider: {chosen}")
    return func(payload)
