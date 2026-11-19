"""本地对接契约设计与分块 Diff 生成器（Step 4 & Gate 4/5）。

完整支持全 5 种复用策略（PACKAGE_DEP / CODE_SLICE / VENDORING / SIDECAR / PATTERN_REF），
原生生成 Python 与 TypeScript/JavaScript（ES Module）薄隔离适配层（Adapter）及冒烟测试，
并自动支持远程 GitHub 仓库按需免克隆切片：
- Chunk A (dependency_and_config): 依赖清单变更或 Sidecar Docker Compose 编排配置
- Chunk B (code_and_provenance): 带 SPDX 头的切片文件 / Clean-Room 架构规约 / THIRD_PARTY_NOTICES.md
- Chunk C (adapter_and_smoke_test): 薄 Facade/Adapter 隔离层 + 自包含冒烟测试
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
    strategy: str,
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
    export_lines = [
        f"{sym} = getattr(_UPSTREAM_MODULE, {sym!r}, None)"
        for sym in exported_symbols
        if sym.isidentifier()
    ]
    exports_block = "\n".join(export_lines) if export_lines else "# 通过 get_upstream_module() 访问上游模块"
    all_names = ["ADAPTER_META", "get_upstream_module"] + [s for s in exported_symbols if s.isidentifier()]

    return (
        f'"""本地隔离适配层：{adapter_name}（由 wf-agents 自动生成，策略 {strategy}）。\n\n'
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
        f'    "strategy": {strategy!r},\n'
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


def _build_python_sidecar_adapter(
    *,
    adapter_name: str,
    cand_name: str,
    repo_url: str,
    spdx_license: str,
    commit_or_version: str,
) -> str:
    return (
        f'"""本地隔离适配层：{adapter_name}（由 wf-agents 自动生成，策略 SIDECAR）。\n\n'
        f"独立进程/容器隔离候选: {cand_name} ({repo_url})\n"
        f"许可证: {spdx_license} | 版本: {commit_or_version}\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n"
        "import subprocess\n"
        "from typing import Any\n"
        "from urllib import request as urlrequest\n\n"
        f"ADAPTER_META = {{\n"
        f'    "name": {adapter_name!r},\n'
        f'    "strategy": "SIDECAR",\n'
        f'    "candidate": {cand_name!r},\n'
        f'    "repository": {repo_url!r},\n'
        f'    "version": {commit_or_version!r},\n'
        f'    "license": {spdx_license!r},\n'
        f'    "defaultEndpoint": "http://127.0.0.1:18080",\n'
        "}\n\n\n"
        "class SidecarClient:\n"
        '    """跨语言或强传染许可证隔离的独立伴生客户端（CLI / HTTP 双通道）。"""\n\n'
        '    def __init__(self, endpoint: str = "http://127.0.0.1:18080", cli_bin: list[str] | None = None) -> None:\n'
        "        self.endpoint = endpoint.rstrip('/')\n"
        "        self.cli_bin = list(cli_bin or [])\n\n"
        "    def call_cli(self, args: list[str], *, timeout: int = 15) -> dict[str, Any]:\n"
        "        if not self.cli_bin:\n"
        "            raise RuntimeError('未配置 Sidecar CLI 可执行命令 cli_bin')\n"
        "        proc = subprocess.run(\n"
        "            [*self.cli_bin, *args],\n"
        "            capture_output=True,\n"
        '            text=True,\n'
        '            encoding="utf-8",\n'
        '            errors="replace",\n'
        "            timeout=timeout,\n"
        "        )\n"
        '        return {"exitCode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}\n\n'
        '    def call_http(self, path: str, payload: dict[str, Any] | None = None, *, timeout: int = 10) -> Any:\n'
        '        url = f"{self.endpoint}/{path.lstrip(\'/\')}"\n'
        "        data = json.dumps(payload).encode('utf-8') if payload is not None else None\n"
        "        headers = {'Content-Type': 'application/json'} if data is not None else {}\n"
        "        req = urlrequest.Request(url, data=data, headers=headers, method='POST' if data else 'GET')\n"
        "        with urlrequest.urlopen(req, timeout=timeout) as resp:\n"
        "            raw = resp.read().decode('utf-8')\n"
        "            return json.loads(raw) if raw.strip() else {}\n\n\n"
        '__all__ = ["ADAPTER_META", "SidecarClient"]\n'
    )


