"""通用跨宿主安装器：支持 Antigravity / Claude Code / Cursor / Codex / Gemini CLI / OpenCode / Haha / dsh / Generic。

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

from host.common import HostError, render_agent  # noqa: E402

ENTRY_FILES = ("wf.md", "wf-plan.md", "wf-report.md")
SUPPORTED_HOSTS = [
    "antigravity",
    "claude",
    "cursor",
    "codex",
    "gemini",
    "opencode",
    "haha",
    "dsh",
    "generic",
]

_EXCLUDE_DIRS = {
    ".git",
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


def install_antigravity(target: Path, python_exe: str, apply: bool) -> list[str]:
    data_dir = Path.home() / ".wf-agents"
    wf_root = target / "wf-mode"
    actions = [
        f"plugin: {target}",
        f"skills: {target / 'skills'} (wf, wf-plan, wf-report)",
        f"rules: {target / 'rules' / 'AGENTS.md'}",
        f"agents: {target / 'agents' / 'wf-researcher.md'}",
        f"mcp: {target / 'mcp_config.json'} (server=wf-agents)",
        f"dataDir: {data_dir}",
    ]
    if not apply:
        return actions

    _copy_universal_assets(target)
    mcp_payload = {"mcpServers": {"wf-agents": _mcp_server_entry(wf_root, python_exe, data_dir)}}
    _write_json(target / "mcp_config.json", mcp_payload)
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
        "description": "通用开源探索、仓库分析与装配规划工作流插件。",
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
    actions = [
        f"skills: {target / 'skills'} (wf, wf-plan, wf-report)",
        f"runtime: {bundle_dir}",
        f"mcp: {mcp_file} (merge wf-agents)",
    ]
    if not apply:
        return actions

    _copy_universal_assets(bundle_dir)
    for skill_dir in (REPO_ROOT / "skills").iterdir():
        if skill_dir.is_dir():
            _copy_tree_clean(skill_dir, target / "skills" / skill_dir.name)
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
    actions = [
        f"skills: {target / 'skills'} (wf, wf-plan, wf-report)",
        f"runtime: {bundle_dir}",
        f"snippet: {bundle_dir / 'codex-mcp.toml'}",
    ]
    if not apply:
        return actions

    _copy_universal_assets(bundle_dir)
    for skill_dir in (REPO_ROOT / "skills").iterdir():
        if skill_dir.is_dir():
            _copy_tree_clean(skill_dir, target / "skills" / skill_dir.name)
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
    actions = [
        f"skills: {target / 'skills'} (wf, wf-plan, wf-report)",
        f"runtime: {bundle_dir}",
        f"snippet: {bundle_dir / 'opencode-mcp.json'}",
    ]
    if not apply:
        return actions

    _copy_universal_assets(bundle_dir)
    for skill_dir in (REPO_ROOT / "skills").iterdir():
        if skill_dir.is_dir():
            _copy_tree_clean(skill_dir, target / "skills" / skill_dir.name)
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


def install_entry(config_dir: Path, apply: bool, wf_root: Path | None = None) -> list[str]:
    root_path = (wf_root or ROOT).as_posix()
    actions: list[str] = []
    for name in ENTRY_FILES:
        source = ROOT / "commands" / name
        if not source.is_file():
            raise HostError(f"缺少命令文件：{source}")
        text = source.read_text(encoding="utf-8").replace("{{WF_ROOT}}", root_path)
        target = config_dir / "commands" / name
        actions.append(f"entry: {target}")
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                _backup(target)
            target.write_text(text, encoding="utf-8")
    return actions


def merge_settings(config_dir: Path, apply: bool) -> list[str]:
    settings = config_dir / "settings.json"
    actions = [f"settings: deny Workflow -> {settings}"]
    if not apply:
        return actions
    data: dict = {}
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise HostError(f"settings.json 不是合法 JSON：{exc}") from exc
        _backup(settings)
    permissions = data.setdefault("permissions", {})
    deny = permissions.setdefault("deny", [])
    if "Workflow" not in deny:
        deny.append("Workflow")
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="wf-agents 通用跨宿主安装器")
    parser.add_argument("--host", default="antigravity", choices=SUPPORTED_HOSTS)
    parser.add_argument("--target", default="", help="目标安装目录（留空则使用该宿主默认目录）")
    parser.add_argument("--config-dir", default="", help="兼容旧参数：普通模式配置目录")
    parser.add_argument("--python", default=sys.executable, help="MCP 服务使用的 Python 解释器路径")
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只打印计划")
    args = parser.parse_args(argv)

    raw_target = args.target or args.config_dir
    python_exe = Path(args.python).as_posix()

    try:
        actions: list[str] = []
        if args.host == "antigravity":
            target = Path(raw_target) if raw_target else Path.home() / ".gemini" / "config" / "plugins" / "wf-agents"
            actions = install_antigravity(target, python_exe, args.apply)
        elif args.host == "gemini":
            target = Path(raw_target) if raw_target else Path.home() / ".gemini" / "extensions" / "wf-agents"
            actions = install_gemini(target, python_exe, args.apply)
        elif args.host == "cursor":
            target = Path(raw_target) if raw_target else Path.home() / ".cursor"
            actions = install_cursor(target, python_exe, args.apply)
        elif args.host == "codex":
            target = Path(raw_target) if raw_target else Path.home() / ".codex"
            actions = install_codex(target, python_exe, args.apply)
        elif args.host == "opencode":
            target = Path(raw_target) if raw_target else Path.home() / ".config" / "opencode"
            actions = install_opencode(target, python_exe, args.apply)
        elif args.host == "generic":
            target = Path(raw_target) if raw_target else ROOT / "runtime" / "generic" / "wf-agents"
            actions = install_generic(target, python_exe, args.apply)
        elif args.host == "haha":
            target = ROOT / "agents" / "wf-agent.md"
            actions.append(f"agent: {target}")
            if args.apply:
                _backup(target)
                render_agent(target)
            if raw_target:
                config_dir = Path(raw_target)
                actions += install_entry(config_dir, args.apply)
                actions += merge_settings(config_dir, args.apply)
            else:
                actions.append("entry: 未提供 --config-dir，跳过普通模式入口安装")
        elif args.host == "claude":
            if raw_target:
                config_dir = Path(raw_target)
                actions += install_entry(config_dir, args.apply)
                if args.apply:
                    for skill_dir in (REPO_ROOT / "skills").iterdir():
                        if skill_dir.is_dir():
                            _copy_tree_clean(skill_dir, config_dir / "skills" / skill_dir.name)
                actions.append(f"skills: {config_dir / 'skills'}")
                mcp_out = config_dir / "wf-agents.mcp.json"
                actions.append(f"mcp snippet: {mcp_out}")
                if args.apply:
                    _write_json(
                        mcp_out,
                        {"mcpServers": {"wf-agents": _mcp_server_entry(ROOT, python_exe, Path.home() / ".wf-agents")}},
                    )
            else:
                target = ROOT / "runtime" / "claude" / "wf-agent-prompt.md"
                actions.append(f"prompt: {target}")
                if args.apply:
                    _backup(target)
                    render_agent(target)
                actions.append("提示: 也可使用 claude plugin install 或传 --target <~/.claude> 安装技能与 MCP。")
        else:  # dsh
            target = ROOT / "runtime" / "dsh" / "wf-agent.md"
            actions.append(f"rules: {target}")
            if args.apply:
                _backup(target)
                render_agent(target)
            actions.append("按 CLI-only 或 MCP 方式接入 dsh，读取该规则文件并调用 wf_stage.py / wf_mcp.py。")

        print("\n".join(actions))
        if not args.apply:
            print("(dry-run) 加 --apply 才会写入。")
        return 0
    except HostError as exc:
        print(f"wf: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
