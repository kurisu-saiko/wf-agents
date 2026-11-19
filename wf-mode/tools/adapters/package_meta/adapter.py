"""package_meta：PyPI / npm / crates.io / GitHub 包与发布元数据查询。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from tools import cache, http_client, repo_utils
from tools.errors import ToolError
from tools.util import utc_now

SLOT = "package_meta"
ACTIONS = ("lookup", "search", "health")
PROVIDERS = ("auto", "pypi", "npm", "crates", "github")
CACHE_TTL = 6 * 3600


def _lookup_pypi(pkg: str) -> dict[str, Any]:
    data = http_client.get_json(f"https://pypi.org/pypi/{quote(pkg)}/json", provider="pypi")
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    urls = info.get("project_urls") if isinstance(info.get("project_urls"), dict) else {}
    repo_url = urls.get("Source") or urls.get("Repository") or urls.get("Homepage") or info.get("home_page") or ""
    releases = data.get("releases") if isinstance(data.get("releases"), dict) else {}
    latest = str(info.get("version") or "")
    rel_files = releases.get(latest) if isinstance(releases.get(latest), list) else []
    published_at = str(rel_files[0].get("upload_time_iso_8601") or "") if rel_files and isinstance(rel_files[0], dict) else ""
    lic = str(info.get("license") or info.get("license_expression") or "").splitlines()[0][:120]
    return {
        "ecosystem": "pypi",
        "name": str(info.get("name") or pkg),
        "version": latest,
        "summary": str(info.get("summary") or ""),
        "license": lic,
        "homepage": str(info.get("home_page") or urls.get("Homepage") or ""),
        "repository": str(repo_url),
        "requiresPython": str(info.get("requires_python") or ""),
        "publishedAt": published_at,
        "url": f"https://pypi.org/project/{pkg}/",
    }


def _lookup_npm(pkg: str) -> dict[str, Any]:
    encoded = quote(pkg, safe="@/")
    data = http_client.get_json(f"https://registry.npmjs.org/{encoded}", provider="npm")
    dist_tags = data.get("dist-tags") if isinstance(data.get("dist-tags"), dict) else {}
    latest = str(dist_tags.get("latest") or "")
    versions = data.get("versions") if isinstance(data.get("versions"), dict) else {}
    latest_obj = versions.get(latest) if isinstance(versions.get(latest), dict) else {}
    time_map = data.get("time") if isinstance(data.get("time"), dict) else {}
    repo_obj = latest_obj.get("repository") or data.get("repository")
    repo_url = repo_obj.get("url", "") if isinstance(repo_obj, dict) else str(repo_obj or "")
    weekly = None
    try:
        dl = http_client.get_json(
            f"https://api.npmjs.org/downloads/point/last-week/{encoded}",
            provider="npm",
        )
        weekly = dl.get("downloads")
    except ToolError:
        weekly = None
    return {
        "ecosystem": "npm",
        "name": str(data.get("name") or pkg),
        "version": latest,
        "summary": str(data.get("description") or ""),
        "license": str(latest_obj.get("license") or data.get("license") or ""),
        "homepage": str(latest_obj.get("homepage") or data.get("homepage") or ""),
        "repository": str(repo_url),
        "weeklyDownloads": weekly,
        "publishedAt": str(time_map.get(latest) or ""),
        "url": f"https://www.npmjs.com/package/{pkg}",
    }


def _lookup_crates(pkg: str) -> dict[str, Any]:
    data = http_client.get_json(f"https://crates.io/api/v1/crates/{quote(pkg)}", provider="crates")
    crate = data.get("crate") if isinstance(data.get("crate"), dict) else {}
    versions = data.get("versions") if isinstance(data.get("versions"), list) else []
    latest_ver = versions[0] if versions and isinstance(versions[0], dict) else {}
    return {
        "ecosystem": "crates",
        "name": str(crate.get("name") or pkg),
        "version": str(crate.get("newest_version") or crate.get("max_version") or ""),
        "summary": str(crate.get("description") or ""),
        "license": str(latest_ver.get("license") or ""),
        "homepage": str(crate.get("homepage") or ""),
        "repository": str(crate.get("repository") or ""),
        "downloads": int(crate.get("downloads") or 0),
        "recentDownloads": int(crate.get("recent_downloads") or 0),
        "publishedAt": str(crate.get("updated_at") or ""),
        "url": f"https://crates.io/crates/{pkg}",
    }


def _lookup_github(raw_repo: str) -> dict[str, Any]:
    owner, name = repo_utils.parse_repo(raw_repo)
    meta = http_client.get_json(
        f"https://api.github.com/repos/{owner}/{name}",
        headers=repo_utils.github_headers(),
        provider="github",
    )
    releases = []
    try:
        rel = http_client.get_json_any(
            f"https://api.github.com/repos/{owner}/{name}/releases",
            headers=repo_utils.github_headers(),
            params={"per_page": 3},
            provider="github",
        )
        if isinstance(rel, list):
            releases = rel
    except ToolError:
        releases = []
    latest = releases[0] if releases and isinstance(releases[0], dict) else {}
    lic = (meta.get("license") or {}).get("spdx_id") if isinstance(meta.get("license"), dict) else ""
    return {
        "ecosystem": "github",
        "name": str(meta.get("full_name") or f"{owner}/{name}"),
        "version": str(latest.get("tag_name") or ""),
        "summary": str(meta.get("description") or ""),
        "license": str(lic or ""),
        "homepage": str(meta.get("homepage") or ""),
        "repository": str(meta.get("html_url") or ""),
        "stars": int(meta.get("stargazers_count") or 0),
        "publishedAt": str(latest.get("published_at") or meta.get("pushed_at") or ""),
        "url": str(meta.get("html_url") or ""),
    }


def _lookup(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    pkg = str(payload.get("package") or payload.get("name") or payload.get("repo") or "").strip()
    if not pkg:
        raise ToolError("INVALID_INPUT", "需要 --package <包名> 或 --repo <owner/name>")
    eco = str(payload.get("ecosystem") or "").strip().lower()
    target = eco if (provider == "auto" and eco) else provider

    if target == "auto":
        if "/" in pkg and not pkg.startswith("@"):
            order = ["github"]
        elif pkg.startswith("@"):
            order = ["npm"]
        else:
            order = ["pypi", "npm", "crates"]
    else:
        order = [target]

    cache_key = cache.make_key("lookup", pkg, ",".join(order))
    cached = cache.get(SLOT, "meta", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    funcs = {
        "pypi": _lookup_pypi,
        "npm": _lookup_npm,
        "crates": _lookup_crates,
        "github": _lookup_github,
    }
    last_err: ToolError | None = None
    for eco_name in order:
        fn = funcs.get(eco_name)
        if fn is None:
            raise ToolError("INVALID_INPUT", f"不支持的生态: {eco_name}")
        try:
            meta = fn(pkg)
            out = {"package": meta}
            cache.put(SLOT, "meta", cache_key, out)
            out["_cached"] = False
            return out
        except ToolError as exc:
            last_err = exc
            continue
    if last_err:
        raise last_err
    raise ToolError("UPSTREAM_ERROR", f"未找到包: {pkg}", allow_fallback=True)


def _search(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise ToolError("INVALID_INPUT", "search 需要 --query")
    limit = max(1, min(20, int(payload.get("maxResults") or 5)))
    eco = str(payload.get("ecosystem") or "").strip().lower()
    target = eco if (provider == "auto" and eco) else ("npm" if provider == "auto" else provider)

    results: list[dict[str, Any]] = []
    if target == "npm":
        data = http_client.get_json(
            "https://registry.npmjs.org/-/v1/search",
            params={"text": query, "size": limit},
            provider="npm",
        )
        for obj in data.get("objects") or []:
            pkg = obj.get("package") if isinstance(obj, dict) else {}
            if not isinstance(pkg, dict):
                continue
            results.append(
                {
                    "ecosystem": "npm",
                    "name": str(pkg.get("name") or ""),
                    "version": str(pkg.get("version") or ""),
                    "summary": str(pkg.get("description") or ""),
                    "url": str((pkg.get("links") or {}).get("npm") or ""),
                }
            )
    elif target == "crates":
        data = http_client.get_json(
            "https://crates.io/api/v1/crates",
            params={"q": query, "per_page": limit},
            provider="crates",
        )
        for crate in data.get("crates") or []:
            if not isinstance(crate, dict):
                continue
            results.append(
                {
                    "ecosystem": "crates",
                    "name": str(crate.get("name") or ""),
                    "version": str(crate.get("newest_version") or ""),
                    "summary": str(crate.get("description") or ""),
                    "downloads": int(crate.get("downloads") or 0),
                    "url": f"https://crates.io/crates/{crate.get('name')}",
                }
            )
    elif target == "pypi":
        # PyPI 已下线官方搜索 JSON，精确名直查 + GitHub Python 仓辅助发现
        try:
            exact = _lookup_pypi(query)
            results.append(exact)
        except ToolError:
            pass
        if len(results) < limit:
            gh = http_client.get_json(
                "https://api.github.com/search/repositories",
                headers=repo_utils.github_headers(),
                params={"q": f"{query} language:python", "per_page": limit, "sort": "stars"},
                provider="github",
            )
            for item in gh.get("items") or []:
                if isinstance(item, dict):
                    results.append(
                        {
                            "ecosystem": "github-python",
                            "name": str(item.get("full_name") or ""),
                            "summary": str(item.get("description") or ""),
                            "stars": int(item.get("stargazers_count") or 0),
                            "url": str(item.get("html_url") or ""),
                        }
                    )
    else:
        raise ToolError("INVALID_INPUT", f"package_meta search 暂不支持生态: {target}")

    return {"query": query, "ecosystem": target, "results": results[:limit]}


def health(provider: str = "auto") -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    return {"ok": True, "provider": provider, "configured": True, "checkedAt": utc_now()}


def execute(action: str, payload: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    chosen = provider or "auto"
    if action == "health":
        return health(chosen)
    if action == "lookup":
        return _lookup(payload, chosen)
    if action == "search":
        return _search(payload, chosen)
    raise ToolError("UNKNOWN_ACTION", f"package_meta 不支持动作: {action}")
