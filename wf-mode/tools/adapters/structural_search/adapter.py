"""structural_search：内置多语言代码模式搜索与 AST 符号大纲（+ ast-grep CLI 备选）。"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from tools import repo_utils
from tools.adapters import cli_tool
from tools.errors import ToolError
from tools.util import utc_now

SLOT = "structural_search"
ACTIONS = ("search", "symbols", "health")
PROVIDERS = ("builtin", "ast-grep")

LANG_EXTS = {
    "python": {".py", ".pyi"},
    "py": {".py", ".pyi"},
    "typescript": {".ts", ".tsx"},
    "ts": {".ts", ".tsx"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
    "js": {".js", ".jsx", ".mjs", ".cjs"},
    "go": {".go"},
    "rust": {".rs"},
    "rs": {".rs"},
}

_TS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(function|class|interface|type|const|enum)\s+([A-Za-z_]\w*)"
)
_GO_SYMBOL_RE = re.compile(r"^(func|type)\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")
_RUST_SYMBOL_RE = re.compile(r"^\s*(?:pub\s+)?(fn|struct|enum|trait|impl|mod)\s+([A-Za-z_]\w*)")


def _search_builtin(payload: dict[str, Any]) -> dict[str, Any]:
    pattern = payload.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ToolError("INVALID_INPUT", "search 需要非空 --pattern")
    pat = pattern.strip()
    root = repo_utils.resolve_local_path(payload.get("path") or ".")
    lang = str(payload.get("lang") or "").strip().lower()
    allowed_exts = LANG_EXTS.get(lang)
    max_results = max(1, min(100, int(payload.get("maxResults") or 30)))

    try:
        regex = re.compile(pat)
    except re.error:
        regex = re.compile(re.escape(pat))

    rel_files = (
        [root.name]
        if root.is_file()
        else repo_utils.iter_project_files(root, max_files=2500)
    )

    matches: list[dict[str, Any]] = []
    for rel in rel_files:
        fpath = root if root.is_file() else root / rel
        ext = fpath.suffix.lower()
        if ext in repo_utils.BINARY_EXTS:
            continue
        if allowed_exts is not None and ext not in allowed_exts:
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(
                    {
                        "file": rel,
                        "line": lineno,
                        "text": line.strip()[:240],
                    }
                )
                if len(matches) >= max_results:
                    return {
                        "root": root.as_posix(),
                        "pattern": pat,
                        "truncated": True,
                        "count": len(matches),
                        "matches": matches,
                    }

    return {
        "root": root.as_posix(),
        "pattern": pat,
        "truncated": False,
        "count": len(matches),
        "matches": matches,
    }


def _py_symbols(rel: str, text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({"file": rel, "kind": "function", "name": node.name, "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            methods = [
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
            ]
            symbols.append(
                {
                    "file": rel,
                    "kind": "class",
                    "name": node.name,
                    "line": node.lineno,
                    "methods": methods[:20],
                }
            )
    return symbols


def _symbols_builtin(payload: dict[str, Any]) -> dict[str, Any]:
    root = repo_utils.resolve_local_path(payload.get("path") or ".")
    rel_files = (
        [root.name]
        if root.is_file()
        else repo_utils.iter_project_files(root, max_files=1000)
    )
    max_symbols = max(1, min(300, int(payload.get("maxResults") or 120)))
    symbols: list[dict[str, Any]] = []

    for rel in rel_files:
        fpath = root if root.is_file() else root / rel
        ext = fpath.suffix.lower()
        if ext not in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}:
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if ext == ".py":
            symbols.extend(_py_symbols(rel, text))
        else:
            regex = (
                _TS_SYMBOL_RE
                if ext in {".ts", ".tsx", ".js", ".jsx"}
                else (_GO_SYMBOL_RE if ext == ".go" else _RUST_SYMBOL_RE)
            )
            for lineno, line in enumerate(text.splitlines(), start=1):
                m = regex.match(line)
                if m:
                    symbols.append(
                        {"file": rel, "kind": m.group(1), "name": m.group(2), "line": lineno}
                    )
        if len(symbols) >= max_symbols:
            break

    return {
        "root": root.as_posix(),
        "count": len(symbols[:max_symbols]),
        "truncated": len(symbols) > max_symbols,
        "symbols": symbols[:max_symbols],
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
        return cli_tool.health(entry, "ast-grep", runtime)
    return {"ok": False, "provider": "ast-grep", "configured": False, "checkedAt": utc_now()}


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
    if action not in {"search", "symbols"}:
        raise ToolError("UNKNOWN_ACTION", f"structural_search 不支持动作: {action}")
    if chosen == "ast-grep":
        if action != "search":
            raise ToolError("UNKNOWN_ACTION", "ast-grep 仅支持 search", allow_fallback=True)
        if not entry:
            raise ToolError("TOOL_MISSING", "缺少 ast-grep 配置", allow_fallback=True)
        return cli_tool.execute("search", payload, "ast-grep", entry, runtime)
    if chosen != "builtin":
        raise ToolError("INVALID_INPUT", f"structural_search 未知 provider: {chosen}")
    if action == "symbols":
        return _symbols_builtin(payload)
    return _search_builtin(payload)
