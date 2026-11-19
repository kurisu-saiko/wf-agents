"""代码切片最小 AST 传递依赖闭包计算器（Step 4 / Step 5）。

给定本地源仓库目录或远程 GitHub 仓库（repo + ref，自动按需拉取至缓存区，免全仓 clone），
通过 AST / 语义解析：
1. 追踪内部相对导入与同仓包导入，计算最小传递依赖闭包 `closure_files`
2. 区分标准库导入 (`stdlib_imports`)、外部三方依赖 (`external_packages`) 与缺失内部引用 (`missing_internal_imports`)
3. 提取导出符号列表 (`exported_symbols`)、干净签名规约 (`signatures`) 与总代码行数 (`loc`)
"""

from __future__ import annotations

import ast
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Callable

from tools import config as local_config
from tools import http_client, repo_utils
from tools.errors import ToolError

_FALLBACK_STDLIB = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "concurrent",
    "contextlib", "copy", "csv", "dataclasses", "datetime", "decimal", "difflib",
    "email", "enum", "functools", "glob", "gzip", "hashlib", "heapq", "hmac",
    "html", "http", "importlib", "inspect", "io", "itertools", "json", "logging",
    "math", "mimetypes", "multiprocessing", "operator", "os", "pathlib", "pickle",
    "platform", "pprint", "queue", "random", "re", "secrets", "shlex", "shutil",
    "signal", "socket", "sqlite3", "ssl", "stat", "statistics", "string",
    "subprocess", "sys", "tempfile", "textwrap", "threading", "time", "tomllib",
    "traceback", "types", "typing", "unicodedata", "unittest", "urllib", "uuid",
    "warnings", "weakref", "xml", "zipfile", "zlib",
}
STDLIB_MODULES: frozenset[str] = getattr(sys, "stdlib_module_names", frozenset(_FALLBACK_STDLIB))

