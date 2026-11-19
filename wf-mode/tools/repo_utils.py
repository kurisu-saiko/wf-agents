"""共用项目读取、GitHub 定位、语言识别、依赖解析与许可证识别工具。"""

from __future__ import annotations

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


def iter_project_files(
    root: Path,
    *,
    max_files: int = 2500,
    include_hidden: bool = False,
) -> list[str]:
    if root.is_file():
        return [root.name]
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in IGNORE_DIRS and (include_hidden or not d.startswith("."))
        )
        rel_dir = Path(dirpath).relative_to(root)
        for fname in sorted(filenames):
            if not include_hidden and fname.startswith(".") and fname not in {".gitignore", ".env.example"}:
                continue
            rel = fname if str(rel_dir) == "." else (rel_dir / fname).as_posix()
            results.append(rel)
            if len(results) >= max_files:
                return results
    return results


def detect_language(rel_path: str) -> str:
    ext = Path(rel_path).suffix.lower()
    return EXT_LANG.get(ext, "")


def license_category(spdx: str | None) -> str:
    code = (spdx or "").strip().upper()
    if not code or code in {"NOASSERTION", "NONE", "UNKNOWN"}:
        return "unknown"
    if code in PERMISSIVE_LICENSES:
        return "permissive"
    if code in WEAK_COPYLEFT_LICENSES:
        return "weak-copyleft"
    if code in STRONG_COPYLEFT_LICENSES:
        return "strong-copyleft"
    if "AGPL" in code or "GPL" in code:
        return "weak-copyleft" if "LGPL" in code else "strong-copyleft"
    if "MPL" in code or "EPL" in code or "CDDL" in code:
        return "weak-copyleft"
    if "MIT" in code or "APACHE" in code or "BSD" in code or "ISC" in code:
        return "permissive"
    return "unknown"


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
    """从常见清单文件解析依赖清单。"""
    deps: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(name: str, spec: str, ecosystem: str, scope: str, source: str) -> None:
        norm = name.strip()
        if not norm:
            return
        key = (ecosystem.lower(), norm.lower(), scope)
        if key in seen:
            return
        seen.add(key)
        deps.append(
            {
                "name": norm,
                "versionSpec": spec.strip(),
                "version": _clean_version(spec),
                "ecosystem": ecosystem,
                "scope": scope,
                "source": source,
            }
        )

    for rel, content in files.items():
        base = Path(rel).name
        lower = base.lower()
        if lower.startswith("requirements") and lower.endswith(".txt"):
            scope = "dev" if "dev" in lower or "test" in lower else "runtime"
            for line in content.splitlines():
                stripped = line.split("#", 1)[0].strip()
                if not stripped or stripped.startswith(("-", "--", "git+", "http://", "https://")):
                    continue
                name, spec = _parse_pep508(stripped)
                add(name, spec, "PyPI", scope, rel)

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
                        add(name, spec, "PyPI", "runtime", rel)
                for group, items in (proj.get("optional-dependencies") or {}).items():
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, str):
                                name, spec = _parse_pep508(item)
                                add(name, spec, "PyPI", f"optional:{group}", rel)
                poetry = ((parsed.get("tool") or {}).get("poetry") or {})
                for pkg, ver in (poetry.get("dependencies") or {}).items():
                    if pkg.lower() == "python":
                        continue
                    spec = ver if isinstance(ver, str) else str((ver or {}).get("version", "")) if isinstance(ver, dict) else ""
                    add(str(pkg), spec, "PyPI", "runtime", rel)

        elif lower == "package.json":
            import json

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
                            add(str(name), str(spec), "npm", scope, rel)

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
                            add(str(name), spec, "crates.io", scope, rel)

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
                        add(parts[0], parts[1], "Go", "runtime", rel)

    return deps
