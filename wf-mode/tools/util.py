"""无副作用的小工具。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def first_env(*names: str) -> tuple[str | None, str]:
    """按顺序返回第一个非空密钥及其实际名称。

    先查面板本地配置，再查环境变量；只返回值和变量名，不打印值。
    用于兼容 TAVILY 与 TAVILY_API_KEY 这类别名。
    """
    from tools.config import resolve_secret

    value, name, _ = resolve_secret(*names)
    if value:
        return value, name
    return None, names[0] if names else ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def dump_json(obj: object, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: str | Path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def truncate(text: str, limit: int = 500) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit]
