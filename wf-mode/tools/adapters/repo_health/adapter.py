"""repo_health：GitHub 仓库维护活跃度、发布节奏、总线因子与许可风险评估。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from tools import cache, http_client, repo_utils
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "repo_health"
ACTIONS = ("analyze", "health")
PROVIDERS = ("github",)
CACHE_TTL = 6 * 3600


def _parse_iso(ts: str | None) -> datetime | None:
    raw = (ts or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_get_list(url: str, params: dict[str, Any] | None = None) -> list[Any]:
    try:
        data = http_client.get_json_any(
            url,
            headers=repo_utils.github_headers(),
            params=params,
            provider="github",
        )
        return data if isinstance(data, list) else []
    except ToolError as exc:
        status = (exc.details or {}).get("status")
        if status in {404, 409}:
            return []
        raise


def _analyze(payload: dict[str, Any]) -> dict[str, Any]:
    raw = str(payload.get("repo") or payload.get("url") or "").strip()
    owner, name = repo_utils.parse_repo(raw)
    cache_key = cache.make_key("analyze", owner, name)
    cached = cache.get(SLOT, "github", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    meta = http_client.get_json(
        f"https://api.github.com/repos/{owner}/{name}",
        headers=repo_utils.github_headers(),
        provider="github",
    )
    releases = _safe_get_list(
        f"https://api.github.com/repos/{owner}/{name}/releases",
        params={"per_page": 5},
    )
    commits = _safe_get_list(
        f"https://api.github.com/repos/{owner}/{name}/commits",
        params={"per_page": 30},
    )

    now = datetime.now(timezone.utc)
    pushed_dt = _parse_iso(meta.get("pushed_at"))
    days_since_push = max(0, (now - pushed_dt).days) if pushed_dt else None

    commits_30d = 0
    commits_90d = 0
    authors: Counter[str] = Counter()
    for item in commits:
        if not isinstance(item, dict):
            continue
        commit_obj = item.get("commit") if isinstance(item.get("commit"), dict) else {}
        author_obj = commit_obj.get("author") if isinstance(commit_obj.get("author"), dict) else {}
        dt = _parse_iso(author_obj.get("date"))
        if dt is not None:
            age_days = (now - dt).days
            if age_days <= 30:
                commits_30d += 1
            if age_days <= 90:
                commits_90d += 1
        login = ((item.get("author") or {}).get("login")) if isinstance(item.get("author"), dict) else None
        ident = str(login or author_obj.get("email") or author_obj.get("name") or "").strip()
        if ident:
            authors[ident] += 1

    total_sampled = sum(authors.values())
    top_share = round(authors.most_common(1)[0][1] / total_sampled, 2) if total_sampled else 0.0

    latest_rel = None
    if releases and isinstance(releases[0], dict):
        rel = releases[0]
        latest_rel = {
            "tagName": str(rel.get("tag_name") or ""),
            "name": str(rel.get("name") or ""),
            "publishedAt": str(rel.get("published_at") or ""),
            "url": str(rel.get("html_url") or ""),
            "prerelease": bool(rel.get("prerelease")),
        }

    license_obj = meta.get("license") if isinstance(meta.get("license"), dict) else {}
    spdx = str(license_obj.get("spdx_id") or "")
    lic_cat = repo_utils.license_category(spdx)
    archived = bool(meta.get("archived"))

    risk_flags: list[str] = []
    if archived:
        risk_flags.append("ARCHIVED")
    if days_since_push is not None:
        if days_since_push > 365:
            risk_flags.append("STALE_365D")
        elif days_since_push > 180:
            risk_flags.append("STALE_180D")
    if not spdx or spdx == "NOASSERTION":
        risk_flags.append("NO_LICENSE")
    elif lic_cat == "strong-copyleft":
        risk_flags.append("STRONG_COPYLEFT")
    elif lic_cat == "weak-copyleft":
        risk_flags.append("WEAK_COPYLEFT")
    if not releases:
        risk_flags.append("NO_RELEASES")
    if total_sampled >= 5 and len(authors) == 1:
        risk_flags.append("LOW_BUS_FACTOR")

    if archived:
        verdict = "archived"
    elif days_since_push is not None and days_since_push > 365:
        verdict = "stale"
    elif (days_since_push is not None and days_since_push > 90) and commits_90d == 0:
        verdict = "slowing"
    else:
        verdict = "active"

    out = {
        "repo": str(meta.get("full_name") or f"{owner}/{name}"),
        "url": str(meta.get("html_url") or f"https://github.com/{owner}/{name}"),
        "archived": archived,
        "stars": int(meta.get("stargazers_count") or 0),
        "forks": int(meta.get("forks_count") or 0),
        "openIssues": int(meta.get("open_issues_count") or 0),
        "pushedAt": str(meta.get("pushed_at") or ""),
        "daysSinceLastPush": days_since_push,
        "commitsSampled": len(commits),
        "commitsLast30d": commits_30d,
        "commitsLast90d": commits_90d,
        "uniqueRecentAuthors": len(authors),
        "topAuthorShare": top_share,
        "latestRelease": latest_rel,
        "releaseCountSampled": len(releases),
        "license": spdx,
        "licenseCategory": lic_cat,
        "verdict": verdict,
        "riskFlags": risk_flags,
    }
    cache.put(SLOT, "github", cache_key, out)
    out["_cached"] = False
    return out


def health(provider: str = "github") -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    token, env_name = first_env("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MCP_TOKEN")
    return {
        "ok": True,
        "provider": "github",
        "configured": True,
        "authenticated": bool(token),
        "env": env_name,
        "checkedAt": utc_now(),
    }


def execute(action: str, payload: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    if action == "health":
        return health(provider or "github")
    if action != "analyze":
        raise ToolError("UNKNOWN_ACTION", f"repo_health 不支持动作: {action}")
    if (provider or "github") != "github":
        raise ToolError("INVALID_INPUT", f"repo_health 未知 provider: {provider}")
    return _analyze(payload)
