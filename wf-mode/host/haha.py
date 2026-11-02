"""Claude Code Haha：复用 sidecar CLI，以 wf-agent 身份执行一次计划会话。"""

from __future__ import annotations

import os
from pathlib import Path

from host.common import ROOT, HostError, merge_env, render_agent, stream_agent
from tools import config as local_config  # noqa: E402


def sidecar() -> Path:
    return Path(local_config.resolve_haha_sidecar())


def detect() -> bool:
    return sidecar().is_file()


def _app_root(exe: Path) -> Path | None:
    """sidecar 位于 resources/app.asar.unpacked/src-tauri/binaries，据此回推 app.asar。"""
    try:
        resources = exe.parents[3]
    except IndexError:
        return None
    candidate = resources / "app.asar"
    return candidate if candidate.exists() else None


def build_cmd(exe: Path, partial: bool = False) -> list[str]:
    cmd = [
        str(exe),
        "cli",
        "-p",
        "--agent",
        "wf-agent",
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--max-budget-usd",
        "1.5",
    ]
    if partial:
        cmd.append("--include-partial-messages")
    return cmd


def run(task: str, stream: bool = True, on_text=None, on_tool=None) -> str:
    exe = sidecar()
    if not exe.is_file():
        raise HostError(
            f"未找到 Haha sidecar：{exe}。"
            " 可设置环境变量 WF_HAHA_SIDECAR，或改用 --host claude。"
        )
    render_agent(ROOT / "agents" / "wf-agent.md")

    env = merge_env()
    env["CLAUDE_CONFIG_DIR"] = str(ROOT)
    root = _app_root(exe)
    if root is not None and not env.get("CLAUDE_APP_ROOT"):
        env["CLAUDE_APP_ROOT"] = str(root)
        dist = exe.parents[2] / "dist"
        if dist.is_dir() and not env.get("CLAUDE_H5_DIST_DIR"):
            env["CLAUDE_H5_DIST_DIR"] = str(dist)
    partial = os.environ.get("WF_STREAM_PARTIAL") == "1"
    return stream_agent(
        build_cmd(exe, partial=partial),
        task,
        env,
        on_text=on_text,
        on_tool=on_tool,
        partial=partial,
    )
