"""project_search：GitHub REST API。"""

from __future__ import annotations

import os
import re
from typing import Any, Callable
from urllib.parse import urlparse

from tools import http_client
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "project_search"
ACTIONS = ("search", "lookup", "health")
PROVIDERS = ("github",)

REPO_RE = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token, _ = first_env("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MCP_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _max_results(payload: dict[str, Any]) -> int:
    raw = payload.get("maxResults", payload.get("max_results", 5))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError("INVALID_INPUT", "maxResults 必须是整数") from exc
    if not 1 <= value <= 30:
        raise ToolError("INVALID_INPUT", "maxResults 必须在 1–30 之间")
    return value


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    license_obj = item.get("license") if isinstance(item.get("license"), dict) else {}
    return {
        "name": str(item.get("name") or ""),
        "fullName": str(item.get("full_name") or ""),
        "url": str(item.get("html_url") or ""),
        "description": str(item.get("description") or ""),
        "stars": int(item.get("stargazers_count") or 0),
        "updatedAt": str(item.get("updated_at") or ""),
        "license": str(license_obj.get("spdx_id") or ""),
        "archived": bool(item.get("archived")),
        "language": str(item.get("language") or ""),
    }


def _search(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("INVALID_INPUT", "query 必须是非空字符串")
    limit = _max_results(payload)
    data = http_client.get_json(
        "https://api.github.com/search/repositories",
        headers=_headers(),
        params={
            "q": query.strip(),
            "per_page": limit,
            "sort": str(payload.get("sort") or "stars"),
            "order": "desc",
        },
        provider="github",
    )
    items = data.get("items")
    if not isinstance(items, list):
        raise ToolError(
            "UPSTREAM_ERROR",
            "GitHub 返回缺少 items 数组",
            details={"provider": "github"},
            allow_fallback=True,
        )
    return {
        "query": query.strip(),
        "candidates": [_normalize(item) for item in items[:limit] if isinstance(item, dict)],
    }


def _parse_repo(payload: dict[str, Any]) -> tuple[str, str]:
    raw = payload.get("repo") or payload.get("url") or ""
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("INVALID_INPUT", "repo 或 url 必须提供")
    value = raw.strip()
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ToolError("INVALID_INPUT", "只支持 github.com 仓库 URL")
        value = parsed.path.strip("/")
        parts = value.split("/")
        if len(parts) < 2:
            raise ToolError("INVALID_INPUT", "GitHub URL 缺少 owner/name")
        value = f"{parts[0]}/{parts[1]}"
    match = REPO_RE.match(value)
    if not match:
        raise ToolError("INVALID_INPUT", "repo 必须是 owner/name")
    return match.group(1), match.group(2)


def _lookup(payload: dict[str, Any]) -> dict[str, Any]:
    owner, name = _parse_repo(payload)
    data = http_client.get_json(
        f"https://api.github.com/repos/{owner}/{name}",
        headers=_headers(),
        provider="github",
    )
    return {"candidate": _normalize(data)}


PROVIDER_FUNCS: dict[str, dict[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "github": {"search": _search, "lookup": _lookup}
}


def health(provider: str = "github") -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    token, env_name = first_env("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MCP_TOKEN")
    return {
        "ok": True,
        "provider": "github",
        "configured": bool(token),
        "authenticated": bool(token),
        "env": env_name,
        "checkedAt": utc_now(),
    }


def execute(action: str, payload: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    if action == "health":
        return health(provider or "github")
    chosen = provider or "github"
    funcs = PROVIDER_FUNCS.get(chosen)
    if funcs is None:
        raise ToolError("INVALID_INPUT", f"project_search 未知 provider: {chosen}")
    func = funcs.get(action)
    if func is None:
        raise ToolError("UNKNOWN_ACTION", f"project_search 不支持动作: {action}")
    return func(payload)
