"""DeepSeek Harness（dsh/dsh-next）适配骨架。

本机尚未验证 dsh 的扩展点，因此第一版只做：
- 探测 dsh/dsh-next；
- 生成可被规则文件加载的 wf-agent（CLI-only 接入形态）；
- 明确说明后续需要确认的接入点，不静默假设。
"""

from __future__ import annotations

import shutil

from host.common import ROOT, HostError, render_agent


def binary() -> str:
    return shutil.which("dsh") or shutil.which("dsh-next") or ""


def detect() -> bool:
    return bool(binary())


def run(task: str, stream: bool = True, on_text=None, on_tool=None) -> str:
    rules = render_agent(ROOT / "runtime" / "dsh" / "wf-agent.md")
    exe = binary()
    if not exe:
        raise HostError(
            "未检测到 DeepSeek Harness（dsh/dsh-next）。"
            f" 已生成规则文件：{rules}。"
            " 按 README 的 CLI-only 方式接入：让 dsh 的 agent 通过 wf-tool 调用能力，"
            "并把该规则文件作为系统提示/规则注入。"
        )
    raise HostError(
        f"检测到 {exe}，但 DeepSeek Harness 的扩展点尚未验证。"
        f" 已生成规则文件：{rules}。"
        " 请先确认 dsh 的 agent/规则加载与工具限制方式，再启用 --host dsh。"
    )
