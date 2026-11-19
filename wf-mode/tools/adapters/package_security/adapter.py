"""package_security：OSV.dev 实时漏洞库扫描（支持单包查询、本地项目与 GitHub 仓库）+ scorecard 备选。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from tools import cache, http_client, repo_utils
from tools.adapters import cli_tool
from tools.adapters.repo_ingest import adapter as repo_ingest_adapter
from tools.errors import ToolError
from tools.util import utc_now

SLOT = "package_security"
ACTIONS = ("scan", "query", "health")
PROVIDERS = ("osv", "scorecard")
CACHE_TTL = 12 * 3600

ECOSYSTEM_MAP = {
    "pypi": "PyPI",
    "python": "PyPI",
    "pip": "PyPI",
    "npm": "npm",
    "node": "npm",
    "js": "npm",
    "crates": "crates.io",
    "crates.io": "crates.io",
    "rust": "crates.io",
    "cargo": "crates.io",
    "go": "Go",
    "golang": "Go",
}

MANIFEST_FILENAMES = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
}


def _norm_ecosystem(raw: str | None) -> str:
    val = (raw or "").strip().lower()
    return ECOSYSTEM_MAP.get(val, raw.strip() if raw else "")


def _summarize_vuln(vuln: dict[str, Any]) -> dict[str, Any]:
    aliases = [str(a) for a in (vuln.get("aliases") or []) if a]
    severity = []
    for s in vuln.get("severity") or []:
        if isinstance(s, dict) and s.get("score"):
            severity.append(f"{s.get('type', '')}:{s.get('score')}")
    db_spec = vuln.get("database_specific") if isinstance(vuln.get("database_specific"), dict) else {}
    fixed_versions: list[str] = []
    for aff in vuln.get("affected") or []:
        if not isinstance(aff, dict):
            continue
        for rng in aff.get("ranges") or []:
            if not isinstance(rng, dict):
                continue
            for ev in rng.get("events") or []:
                if isinstance(ev, dict) and ev.get("fixed"):
                    fixed_versions.append(str(ev["fixed"]))
    vid = str(vuln.get("id") or "")
    return {
        "id": vid,
        "aliases": aliases[:5],
        "summary": str(vuln.get("summary") or vuln.get("details") or "")[:300],
        "severity": str(db_spec.get("severity") or (severity[0] if severity else "")),
        "fixed": sorted(set(fixed_versions))[:5],
        "url": f"https://osv.dev/vulnerability/{vid}" if vid else "",
    }


def _fetch_vuln_detail(vid: str) -> dict[str, Any]:
    cache_key = cache.make_key("vuln", vid)
    cached = cache.get(SLOT, "osv", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        return cached
    try:
        data = http_client.get_json(f"https://api.osv.dev/v1/vulns/{quote(vid)}", provider="osv")
        summary = _summarize_vuln(data)
        cache.put(SLOT, "osv", cache_key, summary)
        return summary
    except ToolError:
        return {
            "id": vid,
            "aliases": [],
            "summary": "",
            "severity": "",
            "fixed": [],
            "url": f"https://osv.dev/vulnerability/{vid}",
        }


def _query_single(payload: dict[str, Any]) -> dict[str, Any]:
    pkg = str(payload.get("package") or payload.get("name") or "").strip()
    if not pkg:
        raise ToolError("INVALID_INPUT", "query 需要 --package <包名>")
    eco = _norm_ecosystem(str(payload.get("ecosystem") or ""))
    version = str(payload.get("version") or "").strip()

    body: dict[str, Any] = {"package": {"name": pkg}}
    if eco:
        body["package"]["ecosystem"] = eco
    if version:
        body["version"] = version

    cache_key = cache.make_key("query", pkg, eco, version)
    cached = cache.get(SLOT, "osv", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    data = http_client.post_json("https://api.osv.dev/v1/query", body, provider="osv")
    raw_vulns = data.get("vulns") or []
    vulns = [_summarize_vuln(v) for v in raw_vulns[:20] if isinstance(v, dict)]
    out = {
        "package": pkg,
        "ecosystem": eco,
        "version": version,
        "vulnerable": bool(vulns),
        "vulnerabilityCount": len(raw_vulns),
        "vulnerabilities": vulns,
    }
    cache.put(SLOT, "osv", cache_key, out)
    out["_cached"] = False
    return out


def _collect_manifest_texts(payload: dict[str, Any]) -> tuple[str, dict[str, str]]:
    if payload.get("repo") or payload.get("url"):
        raw_repo = str(payload.get("repo") or payload.get("url"))
        owner, name = repo_utils.parse_repo(raw_repo)
        tree = repo_ingest_adapter.execute("tree", {"repo": f"{owner}/{name}"}, provider="github_api")
        files: dict[str, str] = {}
        for rel in tree.get("files") or []:
            if Path(rel).name in MANIFEST_FILENAMES:
                try:
                    files[rel] = repo_ingest_adapter._github_read_raw(owner, name, rel)
                except ToolError:
                    continue
                if len(files) >= 6:
                    break
        return f"github:{owner}/{name}", files

    root = repo_utils.resolve_local_path(payload.get("path") or ".")
    files: dict[str, str] = {}
    for rel in repo_utils.iter_project_files(root, max_files=1500):
        if Path(rel).name in MANIFEST_FILENAMES:
            try:
                files[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(files) >= 8:
                break
    return root.as_posix(), files


def _scan_osv(payload: dict[str, Any]) -> dict[str, Any]:
    target, files = _collect_manifest_texts(payload)
    deps = repo_utils.parse_dependencies_from_texts(files)
    if not deps:
        return {
            "target": target,
            "manifestsScanned": sorted(files.keys()),
            "dependencyCount": 0,
            "vulnerablePackages": 0,
            "vulnerabilities": [],
            "note": "未在目标中检测到支持的依赖清单（requirements.txt / pyproject.toml / package.json / Cargo.toml / go.mod）。",
        }

    batch_items: list[tuple[dict[str, str], dict[str, Any]]] = []
    for dep in deps[:60]:
        q: dict[str, Any] = {"package": {"name": dep["name"], "ecosystem": dep["ecosystem"]}}
        if dep.get("version"):
            q["version"] = dep["version"]
        batch_items.append((dep, q))

    resp = http_client.post_json(
        "https://api.osv.dev/v1/querybatch",
        {"queries": [q for _, q in batch_items]},
        provider="osv",
    )
    results = resp.get("results") or []
    findings: list[dict[str, Any]] = []
    detail_budget = 10
    vulnerable_pkgs: set[str] = set()

    for (dep, _), res in zip(batch_items, results):
        vulns = (res.get("vulns") or []) if isinstance(res, dict) else []
        if not vulns:
            continue
        vulnerable_pkgs.add(f"{dep['ecosystem']}:{dep['name']}")
        for v in vulns[:3]:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id") or "")
            if detail_budget > 0 and vid:
                detail = _fetch_vuln_detail(vid)
                detail_budget -= 1
            else:
                detail = {
                    "id": vid,
                    "aliases": [],
                    "summary": "",
                    "severity": "",
                    "fixed": [],
                    "url": f"https://osv.dev/vulnerability/{vid}",
                }
            findings.append(
                {
                    "package": dep["name"],
                    "ecosystem": dep["ecosystem"],
                    "versionSpec": dep["versionSpec"],
                    "versionChecked": dep["version"] or "(unpinned: all versions)",
                    **detail,
                }
            )

    return {
        "target": target,
        "manifestsScanned": sorted(files.keys()),
        "dependencyCount": len(deps),
        "checkedCount": len(batch_items),
        "vulnerablePackages": len(vulnerable_pkgs),
        "vulnerabilityCount": len(findings),
        "vulnerabilities": findings,
    }


def health(
    provider: str = "osv",
    *,
    entry: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    if provider == "osv":
        return {"ok": True, "provider": "osv", "configured": True, "checkedAt": utc_now()}
    if entry:
        return cli_tool.health(entry, "scorecard", runtime)
    return {"ok": False, "provider": "scorecard", "configured": False, "checkedAt": utc_now()}


def execute(
    action: str,
    payload: dict[str, Any],
    provider: str | None = None,
    *,
    entry: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chosen = provider or "osv"
    if action == "health":
        return health(chosen, entry=entry, runtime=runtime)
    if chosen == "scorecard":
        if not entry:
            raise ToolError("TOOL_MISSING", "缺少 scorecard 配置", allow_fallback=True)
        return cli_tool.execute(action, payload, "scorecard", entry, runtime)
    if chosen != "osv":
        raise ToolError("INVALID_INPUT", f"package_security 未知 provider: {chosen}")
    if action == "query":
        return _query_single(payload)
    if action == "scan":
        return _scan_osv(payload)
    raise ToolError("UNKNOWN_ACTION", f"package_security 不支持动作: {action}")
