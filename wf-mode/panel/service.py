"""面板数据层：调用 wf-tool、读写提示词与启停状态。

只做数据转换与最小 IO；不执行业务逻辑，不记录运行历史。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "wf-tool.py"
AGENT = ROOT / "agent" / "wf-agent.md"
STATE = ROOT / "panel" / "state.json"
BACKUPS = ROOT / "panel" / "backups"


def _run_tool(args: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (proc.stdout or "").strip()
    if not text:
        raise RuntimeError(f"wf-tool 没有输出；stderr: {(proc.stderr or '').strip()[:500]}")
    return json.loads(text)


def list_capabilities() -> dict:
    return _run_tool(["list"])["data"]


def health(name: str | None = None) -> dict:
    args = ["health"] + ([name] if name else [])
    return _run_tool(args)["data"]


def doctor() -> dict:
    return _run_tool(["doctor"])["data"]


def load_state() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"disabled": []}
    if not isinstance(data, dict) or not isinstance(data.get("disabled"), list):
        return {"disabled": []}
    return data


def save_state(disabled: set[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps({"disabled": sorted(disabled)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def split_agent() -> tuple[str, str]:
    text = AGENT.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[1].strip(), parts[2].lstrip("\n")
    return "", text


def agent_summary() -> dict:
    frontmatter, body = split_agent()
    tools = ""
    hook = ""
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("tools:"):
            tools = stripped.split(":", 1)[1].strip()
        if "wf_agent_gate.py" in stripped:
            hook = stripped
    return {"frontmatter": frontmatter, "body": body, "tools": tools, "hook": hook}


def save_agent_body(body: str) -> str:
    frontmatter, _ = split_agent()
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUPS / f"wf-agent-{stamp}.md"
    backup.write_text(AGENT.read_text(encoding="utf-8"), encoding="utf-8")
    AGENT.write_text(f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n", encoding="utf-8")
    return str(backup)


