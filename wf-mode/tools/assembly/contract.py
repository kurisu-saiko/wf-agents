"""本地对接契约设计与分块 Diff 生成器（Step 4 & Gate 4/5）。

基于本地项目画像（profiler）和复用策略（PACKAGE_DEP / CODE_SLICE / VENDORING / PATTERN_REF），
生成结构化对接契约（Integration Contract）：
- Chunk A (dependency_and_config): 依赖清单变更（或零传递依赖说明）
- Chunk B (code_and_provenance): 带 SPDX 版权头的切片文件 + THIRD_PARTY_NOTICES.md 变更
- Chunk C (adapter_and_smoke_test): 薄 Facade/Adapter 隔离层 + 自包含冒烟测试

每个文件变更均附带 unified diff 预览，并组装 Gate 4/5 所需的 DecisionBrief。
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from tools import envelope as wf_envelope
from tools.assembly import profiler, provenance, slicer
from tools.errors import ToolError

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def _safe_identifier(raw: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", (raw or "").strip()).strip("_").lower()
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"mod_{cleaned}" if cleaned else "reused_component"
    return cleaned


def _unified_diff(path_rel: str, before: str, after: str) -> str:
    if before == after:
        return ""
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path_rel}" if before else "/dev/null",
        tofile=f"b/{path_rel}",
    )
    return "".join(lines)


def _python_module_from_rel(entry_rel: str) -> tuple[str, list[str]]:
    rel = entry_rel.replace("\\", "/").lstrip("./")
    extra_subdirs: list[str] = []
    if rel.startswith("src/"):
        extra_subdirs.append("src")
        mod_rel = rel[4:]
    else:
        mod_rel = rel
    if mod_rel.endswith("/__init__.py"):
        mod_name = mod_rel[:-12].replace("/", ".")
    elif mod_rel.endswith(".py"):
        mod_name = mod_rel[:-3].replace("/", ".")
    else:
        mod_name = mod_rel.replace("/", ".")
    return mod_name, extra_subdirs


def _build_python_slice_adapter(
    *,
    adapter_name: str,
    vendor_subdir: str,
    entry_rel: str,
    repo_url: str,
    spdx_license: str,
    commit_or_version: str,
    exported_symbols: list[str],
) -> str:
    mod_name, extra_subdirs = _python_module_from_rel(entry_rel)
    sub_list_literal = repr(extra_subdirs)
    sym_tuple = repr(tuple(exported_symbols))
    export_lines: list[str] = []
    for sym in exported_symbols:
        if sym.isidentifier():
            export_lines.append(f"{sym} = getattr(_UPSTREAM_MODULE, {sym!r}, None)")
    exports_block = "\n".join(export_lines) if export_lines else "# 未声明显式符号，可通过 get_upstream_module() 访问上游模块"
    all_names = ["ADAPTER_META", "get_upstream_module"] + [s for s in exported_symbols if s.isidentifier()]

    return (
        f'"""本地隔离适配层：{adapter_name}（由 wf-agents 自动生成，策略 CODE_SLICE）。\n\n'
        f"上游来源: {repo_url}\n"
        f"版本/提交: {commit_or_version}\n"
        f"许可证: {spdx_license}\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "import importlib\n"
        "import sys\n"
        "from pathlib import Path\n"
        "from types import ModuleType\n\n"
        f"ADAPTER_META = {{\n"
        f'    "name": {adapter_name!r},\n'
        f'    "strategy": "CODE_SLICE",\n'
        f'    "repository": {repo_url!r},\n'
        f'    "version": {commit_or_version!r},\n'
        f'    "license": {spdx_license!r},\n'
        f'    "entryFile": {entry_rel!r},\n'
        f'    "exportedSymbols": list({sym_tuple}),\n'
        "}\n\n"
        f"_VENDOR_ROOT = Path(__file__).resolve().parent / {vendor_subdir!r}\n"
        f"for _sub in {sub_list_literal}:\n"
        "    _cand = _VENDOR_ROOT / _sub\n"
        "    if _cand.is_dir() and str(_cand) not in sys.path:\n"
        "        sys.path.insert(0, str(_cand))\n"
        "if _VENDOR_ROOT.is_dir() and str(_VENDOR_ROOT) not in sys.path:\n"
        "    sys.path.insert(0, str(_VENDOR_ROOT))\n\n"
        f"_UPSTREAM_MODULE: ModuleType = importlib.import_module({mod_name!r})\n\n\n"
        "def get_upstream_module() -> ModuleType:\n"
        '    """返回底层的切片上游模块对象。"""\n'
        "    return _UPSTREAM_MODULE\n\n\n"
        f"{exports_block}\n\n"
        f"__all__ = {repr(all_names)}\n"
    )


