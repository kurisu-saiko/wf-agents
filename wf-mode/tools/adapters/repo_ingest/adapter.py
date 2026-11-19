"""repo_ingest：混合仓库与本地项目上下文读取器（GitHub API / 本地读取 / gitingest CLI）。"""

from __future__ import annotations

import base64
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from tools import cache, http_client, repo_utils
from tools.adapters import cli_tool
from tools.errors import ToolError
from tools.util import first_env, utc_now

SLOT = "repo_ingest"
ACTIONS = ("ingest", "tree", "read", "readme", "health")
PROVIDERS = ("github_api", "local", "gitingest")
DEFAULT_MAX_CHARS = 24000
MAX_CHARS_CAP = 80000
CACHE_TTL = 3600


def _max_chars(payload: dict[str, Any]) -> int:
    raw = payload.get("maxChars")
    if raw is None or raw == "":
        return DEFAULT_MAX_CHARS
    try:
        return max(1000, min(MAX_CHARS_CAP, int(raw)))
    except (TypeError, ValueError) as exc:
        raise ToolError("INVALID_INPUT", "maxChars 必须是整数") from exc


def _line_range(payload: dict[str, Any]) -> tuple[int, int]:
    start = int(payload.get("startLine") or 1)
    end = int(payload.get("endLine") or (start + 299))
    if start < 1:
        start = 1
    if end < start:
        end = start + 299
    return start, min(end, start + 799)


def _format_lines(text: str, start: int, end: int) -> dict[str, Any]:
    lines = text.splitlines()
    total = len(lines)
    sliced = lines[start - 1 : end]
    numbered = "\n".join(f"{idx}: {line}" for idx, line in enumerate(sliced, start=start))
    return {
        "totalLines": total,
        "startLine": start,
        "endLine": min(end, total),
        "truncated": total > end,
        "content": numbered,
    }


def _summarize_files(files: list[str]) -> tuple[dict[str, int], list[str]]:
    lang_counts: Counter[str] = Counter()
    manifests: list[str] = []
    for rel in files:
        lang = repo_utils.detect_language(rel)
        if lang and lang not in {"Markdown", "JSON", "YAML", "TOML"}:
            lang_counts[lang] += 1
        if Path(rel).name in repo_utils.MANIFEST_FILES:
            manifests.append(rel)
    return dict(lang_counts.most_common(12)), manifests[:25]


def _local_root(payload: dict[str, Any]) -> Path:
    raw = payload.get("path")
    if not raw:
        raise ToolError("INVALID_INPUT", "本地读取需要 --path", allow_fallback=True)
    return repo_utils.resolve_local_path(str(raw))


def _local_tree(payload: dict[str, Any]) -> dict[str, Any]:
    root = _local_root(payload)
    files = repo_utils.iter_project_files(root, max_files=2500)
    langs, manifests = _summarize_files(files)
    return {
        "source": "local",
        "path": root.as_posix(),
        "totalFiles": len(files),
        "truncated": len(files) > 400,
        "files": files[:400],
        "languages": langs,
        "manifests": manifests,
    }


def _local_read(payload: dict[str, Any]) -> dict[str, Any]:
    root = _local_root(payload)
    sub = str(payload.get("file") or payload.get("subpath") or "").strip()
    if root.is_file() and not sub:
        target = root
    else:
        if not sub:
            raise ToolError("INVALID_INPUT", "读取文件需要 --file 或指向文件的 --path")
        target = (root / sub).resolve()
        if not target.is_relative_to(root):
            raise ToolError("INVALID_INPUT", "文件路径超出项目根目录")
    if not target.is_file():
        raise ToolError("INVALID_INPUT", f"文件不存在: {target}")
    text = target.read_text(encoding="utf-8", errors="replace")
    start, end = _line_range(payload)
    formatted = _format_lines(text, start, end)
    formatted["source"] = "local"
    formatted["file"] = target.name if root.is_file() else target.relative_to(root).as_posix()
    return formatted