def _build_python_pattern_ref_adapter(
    *,
    adapter_name: str,
    cand_name: str,
    repo_url: str,
    spdx_license: str,
    signatures: list[dict[str, Any]],
) -> str:
    stubs: list[str] = []
    exported_names: list[str] = ["ADAPTER_META"]
    for sig in signatures:
        sym = str(sig.get("name") or "").strip()
        if not sym or not sym.isidentifier():
            continue
        exported_names.append(sym)
        if sig.get("kind") == "class":
            methods = sig.get("methods") or ["run"]
            m_blocks = "\n".join(
                f"    def {m}(self, *args, **kwargs):\n"
                f'        raise NotImplementedError("TODO(clean-room): 实现 {sym}.{m}")\n'
                for m in methods
                if str(m).isidentifier()
            )
            stubs.append(
                f"class {sym}:\n"
                f'    """Clean-Room 骨架类：参考 `{cand_name}` 契约在本地自主实现。"""\n\n'
                f"{m_blocks}"
            )
        else:
            raw_args = [str(a) for a in (sig.get("args") or []) if str(a).isidentifier()]
            arg_str = ", ".join(raw_args) if raw_args else "*args, **kwargs"
            stubs.append(
                f"def {sym}({arg_str}):\n"
                f'    """Clean-Room 骨架函数：参考 `{cand_name}` 契约在本地自主实现。"""\n'
                f'    raise NotImplementedError("TODO(clean-room): 实现 {sym}")\n'
            )

    if not stubs:
        stubs.append(
            "def execute_cleanroom(*args, **kwargs):\n"
            f'    """Clean-Room 骨架函数：参考 `{cand_name}` 设计规约在本地自主实现。"""\n'
            '    raise NotImplementedError("TODO(clean-room): 实现本地逻辑")\n'
        )
        exported_names.append("execute_cleanroom")

    stubs_block = "\n\n".join(stubs)
    return (
        f'"""净室模式（Clean-Room）本地骨架适配器：{adapter_name}（策略 PATTERN_REF）。\n\n'
        f"架构灵感来源: {repo_url} (原协议: {spdx_license})\n"
        "声明: 本文件未复制任何上游源码，仅保留独立抽取的公开接口签名用于本地干净实现。\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        f"ADAPTER_META = {{\n"
        f'    "name": {adapter_name!r},\n'
        f'    "strategy": "PATTERN_REF",\n'
        f'    "cleanRoom": True,\n'
        f'    "referenceRepository": {repo_url!r},\n'
        f'    "referenceLicense": {spdx_license!r},\n'
        f'    "skeletonSymbols": {repr(exported_names[1:])},\n'
        "}\n\n\n"
        f"{stubs_block}\n\n"
        f"__all__ = {repr(exported_names)}\n"
    )


def _build_python_smoke_test(
    *,
    adapter_rel: str,
    adapter_name: str,
    strategy: str,
    exported_symbols: list[str],
    has_src_layout: bool,
) -> str:
    rel_no_ext = adapter_rel[:-3] if adapter_rel.endswith(".py") else adapter_rel
    if has_src_layout and rel_no_ext.startswith("src/"):
        import_path = rel_no_ext[4:].replace("/", ".")
        sys_path_line = 'SRC = PROJECT_ROOT / "src"\nif SRC.is_dir() and str(SRC) not in sys.path:\n    sys.path.insert(0, str(SRC))\n'
    else:
        import_path = rel_no_ext.replace("/", ".")
        sys_path_line = ""

    extra_checks = ""
    if strategy in {"CODE_SLICE", "VENDORING"} and exported_symbols:
        extra_checks = (
            f"    for sym in {repr(exported_symbols)}:\n"
            "        assert hasattr(mod, sym), f'缺少预期导出符号: {sym}'\n"
            "        assert getattr(mod, sym) is not None, f'导出符号为 None: {sym}'\n"
        )
    elif strategy == "PACKAGE_DEP":
        extra_checks = '    assert hasattr(mod, "load_upstream_package")\n'
    elif strategy == "SIDECAR":
        extra_checks = (
            '    client = mod.SidecarClient()\n'
            '    assert client.endpoint.startswith("http://")\n'
        )
    elif strategy == "PATTERN_REF":
        extra_checks = (
            '    assert mod.ADAPTER_META.get("cleanRoom") is True\n'
            '    for sym in mod.ADAPTER_META.get("skeletonSymbols", []):\n'
            "        assert hasattr(mod, sym)\n"
        )

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
        f"{extra_checks}"
        "\n\n"
        'if __name__ == "__main__":\n'
        f"    test_{adapter_name}_adapter_smoke()\n"
        f'    print("SMOKE_OK:{adapter_name}")\n'
    )


def _build_js_ts_adapter(
    *,
    adapter_name: str,
    strategy: str,
    is_ts: bool,
    vendor_subdir: str,
    entry_rel: str,
    package_name: str,
    repo_url: str,
    spdx_license: str,
    commit_or_version: str,
    exported_symbols: list[str],
) -> str:
    clean_syms = [s for s in exported_symbols if s.isidentifier()]
    meta_block = (
        f"export const ADAPTER_META = {{\n"
        f"  name: {adapter_name!r},\n"
        f"  strategy: {strategy!r},\n"
        f"  repository: {repo_url!r},\n"
        f"  version: {commit_or_version!r},\n"
        f"  license: {spdx_license!r},\n"
        f"  cleanRoom: {str(strategy == 'PATTERN_REF').lower()},\n"
        f"}};\n"
    )

    if strategy in {"CODE_SLICE", "VENDORING"}:
        rel_import = f"./{vendor_subdir}/{entry_rel.lstrip('./')}"
        reexports = "\n".join(f"export const {s} = upstreamModule.{s};" for s in clean_syms)
        return (
            f"// 本地隔离适配层 ({strategy}) - 由 wf-agents 自动生成\n"
            f'import * as upstreamModule from "{rel_import}";\n\n'
            f"{meta_block}\n"
            "export function getUpstreamModule() {\n"
            "  return upstreamModule;\n"
            "}\n"
            f"{reexports}\n"
        )

    if strategy == "SIDECAR":
        type_str = ": string" if is_ts else ""
        opt_type = ": Record<string, unknown> | null = null" if is_ts else " = null"
        return (
            "// 伴生服务隔离适配器 (SIDECAR) - 由 wf-agents 自动生成\n"
            f"{meta_block}\n"
            "export class SidecarClient {\n"
            f"  constructor(endpoint{type_str} = 'http://127.0.0.1:18080') {{\n"
            "    this.endpoint = endpoint.replace(/\\/+$/, '');\n"
            "  }\n"
            f"  async callHttp(path{type_str}, payload{opt_type}) {{\n"
            "    const url = `${this.endpoint}/${path.replace(/^\\/+/, '')}`;\n"
            "    const res = await fetch(url, payload ? {\n"
            "      method: 'POST',\n"
            "      headers: { 'Content-Type': 'application/json' },\n"
            "      body: JSON.stringify(payload),\n"
            "    } : { method: 'GET' });\n"
            "    return await res.json();\n"
            "  }\n"
            "}\n"
        )

    if strategy == "PATTERN_REF":
        stubs = "\n".join(
            f"export function {s}() {{\n  throw new Error('TODO(clean-room): implement {s}');\n}}"
            for s in (clean_syms or ["executeCleanRoom"])
        )
        return (
            "// 净室模式 (PATTERN_REF) 本地骨架适配器 - 零上游源码复制\n"
            f"{meta_block}\n"
            f"{stubs}\n"
        )

    return (
        f"// 包依赖隔离适配器 (PACKAGE_DEP) - {package_name}\n"
        f"{meta_block}\n"
        "export async function loadUpstreamPackage() {\n"
        f"  return await import({package_name!r});\n"
        "}\n"
    )


def _build_js_ts_smoke_test(
    *,
    adapter_rel: str,
    smoke_test_rel: str,
    adapter_name: str,
    strategy: str,
    is_ts: bool,
    exported_symbols: list[str],
) -> str:
    # 计算相对导入路径
    depth = len(Path(smoke_test_rel).parent.parts)
    up_prefix = "../" * depth
    rel_to_adapter = up_prefix + adapter_rel.lstrip("./")

    if is_ts:
        # 对于 .ts 适配器，直接检查文件存在性、策略标识及导出声明，无需外部 ts-node 即可跑通 Node 冒烟
        return (
            "import assert from 'node:assert/strict';\n"
            "import fs from 'node:fs';\n"
            "import path from 'node:path';\n"
            "import { fileURLToPath } from 'node:url';\n\n"
            "const __dirname = path.dirname(fileURLToPath(import.meta.url));\n"
            f"const adapterPath = path.resolve(__dirname, {rel_to_adapter!r});\n"
            "const text = fs.readFileSync(adapterPath, 'utf-8');\n"
            f"assert.ok(text.includes({adapter_name!r}), 'Adapter name missing');\n"
            f"assert.ok(text.includes({strategy!r}), 'Adapter strategy missing');\n"
            f"console.log('SMOKE_OK:{adapter_name}');\n"
        )

    sym_checks = "\n".join(
        f"assert.ok({s!r} in mod && mod[{s!r}] !== undefined, 'Missing symbol {s}');"
        for s in exported_symbols
        if s.isidentifier()
    )
    sidecar_check = (
        "const client = new mod.SidecarClient();\nassert.ok(client.endpoint.startsWith('http://'));"
        if strategy == "SIDECAR"
        else ""
    )
    return (
        "import assert from 'node:assert/strict';\n"
        f"import * as mod from {rel_to_adapter!r};\n\n"
        f"assert.equal(mod.ADAPTER_META.name, {adapter_name!r});\n"
        f"assert.equal(mod.ADAPTER_META.strategy, {strategy!r});\n"
        f"{sym_checks}\n"
        f"{sidecar_check}\n"
        f"console.log('SMOKE_OK:{adapter_name}');\n"
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
        before = (
            pkg_file.read_text(encoding="utf-8")
            if pkg_file.is_file()
            else '{\n  "name": "app",\n  "type": "module",\n  "dependencies": {}\n}\n'
        )
        try:
            obj = json.loads(before)
        except ValueError:
            obj = {"dependencies": {}}
        deps = obj.setdefault("dependencies", {})
        if package_name not in deps:
            deps[package_name] = version_spec or "latest"
        after = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        return "package.json", before, after

    pyproject = project_root / "pyproject.toml"
    req_txt = project_root / "requirements.txt"
    if pyproject.is_file():
        before = pyproject.read_text(encoding="utf-8")
        if package_name.lower() in before.lower():
            return None
        if "dependencies = [" in before:
            after = before.replace("dependencies = [", f'dependencies = [\n  "{dep_line}",', 1)
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


def _sidecar_compose_template(safe_name: str, cand_name: str, repo_url: str, cand_lang: str) -> str:
    image = "python:3.12-slim" if cand_lang.lower() == "python" else "alpine:3.20"
    return (
        "# 由 wf-agents 生成的伴生隔离服务编排模板 (SIDECAR 策略)\n"
        f"# 候选组件: {cand_name} ({repo_url})\n"
        "services:\n"
        f"  {safe_name}-sidecar:\n"
        f"    image: {image}\n"
        f"    container_name: wf-{safe_name}-sidecar\n"
        "    ports:\n"
        '      - "127.0.0.1:18080:8080"\n'
        "    restart: unless-stopped\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "exit 0"]\n'
        "      interval: 15s\n"
        "      timeout: 5s\n"
        "      retries: 3\n"
    )


def _cleanroom_spec_markdown(
    *,
    cand_name: str,
    repo_url: str,
    spdx_license: str,
    commit_or_version: str,
    signatures: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Clean-Room Architectural Specification — {cand_name}",
        "",
        f"- **Reference Repository**: {repo_url}",
        f"- **Reference Version / Commit**: `{commit_or_version}`",
        f"- **Reference License**: `{spdx_license}`",
        "- **Compliance Isolation**: Zero upstream source implementation copied; skeleton signatures extracted for clean-room re-implementation.",
        "",
        "## Extracted Public Interface Signatures",
        "",
    ]
    if not signatures:
        lines.append("- `execute_cleanroom(*args, **kwargs)` — 通用净室入口")
    else:
        for sig in signatures:
            if sig.get("kind") == "class":
                methods = ", ".join(sig.get("methods") or [])
                lines.append(f"- `class {sig['name']}` (methods: `{methods or 'run'}`)")
            else:
                args = ", ".join(sig.get("args") or [])
                lines.append(f"- `{sig['name']}({args})`")
    lines.extend(
        [
            "",
            "## Clean-Room Implementation Checklist",
            "1. 根据以上公开签名与业务需求独立编写本地实现，勿抄袭原仓实现源码。",
            "2. 通过生成的冒烟测试与业务单测后提交 Gate 6 验收。",
        ]
    )
    return "\n".join(lines) + "\n"


def design_integration_contract(
    *,
    project_path: str | Path,
    strategy: str,
    candidate: dict[str, Any],
    adapter_name: str,
    source_path: str | Path | None = None,
    repo: str | None = None,
    ref: str | None = None,
    slice_files: list[str] | None = None,
    file_contents: dict[str, str] | None = None,
    exported_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """设计本地对接契约与分块 Diff（支持全 5 种策略及 Python / TS / JS 原生适配）。"""
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise ToolError("INVALID_INPUT", f"本地目标项目目录不存在: {project_path}")

    norm_strategy = (strategy or "").strip().upper()
    if norm_strategy not in {"PACKAGE_DEP", "CODE_SLICE", "VENDORING", "SIDECAR", "PATTERN_REF"}:
        raise ToolError("INVALID_INPUT", f"不支持的策略: {strategy}")

    safe_name = _safe_identifier(adapter_name)
    profile = profiler.profile_local_project(root)
    primary_lang = profile.get("primaryLanguage") or "Python"
    is_js_ts = primary_lang in {"TypeScript", "JavaScript"}
    is_ts = primary_lang == "TypeScript"
    adapter_dir = profile.get("adapterDir") or "adapters"
    test_dir = profile.get("testDir") or "tests"
    has_src_layout = profile.get("layout") == "src_layout"

    cand_name = str(candidate.get("name") or candidate.get("repo") or safe_name)
    cand_repo = str(repo or candidate.get("repo") or "").strip()
    cand_lang = str(candidate.get("language") or primary_lang)
    repo_url = str(
        candidate.get("url")
        or candidate.get("repoUrl")
        or (f"https://github.com/{cand_repo}" if cand_repo else f"https://github.com/{cand_name}")
    )
    spdx_license = str(candidate.get("license") or "UNKNOWN")
    commit_or_version = str(ref or candidate.get("version") or candidate.get("commit") or "HEAD")
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

    integrated_paths: list[str] = []
    slice_closure_info: dict[str, Any] = {}
    resolved_symbols: list[str] = list(exported_symbols or [])

    adapter_ext = ".ts" if is_ts else (".mjs" if is_js_ts else ".py")
    adapter_rel = f"{adapter_dir}/{safe_name}_adapter{adapter_ext}"
    smoke_test_rel = f"{test_dir}/test_{safe_name}_smoke{'.mjs' if is_js_ts else '.py'}"

    if not is_js_ts and not (root / f"{adapter_dir}/__init__.py").is_file():
        # 非切片模式也保证包可导入
        if norm_strategy not in {"CODE_SLICE", "VENDORING"}:
            parts = Path(adapter_dir).parts
            if len(parts) >= 2 and parts[0] == "src" and not (root / f"src/{parts[1]}/__init__.py").is_file():
                add_file(chunk_c, f"src/{parts[1]}/__init__.py", '"""Package marker."""\n', "python_package_init")
            add_file(chunk_c, f"{adapter_dir}/__init__.py", '"""Adapter package."""\n', "python_package_init")

    # 1. PACKAGE_DEP
    if norm_strategy == "PACKAGE_DEP":
        dep_chg = _dependency_change_for_package(root, pkg_name, version_spec, primary_lang)
        if dep_chg is not None:
            dep_rel, _, dep_after = dep_chg
            add_file(chunk_a, dep_rel, dep_after, "dependency_manifest")

        if is_js_ts:
            adapter_code = _build_js_ts_adapter(
                adapter_name=safe_name,
                strategy=norm_strategy,
                is_ts=is_ts,
                vendor_subdir="",
                entry_rel="",
                package_name=pkg_name,
                repo_url=repo_url,
                spdx_license=spdx_license,
                commit_or_version=commit_or_version,
                exported_symbols=resolved_symbols,
            )
        else:
            adapter_code = _build_python_pkg_adapter(
                adapter_name=safe_name,
                package_name=pkg_name,
                import_name=import_name,
                repo_url=repo_url,
                spdx_license=spdx_license,
                version_spec=version_spec,
            )
        add_file(chunk_c, adapter_rel, adapter_code, "facade_adapter")
        integrated_paths = [adapter_rel]

    # 2. CODE_SLICE & VENDORING (支持本地 source_path、file_contents 与远程 repo 免克隆按需拉取)
    elif norm_strategy in {"CODE_SLICE", "VENDORING"}:
        vendor_subdir = f"vendor_{safe_name}"
        raw_files: dict[str, str] = {}
        entry_rel = ""

        if source_path is not None or (cand_repo and slice_files and not file_contents):
            targets = list(slice_files or [])
            if not targets:
                raise ToolError("INVALID_INPUT", f"{norm_strategy} 策略必须提供 slice_files")
            closure = slicer.compute_slice_closure(
                source_path,
                targets,
                repo=None if source_path is not None else cand_repo,
                ref=ref,
            )
            slice_closure_info = closure
            staged_root = Path(closure["sourceRoot"])
            entry_rel = closure["entryFiles"][0]
            if not resolved_symbols:
                resolved_symbols = list(closure.get("exportedSymbols") or [])
            for rel in closure["closureFiles"]:
                raw_files[rel] = (staged_root / rel).read_text(encoding="utf-8", errors="replace")
        elif file_contents:
            raw_files = {k.replace("\\", "/").lstrip("./"): v for k, v in file_contents.items()}
            entry_rel = slice_files[0].replace("\\", "/").lstrip("./") if slice_files else sorted(raw_files.keys())[0]
        else:
            raise ToolError("INVALID_INPUT", f"{norm_strategy} 策略需要提供 source_path、file_contents 或 candidate.repo + slice_files")

        if not is_js_ts:
            init_dirs: set[str] = {adapter_dir, f"{adapter_dir}/{vendor_subdir}"}
            for rel in raw_files:
                parent_parts = Path(rel).parent.parts
                cur = f"{adapter_dir}/{vendor_subdir}"
                for part in parent_parts:
                    if part and part != ".":
                        cur = f"{cur}/{part}"
                        init_dirs.add(cur)
            parts = Path(adapter_dir).parts
            if len(parts) >= 2 and parts[0] == "src":
                init_dirs.add(f"src/{parts[1]}")
            raw_set = {f"{adapter_dir}/{vendor_subdir}/{rf}" for rf in raw_files}
            for d in sorted(init_dirs):
                init_rel = f"{d}/__init__.py"
                if not (root / init_rel).is_file() and init_rel not in raw_set:
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

        if is_js_ts:
            adapter_code = _build_js_ts_adapter(
                adapter_name=safe_name,
                strategy=norm_strategy,
                is_ts=is_ts,
                vendor_subdir=vendor_subdir,
                entry_rel=entry_rel,
                package_name=pkg_name,
                repo_url=repo_url,
                spdx_license=spdx_license,
                commit_or_version=commit_or_version,
                exported_symbols=resolved_symbols,
            )
        else:
            adapter_code = _build_python_slice_adapter(
                adapter_name=safe_name,
                strategy=norm_strategy,
                vendor_subdir=vendor_subdir,
                entry_rel=entry_rel,
                repo_url=repo_url,
                spdx_license=spdx_license,
                commit_or_version=commit_or_version,
                exported_symbols=resolved_symbols,
            )
        add_file(chunk_c, adapter_rel, adapter_code, "facade_adapter")

    # 3. SIDECAR (Chunk A docker-compose.sidecar.yml + SidecarClient)
    elif norm_strategy == "SIDECAR":
        compose_yaml = _sidecar_compose_template(safe_name, cand_name, repo_url, cand_lang)
        add_file(chunk_a, "docker-compose.sidecar.yml", compose_yaml, "sidecar_compose")
        if is_js_ts:
            adapter_code = _build_js_ts_adapter(
                adapter_name=safe_name,
                strategy="SIDECAR",
                is_ts=is_ts,
                vendor_subdir="",
                entry_rel="",
                package_name=pkg_name,
                repo_url=repo_url,
                spdx_license=spdx_license,
                commit_or_version=commit_or_version,
                exported_symbols=[],
            )
        else:
            adapter_code = _build_python_sidecar_adapter(
                adapter_name=safe_name,
                cand_name=cand_name,
                repo_url=repo_url,
                spdx_license=spdx_license,
                commit_or_version=commit_or_version,
            )
        add_file(chunk_c, adapter_rel, adapter_code, "sidecar_client_adapter")
        integrated_paths = ["docker-compose.sidecar.yml", adapter_rel]

    # 4. PATTERN_REF (Clean-Room Spec + Zero-Contamination Skeleton)
    else:
        sig_texts: dict[str, str] = {}
        if source_path is not None and slice_files:
            sroot = Path(source_path).expanduser().resolve()
            for rf in slice_files:
                p = sroot / rf
                if p.is_file():
                    sig_texts[rf] = p.read_text(encoding="utf-8", errors="replace")
        elif file_contents:
            sig_texts = dict(file_contents)
        elif cand_repo and slice_files:
            closure = slicer.compute_slice_closure(None, slice_files, repo=cand_repo, ref=ref)
            sroot = Path(closure["sourceRoot"])
            for rf in closure["entryFiles"]:
                sig_texts[rf] = (sroot / rf).read_text(encoding="utf-8", errors="replace")

        signatures = slicer.extract_symbol_signatures(sig_texts) if sig_texts else [
            {"kind": "function", "name": s, "args": []} for s in resolved_symbols
        ]
        if not resolved_symbols:
            resolved_symbols = [str(sig["name"]) for sig in signatures if sig.get("name")]

        spec_rel = f"{adapter_dir}/{safe_name}_cleanroom_spec.md"
        spec_md = _cleanroom_spec_markdown(
            cand_name=cand_name,
            repo_url=repo_url,
            spdx_license=spdx_license,
            commit_or_version=commit_or_version,
            signatures=signatures,
        )
        add_file(chunk_b, spec_rel, spec_md, "cleanroom_architecture_spec")

        if is_js_ts:
            adapter_code = _build_js_ts_adapter(
                adapter_name=safe_name,
                strategy="PATTERN_REF",
                is_ts=is_ts,
                vendor_subdir="",
                entry_rel="",
                package_name=pkg_name,
                repo_url=repo_url,
                spdx_license=spdx_license,
                commit_or_version=commit_or_version,
                exported_symbols=resolved_symbols,
            )
        else:
            adapter_code = _build_python_pattern_ref_adapter(
                adapter_name=safe_name,
                cand_name=cand_name,
                repo_url=repo_url,
                spdx_license=spdx_license,
                signatures=signatures,
            )
        add_file(chunk_c, adapter_rel, adapter_code, "cleanroom_skeleton_adapter")
        integrated_paths = [spec_rel, adapter_rel]

    # 更新 THIRD_PARTY_NOTICES.md (Chunk B)
    notices_file = root / "THIRD_PARTY_NOTICES.md"
    existing_notices = notices_file.read_text(encoding="utf-8") if notices_file.is_file() else ""
    strategy_note = {
        "CODE_SLICE": f"最小传递闭包共 {len(slice_closure_info.get('closureFiles') or integrated_paths)} 个文件；已注入 SPDX 并通过 Adapter 隔离。",
        "VENDORING": "整仓源码内嵌，已保留原版权与 SPDX 头并通过 Adapter 隔离。",
        "PACKAGE_DEP": "标准化包依赖导入，经由 Adapter 隔离接入。",
        "SIDECAR": "通过独立进程/容器（docker-compose.sidecar.yml）物理边界隔离。",
        "PATTERN_REF": "仅参考公开设计规约实现（Clean-Room），未复制上游实现代码。",
    }[norm_strategy]
    updated_notices = provenance.render_updated_notices(
        existing_notices,
        {
            "name": cand_name,
            "repo_url": repo_url,
            "commit_or_version": commit_or_version,
            "spdx_license": spdx_license,
            "strategy": norm_strategy,
            "files": integrated_paths,
            "notes": strategy_note,
        },
    )
    add_file(chunk_b, "THIRD_PARTY_NOTICES.md", updated_notices, "license_provenance")

    # Smoke Test (Chunk C)
    if is_js_ts:
        smoke_code = _build_js_ts_smoke_test(
            adapter_rel=adapter_rel,
            smoke_test_rel=smoke_test_rel,
            adapter_name=safe_name,
            strategy=norm_strategy,
            is_ts=is_ts,
            exported_symbols=resolved_symbols,
        )
    else:
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
    if norm_strategy in {"CODE_SLICE", "VENDORING"} and slice_closure_info.get("externalPackages"):
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
        "primaryLanguage": primary_lang,
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
