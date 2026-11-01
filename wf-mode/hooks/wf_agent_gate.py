"""wf-agent 的 PreToolUse 权限闸门。

只放行：
- `python .../tools/wf-tool.py list|health|doctor|call ...`；
- 能力目录中已登记、非 pending、非写类能力的动作。

拒绝：
- Write/Edit/MultiEdit/NotebookEdit；
- 任意其它 shell 命令、curl/git/npm/pip；
- shell 操作符与路径穿越；
- 写类能力（计划模式下）。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

WF_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOL = (WF_ROOT / "tools" / "wf-tool.py").resolve()
CATALOG = WF_ROOT / "capabilities.yaml"
AGENT_NAME = "wf-agent"

SHELL_OPS = re.compile(r"[;&|`]|\$\(|\r|\n|[<>]")
WF_TOOL_RE = re.compile(
    r'^(?:python(?:\d+(?:\.\d+)*)?|py)(?:\.exe)?(?:\s+-3)?\s+'
    r'(?:"([^"]*wf-tool\.py)"|\'([^\']*wf-tool\.py)\'|(\S*wf-tool\.py))'
    r'\s+(.+)$',
    re.I,
)

# 计划模式禁止会写文件或改变系统的能力；执行阶段再通过 WF_ALLOW_WRITE=1 放开。
WRITE_CAPABILITIES = {
    "scaffold",
    "repo_fetch",
    "toolchain",
    "deploy_runtime",
    "reverse_proxy",
    "managed_platform",
}
READ_ONLY_COMMANDS = {"list", "health", "doctor"}


def emit(decision: str, reason: str) -> None:
    payload = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()
    sys.exit(0)


def deny(reason: str) -> None:
    emit("deny", reason)


def allow() -> None:
    emit("allow", "")


def resolve(value: str, cwd: Path) -> Path | None:
    raw = value.strip().strip('"').strip("'").replace("\\", "/")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = cwd / path
    try:
        return path.resolve()
    except OSError:
        return None


def load_capabilities() -> dict:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data.get("capabilities") or {}


def valid_wftool_args(rest: str) -> bool:
    try:
        tokens = shlex.split(rest.replace("\\", "/"), posix=True)
    except ValueError:
        return False
    if not tokens:
        return False

    command = tokens[0]
    if command in READ_ONLY_COMMANDS:
        return len(tokens) <= 2
    if command == "panel":
        return False
    if command == "call":
        if len(tokens) < 3:
            return False
        capability, action = tokens[1], tokens[2]
    else:
        # 兼容旧式 <capability> <action>
        if len(tokens) < 2:
            return False
        capability, action = tokens[0], tokens[1]

    caps = load_capabilities()
    entry = caps.get(capability)
    if not isinstance(entry, dict):
        return False
    if entry.get("status") == "pending" or entry.get("kind") == "pending":
        return False
    if action not in (entry.get("actions") or []):
        return False
    if capability in WRITE_CAPABILITIES and not os.environ.get("WF_ALLOW_WRITE"):
        return False
    return True


def check(data: dict, cwd: Path) -> None:
    tool = str(data.get("tool_name") or "")

    if tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        deny("wf-agent 处于计划模式，不允许写文件或改文件。")

    if tool not in {"Bash", "PowerShell"}:
        # Read/Grep/Glob 与 MCP 工具由 agent 的 tools 白名单约束。
        sys.exit(0)

    cmd = str((data.get("tool_input") or {}).get("command") or "").strip()
    if not cmd:
        deny("空命令。")
    if SHELL_OPS.search(cmd):
        deny("命令包含不允许的 shell 操作符（; | & 反引号 $() 重定向 或换行）。")
    if ".." in cmd:
        deny("禁止路径穿越（..）。")

    match = WF_TOOL_RE.match(cmd)
    if not match:
        deny(
            "只允许通过 wf-tool.py 调用能力。"
            " 例如：python \".../tools/wf-tool.py\" call project_search search --query \"...\""
        )

    raw_path = match.group(1) or match.group(2) or match.group(3) or ""
    target = resolve(raw_path, cwd)
    if target != EXPECTED_TOOL:
        deny("只允许调用本插件的 tools/wf-tool.py。")

    if not valid_wftool_args(match.group(4).strip()):
        deny("wf-tool 子命令不在允许范围内：仅限已登记、非 pending、非写类能力的动作。")

    allow()


def main() -> None:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        data = json.loads(raw or "{}")
    except Exception:
        deny("权限校验无法解析 hook 输入（要求 UTF-8 JSON），按拒绝处理。")

    agent = str(data.get("agent_type") or "")
    if agent and agent != AGENT_NAME:
        sys.exit(0)

    cwd = Path(str(data.get("cwd") or os.getcwd()))
    check(data, cwd)


if __name__ == "__main__":
    main()
