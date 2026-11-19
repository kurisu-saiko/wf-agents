"""dependency_graph：内置多语言项目架构、模块依赖图与循环依赖分析（+ pydeps CLI 备选）。"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tools import repo_utils
from tools.adapters import cli_tool
from tools.errors import ToolError
from tools.util import utc_now

SLOT = "dependency_graph"
ACTIONS = ("graph", "analyze", "health")
PROVIDERS = ("builtin", "pydeps")

_JS_IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)"""
)
_GO_IMPORT_SINGLE_RE = re.compile(r'^\s*import\s+(?:[A-Za-z_]\w*\s+)?"([^"]+)"')
_GO_IMPORT_BLOCK_RE = re.compile(r'^\s*(?:[A-Za-z_]\w*\s+)?"([^"]+)"')
_RUST_USE_RE = re.compile(r"^\s*(?:use|mod)\s+([A-Za-z0-9_:]+)")

_PY_STDLIB_HINTS = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "concurrent",
    "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal",
    "difflib", "email", "enum", "errno", "fnmatch", "functools", "gc", "getopt",
    "getpass", "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "importlib", "inspect", "io", "ipaddress", "itertools", "json", "keyword",
    "linecache", "locale", "logging", "math", "mimetypes", "multiprocessing",
    "numbers", "operator", "os", "pathlib", "pickle", "platform", "plistlib",
    "posixpath", "pprint", "profile", "pstats", "queue", "random", "re",
    "secrets", "selectors", "shlex", "shutil", "signal", "site", "smtplib",
    "socket", "sqlite3", "ssl", "stat", "statistics", "string", "struct",
    "subprocess", "sys", "sysconfig", "tempfile", "textwrap", "threading",
    "time", "timeit", "tkinter", "tomllib", "traceback", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings", "wave",
    "weakref", "webbrowser", "xml", "zipfile", "zlib", "__future__",
}

_ENTRYPOINT_NAMES = {
    "main.py", "app.py", "server.py", "cli.py", "index.ts", "index.js",
    "main.ts", "main.js", "main.go", "main.rs", "lib.rs", "__main__.py",
}