def _build_python_pkg_adapter(
    *,
    adapter_name: str,
    package_name: str,
    import_name: str,
    repo_url: str,
    spdx_license: str,
    version_spec: str,
) -> str:
    return (
        f'"""本地隔离适配层：{adapter_name}（由 wf-agents 自动生成，策略 PACKAGE_DEP）。\n\n'
        f"依赖包: {package_name} ({version_spec or 'latest'})\n"
        f"上游来源: {repo_url}\n"
        f"许可证: {spdx_license}\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "import importlib\n"
        "from types import ModuleType\n\n"
        f"ADAPTER_META = {{\n"
        f'    "name": {adapter_name!r},\n'
        f'    "strategy": "PACKAGE_DEP",\n'
        f'    "package": {package_name!r},\n'
        f'    "versionSpec": {version_spec!r},\n'
        f'    "repository": {repo_url!r},\n'
        f'    "license": {spdx_license!r},\n'
        "}\n\n"
        "_CACHED_MOD: ModuleType | None = None\n\n\n"
        "def load_upstream_package() -> ModuleType:\n"
        '    """延迟加载三方包依赖；若本地尚未安装则抛出清晰中文指引。"""\n'
        "    global _CACHED_MOD\n"
        "    if _CACHED_MOD is None:\n"
        "        try:\n"
        f"            _CACHED_MOD = importlib.import_module({import_name!r})\n"
        "        except ModuleNotFoundError as exc:\n"
        f"            raise RuntimeError(f'请先安装依赖包 {package_name}: pip install {package_name}') from exc\n"
        "    return _CACHED_MOD\n\n\n"
        '__all__ = ["ADAPTER_META", "load_upstream_package"]\n'
    )


def _build_python_smoke_test(
    *,
    adapter_rel: str,
    adapter_name: str,
    strategy: str,
    exported_symbols: list[str],
    has_src_layout: bool,
) -> str:
    # 将 adapter_rel 转为可导入模块路径
    rel_no_ext = adapter_rel[:-3] if adapter_rel.endswith(".py") else adapter_rel
    if has_src_layout and rel_no_ext.startswith("src/"):
        import_path = rel_no_ext[4:].replace("/", ".")
        sys_path_line = 'SRC = PROJECT_ROOT / "src"\nif SRC.is_dir() and str(SRC) not in sys.path:\n    sys.path.insert(0, str(SRC))\n'
    else:
        import_path = rel_no_ext.replace("/", ".")
        sys_path_line = ""

    sym_checks = ""
    if strategy == "CODE_SLICE" and exported_symbols:
        sym_checks = (
            f"    for sym in {repr(exported_symbols)}:\n"
            "        assert hasattr(mod, sym), f'缺少预期导出符号: {sym}'\n"
            "        assert getattr(mod, sym) is not None, f'导出符号为 None: {sym}'\n"
        )
    elif strategy == "PACKAGE_DEP":
        sym_checks = '    assert hasattr(mod, "load_upstream_package")\n'

    return (
        f'"""由 wf-agents 生成的适配器冒烟测试：{adapter_name}。"""\n\n'
        "from __future__ import annotations\n\n"
        "import importlib\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        "PROJECT_ROOT = Path(__file__).resolve().parents[1]\n"
        "if str(PROJECT_ROOT) not in sys.path:\n"
        "    sys.path.insert(0, str(PROJECT_ROOT))\n"
        f"{sys_path_line}\n\n"
        f"def test_{adapter_name}_adapter_smoke() -> None:\n"
        f"    mod = importlib.import_module({import_path!r})\n"
        f'    assert mod.ADAPTER_META["name"] == {adapter_name!r}\n'
        f'    assert mod.ADAPTER_META["strategy"] == {strategy!r}\n'
        f"{sym_checks}"
        "\n\n"
        'if __name__ == "__main__":\n'
        f"    test_{adapter_name}_adapter_smoke()\n"
        f'    print("SMOKE_OK:{adapter_name}")\n'
    )


