"""Agent-level PreToolUse gate for wf-* pipeline agents.

Phase 1 的 wf-retrieval 采用严格模式：
- 只允许通过 `python .../tools/wf-tool.py` 调用能力；
- 拒绝 Write/Edit/MultiEdit（账本由 `wf-tool ledger commit` 写入）；
- 拒绝 curl/git/scorecard 等底层命令；
- 解析失败按拒绝处理。

wf-project-eval / wf-project-reading 暂时保留旧规则，等各自阶段再迁移。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

WF_MODE = Path(__file__).resolve().parents[2]
STRICT_AGENTS = {"wf-retrieval"}
LEGACY_AGENTS = {"wf-project-eval", "wf-project-reading"}
WF_AGENTS = STRICT_AGENTS | LEGACY_AGENTS

RUN_FILES = {"run.json", "evidence.json", "result.md"}
READ_ONLY_SUBS = "log|show|ls-files|shortlog|diff|status|rev-parse|branch|tag|remote"
SHELL_OPS = re.compile(r"[;&|`]|\$\(|\r|\n|[<>]")
CLONE_RE = re.compile(r"^git\s+clone\s+--depth\s+1\s+(https://\S+)\s+(\S+)$", re.I)
LSREMOTE_RE = re.compile(r"^git\s+ls-remote\s+(https://\S+)$", re.I)
GIT_C_RE = re.compile(rf"^git\s+-C\s+(\S+)\s+({READ_ONLY_SUBS})(?:\s+(.*))?$", re.I)
GIT_PLAIN_RE = re.compile(rf"^git\s+({READ_ONLY_SUBS})(?:\s+(.*))?$", re.I)
MKDIR_RE = re.compile(
    r"^(?:New-Item\s+-ItemType\s+Directory\s+-Force\s+(?:-Path\s+)?(\S+)|mkdir\s+(\S+))\s*$",
    re.I,
)
WF_TOOL_RE = re.compile(
    r'^(?:python(?:\d+(?:\.\d+)*)?|py)(?:\.exe)?(?:\s+-3)?\s+'
    r'(?:"([^"]*wf-tool\.py)"|\'([^\']*wf-tool\.py)\'|(\S*wf-tool\.py))'
    r'\s+(.+)$',
    re.I,
)
ALLOWED_WF_ACTIONS = {
    "web_search": {"search", "health"},
    "web_extract": {"extract", "health"},
    "project_search": {"search", "lookup", "health"},
    "ledger": {"commit", "validate"},
    "render_prompt": {"check", "write", "render"},
    "gates": {"check"},
}


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


def unquote(value: str) -> str:
    return value.strip().strip('"').strip("'")


def resolve(value: str, cwd: Path) -> Path | None:
    raw = unquote(value).replace("\\", "/")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = cwd / p
    try:
        return p.resolve()
    except OSError:
        return None


def within(child: Path | None, parent: Path) -> bool:
    if child is None:
        return False
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# wf-retrieval：严格模式
# ---------------------------------------------------------------------------


def _valid_wftool_args(rest: str) -> bool:
    try:
        tokens = shlex.split(rest, posix=True)
    except ValueError:
        return False
    if not tokens:
        return False
    slot = tokens[0]
    if slot == "list":
        return len(tokens) == 1
    if slot == "health":
        return len(tokens) <= 2
    actions = ALLOWED_WF_ACTIONS.get(slot)
    if not actions or len(tokens) < 2:
        return False
    return tokens[1] in actions


def check_retrieval(data: dict, cwd: Path) -> None:
    tool = str(data.get("tool_name") or "")

    if tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        deny("账本只允许通过 `wf-tool ledger commit` 写入；管线代理不允许直接写文件。")

    if tool not in {"Bash", "PowerShell"}:
        # Read/Grep/Glob/WebFetch 由 agent 的 tools 白名单约束。
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
            "只允许调用 wf-tool.py。"
            " 例如：python \"D:/claude-code/workflow/wf-mode/tools/wf-tool.py\" web_search search --query \"...\""
        )

    raw_path = match.group(1) or match.group(2) or match.group(3) or ""
    target = resolve(raw_path, cwd)
    expected = (WF_MODE / "tools" / "wf-tool.py").resolve()
    if target != expected:
        deny("只允许调用 wf-mode/tools/wf-tool.py 这一个入口。")

    if not _valid_wftool_args(match.group(4).strip()):
        deny("wf-tool 子命令不在允许范围内（只允许 registry 中声明的槽与动作）。")

    allow()


# ---------------------------------------------------------------------------
# 旧规则：wf-project-eval / wf-project-reading
# ---------------------------------------------------------------------------


def is_run_dir(target: Path | None, cwd: Path) -> bool:
    runs = (cwd / ".wf" / "runs").resolve()
    if not within(target, runs) or target == runs:
        return False
    rel = target.relative_to(runs)
    return len(rel.parts) == 1 and rel.parts[0] not in {".", ".."}


def check_write(data: dict, cwd: Path) -> None:
    raw = str((data.get("tool_input") or {}).get("file_path") or "")
    path = resolve(raw, cwd)
    if path is None:
        deny("Write 缺少合法 file_path。")
    runs = (cwd / ".wf" / "runs").resolve()
    if not within(path, runs):
        deny("只允许写入 .wf/runs/<本次运行>/ 下的账本文件。")
    rel = path.relative_to(runs)
    if len(rel.parts) != 2 or rel.parts[1] not in RUN_FILES:
        deny("只允许写 .wf/runs/<本次运行>/{run.json,evidence.json,result.md}。")
    allow()


def check_mkdir(target: Path | None, cwd: Path, agent: str) -> None:
    if is_run_dir(target, cwd):
        allow()
    if agent == "wf-project-eval":
        cache = (cwd / ".wf" / "cache").resolve()
        if target == cache:
            allow()
    deny("只允许创建本次运行目录，或 wf-project-eval 的 .wf/cache。")


def check_args(sub: str, rest: str) -> str | None:
    if "--output" in rest or re.search(r"(^|\s)-o(\s|$)", rest):
        return "禁止使用会写文件的 git 参数（--output/-o）"
    if sub == "branch":
        allowed = {"", "-a", "-r", "-v", "-vv", "--list", "--show-current", "--all", "--remotes"}
        tokens = set(rest.split())
        if not tokens.issubset(allowed):
            return "git branch 只允许只读查询（无参数或 -a/-r/-v/--list/--show-current）"
    if sub == "tag":
        allowed = {"", "-l", "--list"}
        if not set(rest.split()).issubset(allowed):
            return "git tag 只允许只读查询（无参数或 -l/--list）"
    if sub == "remote":
        allowed = {"", "-v", "--verbose", "show", "get-url"}
        tokens = rest.split()
        if not tokens or tokens[0] not in allowed - {""}:
            if rest.strip():
                return "git remote 只允许只读查询（无参数、-v、show、get-url）"
    return None


def legacy_check(data: dict, cwd: Path, agent: str) -> None:
    tool = str(data.get("tool_name") or "")

    if tool in {"Edit", "MultiEdit", "NotebookEdit"}:
        deny(f"{tool} 不在管线允许范围内；账本只允许用 Write 创建。")

    if tool == "Write":
        check_write(data, cwd)

    if tool != "PowerShell":
        sys.exit(0)

    cmd = str((data.get("tool_input") or {}).get("command") or "").strip()

    if not cmd:
        deny("空命令。")
    if SHELL_OPS.search(cmd):
        deny("命令包含不允许的 shell 操作符（; | & 反引号 $() 重定向 或换行）。")
    if ".." in cmd:
        deny("禁止路径穿越（..）。")

    cache = (cwd / ".wf" / "cache").resolve()

    m = MKDIR_RE.match(cmd)
    if m:
        target = resolve(m.group(1) or m.group(2) or "", cwd)
        check_mkdir(target, cwd, agent)

    m = CLONE_RE.match(cmd)
    if m:
        if agent != "wf-project-eval":
            deny("只有 wf-project-eval 允许 git clone。")
        dest = resolve(m.group(2), cwd)
        if not within(dest, cache) or dest == cache:
            deny("clone 目标必须位于 .wf/cache/<name>。")
        allow()

    if LSREMOTE_RE.match(cmd):
        if agent != "wf-project-eval":
            deny("只有 wf-project-eval 允许 git ls-remote。")
        allow()

    m = GIT_C_RE.match(cmd)
    if m:
        path = resolve(m.group(1), cwd)
        if agent == "wf-project-eval":
            if not within(path, cache):
                deny("wf-project-eval 的 git -C 只能指向 .wf/cache 下的仓库。")
        else:
            if not within(path, cwd):
                deny("wf-project-reading 的 git -C 只能指向工作目录内。")
        problem = check_args(str(m.group(2)).lower(), m.group(3) or "")
        if problem:
            deny(problem)
        allow()

    m = GIT_PLAIN_RE.match(cmd)
    if m:
        if agent != "wf-project-reading":
            deny("wf-project-eval 不允许在工作目录直接运行 git；只能对 .wf/cache 使用 git -C。")
        problem = check_args(str(m.group(1)).lower(), m.group(2) or "")
        if problem:
            deny(problem)
        allow()

    deny(
        "命令不在该管线允许范围内。"
        " 各管线只允许创建本次运行目录；"
        " wf-project-eval 另允许创建 .wf/cache、git clone --depth 1 https://... .wf/cache/<name>、"
        "git ls-remote https://...、.wf/cache 内的只读 git；"
        " wf-project-reading 另允许工作目录内的只读 git。"
    )


# ---------------------------------------------------------------------------


def main() -> None:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        data = json.loads(raw or "{}")
    except Exception:
        deny("管线权限校验无法解析 hook 输入（要求 UTF-8 JSON），按拒绝处理。")

    agent = str(data.get("agent_type") or "")
    if agent not in WF_AGENTS:
        sys.exit(0)

    cwd = Path(str(data.get("cwd") or os.getcwd()))

    if agent in STRICT_AGENTS:
        check_retrieval(data, cwd)

    legacy_check(data, cwd, agent)


if __name__ == "__main__":
    main()