_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))"""
)
_JS_EXPORT_RE = re.compile(
    r"""export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|type|interface)\s+([A-Za-z_][A-Za-z0-9_]*)"""
)
_JS_FUNC_SIG_RE = re.compile(
    r"""export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)"""
)


def _normalize_rel(rel_path: str) -> str:
    return rel_path.replace("\\", "/").lstrip("./")


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _candidate_roots(source_root: Path, current_file: Path) -> list[Path]:
    roots = [source_root]
    src_dir = source_root / "src"
    if src_dir.is_dir():
        roots.append(src_dir)
    if current_file.parent not in roots:
        roots.append(current_file.parent)
    return roots


def _python_module_candidates(
    source_root: Path,
    current_rel: str,
    module_name: str,
    level: int,
    *,
    include_src_guess: bool = False,
) -> list[Path]:
    current_file = source_root / current_rel
    if level > 0:
        base_dir = current_file.parent
        for _ in range(level - 1):
            base_dir = base_dir.parent
        roots = [base_dir]
    else:
        roots = _candidate_roots(source_root, current_file)
        if include_src_guess and (source_root / "src") not in roots:
            roots.append(source_root / "src")

    parts = [p for p in module_name.split(".") if p] if module_name else []
    cands: list[Path] = []
    for base in roots:
        target_base = base.joinpath(*parts) if parts else base
        for item in (target_base.with_suffix(".py"), target_base / "__init__.py"):
            if _is_within(source_root, item) and item not in cands:
                cands.append(item)
    return cands


def _resolve_python_module(source_root: Path, current_rel: str, module_name: str, level: int) -> Path | None:
    for item in _python_module_candidates(source_root, current_rel, module_name, level):
        if item.is_file():
            return item
    return None


def _js_module_candidates(source_root: Path, current_rel: str, spec: str) -> list[Path]:
    if not spec.startswith("."):
        return []
    base_dir = (source_root / current_rel).parent
    raw_target = (base_dir / spec).resolve()
    if not _is_within(source_root, raw_target):
        return []
    cands: list[Path] = [raw_target]
    for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
        cands.append(raw_target.with_suffix(ext))
    for idx_name in ("index.ts", "index.tsx", "index.js"):
        cands.append(raw_target / idx_name)
    return cands


def _resolve_js_module(source_root: Path, current_rel: str, spec: str) -> Path | None:
    for item in _js_module_candidates(source_root, current_rel, spec):
        if item.is_file():
            return item
    return None


def _analyze_python_file(
    source_root: Path,
    rel: str,
    text: str,
    resolver: Callable[[Path, str, str, int], Path | None] = _resolve_python_module,
) -> tuple[list[Path], set[str], set[str], list[str], list[str]]:
    internal: list[Path] = []
    stdlib: set[str] = set()
    external: set[str] = set()
    missing: list[str] = []
    exports: list[str] = []

    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        raise ToolError("INVALID_INPUT", f"切片文件存在 Python 语法错误 ({rel}): {exc.msg}") from exc

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                exports.append(node.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_name = alias.name
                top = mod_name.split(".", 1)[0]
                resolved = resolver(source_root, rel, mod_name, 0)
                if resolved is not None:
                    internal.append(resolved)
                elif top in STDLIB_MODULES:
                    stdlib.add(top)
                else:
                    external.add(top)
        elif isinstance(node, ast.ImportFrom):
            level = int(node.level or 0)
            mod_name = node.module or ""
            resolved = resolver(source_root, rel, mod_name, level)
            if resolved is not None:
                internal.append(resolved)
                for alias in node.names:
                    sub_mod = f"{mod_name}.{alias.name}" if mod_name else alias.name
                    sub_resolved = resolver(source_root, rel, sub_mod, level)
                    if sub_resolved is not None:
                        internal.append(sub_resolved)
            elif level > 0:
                missing.append(f"{rel}: relative import {'.' * level}{mod_name}")
            else:
                top = mod_name.split(".", 1)[0] if mod_name else ""
                if not top:
                    continue
                if top in STDLIB_MODULES:
                    stdlib.add(top)
                else:
                    external.add(top)

    return internal, stdlib, external, missing, exports


def _analyze_js_file(
    source_root: Path,
    rel: str,
    text: str,
    resolver: Callable[[Path, str, str], Path | None] = _resolve_js_module,
) -> tuple[list[Path], set[str], set[str], list[str], list[str]]:
    internal: list[Path] = []
    stdlib: set[str] = set()
    external: set[str] = set()
    missing: list[str] = []
    exports = _JS_EXPORT_RE.findall(text)

    for m in _JS_IMPORT_RE.finditer(text):
        spec = m.group(1) or m.group(2) or ""
        if not spec:
            continue
        if spec.startswith("."):
            resolved = resolver(source_root, rel, spec)
            if resolved is not None:
                internal.append(resolved)
            else:
                missing.append(f"{rel}: {spec}")
        elif spec.startswith("node:"):
            stdlib.add(spec)
        else:
            pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/", 1)[0]
            external.add(pkg)

    return internal, stdlib, external, missing, exports


def extract_symbol_signatures(texts_by_rel: dict[str, str]) -> list[dict[str, Any]]:
    """从给定文件内容字典中提取公开函数/类签名（仅接口定义，不含实现体，供 PATTERN_REF 净室参考）。"""
    signatures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rel, text in sorted(texts_by_rel.items()):
        ext = Path(rel).suffix.lower()
        if ext == ".py":
            try:
                tree = ast.parse(text, filename=rel)
            except SyntaxError:
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                    if node.name in seen:
                        continue
                    seen.add(node.name)
                    args = [a.arg for a in node.args.posonlyargs + node.args.args]
                    if node.args.kwonlyargs:
                        args.extend(a.arg for a in node.args.kwonlyargs)
                    signatures.append({"kind": "function", "name": node.name, "args": args, "file": rel})
                elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                    if node.name in seen:
                        continue
                    seen.add(node.name)
                    methods = [
                        n.name
                        for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
                    ]
                    signatures.append({"kind": "class", "name": node.name, "methods": methods[:12], "file": rel})
        elif ext in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
            for name, raw_args in _JS_FUNC_SIG_RE.findall(text):
                if name in seen:
                    continue
                seen.add(name)
                args = [a.strip().split(":")[0].split("=")[0].strip() for a in raw_args.split(",") if a.strip()]
                signatures.append({"kind": "function", "name": name, "args": args, "file": rel})
            for sym in _JS_EXPORT_RE.findall(text):
                if sym not in seen:
                    seen.add(sym)
                    signatures.append({"kind": "export", "name": sym, "args": [], "file": rel})
    return signatures


def stage_remote_repo_files(
    repo: str,
    target_files: list[str],
    *,
    ref: str | None = None,
    fetcher: Callable[[str], str | None] | None = None,
) -> tuple[Path, str]:
    """免克隆按需拉取远程 GitHub 仓库的入口文件及内部传递依赖到本地缓存暂存区。"""
    owner, name = repo_utils.parse_repo(repo)
    if not target_files:
        raise ToolError("INVALID_INPUT", "target_files 至少需要指定 1 个文件")

    resolved_ref = (ref or "").strip()
    tree_paths: set[str] | None = None
    headers = repo_utils.github_headers()

    if not resolved_ref:
        if fetcher is None:
            meta = http_client.get_json(
                f"https://api.github.com/repos/{owner}/{name}",
                provider="github_api",
                headers=headers,
            )
            resolved_ref = str(meta.get("default_branch") or "HEAD")
        else:
            resolved_ref = "HEAD"

    if fetcher is None:
        try:
            tree_data = http_client.get_json(
                f"https://api.github.com/repos/{owner}/{name}/git/trees/{resolved_ref}",
                provider="github_api",
                headers=headers,
                params={"recursive": "1"},
            )
            if not tree_data.get("truncated"):
                tree_paths = {
                    str(item.get("path") or "")
                    for item in (tree_data.get("tree") or [])
                    if item.get("type") == "blob" and item.get("path")
                }
        except ToolError:
            tree_paths = None

    safe_ref = re.sub(r"[^A-Za-z0-9_.-]+", "_", resolved_ref).strip("._") or "HEAD"
    staged_dir = local_config.data_dir() / "cache" / "staged_repos" / f"{owner}__{name}__{safe_ref}"
    staged_dir.mkdir(parents=True, exist_ok=True)

    raw_headers = {"User-Agent": headers.get("Authorization", "") and "wf-agents/2.0" or "wf-agents/2.0"}
    if headers.get("Authorization"):
        raw_headers["Authorization"] = headers["Authorization"]

    def _fetch_rel(rel: str) -> str | None:
        norm = _normalize_rel(rel)
        dest = (staged_dir / norm).resolve()
        if not _is_within(staged_dir, dest):
            return None
        if fetcher is not None:
            content = fetcher(norm)
        else:
            if tree_paths is not None and norm not in tree_paths:
                return None
            url = f"https://raw.githubusercontent.com/{owner}/{name}/{resolved_ref}/{norm}"
            try:
                content = http_client.get_text(url, provider="github_raw", headers=raw_headers)
            except ToolError:
                return None
        if content is None:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return content

    def _remote_py_resolver(sroot: Path, cur_rel: str, mod_name: str, level: int) -> Path | None:
        for cand in _python_module_candidates(sroot, cur_rel, mod_name, level, include_src_guess=True):
            if cand.is_file():
                return cand
            cand_rel = cand.resolve().relative_to(sroot.resolve()).as_posix()
            if _fetch_rel(cand_rel) is not None and cand.is_file():
                return cand
        return None

    def _remote_js_resolver(sroot: Path, cur_rel: str, spec: str) -> Path | None:
        for cand in _js_module_candidates(sroot, cur_rel, spec):
            if cand.is_file():
                return cand
            cand_rel = cand.resolve().relative_to(sroot.resolve()).as_posix()
            if _fetch_rel(cand_rel) is not None and cand.is_file():
                return cand
        return None

    queue: deque[str] = deque()
    for raw in target_files:
        norm = _normalize_rel(raw)
        if _fetch_rel(norm) is None:
            raise ToolError("INVALID_INPUT", f"无法从远程仓库 {owner}/{name}@{resolved_ref} 获取文件: {raw}")
        queue.append(norm)

    visited: set[str] = set()
    while queue:
        rel = queue.popleft()
        if rel in visited:
            continue
        visited.add(rel)
        full = staged_dir / rel
        text = full.read_text(encoding="utf-8", errors="replace")
        ext = full.suffix.lower()
        internal: list[Path] = []
        if ext == ".py":
            internal, _, _, _, _ = _analyze_python_file(staged_dir, rel, text, resolver=_remote_py_resolver)
        elif ext in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
            internal, _, _, _, _ = _analyze_js_file(staged_dir, rel, text, resolver=_remote_js_resolver)
        for dep in internal:
            dep_rel = dep.resolve().relative_to(staged_dir.resolve()).as_posix()
            if dep_rel not in visited:
                queue.append(dep_rel)

    return staged_dir, resolved_ref


def compute_slice_closure(
    source_path: str | Path | None = None,
    target_files: list[str] | None = None,
    *,
    repo: str | None = None,
    ref: str | None = None,
    fetcher: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """计算目标切片文件的最小内部传递依赖闭包（支持本地目录或远程 GitHub 仓库）。"""
    targets = list(target_files or [])
    if not targets:
        raise ToolError("INVALID_INPUT", "target_files 至少需要指定 1 个文件")

    resolved_repo = ""
    resolved_ref = ""
    staged = False
    if source_path is not None and str(source_path).strip():
        source_root = Path(source_path).expanduser().resolve()
        if not source_root.is_dir():
            raise ToolError("INVALID_INPUT", f"源仓库目录不存在: {source_path}")
    elif repo and str(repo).strip():
        owner, name = repo_utils.parse_repo(repo)
        resolved_repo = f"{owner}/{name}"
        source_root, resolved_ref = stage_remote_repo_files(
            resolved_repo, targets, ref=ref, fetcher=fetcher
        )
        staged = True
    else:
        raise ToolError("INVALID_INPUT", "必须提供本地 source_path 或远程 repo（owner/name）")

    seeds: list[str] = []
    for raw in targets:
        rel = _normalize_rel(raw)
        candidate = (source_root / rel).resolve()
        if not candidate.is_file() or not _is_within(source_root, candidate):
            raise ToolError("INVALID_INPUT", f"目标切片文件不存在或越界: {raw}")
        seeds.append(candidate.relative_to(source_root).as_posix())

    queue: deque[str] = deque(seeds)
    visited: set[str] = set()
    closure: list[str] = []
    stdlib_all: set[str] = set()
    external_all: set[str] = set()
    missing_all: list[str] = []
    exported_symbols: list[str] = []
    total_loc = 0

    seed_set = set(seeds)
    while queue:
        rel = queue.popleft()
        if rel in visited:
            continue
        visited.add(rel)
        closure.append(rel)

        full = source_root / rel
        text = full.read_text(encoding="utf-8", errors="replace")
        total_loc += len(text.splitlines())

        ext = full.suffix.lower()
        if ext == ".py":
            internal, stdlib, external, missing, exports = _analyze_python_file(source_root, rel, text)
        elif ext in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
            internal, stdlib, external, missing, exports = _analyze_js_file(source_root, rel, text)
        else:
            internal, stdlib, external, missing, exports = [], set(), set(), [], []

        stdlib_all.update(stdlib)
        external_all.update(external)
        missing_all.extend(missing)
        if rel in seed_set:
            for sym in exports:
                if sym not in exported_symbols:
                    exported_symbols.append(sym)

        for dep_path in internal:
            dep_rel = dep_path.resolve().relative_to(source_root).as_posix()
            if dep_rel not in visited:
                queue.append(dep_rel)

    closure_sorted = sorted(closure)
    result: dict[str, Any] = {
        "sourceRoot": str(source_root),
        "entryFiles": seeds,
        "closureFiles": closure_sorted,
        "internalDeps": [f for f in closure_sorted if f not in seed_set],
        "stdlibImports": sorted(stdlib_all),
        "externalPackages": sorted(external_all),
        "missingInternalImports": missing_all,
        "closureComplete": len(missing_all) == 0,
        "exportedSymbols": exported_symbols,
        "loc": total_loc,
        "fileCount": len(closure_sorted),
    }
    if staged:
        result["repo"] = resolved_repo
        result["ref"] = resolved_ref
        result["staged"] = True
    return result
