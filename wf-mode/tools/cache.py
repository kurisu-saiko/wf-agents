"""检索结果缓存。

只缓存成功结果；key 由 slot/provider/参数归一化后哈希。
默认目录 <cwd>/.wf/cache/http；TTL 7 天。写入使用临时文件 + os.replace，损坏/过期按 miss。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

CACHE_VERSION = "1"
DEFAULT_TTL = 7 * 24 * 3600


def _disabled() -> bool:
    return os.environ.get("WF_CACHE_DISABLE", "").strip() in {"1", "true", "yes"}


def _root() -> Path:
    raw = os.environ.get("WF_CACHE_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path.cwd() / ".wf" / "cache"


def _ttl() -> int:
    try:
        return max(0, int(os.environ.get("WF_CACHE_TTL", str(DEFAULT_TTL))))
    except ValueError:
        return DEFAULT_TTL


def make_key(*parts: Any) -> str:
    normalized = "|".join(str(part).strip() for part in parts)
    payload = f"v{CACHE_VERSION}|{normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _path(slot: str, provider: str, key: str) -> Path:
    return _root() / "http" / slot / provider / f"{key}.json"


def get(slot: str, provider: str, key: str) -> dict[str, Any] | None:
    if _disabled():
        return None
    path = _path(slot, provider, key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        cached_at = float(raw.get("cachedAt") or 0)
    except (TypeError, ValueError):
        return None
    if not cached_at or time.time() - cached_at > _ttl():
        return None
    value = raw.get("value")
    return value if isinstance(value, dict) else None


def put(slot: str, provider: str, key: str, value: dict[str, Any]) -> None:
    if _disabled() or not isinstance(value, dict):
        return
    path = _path(slot, provider, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"cachedAt": time.time(), "value": value},
                    handle,
                    ensure_ascii=False,
                )
                handle.write("\n")
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
    except OSError:
        # 缓存失败不影响主流程。
        return
