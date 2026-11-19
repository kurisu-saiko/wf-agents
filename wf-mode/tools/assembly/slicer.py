"""代码切片最小 AST 传递依赖闭包计算器（Step 4 / Step 5）。

给定源仓库根目录与目标切片文件列表（1~5 个核心文件），通过 AST / 语义解析：
1. 追踪内部相对导入与同仓包导入，计算最小传递依赖闭包 `closure_files`
2. 区分标准库导入 (`stdlib_imports`)、外部三方依赖 (`external_packages`) 与缺失内部引用 (`missing_internal_imports`)
3. 提取导出符号列表 (`exported_symbols`) 与总代码行数 (`loc`)
"""

from __future__ import annotations

import ast
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any

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


def _normalize_rel(rel_path: str) -> str:
    return rel_path.replace("\\", "/").lstrip("./")


def _candidate_roots(source_root: Path, current_file: Path) -> list[Path]:
    roots = [source_root]
    src_dir = source_root / "src"
    if src_dir.is_dir():
        roots.append(src_dir)
    if current_file.parent not in roots:
        roots.append(current_file.parent)
    return roots


def _resolve_python_module(source_root: Path, current_rel: str, module_name: str, level: int) -> Path | None:
    current_file = source_root / current_rel
    if level > 0:
        base_dir = current_file.parent
        for _ in range(level - 1):
            base_dir = base_dir.parent
        roots = [base_dir]
    else:
        roots = _candidate_roots(source_root, current_file)

    parts = [p for p in module_name.split(".") if p] if module_name else []
    for base in roots:
        target_base = base.joinpath(*parts) if parts else base
        py_file = target_base.with_suffix(".py")
        if py_file.is_file() and _is_within(source_root, py_file):
            return py_file
        init_file = target_base / "__init__.py"
        if init_file.is_file() and _is_within(source_root, init_file):
            return init_file
    return None


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_js_module(source_root: Path, current_rel: str, spec: str) -> Path | None:
    if not spec.startswith("."):
        return None
    base_dir = (source_root / current_rel).parent
    raw_target = (base_dir / spec).resolve()
    if not _is_within(source_root, raw_target):
        return None
    if raw_target.is_file():
        return raw_target
    for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
        with_ext = raw_target.with_suffix(ext)
        if with_ext.is_file():
            return with_ext
    for idx_name in ("index.ts", "index.tsx", "index.js"):
        idx = raw_target / idx_name
        if idx.is_file():
            return idx
    return None


def _analyze_python_file(
    source_root: Path,
    rel: str,
    text: str,
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
                resolved = _resolve_python_module(source_root, rel, mod_name, 0)
                if resolved is not None:
                    internal.append(resolved)
                elif top in STDLIB_MODULES:
                    stdlib.add(top)
                else:
                    external.add(top)
        elif isinstance(node, ast.ImportFrom):
            level = int(node.level or 0)
            mod_name = node.module or ""
            resolved = _resolve_python_module(source_root, rel, mod_name, level)
            if resolved is not None:
                internal.append(resolved)
                # 支持 `from pkg import submod` 形式下子模块文件探测
                for alias in node.names:
                    sub_mod = f"{mod_name}.{alias.name}" if mod_name else alias.name
                    sub_resolved = _resolve_python_module(source_root, rel, sub_mod, level)
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
            resolved = _resolve_js_module(source_root, rel, spec)
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


def compute_slice_closure(source_path: str | Path, target_files: list[str]) -> dict[str, Any]:
    """计算目标切片文件的最小内部传递依赖闭包。"""
    source_root = Path(source_path).expanduser().resolve()
    if not source_root.is_dir():
        raise ToolError("INVALID_INPUT", f"源仓库目录不存在: {source_path}")
    if not target_files:
        raise ToolError("INVALID_INPUT", "target_files 至少需要指定 1 个文件")

    seeds: list[str] = []
    for raw in target_files:
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
    return {
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
