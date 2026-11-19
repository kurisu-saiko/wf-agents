"""通用跨宿主统一安装器：支持 Antigravity / Claude Code / Cursor / Codex / Gemini CLI / OpenCode / Generic。

以顶层 skills/、rules/、agents/ 与 wf-mode/tools/wf_mcp.py 为唯一真源；
只写声明的目标路径；不复制用户配置、会话或密钥。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent if (ROOT.parent / "plugin.json").is_file() else ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUPPORTED_HOSTS = [
    "antigravity",
    "claude",
    "cursor",
    "codex",
    "gemini",
    "opencode",
    "generic",
]

_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".wf",
    "tests",
    "runtime",
    "agents",
    "legacy",
    "sessions",
    "projects",
    "backups",
}
_EXCLUDE_REL = {
    "panel/state.json",
    "panel/backups",
    "settings.json",
}


class HostError(RuntimeError):
    """宿主安装器异常；消息直接展示给用户。"""


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def _copy_wf_runtime(dest_wf_mode: Path) -> None:
    if dest_wf_mode.exists():
        shutil.rmtree(dest_wf_mode)
    dest_wf_mode.mkdir(parents=True, exist_ok=True)
    for item in ROOT.iterdir():
        name = item.name
        if name in _EXCLUDE_DIRS:
            continue
        if item.is_dir():
            def _ignore(directory: str, entries: list[str]) -> list[str]:
                ignored: list[str] = []
                rel_base = Path(directory).relative_to(ROOT).as_posix()
                for entry in entries:
                    rel = f"{rel_base}/{entry}" if rel_base != "." else entry
                    if (
                        entry in _EXCLUDE_DIRS
                        or entry.endswith((".pyc", ".pyo"))
                        or ".bak." in entry
                        or rel in _EXCLUDE_REL
                    ):
                        ignored.append(entry)
                return ignored

            shutil.copytree(item, dest_wf_mode / name, ignore=_ignore)
        else:
            if name in {"settings.json"} or name.endswith(".pyc") or ".bak." in name:
                continue
            shutil.copy2(item, dest_wf_mode / name)


def _copy_tree_clean(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _backup(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mcp_server_entry(installed_wf_mode: Path, python_exe: str, data_dir: Path) -> dict[str, Any]:
    return {
        "command": python_exe,
        "args": [(installed_wf_mode / "tools" / "wf_mcp.py").as_posix()],
        "env": {
            "WF_ROOT": installed_wf_mode.as_posix(),
            "WF_DATA_DIR": data_dir.as_posix(),
        },
    }


def _copy_universal_assets(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for fname in ("plugin.json", "README.md", "LICENSE"):
        src = REPO_ROOT / fname
        if src.is_file():
            shutil.copy2(src, target / fname)
    for folder in ("assets", "skills", "agents", "rules"):
        _copy_tree_clean(REPO_ROOT / folder, target / folder)
    _copy_wf_runtime(target / "wf-mode")


def _skill_names() -> list[str]:
    skills_dir = REPO_ROOT / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def _copy_skills_flat(target_skills_dir: Path) -> None:
    skills_dir = REPO_ROOT / "skills"
    if not skills_dir.is_dir():
        return
    for skill_dir in skills_dir.iterdir():
        if skill_dir.is_dir():
            _copy_tree_clean(skill_dir, target_skills_dir / skill_dir.name)


def install_antigravity(target: Path, python_exe: str, apply: bool) -> list[str]:
    data_dir = Path.home() / ".wf-agents"
    wf_root = target / "wf-mode"
    skill_list = ", ".join(_skill_names())
    actions = [
        f"plugin: {target}",
        f"skills: {target / 'skills'} ({skill_list})",
        f"rules: {target / 'rules' / 'AGENTS.md'}",
        f"agents: {target / 'agents'}",
        f"mcp: {target / 'mcp_config.json'} (server=wf-agents)",
        f"dataDir: {data_dir}",
    ]
    if not apply:
        return actions

    _copy_universal_assets(target)
    mcp_payload = {"mcpServers": {"wf-agents": _mcp_server_entry(wf_root, python_exe, data_dir)}}
    _write_json(target / "mcp_config.json", mcp_payload)
    return actions


def install_claude(target: Path, python_exe: str, apply: bool) -> list[str]:
    data_dir = Path.home() / ".wf-agents"
    bundle_dir = target / "wf-agents"
    wf_root = bundle_dir / "wf-mode"
    mcp_out = target / "wf-agents.mcp.json"
    skill_list = ", ".join(_skill_names())
    actions = [
        f"skills: {target / 'skills'} ({skill_list})",
        f"runtime: {bundle_dir}",
        f"mcp snippet: {mcp_out}",
        f"dataDir: {data_dir}",
    ]
    if not apply:
        return actions

    _copy_universal_assets(bundle_dir)
    _copy_skills_flat(target / "skills")
    _write_json(
        mcp_out,
        {"mcpServers": {"wf-agents": _mcp_server_entry(wf_root, python_exe, data_dir)}},
    )
    return actions


def install_gemini(target: Path, python_exe: str, apply: bool) -> list[str]:
    data_dir = Path.home() / ".wf-agents"
    wf_root = target / "wf-mode"
    actions = [
        f"extension: {target}",
        f"manifest: {target / 'gemini-extension.json'}",
        f"rules: {target / 'rules' / 'AGENTS.md'}",
        f"skills: {target / 'skills'}",
    ]
    if not apply:
        return actions

    _copy_universal_assets(target)
    ext_manifest = {
        "name": "wf-agents",
        "version": "2.0.0",
        "description": "开源复用与工程组装工作流插件（6 步人机闸口、策略评估、切片与安全回滚）。",
        "contextFileName": "rules/AGENTS.md",
        "mcpServers": {"wf-agents": _mcp_server_entry(wf_root, python_exe, data_dir)},
    }
    _write_json(target / "gemini-extension.json", ext_manifest)
    return actions


def install_cursor(target: Path, python_exe: str, apply: bool) -> list[str]:
    data_dir = Path.home() / ".wf-agents"
    bundle_dir = target / "wf-agents"
    wf_root = bundle_dir / "wf-mode"
    mcp_file = target / "mcp.json"
    skill_list = ", ".join(_skill_names())
    actions = [
        f"skills: {target / 'skills'} ({skill_list})",
        f"runtime: {bundle_dir}",
        f"mcp: {mcp_file} (merge wf-agents)",
    ]
    if not apply:
        return actions

    _copy_universal_assets(bundle_dir)
    _copy_skills_flat(target / "skills")
    existing: dict[str, Any] = {}
    if mcp_file.is_file():
        try:
            existing = json.loads(mcp_file.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise HostError(f"{mcp_file} 不是合法 JSON：{exc}") from exc
    if not isinstance(existing, dict):
        existing = {}
    servers = existing.setdefault("mcpServers", {})
    servers["wf-agents"] = _mcp_server_entry(wf_root, python_exe, data_dir)
    _write_json(mcp_file, existing)
    return actions


def install_codex(target: Path, python_exe: str, apply: bool) -> list[str]:
    data_dir = Path.home() / ".wf-agents"
    bundle_dir = target / "wf-agents"
    wf_root = bundle_dir / "wf-mode"
    mcp_script = (wf_root / "tools" / "wf_mcp.py").as_posix()
    skill_list = ", ".join(_skill_names())
    actions = [
        f"skills: {target / 'skills'} ({skill_list})",
        f"runtime: {bundle_dir}",
        f"snippet: {bundle_dir / 'codex-mcp.toml'}",
    ]
    if not apply:
        return actions

    _copy_universal_assets(bundle_dir)
    _copy_skills_flat(target / "skills")
    toml_snippet = (
        "[mcp_servers.wf-agents]\n"
        f'command = "{python_exe}"\n'
        f'args = ["{mcp_script}"]\n'
        f'env = {{ WF_ROOT = "{wf_root.as_posix()}", WF_DATA_DIR = "{data_dir.as_posix()}" }}\n'
    )
    (bundle_dir / "codex-mcp.toml").write_text(toml_snippet, encoding="utf-8")
    return actions


def install_opencode(target: Path, python_exe: str, apply: bool) -> list[str]:
    data_dir = Path.home() / ".wf-agents"
    bundle_dir = target / "wf-agents"
    wf_root = bundle_dir / "wf-mode"
    skill_list = ", ".join(_skill_names())
    actions = [
        f"skills: {target / 'skills'} ({skill_list})",
        f"runtime: {bundle_dir}",
        f"snippet: {bundle_dir / 'opencode-mcp.json'}",
    ]
    if not apply:
        return actions

    _copy_universal_assets(bundle_dir)
    _copy_skills_flat(target / "skills")
    snippet = {
        "mcp": {
            "wf-agents": {
                "type": "local",
                "command": [python_exe, (wf_root / "tools" / "wf_mcp.py").as_posix()],
                "environment": {
                    "WF_ROOT": wf_root.as_posix(),
                    "WF_DATA_DIR": data_dir.as_posix(),
                },
            }
        }
    }
    _write_json(bundle_dir / "opencode-mcp.json", snippet)
    return actions


def install_generic(target: Path, python_exe: str, apply: bool) -> list[str]:
    data_dir = Path.home() / ".wf-agents"
    wf_root = target / "wf-mode"
    actions = [
        f"bundle: {target}",
        f"skills: {target / 'skills'}",
        f"rules: {target / 'rules' / 'AGENTS.md'}",
        f"mcp: {target / 'mcp_config.json'}",
    ]
    if not apply:
        return actions
    _copy_universal_assets(target)
    _write_json(
        target / "mcp_config.json",
        {"mcpServers": {"wf-agents": _mcp_server_entry(wf_root, python_exe, data_dir)}},
    )
    return actions


DEFAULT_TARGETS: dict[str, Path] = {
    "antigravity": Path.home() / ".gemini" / "config" / "plugins" / "wf-agents",
    "claude": Path.home() / ".claude",
    "gemini": Path.home() / ".gemini" / "extensions" / "wf-agents",
    "cursor": Path.home() / ".cursor",
    "codex": Path.home() / ".codex",
    "opencode": Path.home() / ".config" / "opencode",
    "generic": ROOT / "runtime" / "generic" / "wf-agents",
}

INSTALLERS = {
    "antigravity": install_antigravity,
    "claude": install_claude,
    "gemini": install_gemini,
    "cursor": install_cursor,
    "codex": install_codex,
    "opencode": install_opencode,
    "generic": install_generic,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="wf-agents 通用跨宿主统一安装器")
    parser.add_argument("--host", default="antigravity", choices=SUPPORTED_HOSTS)
    parser.add_argument("--target", default="", help="目标安装目录（留空则使用该宿主默认目录）")
    parser.add_argument("--config-dir", default="", help="兼容参数：目标配置目录")
    parser.add_argument("--python", default=sys.executable, help="MCP 服务使用的 Python 解释器路径")
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只打印计划")
    args = parser.parse_args(argv)

    raw_target = args.target or args.config_dir
    target = Path(raw_target) if raw_target else DEFAULT_TARGETS[args.host]
    python_exe = Path(args.python).as_posix()

    try:
        actions = INSTALLERS[args.host](target, python_exe, args.apply)
        print("\n".join(actions))
        if not args.apply:
            print("(dry-run) 加 --apply 才会写入。")
        return 0
    except HostError as exc:
        print(f"wf: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
