"""project_search：GitHub 仓库发现、详细元数据查询与代码搜索。"""

from __future__ import annotations

from typing import Any, Callable

from tools import cache, http_client, repo_utils
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "project_search"
ACTIONS = ("search", "lookup", "search_code", "health")
PROVIDERS = ("github",)
CACHE_TTL = 6 * 3600


def _headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    return repo_utils.github_headers(accept=accept)


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
        "forks": int(item.get("forks_count") or 0),
        "openIssues": int(item.get("open_issues_count") or 0),
        "updatedAt": str(item.get("updated_at") or ""),
        "pushedAt": str(item.get("pushed_at") or ""),
        "createdAt": str(item.get("created_at") or ""),
        "license": str(license_obj.get("spdx_id") or ""),
        "archived": bool(item.get("archived")),
        "language": str(item.get("language") or ""),
        "topics": [str(t) for t in (item.get("topics") or []) if t],
        "homepage": str(item.get("homepage") or ""),
        "defaultBranch": str(item.get("default_branch") or ""),
        "sizeKb": int(item.get("size") or 0),
    }


def _build_repo_query(payload: dict[str, Any]) -> str:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("INVALID_INPUT", "query 必须是非空字符串")
    parts = [query.strip()]
    if payload.get("language"):
        parts.append(f"language:{str(payload['language']).strip()}")
    if payload.get("minStars") is not None:
        parts.append(f"stars:>={int(payload['minStars'])}")
    if payload.get("license"):
        parts.append(f"license:{str(payload['license']).strip()}")
    if payload.get("topic"):
        parts.append(f"topic:{str(payload['topic']).strip()}")
    if payload.get("pushedAfter"):
        parts.append(f"pushed:>={str(payload['pushedAfter']).strip()}")
    return " ".join(parts)


def _search(payload: dict[str, Any]) -> dict[str, Any]:
    q = _build_repo_query(payload)
    limit = _max_results(payload)
    sort_raw = str(payload.get("sort") or "stars").strip()
    params: dict[str, Any] = {"q": q, "per_page": limit, "order": "desc"}
    if sort_raw in {"stars", "forks", "updated", "help-wanted-issues"}:
        params["sort"] = sort_raw

    cache_key = cache.make_key("search", q, limit, sort_raw)
    cached = cache.get(SLOT, "github", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    data = http_client.get_json(
        "https://api.github.com/search/repositories",
        headers=_headers(),
        params=params,
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
    out = {
        "query": q,
        "totalCount": int(data.get("total_count") or len(items)),
        "candidates": [_normalize(item) for item in items[:limit] if isinstance(item, dict)],
    }
    cache.put(SLOT, "github", cache_key, out)
    out["_cached"] = False
    return out


def _lookup(payload: dict[str, Any]) -> dict[str, Any]:
    raw = str(payload.get("repo") or payload.get("url") or "")
    owner, name = repo_utils.parse_repo(raw)
    cache_key = cache.make_key("lookup", owner, name)
    cached = cache.get(SLOT, "github", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    data = http_client.get_json(
        f"https://api.github.com/repos/{owner}/{name}",
        headers=_headers(),
        provider="github",
    )
    out = {"candidate": _normalize(data)}
    cache.put(SLOT, "github", cache_key, out)
    out["_cached"] = False
    return out


def _search_code(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("INVALID_INPUT", "query 必须是非空字符串")
    limit = _max_results(payload)
    parts = [query.strip()]
    if payload.get("repo"):
        owner, name = repo_utils.parse_repo(str(payload["repo"]))
        parts.append(f"repo:{owner}/{name}")
    if payload.get("language"):
        parts.append(f"language:{str(payload['language']).strip()}")
    if payload.get("path"):
        parts.append(f"path:{str(payload['path']).strip()}")
    q = " ".join(parts)

    cache_key = cache.make_key("code", q, limit)
    cached = cache.get(SLOT, "github", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    data = http_client.get_json(
        "https://api.github.com/search/code",
        headers=_headers(accept="application/vnd.github.text-match+json"),
        params={"q": q, "per_page": limit},
        provider="github",
    )
    items = data.get("items")
    if not isinstance(items, list):
        raise ToolError(
            "UPSTREAM_ERROR",
            "GitHub code search 返回缺少 items 数组",
            details={"provider": "github"},
            allow_fallback=True,
        )
    matches = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        repo_info = item.get("repository") if isinstance(item.get("repository"), dict) else {}
        snippets = []
        for tm in item.get("text_matches") or []:
            if isinstance(tm, dict) and tm.get("fragment"):
                snippets.append(str(tm["fragment"]))
        matches.append(
            {
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
                "repository": str(repo_info.get("full_name") or ""),
                "url": str(item.get("html_url") or ""),
                "fragments": snippets[:3],
            }
        )
    out = {
        "query": q,
        "totalCount": int(data.get("total_count") or len(matches)),
        "matches": matches,
    }
    cache.put(SLOT, "github", cache_key, out)
    out["_cached"] = False
    return out


PROVIDER_FUNCS: dict[str, dict[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "github": {"search": _search, "lookup": _lookup, "search_code": _search_code}
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
