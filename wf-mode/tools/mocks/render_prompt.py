"""假提示词拼装器。

接口与对方交付的 render-prompt 模块一致：
- check(payload) -> {"ok", "missing", "empty", "blocks"}
- write(payload) -> {"ok", "out", "sha256", "blocks"}
- render(payload) -> 文本
- handle(action, payload)
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tools.errors import ToolError

ROOT = Path(__file__).resolve().parents[2]


def _root(payload: dict[str, Any]) -> Path:
    raw = payload.get("root")
    return Path(str(raw)).resolve() if raw else ROOT


def _blocks(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("blocks") or payload.get("promptBlocks") or []
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ToolError("INVALID_INPUT", "blocks 必须是字符串数组")
    return raw


def check(payload: dict[str, Any]) -> dict[str, Any]:
    root = _root(payload)
    blocks = _blocks(payload)
    missing: list[str] = []
    empty: list[str] = []
    for block in blocks:
        path = (root / block).resolve()
        if not path.is_file():
            missing.append(block)
        elif not path.read_text(encoding="utf-8").strip():
            empty.append(block)
    return {
        "ok": not missing and not empty,
        "missing": missing,
        "empty": empty,
        "blocks": blocks,
    }


def render(payload: dict[str, Any]) -> str:
    root = _root(payload)
    parts = []
    for block in _blocks(payload):
        path = (root / block).resolve()
        if not path.is_file():
            raise ToolError("INVALID_INPUT", f"prompt block 不存在: {block}")
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts) + "\n"


def write(payload: dict[str, Any]) -> dict[str, Any]:
    out = payload.get("out")
    if not isinstance(out, str) or not out.strip():
        raise ToolError("INVALID_INPUT", "out 必须提供")
    text = render(payload)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "out": str(path),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "blocks": _blocks(payload),
    }


def handle(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "check":
        return check(payload)
    if action == "write":
        return write(payload)
    if action == "render":
        return {"text": render(payload)}
    raise ToolError("UNKNOWN_ACTION", f"render_prompt 不支持动作: {action}")
