"""license_sbom：内置许可证合规分类 + 多生态依赖 SBOM 清单扫描（本地或 GitHub 仓库）。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from tools import http_client, repo_utils
from tools.adapters import cli_tool
from tools.adapters.repo_ingest import adapter as repo_ingest_adapter
from tools.errors import ToolError
from tools.util import utc_now

SLOT = "license_sbom"
ACTIONS = ("scan", "health")
PROVIDERS = ("builtin", "syft")

LICENSE_NAMES = {"LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md", "COPYING.txt"}
MANIFEST_FILENAMES = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
}


def _scan_remote(raw_repo: str) -> dict[str, Any]:
    owner, name = repo_utils.parse_repo(raw_repo)
    meta = http_client.get_json(
        f"https://api.github.com/repos/{owner}/{name}",
        headers=repo_utils.github_headers(),
        provider="github",
    )
    lic_obj = meta.get("license") if isinstance(meta.get("license"), dict) else {}
    spdx = str(lic_obj.get("spdx_id") or "")
    cat = repo_utils.license_category(spdx)

    tree = repo_ingest_adapter.execute("tree", {"repo": f"{owner}/{name}"}, provider="github_api")
    files_list = tree.get("files") or []
    lic_file = next((f for f in files_list if Path(f).name in LICENSE_NAMES), "")
    if (not spdx or spdx == "NOASSERTION") and lic_file:
        try:
            lic_text = repo_ingest_adapter._github_read_raw(owner, name, lic_file)
            spdx, cat = repo_utils.detect_license_from_text(lic_text)
        except ToolError:
            pass

    manifests: dict[str, str] = {}
    for rel in files_list:
        if Path(rel).name in MANIFEST_FILENAMES:
            try:
                manifests[rel] = repo_ingest_adapter._github_read_raw(owner, name, rel)
            except ToolError:
                continue
            if len(manifests) >= 6:
                break

    deps = repo_utils.parse_dependencies_from_texts(manifests)
    ecos = dict(Counter(d["ecosystem"] for d in deps))
    return {
        "target": f"github:{owner}/{name}",
        "license": spdx or "UNKNOWN",
        "licenseCategory": cat,
        "licenseFile": lic_file,
        "manifests": sorted(manifests.keys()),
        "dependencyCount": len(deps),
        "ecosystems": ecos,
        "dependencies": deps,
    }


def _scan_local(raw_path: str | None) -> dict[str, Any]:
    root = repo_utils.resolve_local_path(raw_path or ".")
    files_list = repo_utils.iter_project_files(root, max_files=2000)
    lic_file = next((f for f in files_list if Path(f).name in LICENSE_NAMES), "")
    spdx = "UNKNOWN"
    cat = "unknown"
    if lic_file:
        try:
            text = (root / lic_file).read_text(encoding="utf-8", errors="replace")
            spdx, cat = repo_utils.detect_license_from_text(text)
        except OSError:
            pass

    manifests: dict[str, str] = {}
    for rel in files_list:
        if Path(rel).name in MANIFEST_FILENAMES:
            try:
                manifests[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(manifests) >= 10:
                break

    deps = repo_utils.parse_dependencies_from_texts(manifests)
    ecos = dict(Counter(d["ecosystem"] for d in deps))
    return {
        "target": root.as_posix(),
        "license": spdx,
        "licenseCategory": cat,
        "licenseFile": lic_file,
        "manifests": sorted(manifests.keys()),
        "dependencyCount": len(deps),
        "ecosystems": ecos,
        "dependencies": deps,
    }


def health(
    provider: str = "builtin",
    *,
    entry: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    if provider == "builtin":
        return {"ok": True, "provider": "builtin", "configured": True, "checkedAt": utc_now()}
    if entry:
        return cli_tool.health(entry, "syft", runtime)
    return {"ok": False, "provider": "syft", "configured": False, "checkedAt": utc_now()}


def execute(
    action: str,
    payload: dict[str, Any],
    provider: str | None = None,
    *,
    entry: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chosen = provider or "builtin"
    if action == "health":
        return health(chosen, entry=entry, runtime=runtime)
    if action != "scan":
        raise ToolError("UNKNOWN_ACTION", f"license_sbom 不支持动作: {action}")
    if chosen == "syft":
        if not entry:
            raise ToolError("TOOL_MISSING", "缺少 syft 配置", allow_fallback=True)
        return cli_tool.execute("scan", payload, "syft", entry, runtime)
    if chosen != "builtin":
        raise ToolError("INVALID_INPUT", f"license_sbom 未知 provider: {chosen}")
    if payload.get("repo") or payload.get("url"):
        return _scan_remote(str(payload.get("repo") or payload.get("url")))
    return _scan_local(payload.get("path"))
