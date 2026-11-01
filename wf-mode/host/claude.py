"""通用 Claude Code CLI：用系统提示词注入 wf-agent，并收窄工具面。

不写用户全局 agents/，避免污染普通模式；宿主差异只在这一层。
"""

from __future__ import annotations

import os
import shutil

from host.common import HostError, merge_env, read_agent, stream_agent


def binary() -> str:
    return shutil.which("claude") or ""


def detect() -> bool:
    return bool(binary())


def build_cmd(exe: str, agent_text: str, partial: bool = False) -> list[str]:
    cmd = [
        exe,
        "-p",
        "--append-system-prompt",
        agent_text,
        "--tools",
        "Read,Grep,Glob,Bash",
        "--disallowedTools",
        "Write,Edit,MultiEdit,WebFetch",
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
    ]
    if partial:
        cmd.append("--include-partial-messages")
    return cmd


def run(task: str, stream: bool = True, on_text=None, on_tool=None) -> str:
    exe = binary()
    if not exe:
        raise HostError("未找到 claude 命令。请先安装 Claude Code CLI，或改用 --host haha。")

    partial = os.environ.get("WF_STREAM_PARTIAL") == "1"
    return stream_agent(
        build_cmd(exe, read_agent(), partial=partial),
        task,
        merge_env(),
        on_text=on_text,
        on_tool=on_tool,
        partial=partial,
    )
