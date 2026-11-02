"""最小安装器：按宿主渲染 agent、写入口、合并 deny Workflow。

只写声明的路径；不复制宿主配置、会话或凭据。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host.common import HostError, render_agent  # noqa: E402


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


ENTRY_FILES = ("wf.md", "wf-plan.md", "wf-report.md")


def install_entry(config_dir: Path, apply: bool) -> list[str]:
    actions: list[str] = []
    for name in ENTRY_FILES:
        source = ROOT / "commands" / name
        if not source.is_file():
            raise HostError(f"缺少命令文件：{source}")
        text = source.read_text(encoding="utf-8").replace(
            "{{WF_ROOT}}", ROOT.as_posix()
        )
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
    parser = argparse.ArgumentParser(description="wf-agent 最小安装器")
    parser.add_argument("--host", default="haha", choices=["haha", "claude", "dsh"])
    parser.add_argument("--config-dir", default="", help="普通模式配置目录（haha 用）")
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只打印计划")
    args = parser.parse_args(argv)

    try:
        actions: list[str] = []
        if args.host == "haha":
            target = ROOT / "agents" / "wf-agent.md"
            actions.append(f"agent: {target}")
            if args.apply:
                _backup(target)
                render_agent(target)
            if args.config_dir:
                config_dir = Path(args.config_dir)
                actions += install_entry(config_dir, args.apply)
                actions += merge_settings(config_dir, args.apply)
            else:
                actions.append("entry: 未提供 --config-dir，跳过普通模式入口安装")
        elif args.host == "claude":
            target = ROOT / "runtime" / "claude" / "wf-agent-prompt.md"
            actions.append(f"prompt: {target}")
            if args.apply:
                _backup(target)
                render_agent(target)
            actions.append("用法: claude -p --append-system-prompt <该文件内容> --tools Read,Grep,Glob,Bash ...")
        else:
            target = ROOT / "runtime" / "dsh" / "wf-agent.md"
            actions.append(f"rules: {target}")
            if args.apply:
                _backup(target)
                render_agent(target)
            actions.append("待验证: 确认 dsh 的 agent/规则加载与工具限制方式；第一版按 CLI-only 接入")
        print("\n".join(actions))
        if not args.apply:
            print("(dry-run) 加 --apply 才会写入。")
        return 0
    except HostError as exc:
        print(f"wf: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