def _module_name_py(rel: str) -> str:
    p = Path(rel)
    parts = list(p.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or p.stem


def _parse_python(text: str) -> tuple[list[str], bool]:
    imports: list[str] = []
    has_main = False
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return imports, has_main
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                prefix = "." * node.level
                mod = f"{prefix}{node.module or ''}"
                imports.append(mod)
            elif node.module:
                imports.append(node.module)
        elif isinstance(node, ast.If):
            seg = ast.get_source_segment(text, node.test) or ""
            if "__name__" in seg and "__main__" in seg:
                has_main = True
    return imports, has_main


def _resolve_py_internal(mod_name: str, imp: str, internal_modules: set[str]) -> str | None:
    if imp.startswith("."):
        dots = len(imp) - len(imp.lstrip("."))
        rest = imp.lstrip(".")
        base_parts = mod_name.split(".")
        up = max(0, len(base_parts) - dots)
        candidate = ".".join([*base_parts[:up], *(rest.split(".") if rest else [])]).strip(".")
        if candidate in internal_modules:
            return candidate
    parts = imp.split(".")
    for end in range(len(parts), 0, -1):
        prefix = ".".join(parts[:end])
        if prefix in internal_modules:
            return prefix
    return None


def _parse_js(text: str) -> list[str]:
    imports: list[str] = []
    for m in _JS_IMPORT_RE.finditer(text):
        spec = m.group(1) or m.group(2)
        if spec:
            imports.append(spec)
    return imports


def _resolve_js_internal(rel: str, spec: str, all_files_set: set[str]) -> str | None:
    if not spec.startswith("."):
        return None
    base_dir = Path(rel).parent
    raw_target = (base_dir / spec).as_posix()
    parts: list[str] = []
    for part in raw_target.split("/"):
        if part in {"", "."}:
            continue
        if part == ".." and parts:
            parts.pop()
        elif part != "..":
            parts.append(part)
    clean = "/".join(parts)
    for ext in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.js"):
        cand = clean + ext
        if cand in all_files_set:
            return cand
    return None


def _parse_go(text: str) -> list[str]:
    imports: list[str] = []
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("import ("):
            in_block = True
            continue
        if in_block:
            if s == ")":
                in_block = False
                continue
            m = _GO_IMPORT_BLOCK_RE.match(s)
            if m:
                imports.append(m.group(1))
        else:
            m = _GO_IMPORT_SINGLE_RE.match(s)
            if m:
                imports.append(m.group(1))
    return imports


def _parse_rust(text: str) -> list[str]:
    imports: list[str] = []
    for line in text.splitlines():
        m = _RUST_USE_RE.match(line)
        if m:
            imports.append(m.group(1).split("::")[0])
    return imports


def _find_cycles(adj: dict[str, set[str]], limit: int = 10) -> list[list[str]]:
    cycles: list[list[str]] = []
    state: dict[str, int] = {}
    stack: list[str] = []

    def dfs(node: str) -> None:
        if len(cycles) >= limit:
            return
        state[node] = 1
        stack.append(node)
        for nxt in sorted(adj.get(node, ())):
            if nxt == node:
                continue
            st = state.get(nxt, 0)
            if st == 1:
                idx = stack.index(nxt)
                cycles.append([*stack[idx:], nxt])
                if len(cycles) >= limit:
                    break
            elif st == 0:
                dfs(nxt)
        stack.pop()
        state[node] = 2

    for n in sorted(adj):
        if state.get(n, 0) == 0:
            dfs(n)
    return cycles


def _analyze_local(payload: dict[str, Any]) -> dict[str, Any]:
    root = repo_utils.resolve_local_path(payload.get("path") or ".")
    files = repo_utils.iter_project_files(root, max_files=2500)
    all_files_set = set(files)

    lang_files: Counter[str] = Counter()
    lang_lines: Counter[str] = Counter()
    manifests: list[str] = []
    entrypoints: list[str] = []

    py_files: dict[str, str] = {}
    js_files: list[str] = []
    go_files: list[str] = []
    rs_files: list[str] = []

    for rel in files:
        p = root / rel
        if p.name in repo_utils.MANIFEST_FILES:
            manifests.append(rel)
        if p.name in _ENTRYPOINT_NAMES:
            entrypoints.append(rel)
        ext = p.suffix.lower()
        if ext in repo_utils.BINARY_EXTS:
            continue
        lang = repo_utils.detect_language(rel)
        if lang:
            lang_files[lang] += 1
        if ext in {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs"}:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if lang:
                lang_lines[lang] += len(text.splitlines())
            if ext == ".py":
                py_files[rel] = _module_name_py(rel)
            elif ext in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
                js_files.append(rel)
            elif ext == ".go":
                go_files.append(rel)
            elif ext == ".rs":
                rs_files.append(rel)

    internal_py = set(py_files.values())
    adj: dict[str, set[str]] = defaultdict(set)
    in_degree: Counter[str] = Counter()
    external_deps: Counter[str] = Counter()
    node_meta: dict[str, dict[str, Any]] = {}

    for rel, mod in py_files.items():
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        imps, has_main = _parse_python(text)
        if has_main and rel not in entrypoints:
            entrypoints.append(rel)
        node_meta[mod] = {"file": rel, "language": "Python"}
        adj.setdefault(mod, set())
        for imp in imps:
            target = _resolve_py_internal(mod, imp, internal_py)
            if target and target != mod:
                adj[mod].add(target)
                in_degree[target] += 1
            elif not imp.startswith("."):
                top = imp.split(".")[0]
                if top and top not in _PY_STDLIB_HINTS and top not in internal_py:
                    external_deps[top] += 1

    for rel in js_files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        node_meta[rel] = {"file": rel, "language": repo_utils.detect_language(rel)}
        adj.setdefault(rel, set())
        for spec in _parse_js(text):
            target = _resolve_js_internal(rel, spec, all_files_set)
            if target and target != rel:
                adj[rel].add(target)
                in_degree[target] += 1
            elif not spec.startswith("."):
                pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
                if pkg and not pkg.startswith("node:"):
                    external_deps[pkg] += 1

    for rel in go_files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        node_meta[rel] = {"file": rel, "language": "Go"}
        for imp in _parse_go(text):
            if "." in imp.split("/")[0]:
                external_deps[imp] += 1

    for rel in rs_files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        node_meta[rel] = {"file": rel, "language": "Rust"}
        for imp in _parse_rust(text):
            if imp not in {"crate", "self", "super", "std", "core", "alloc"}:
                external_deps[imp] += 1

    edges = [
        {"from": src, "to": dst}
        for src in sorted(adj)
        for dst in sorted(adj[src])
    ]
    cycles = _find_cycles(adj)
    top_hubs = [{"module": m, "importedBy": c} for m, c in in_degree.most_common(10)]
    languages = {
        lang: {"files": count, "lines": lang_lines.get(lang, 0)}
        for lang, count in lang_files.most_common(12)
    }

    return {
        "root": root.as_posix(),
        "totalFiles": len(files),
        "languages": languages,
        "manifests": sorted(manifests)[:30],
        "entrypoints": sorted(set(entrypoints))[:20],
        "moduleCount": len(node_meta),
        "edgeCount": len(edges),
        "edges": edges[:250],
        "topHubs": top_hubs,
        "externalDependencies": [
            {"name": name, "references": count} for name, count in external_deps.most_common(40)
        ],
        "circularDependencies": cycles,
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
        return cli_tool.health(entry, "pydeps", runtime)
    return {"ok": False, "provider": "pydeps", "configured": False, "checkedAt": utc_now()}


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
    if action not in {"graph", "analyze"}:
        raise ToolError("UNKNOWN_ACTION", f"dependency_graph 不支持动作: {action}")
    if chosen == "pydeps":
        if not entry:
            raise ToolError("TOOL_MISSING", "缺少 pydeps 配置", allow_fallback=True)
        return cli_tool.execute("graph", payload, "pydeps", entry, runtime)
    if chosen != "builtin":
        raise ToolError("INVALID_INPUT", f"dependency_graph 未知 provider: {chosen}")
    return _analyze_local(payload)