def _local_readme(payload: dict[str, Any]) -> dict[str, Any]:
    root = _local_root(payload)
    if root.is_file():
        text = root.read_text(encoding="utf-8", errors="replace")
        return {"source": "local", "file": root.name, "text": text[:_max_chars(payload)]}
    for name in ("README.md", "README.rst", "README.txt", "README", "readme.md"):
        cand = root / name
        if cand.is_file():
            text = cand.read_text(encoding="utf-8", errors="replace")
            return {"source": "local", "file": name, "text": text[:_max_chars(payload)]}
    return {"source": "local", "file": "", "text": ""}


def _local_ingest(payload: dict[str, Any]) -> dict[str, Any]:
    limit = _max_chars(payload)
    tree = _local_tree(payload)
    readme = _local_readme(payload)
    root = Path(tree["path"])
    manifest_snippets: dict[str, str] = {}
    for rel in tree["manifests"][:6]:
        try:
            manifest_snippets[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")[:2500]
        except OSError:
            continue
    digest = _compose_digest(
        header=f"Local Project: {tree['path']}",
        files=tree["files"],
        total_files=tree["totalFiles"],
        languages=tree["languages"],
        manifests=manifest_snippets,
        readme_text=readme["text"],
        max_chars=limit,
    )
    return {
        "source": "local",
        "path": tree["path"],
        "totalFiles": tree["totalFiles"],
        "languages": tree["languages"],
        "manifests": tree["manifests"],
        "digest": digest,
    }


def _github_repo(payload: dict[str, Any]) -> tuple[str, str]:
    raw = str(payload.get("repo") or payload.get("url") or "").strip()
    if not raw:
        raise ToolError("INVALID_INPUT", "需要 --repo owner/name 或 --path <本地路径>", allow_fallback=True)
    return repo_utils.parse_repo(raw)


def _github_meta(owner: str, name: str) -> dict[str, Any]:
    return http_client.get_json(
        f"https://api.github.com/repos/{owner}/{name}",
        headers=repo_utils.github_headers(),
        provider="github_api",
    )


def _github_tree(payload: dict[str, Any]) -> dict[str, Any]:
    owner, name = _github_repo(payload)
    branch = str(payload.get("ref") or "").strip()
    cache_key = cache.make_key("tree", owner, name, branch)
    cached = cache.get(SLOT, "github_api", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        cached["_cached"] = True
        return cached

    meta = _github_meta(owner, name)
    ref = branch or str(meta.get("default_branch") or "main")
    tree_data = http_client.get_json(
        f"https://api.github.com/repos/{owner}/{name}/git/trees/{ref}",
        headers=repo_utils.github_headers(),
        params={"recursive": "1"},
        provider="github_api",
    )
    raw_tree = tree_data.get("tree") or []
    files: list[str] = []
    for item in raw_tree:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        p = str(item.get("path") or "")
        parts = p.split("/")
        if any(part in repo_utils.IGNORE_DIRS for part in parts[:-1]):
            continue
        files.append(p)

    langs, manifests = _summarize_files(files)
    out = {
        "source": "github_api",
        "repo": f"{owner}/{name}",
        "defaultBranch": ref,
        "treeTruncatedByApi": bool(tree_data.get("truncated")),
        "totalFiles": len(files),
        "truncated": len(files) > 400,
        "files": files[:400],
        "languages": langs,
        "manifests": manifests,
    }
    cache.put(SLOT, "github_api", cache_key, out)
    out["_cached"] = False
    return out


def _github_read_raw(owner: str, name: str, file_path: str, ref: str = "") -> str:
    params = {"ref": ref} if ref else None
    data = http_client.get_json(
        f"https://api.github.com/repos/{owner}/{name}/contents/{file_path.lstrip('/')}",
        headers=repo_utils.github_headers(),
        params=params,
        provider="github_api",
    )
    encoding = data.get("encoding")
    content = data.get("content")
    if encoding == "base64" and isinstance(content, str) and content.strip():
        return base64.b64decode(content).decode("utf-8", errors="replace")
    dl_url = str(data.get("download_url") or "")
    if dl_url:
        return http_client.get_text(dl_url, provider="github_api")
    raise ToolError("UPSTREAM_ERROR", f"无法读取远程文件: {file_path}", allow_fallback=True)


def _github_read(payload: dict[str, Any]) -> dict[str, Any]:
    owner, name = _github_repo(payload)
    file_path = str(payload.get("file") or payload.get("subpath") or "").strip()
    if not file_path:
        raise ToolError("INVALID_INPUT", "读取仓库文件需要 --file <相对路径>")
    ref = str(payload.get("ref") or "").strip()
    cache_key = cache.make_key("read", owner, name, file_path, ref)
    cached_raw = cache.get(SLOT, "github_api", cache_key, ttl=CACHE_TTL)
    if isinstance(cached_raw, dict) and isinstance(cached_raw.get("text"), str):
        text = cached_raw["text"]
        was_cached = True
    else:
        text = _github_read_raw(owner, name, file_path, ref=ref)
        cache.put(SLOT, "github_api", cache_key, {"text": text[:100000]})
        was_cached = False

    start, end = _line_range(payload)
    formatted = _format_lines(text, start, end)
    formatted["source"] = "github_api"
    formatted["repo"] = f"{owner}/{name}"
    formatted["file"] = file_path
    formatted["_cached"] = was_cached
    return formatted


def _github_readme(payload: dict[str, Any]) -> dict[str, Any]:
    owner, name = _github_repo(payload)
    limit = _max_chars(payload)
    cache_key = cache.make_key("readme", owner, name)
    cached = cache.get(SLOT, "github_api", cache_key, ttl=CACHE_TTL)
    if isinstance(cached, dict):
        out = dict(cached)
        out["text"] = str(out.get("text") or "")[:limit]
        out["_cached"] = True
        return out

    try:
        data = http_client.get_json(
            f"https://api.github.com/repos/{owner}/{name}/readme",
            headers=repo_utils.github_headers(),
            provider="github_api",
        )
        raw_b64 = str(data.get("content") or "")
        text = base64.b64decode(raw_b64).decode("utf-8", errors="replace") if raw_b64 else ""
        fname = str(data.get("name") or "README.md")
    except ToolError as exc:
        if (exc.details or {}).get("status") == 404:
            text, fname = "", ""
        else:
            raise
    out = {"source": "github_api", "repo": f"{owner}/{name}", "file": fname, "text": text[:40000]}
    cache.put(SLOT, "github_api", cache_key, out)
    out = dict(out)
    out["text"] = out["text"][:limit]
    out["_cached"] = False
    return out


def _compose_digest(
    *,
    header: str,
    files: list[str],
    total_files: int,
    languages: dict[str, int],
    manifests: dict[str, str],
    readme_text: str,
    max_chars: int,
) -> str:
    sections = [f"# {header}", f"Total files: {total_files}"]
    if languages:
        lang_str = ", ".join(f"{k}: {v}" for k, v in languages.items())
        sections.append(f"Languages: {lang_str}")
    tree_block = "\n".join(files[:120])
    if len(files) > 120:
        tree_block += f"\n... ({len(files) - 120} more in sample)"
    sections.append("## File Tree (sample)\n" + tree_block)
    if manifests:
        m_parts = [f"### {name}\n```\n{body.strip()}\n```" for name, body in manifests.items()]
        sections.append("## Key Manifests\n" + "\n\n".join(m_parts))
    if readme_text.strip():
        sections.append("## README\n" + readme_text.strip())
    return "\n\n".join(sections)[:max_chars]


def _github_ingest(payload: dict[str, Any]) -> dict[str, Any]:
    limit = _max_chars(payload)
    owner, name = _github_repo(payload)
    tree = _github_tree({"repo": f"{owner}/{name}"})
    readme = _github_readme({"repo": f"{owner}/{name}", "maxChars": min(limit, 12000)})
    manifests: dict[str, str] = {}
    for rel in tree.get("manifests", [])[:5]:
        try:
            manifests[rel] = _github_read_raw(owner, name, rel)[:2500]
        except ToolError:
            continue
    digest = _compose_digest(
        header=f"GitHub Repo: {owner}/{name} (branch: {tree.get('defaultBranch', 'main')})",
        files=tree["files"],
        total_files=tree["totalFiles"],
        languages=tree["languages"],
        manifests=manifests,
        readme_text=readme["text"],
        max_chars=limit,
    )
    return {
        "source": "github_api",
        "repo": f"{owner}/{name}",
        "defaultBranch": tree.get("defaultBranch", "main"),
        "totalFiles": tree["totalFiles"],
        "languages": tree["languages"],
        "manifests": tree["manifests"],
        "digest": digest,
    }


def _dispatch_github_api(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    # 若只传了 --path 没传 --repo，自动走本地路径读取，避免误报错。
    if payload.get("path") and not payload.get("repo") and not payload.get("url"):
        return _dispatch_local(action, payload)
    if action == "tree":
        return _github_tree(payload)
    if action == "read":
        return _github_read(payload)
    if action == "readme":
        return _github_readme(payload)
    if action == "ingest":
        return _github_ingest(payload)
    raise ToolError("UNKNOWN_ACTION", f"repo_ingest 不支持动作: {action}")


def _dispatch_local(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "tree":
        return _local_tree(payload)
    if action == "read":
        return _local_read(payload)
    if action == "readme":
        return _local_readme(payload)
    if action == "ingest":
        return _local_ingest(payload)
    raise ToolError("UNKNOWN_ACTION", f"repo_ingest 不支持动作: {action}")


def _dispatch_gitingest(
    action: str,
    payload: dict[str, Any],
    entry: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
) -> dict[str, Any]:
    if action != "ingest":
        raise ToolError("UNKNOWN_ACTION", "gitingest 仅支持 ingest 动作", allow_fallback=True)
    if not entry:
        raise ToolError("TOOL_MISSING", "缺少 gitingest 配置", allow_fallback=True)
    return cli_tool.execute("ingest", payload, "gitingest", entry, runtime)


def health(
    provider: str = "github_api",
    *,
    entry: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ToolError("INVALID_INPUT", f"未知 provider: {provider}")
    if provider == "github_api":
        token, env_name = first_env("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MCP_TOKEN")
        return {
            "ok": True,
            "provider": provider,
            "configured": True,
            "authenticated": bool(token),
            "env": env_name,
            "checkedAt": utc_now(),
        }
    if provider == "local":
        return {"ok": True, "provider": provider, "configured": True, "checkedAt": utc_now()}
    if entry:
        return cli_tool.health(entry, "gitingest", runtime)
    return {"ok": False, "provider": "gitingest", "configured": False, "checkedAt": utc_now()}


def execute(
    action: str,
    payload: dict[str, Any],
    provider: str | None = None,
    *,
    entry: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chosen = provider or "github_api"
    if action == "health":
        return health(chosen, entry=entry, runtime=runtime)
    if action not in ACTIONS:
        raise ToolError("UNKNOWN_ACTION", f"repo_ingest 不支持动作: {action}")
    funcs: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
        "github_api": _dispatch_github_api,
        "local": _dispatch_local,
    }
    if chosen in funcs:
        return funcs[chosen](action, payload)
    if chosen == "gitingest":
        return _dispatch_gitingest(action, payload, entry, runtime)
    raise ToolError("INVALID_INPUT", f"repo_ingest 未知 provider: {chosen}")
