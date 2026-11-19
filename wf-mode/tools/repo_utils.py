"""共用项目读取、GitHub 定位、.gitignore 过滤、依赖/锁文件解析与许可证识别工具。"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore

from tools.errors import ToolError
from tools.util import first_env

REPO_RE = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")

IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    "coverage",
    ".wf",
    "vendor",
    ".tox",
    ".eggs",
}

BINARY_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".db",
    ".mp3",
    ".mp4",
    ".wav",
}

MANIFEST_FILES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Gemfile",
    "composer.json",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "plugin.json",
}

LOCKFILE_NAMES = {
    "package-lock.json",
    "uv.lock",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
}

EXT_LANG = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sh": "Shell",
    ".ps1": "PowerShell",
    ".md": "Markdown",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".html": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
}

PERMISSIVE_LICENSES = {
    "MIT",
    "MIT-0",
    "APACHE-2.0",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "ISC",
    "UNLICENSE",
    "CC0-1.0",
    "ZLIB",
    "ARTISTIC-2.0",
    "BSL-1.0",
}
WEAK_COPYLEFT_LICENSES = {
    "MPL-2.0",
    "LGPL-2.1",
    "LGPL-2.1-ONLY",
    "LGPL-2.1-OR-LATER",
    "LGPL-3.0",
    "LGPL-3.0-ONLY",
    "LGPL-3.0-OR-LATER",
    "EPL-2.0",
    "EPL-1.0",
}
STRONG_COPYLEFT_LICENSES = {
    "GPL-2.0",
    "GPL-2.0-ONLY",
    "GPL-2.0-OR-LATER",
    "GPL-3.0",
    "GPL-3.0-ONLY",
    "GPL-3.0-OR-LATER",
    "AGPL-3.0",
    "AGPL-3.0-ONLY",
    "AGPL-3.0-OR-LATER",
    "SSPL-1.0",
}

_PEP508_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)$")


def parse_repo(raw: str) -> tuple[str, str]:
    value = (raw or "").strip()
    if not value:
        raise ToolError("INVALID_INPUT", "repo 或 url 必须提供")
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ToolError("INVALID_INPUT", "只支持 github.com 仓库 URL")
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) < 2:
            raise ToolError("INVALID_INPUT", "GitHub URL 缺少 owner/name")
        owner, name = parts[0], parts[1]
        if name.endswith(".git"):
            name = name[:-4]
        value = f"{owner}/{name}"
    if value.endswith(".git"):
        value = value[:-4]
    match = REPO_RE.match(value)
    if not match:
        raise ToolError("INVALID_INPUT", "repo 必须是 owner/name")
    return match.group(1), match.group(2)


def github_headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token, _ = first_env("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MCP_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def resolve_local_path(raw: str | Path | None) -> Path:
    value = str(raw or ".").strip()
    path = Path(value).expanduser()
    if not path.exists():
        raise ToolError("INVALID_INPUT", f"本地路径不存在: {value}")
    return path.resolve()


def load_gitignore_patterns(root: Path) -> list[str]:
    gi = root / ".gitignore"
    if not gi.is_file():
        return []
    patterns: list[str] = []
    try:
        for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("!"):
                continue
            patterns.append(s)
    except OSError:
        return []
    return patterns


def _is_gitignored(rel_posix: str, is_dir: bool, patterns: list[str]) -> bool:
    if not patterns:
        return False
    name = rel_posix.rsplit("/", 1)[-1]
    for raw in patterns:
        dir_only = raw.endswith("/")
        pat = raw.rstrip("/")
        if not pat:
            continue
        if dir_only and not is_dir:
            # 目录规则也过滤其下文件
            if any(fnmatch.fnmatch(part, pat.lstrip("/")) for part in rel_posix.split("/")[:-1]):
                return True
            continue
        anchored = pat.startswith("/")
        clean = pat.lstrip("/")
        if anchored:
            if fnmatch.fnmatch(rel_posix, clean):
                return True
        else:
            if fnmatch.fnmatch(name, clean) or fnmatch.fnmatch(rel_posix, clean):
                return True
    return False


def iter_project_files(
    root: Path,
    *,
    max_files: int = 2500,
    include_hidden: bool = False,
    respect_gitignore: bool = True,
) -> list[str]:
    if root.is_file():
        return [root.name]
    patterns = load_gitignore_patterns(root) if respect_gitignore else []
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        rel_prefix = "" if str(rel_dir) == "." else rel_dir.as_posix() + "/"

        kept_dirs: list[str] = []
        for d in sorted(dirnames):
            if d in IGNORE_DIRS or (not include_hidden and d.startswith(".")):
                continue
            if _is_gitignored(rel_prefix + d, True, patterns):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fname in sorted(filenames):
            if not include_hidden and fname.startswith(".") and fname not in {".gitignore", ".env.example"}:
                continue
            rel = rel_prefix + fname
            if _is_gitignored(rel, False, patterns):
                continue
            results.append(rel)
            if len(results) >= max_files:
                return results
    return results


def detect_language(rel_path: str) -> str:
    ext = Path(rel_path).suffix.lower()
    return EXT_LANG.get(ext, "")


def _single_license_category(code: str) -> str:
    c = code.strip().upper()
    if not c or c in {"NOASSERTION", "NONE", "UNKNOWN"}:
        return "unknown"
    if c in PERMISSIVE_LICENSES:
        return "permissive"
    if c in WEAK_COPYLEFT_LICENSES:
        return "weak-copyleft"
    if c in STRONG_COPYLEFT_LICENSES:
        return "strong-copyleft"
    if "AGPL" in c or "GPL" in c:
        return "weak-copyleft" if "LGPL" in c else "strong-copyleft"
    if "MPL" in c or "EPL" in c or "CDDL" in c:
        return "weak-copyleft"
    if "MIT" in c or "APACHE" in c or "BSD" in c or "ISC" in c:
        return "permissive"
    return "unknown"


def license_category(spdx: str | None) -> str:
    """支持复合 SPDX 表达式（如 'MIT OR Apache-2.0' / 'MIT AND GPL-3.0'）。"""
    raw = (spdx or "").strip()
    if not raw:
        return "unknown"
    if " OR " in raw.upper():
        parts = [p.strip(" ()") for p in re.split(r"\s+OR\s+", raw, flags=re.I) if p.strip()]
        cats = [_single_license_category(p) for p in parts]
        for pref in ("permissive", "weak-copyleft", "strong-copyleft"):
            if pref in cats:
                return pref
        return "unknown"
    if " AND " in raw.upper():
        parts = [p.strip(" ()") for p in re.split(r"\s+AND\s+", raw, flags=re.I) if p.strip()]
        cats = [_single_license_category(p) for p in parts]
        for strict in ("strong-copyleft", "weak-copyleft", "unknown", "permissive"):
            if strict in cats:
                return strict
        return "unknown"
    return _single_license_category(raw)


def detect_license_from_text(text: str) -> tuple[str, str]:
    sample = (text or "")[:6000]
    lower = sample.lower()
    if not lower.strip():
        return "UNKNOWN", "unknown"
    if "gnu affero general public license" in lower or "agpl" in lower:
        return "AGPL-3.0", "strong-copyleft"
    if "gnu lesser general public license" in lower:
        spdx = "LGPL-3.0" if "version 3" in lower else "LGPL-2.1"
        return spdx, "weak-copyleft"
    if "gnu general public license" in lower:
        spdx = "GPL-3.0" if "version 3" in lower else ("GPL-2.0" if "version 2" in lower else "GPL")
        return spdx, "strong-copyleft"
    if "mozilla public license" in lower and "2.0" in lower:
        return "MPL-2.0", "weak-copyleft"
    if "apache license" in lower and "2.0" in lower:
        return "Apache-2.0", "permissive"
    if "permission is hereby granted, free of charge" in lower or "mit license" in lower:
        return "MIT", "permissive"
    if "redistribution and use in source and binary forms" in lower:
        if "neither the name of" in lower:
            return "BSD-3-Clause", "permissive"
        return "BSD-2-Clause", "permissive"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in lower:
        return "ISC", "permissive"
    if "this is free and unencumbered software released into the public domain" in lower:
        return "Unlicense", "permissive"
    return "UNKNOWN", "unknown"


def _parse_pep508(spec: str) -> tuple[str, str]:
    cleaned = spec.split(";", 1)[0].strip()
    match = _PEP508_RE.match(cleaned)
    if not match:
        return "", ""
    return match.group(1), match.group(2).strip()


def _clean_version(spec: str) -> str:
    raw = (spec or "").strip()
    match = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[A-Za-z0-9._-]+)?)", raw)
    return match.group(1) if match else ""


def parse_dependencies_from_texts(files: dict[str, str]) -> list[dict[str, str]]:
    """从清单与锁文件解析依赖（同生态+包名时，锁文件的精确版本优先覆盖范围约束）。"""
    deps_by_key: dict[tuple[str, str], dict[str, str]] = {}

    def put(name: str, spec: str, ecosystem: str, scope: str, source: str, *, locked: bool = False) -> None:
        norm = name.strip()
        if not norm:
            return
        key = (ecosystem.lower(), norm.lower())
        existing = deps_by_key.get(key)
        if existing and existing.get("locked") and not locked:
            return
        deps_by_key[key] = {
            "name": norm,
            "versionSpec": spec.strip(),
            "version": _clean_version(spec),
            "ecosystem": ecosystem,
            "scope": scope,
            "source": source,
            "locked": locked,  # type: ignore[dict-item]
        }

    # 先解析普通清单，再解析锁文件以便精确版本覆盖
    ordered = sorted(
        files.items(),
        key=lambda kv: (1 if Path(kv[0]).name in LOCKFILE_NAMES else 0, kv[0]),
    )

    for rel, content in ordered:
        lower = Path(rel).name.lower()
        if lower.startswith("requirements") and lower.endswith(".txt"):
            scope = "dev" if "dev" in lower or "test" in lower else "runtime"
            for line in content.splitlines():
                stripped = line.split("#", 1)[0].strip()
                if not stripped or stripped.startswith(("-", "--", "git+", "http://", "https://")):
                    continue
                name, spec = _parse_pep508(stripped)
                put(name, spec, "PyPI", scope, rel, locked=spec.startswith("=="))

        elif lower == "pyproject.toml" and tomllib is not None:
            try:
                parsed = tomllib.loads(content)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                proj = parsed.get("project") or {}
                for item in proj.get("dependencies") or []:
                    if isinstance(item, str):
                        name, spec = _parse_pep508(item)
                        put(name, spec, "PyPI", "runtime", rel)
                for group, items in (proj.get("optional-dependencies") or {}).items():
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, str):
                                name, spec = _parse_pep508(item)
                                put(name, spec, "PyPI", f"optional:{group}", rel)
                poetry = ((parsed.get("tool") or {}).get("poetry") or {})
                for pkg, ver in (poetry.get("dependencies") or {}).items():
                    if pkg.lower() == "python":
                        continue
                    spec = ver if isinstance(ver, str) else str((ver or {}).get("version", "")) if isinstance(ver, dict) else ""
                    put(str(pkg), spec, "PyPI", "runtime", rel)

        elif lower == "package.json":
            try:
                pkg = json.loads(content)
            except ValueError:
                pkg = {}
            if isinstance(pkg, dict):
                for section, scope in (
                    ("dependencies", "runtime"),
                    ("devDependencies", "dev"),
                    ("peerDependencies", "peer"),
                ):
                    mapping = pkg.get(section) or {}
                    if isinstance(mapping, dict):
                        for name, spec in mapping.items():
                            put(str(name), str(spec), "npm", scope, rel)

        elif lower == "package-lock.json":
            try:
                lock = json.loads(content)
            except ValueError:
                lock = {}
            if isinstance(lock, dict):
                packages = lock.get("packages") or {}
                if isinstance(packages, dict):
                    for pkg_path, info in packages.items():
                        if not pkg_path or not isinstance(info, dict) or not info.get("version"):
                            continue
                        if "node_modules/" in pkg_path:
                            pkg_name = pkg_path.split("node_modules/")[-1]
                            scope = "dev" if info.get("dev") else "runtime"
                            put(pkg_name, str(info["version"]), "npm", scope, rel, locked=True)
                for pkg_name, info in (lock.get("dependencies") or {}).items():
                    if isinstance(info, dict) and info.get("version"):
                        scope = "dev" if info.get("dev") else "runtime"
                        put(str(pkg_name), str(info["version"]), "npm", scope, rel, locked=True)

        elif lower in {"uv.lock", "poetry.lock"} and tomllib is not None:
            try:
                lock_toml = tomllib.loads(content)
            except Exception:
                lock_toml = {}
            for pkg in (lock_toml.get("package") or []) if isinstance(lock_toml, dict) else []:
                if isinstance(pkg, dict) and pkg.get("name") and pkg.get("version"):
                    put(str(pkg["name"]), str(pkg["version"]), "PyPI", "runtime", rel, locked=True)

        elif lower == "cargo.toml" and tomllib is not None:
            try:
                cargo = tomllib.loads(content)
            except Exception:
                cargo = {}
            if isinstance(cargo, dict):
                for section, scope in (("dependencies", "runtime"), ("dev-dependencies", "dev")):
                    mapping = cargo.get(section) or {}
                    if isinstance(mapping, dict):
                        for name, val in mapping.items():
                            spec = val if isinstance(val, str) else str(val.get("version", "")) if isinstance(val, dict) else ""
                            put(str(name), spec, "crates.io", scope, rel)

        elif lower == "cargo.lock" and tomllib is not None:
            try:
                cargo_lock = tomllib.loads(content)
            except Exception:
                cargo_lock = {}
            for pkg in (cargo_lock.get("package") or []) if isinstance(cargo_lock, dict) else []:
                if isinstance(pkg, dict) and pkg.get("name") and pkg.get("version"):
                    put(str(pkg["name"]), str(pkg["version"]), "crates.io", "runtime", rel, locked=True)

        elif lower == "go.mod":
            in_block = False
            for line in content.splitlines():
                stripped = line.split("//", 1)[0].strip()
                if not stripped:
                    continue
                if stripped.startswith("require ("):
                    in_block = True
                    continue
                if in_block and stripped == ")":
                    in_block = False
                    continue
                if in_block or stripped.startswith("require "):
                    body = stripped[8:].strip() if stripped.startswith("require ") else stripped
                    parts = body.split()
                    if len(parts) >= 2:
                        put(parts[0], parts[1], "Go", "runtime", rel, locked=True)

    result: list[dict[str, str]] = []
    for item in deps_by_key.values():
        cleaned = dict(item)
        cleaned.pop("locked", None)
        result.append(cleaned)
    return result
