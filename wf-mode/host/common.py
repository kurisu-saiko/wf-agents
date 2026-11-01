"""宿主适配共用的路径、渲染与流式执行逻辑。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_SRC = ROOT / "agent" / "wf-agent.md"

CREDENTIALS_CANDIDATES = (
    Path("D:/claude-code/data/.credentials.json"),
    Path.home() / ".claude" / ".credentials.json",
)


class HostError(RuntimeError):
    """宿主不可用或启动失败；消息直接展示给用户。"""


def render_agent(target: Path | None = None) -> Path:
    """把 agent 源渲染成实际路径，替换 {{WF_ROOT}} 占位符。"""
    text = AGENT_SRC.read_text(encoding="utf-8").replace("{{WF_ROOT}}", ROOT.as_posix())
    target = target or ROOT / "agents" / "wf-agent.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def read_agent() -> str:
    return AGENT_SRC.read_text(encoding="utf-8").replace("{{WF_ROOT}}", ROOT.as_posix())


def _plugin_token() -> str:
    """读取桌面连接器的 GitHub MCP key；只进进程环境，不落盘、不回显。"""
    raw = os.environ.get("WF_CREDENTIALS")
    paths = ([Path(raw)] if raw else []) + list(CREDENTIALS_CANDIDATES)
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        secrets = data.get("pluginSecrets") or {}
        for name, item in secrets.items():
            if "office-github" in str(name) and isinstance(item, dict):
                token = item.get("apiKey")
                if isinstance(token, str) and token:
                    return token
    return ""


def merge_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    if not env.get("WF_GITHUB_MCP_TOKEN"):
        token = _plugin_token()
        if token:
            env["WF_GITHUB_MCP_TOKEN"] = token
    return env


def _progress(text: str) -> None:
    sys.stderr.buffer.write((text + "\n").encode("utf-8", "replace"))
    sys.stderr.buffer.flush()


def _short_tool(name: str) -> str:
    return name.rsplit("__", 1)[-1] if name.startswith("mcp__") else name


def _text_of(message: dict) -> list[str]:
    texts: list[str] = []
    for block in message.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
    return texts


def _delta_text(event: dict) -> str:
    if event.get("type") != "stream_event":
        return ""
    inner = event.get("event") or {}
    if not isinstance(inner, dict) or inner.get("type") != "content_block_delta":
        return ""
    delta = inner.get("delta") or {}
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return ""
    text = delta.get("text")
    return text if isinstance(text, str) else ""


def stream_agent(
    cmd: list[str],
    task: str,
    env: dict[str, str] | None = None,
    on_text=None,
    on_tool=None,
    partial: bool = False,
) -> str:
    """以 stream-json 运行宿主；文本与工具进度可回调，最终文本作为返回值。

    partial 只表示调用方已请求部分消息；是否追加 CLI 参数由宿主适配层决定。
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=merge_env(env),
        bufsize=1,
    )
    try:
        proc.stdin.write(task)
        proc.stdin.close()
    except OSError:
        pass

    stderr_tail: list[str] = []

    def _drain_stderr() -> None:
        for line in proc.stderr or []:
            text = line.rstrip("\n")
            if text:
                stderr_tail.append(text)
                _progress(f"[host] {text}")

    reader = threading.Thread(target=_drain_stderr, daemon=True)
    reader.start()

    final = ""
    raw: list[str] = []
    delta_since_assistant = False
    for line in proc.stdout or []:
        text = line.rstrip("\n")
        if not text.strip():
            continue
        try:
            event = json.loads(text)
        except ValueError:
            raw.append(text)
            continue
        kind = event.get("type")
        if kind == "stream_event":
            delta = _delta_text(event)
            if delta:
                delta_since_assistant = True
                if on_text:
                    on_text(delta)
        elif kind == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = _short_tool(str(block.get("name") or ""))
                    if on_tool:
                        on_tool(name)
                    else:
                        _progress(f"[wf] 工具 {name}")
            if not delta_since_assistant:
                for chunk in _text_of(message):
                    if on_text:
                        on_text(chunk)
            delta_since_assistant = False
        elif kind == "result":
            result = event.get("result")
            if isinstance(result, str):
                final = result

    code = proc.wait()
    reader.join(timeout=2)
    if code != 0:
        detail = "\n".join(stderr_tail[-20:] or raw[-20:])[:2000] or "无输出"
        raise HostError(f"claude 退出码 {code}：{detail}")
    if not final.strip():
        final = "\n".join(raw).strip()
    if not final:
        raise HostError("claude 没有返回结果。")
    return final