def _dependency_change_for_package(
    project_root: Path,
    package_name: str,
    version_spec: str,
    primary_language: str,
) -> tuple[str, str, str] | None:
    dep_line = f"{package_name}{version_spec}" if version_spec else package_name
    if primary_language in {"TypeScript", "JavaScript"}:
        pkg_file = project_root / "package.json"
        before = pkg_file.read_text(encoding="utf-8") if pkg_file.is_file() else '{\n  "name": "app",\n  "dependencies": {}\n}\n'
        try:
            obj = json.loads(before)
        except ValueError:
            obj = {"dependencies": {}}
        deps = obj.setdefault("dependencies", {})
        if package_name not in deps:
            deps[package_name] = version_spec or "latest"
        after = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        return "package.json", before, after

    # Python
    pyproject = project_root / "pyproject.toml"
    req_txt = project_root / "requirements.txt"
    if pyproject.is_file():
        before = pyproject.read_text(encoding="utf-8")
        if package_name.lower() in before.lower():
            return None
        if "dependencies = [" in before:
            after = before.replace(
                "dependencies = [",
                f'dependencies = [\n  "{dep_line}",',
                1,
            )
        else:
            after = before.rstrip() + f'\n\n[project]\ndependencies = [\n  "{dep_line}",\n]\n'
        return "pyproject.toml", before, after

    before = req_txt.read_text(encoding="utf-8") if req_txt.is_file() else ""
    existing_names = {
        re.split(r"[<>=!~;\[]", ln.strip(), maxsplit=1)[0].strip().lower()
        for ln in before.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    if package_name.lower() not in existing_names:
        after = (before.rstrip() + "\n" if before.strip() else "") + dep_line + "\n"
        return "requirements.txt", before, after
    return None


def design_integration_contract(
    *,
    project_path: str | Path,
    strategy: str,
    candidate: dict[str, Any],
    adapter_name: str,
    source_path: str | Path | None = None,
    slice_files: list[str] | None = None,
    file_contents: dict[str, str] | None = None,
    exported_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """设计本地对接契约与分块 Diff（Chunk A 依赖配置 / Chunk B 源码与合规 / Chunk C 适配层与冒烟测试）。"""
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise ToolError("INVALID_INPUT", f"本地目标项目目录不存在: {project_path}")

    norm_strategy = (strategy or "").strip().upper()
    if norm_strategy not in {"PACKAGE_DEP", "CODE_SLICE", "VENDORING", "SIDECAR", "PATTERN_REF"}:
        raise ToolError("INVALID_INPUT", f"不支持的策略: {strategy}")

    safe_name = _safe_identifier(adapter_name)
    profile = profiler.profile_local_project(root)
    primary_lang = profile.get("primaryLanguage") or "Python"
    adapter_dir = profile.get("adapterDir") or "adapters"
    test_dir = profile.get("testDir") or "tests"
    has_src_layout = profile.get("layout") == "src_layout"

    cand_name = str(candidate.get("name") or candidate.get("repo") or safe_name)
    repo_url = str(candidate.get("url") or candidate.get("repoUrl") or f"https://github.com/{candidate.get('repo') or cand_name}")
    spdx_license = str(candidate.get("license") or "UNKNOWN")
    commit_or_version = str(candidate.get("version") or candidate.get("commit") or "HEAD")
    pkg_name = str(candidate.get("packageName") or cand_name)
    import_name = str(candidate.get("importName") or pkg_name.replace("-", "_"))
    version_spec = str(candidate.get("versionSpec") or "")

    chunk_a: list[dict[str, Any]] = []
    chunk_b: list[dict[str, Any]] = []
    chunk_c: list[dict[str, Any]] = []

    def add_file(bucket: list[dict[str, Any]], rel_path: str, new_content: str, role: str) -> None:
        rel_posix = rel_path.replace("\\", "/").lstrip("./")
        target_file = root / rel_posix
        before = target_file.read_text(encoding="utf-8", errors="replace") if target_file.is_file() else ""
        bucket.append(
            {
                "path": rel_posix,
                "action": "modify" if target_file.is_file() else "create",
                "role": role,
                "content": new_content,
                "diff": _unified_diff(rel_posix, before, new_content),
            }
        )

    # Chunk A: 依赖与配置
    if norm_strategy == "PACKAGE_DEP":
        dep_chg = _dependency_change_for_package(root, pkg_name, version_spec, primary_lang)
        if dep_chg is not None:
            dep_rel, _, dep_after = dep_chg
            add_file(chunk_a, dep_rel, dep_after, "dependency_manifest")

    # Chunk B: 代码切片与合规追溯
    integrated_paths: list[str] = []
    slice_closure_info: dict[str, Any] = {}
    resolved_symbols: list[str] = list(exported_symbols or [])

    if norm_strategy in {"CODE_SLICE", "VENDORING"}:
        vendor_subdir = f"vendor_{safe_name}"
        raw_files: dict[str, str] = {}
        entry_rel = ""

        if source_path is not None:
            src_root = Path(source_path).expanduser().resolve()
            targets = list(slice_files or [])
            if not targets:
                raise ToolError("INVALID_INPUT", f"{norm_strategy} 策略必须提供 slice_files")
            closure = slicer.compute_slice_closure(src_root, targets)
            slice_closure_info = closure
            entry_rel = closure["entryFiles"][0]
            if not resolved_symbols:
                resolved_symbols = list(closure.get("exportedSymbols") or [])
            for rel in closure["closureFiles"]:
                raw_files[rel] = (src_root / rel).read_text(encoding="utf-8", errors="replace")
        elif file_contents:
            raw_files = {k.replace("\\", "/").lstrip("./"): v for k, v in file_contents.items()}
            entry_rel = (slice_files[0].replace("\\", "/").lstrip("./") if slice_files else sorted(raw_files.keys())[0])
        else:
            raise ToolError("INVALID_INPUT", f"{norm_strategy} 策略需要提供 source_path 或 file_contents")

        # 为 Python 包路径补齐 __init__.py
        init_dirs: set[str] = {adapter_dir, f"{adapter_dir}/{vendor_subdir}"}
        for rel in raw_files:
            parent_parts = Path(rel).parent.parts
            cur = f"{adapter_dir}/{vendor_subdir}"
            for part in parent_parts:
                if part and part != ".":
                    cur = f"{cur}/{part}"
                    init_dirs.add(cur)

        if primary_lang == "Python":
            # 如果采用 src_layout 且 adapter_dir 为 src/pkg/adapters，也确保 parent __init__.py 存在
            parts = Path(adapter_dir).parts
            if len(parts) >= 2 and parts[0] == "src":
                init_dirs.add(f"src/{parts[1]}")
            for d in sorted(init_dirs):
                init_rel = f"{d}/__init__.py"
                if not (root / init_rel).is_file() and f"{d}/__init__.py" not in {
                    f"{adapter_dir}/{vendor_subdir}/{rf}" for rf in raw_files
                }:
                    add_file(chunk_b, init_rel, '"""Package marker."""\n', "python_package_init")

        for rel, content in sorted(raw_files.items()):
            with_spdx = provenance.inject_spdx_header(
                content,
                repo_url=repo_url,
                commit_or_version=commit_or_version,
                spdx_license=spdx_license,
                original_path=rel,
            )
            dest_rel = f"{adapter_dir}/{vendor_subdir}/{rel}"
            integrated_paths.append(dest_rel)
            add_file(chunk_b, dest_rel, with_spdx, "sliced_upstream_source")

        # THIRD_PARTY_NOTICES.md
        notices_file = root / "THIRD_PARTY_NOTICES.md"
        existing_notices = notices_file.read_text(encoding="utf-8") if notices_file.is_file() else ""
        updated_notices = provenance.render_updated_notices(
            existing_notices,
            {
                "name": cand_name,
                "repo_url": repo_url,
                "commit_or_version": commit_or_version,
                "spdx_license": spdx_license,
                "strategy": norm_strategy,
                "files": integrated_paths,
                "notes": f"最小传递闭包共 {len(raw_files)} 个文件；已通过 Adapter 隔离封装。",
            },
        )
        add_file(chunk_b, "THIRD_PARTY_NOTICES.md", updated_notices, "license_provenance")

        # Chunk C: Adapter + Smoke Test
        adapter_rel = f"{adapter_dir}/{safe_name}_adapter.py"
        adapter_code = _build_python_slice_adapter(
            adapter_name=safe_name,
            vendor_subdir=vendor_subdir,
            entry_rel=entry_rel,
            repo_url=repo_url,
            spdx_license=spdx_license,
            commit_or_version=commit_or_version,
            exported_symbols=resolved_symbols,
        )
        add_file(chunk_c, adapter_rel, adapter_code, "facade_adapter")

    else:
        # PACKAGE_DEP / SIDECAR / PATTERN_REF -> 记录合规清单并生成薄 Adapter 契约
        notices_file = root / "THIRD_PARTY_NOTICES.md"
        existing_notices = notices_file.read_text(encoding="utf-8") if notices_file.is_file() else ""
        updated_notices = provenance.render_updated_notices(
            existing_notices,
            {
                "name": cand_name,
                "repo_url": repo_url,
                "commit_or_version": commit_or_version,
                "spdx_license": spdx_license,
                "strategy": norm_strategy,
                "files": [f"{adapter_dir}/{safe_name}_adapter.py"],
                "notes": f"通过 {norm_strategy} 策略以 Adapter 接口契约接入。",
            },
        )
        add_file(chunk_b, "THIRD_PARTY_NOTICES.md", updated_notices, "license_provenance")

        if primary_lang == "Python" and not (root / f"{adapter_dir}/__init__.py").is_file():
            add_file(chunk_c, f"{adapter_dir}/__init__.py", '"""Adapter package."""\n', "python_package_init")

        adapter_rel = f"{adapter_dir}/{safe_name}_adapter.py"
        adapter_code = _build_python_pkg_adapter(
            adapter_name=safe_name,
            package_name=pkg_name,
            import_name=import_name,
            repo_url=repo_url,
            spdx_license=spdx_license,
            version_spec=version_spec,
        )
        add_file(chunk_c, adapter_rel, adapter_code, "facade_adapter")

    smoke_test_rel = f"{test_dir}/test_{safe_name}_smoke.py"
    smoke_code = _build_python_smoke_test(
        adapter_rel=adapter_rel,
        adapter_name=safe_name,
        strategy=norm_strategy,
        exported_symbols=resolved_symbols,
        has_src_layout=has_src_layout,
    )
    add_file(chunk_c, smoke_test_rel, smoke_code, "smoke_test")

    all_planned_files = [item["path"] for item in (*chunk_a, *chunk_b, *chunk_c)]

    evidences = [
        f"Local Project Profile: primaryLanguage={primary_lang}, layout={profile.get('layout')}, adapterDir={adapter_dir}",
        f"Strategy: {norm_strategy}, Planned Files: {len(all_planned_files)}",
        f"Provenance: SPDX `{spdx_license}` + THIRD_PARTY_NOTICES.md 变更已就绪",
    ]
    if slice_closure_info:
        evidences.append(
            f"Slice Closure: {slice_closure_info.get('fileCount')} files, {slice_closure_info.get('loc')} LOC, "
            f"closureComplete={slice_closure_info.get('closureComplete')}"
        )

    tradeoffs = [
        f"将上游能力隔离在 `{adapter_rel}`，业务代码只调用该内部契约，便于未来替换",
        "应用前会自动生成 `.wf/checkpoints/` 安全快照，验证失败或人工不满意可 1 秒回滚",
    ]
    if norm_strategy == "CODE_SLICE" and slice_closure_info.get("externalPackages"):
        tradeoffs.append(f"切片仍存在上游三方包依赖: {', '.join(slice_closure_info['externalPackages'])}")

    brief = wf_envelope.build_decision_brief(
        requirement_fit=f"已完成 `{norm_strategy}` 对接契约设计：共 {len(all_planned_files)} 个受控文件变更，含 Facade 隔离与冒烟测试。",
        verifiable_evidence=evidences,
        limitations_and_tradeoffs=tradeoffs,
        actionable_options=[
            {
                "id": "approve_contract_and_diff",
                "recommended": True,
                "summary": "批准对接契约与分块 Diff（通过 Gate 4 / Gate 5），继续创建检查点并组装落地",
            },
            {
                "id": "revise_slice_or_adapter",
                "recommended": False,
                "summary": "调整切片范围、目标目录或 Adapter 导出符号后重新生成契约",
            },
        ],
    )

    return {
        "projectRoot": str(root),
        "strategy": norm_strategy,
        "adapterName": safe_name,
        "adapterFile": adapter_rel,
        "smokeTestFile": smoke_test_rel,
        "localProfile": profile,
        "sliceClosure": slice_closure_info,
        "plannedFiles": all_planned_files,
        "chunks": {
            "A_dependency_and_config": chunk_a,
            "B_code_and_provenance": chunk_b,
            "C_adapter_and_smoke_test": chunk_c,
        },
        "decision_brief": brief,
    }
