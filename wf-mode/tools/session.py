"""轻量会话状态管理：跟踪工作流阶段、闸口确认与配置面板“仅首轮打开”状态。

状态存放在插件数据目录（`data_dir()/sessions/<session_id>.json`），不写入用户工作区。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from tools import config as local_config
from tools.util import utc_now

VALID_STAGES = {"init", "plan", "report", "closed"}
_SAFE_SID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def default_session_id() -> str:
    raw = os.environ.get("WF_SESSION_ID", "").strip() or "default"
    return _sanitize_id(raw)


def _sanitize_id(session_id: str | None) -> str:
    cleaned = _SAFE_SID_RE.sub("_", (session_id or "default").strip()).strip("._")
    return cleaned or "default"


def session_path(session_id: str | None = None) -> Path:
    sid = _sanitize_id(session_id or default_session_id())
    return local_config.data_dir() / "sessions" / f"{sid}.json"


def _empty_session(sid: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "sessionId": sid,
        "stage": "init",
        "task": "",
        "requirements": "",
        "planSummary": "",
        "panelOpened": False,
        "gate1Confirmed": False,
        "gate2Confirmed": False,
        "createdAt": now,
        "updatedAt": now,
    }


def load_session(session_id: str | None = None) -> dict[str, Any]:
    sid = _sanitize_id(session_id or default_session_id())
    path = session_path(sid)
    if not path.is_file():
        return _empty_session(sid)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_session(sid)
    if not isinstance(data, dict):
        return _empty_session(sid)
    base = _empty_session(sid)
    base.update(data)
    base["sessionId"] = sid
    if base.get("stage") not in VALID_STAGES:
        base["stage"] = "init"
    return base


def save_session(state: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
    sid = _sanitize_id(session_id or state.get("sessionId") or default_session_id())
    path = session_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["sessionId"] = sid
    payload["updatedAt"] = utc_now()
    if not payload.get("createdAt"):
        payload["createdAt"] = payload["updatedAt"]
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return payload


def reset_session(
    session_id: str | None = None,
    task: str = "",
    *,
    preserve_panel_opened: bool = False,
) -> dict[str, Any]:
    sid = _sanitize_id(session_id or default_session_id())
    prev = load_session(sid)
    state = _empty_session(sid)
    state["task"] = task.strip()
    if preserve_panel_opened:
        state["panelOpened"] = bool(prev.get("panelOpened"))
    return save_session(state, sid)


def mark_panel_opened(session_id: str | None = None) -> dict[str, Any]:
    state = load_session(session_id)
    state["panelOpened"] = True
    return save_session(state, state["sessionId"])


def transition_to_plan(
    session_id: str | None = None,
    requirements: str | None = None,
) -> dict[str, Any]:
    state = load_session(session_id)
    state["stage"] = "plan"
    state["gate1Confirmed"] = True
    if requirements is not None and requirements.strip():
        state["requirements"] = requirements.strip()
    return save_session(state, state["sessionId"])


def transition_to_report(
    session_id: str | None = None,
    plan_summary: str | None = None,
) -> dict[str, Any]:
    state = load_session(session_id)
    state["stage"] = "report"
    state["gate1Confirmed"] = True
    state["gate2Confirmed"] = True
    if plan_summary is not None and plan_summary.strip():
        state["planSummary"] = plan_summary.strip()
    return save_session(state, state["sessionId"])


def close_session(session_id: str | None = None) -> dict[str, Any]:
    state = load_session(session_id)
    state["stage"] = "closed"
    return save_session(state, state["sessionId"])


def is_research_allowed(session_id: str | None = None) -> tuple[bool, dict[str, Any]]:
    """当显式会话存在且处于 init（闸口 1 未确认）时拒绝外部调研；独立调用默认放行。"""
    sid = _sanitize_id(session_id or default_session_id())
    path = session_path(sid)
    if not path.is_file():
        return True, _empty_session(sid)
    state = load_session(sid)
    if state.get("stage") == "init" and not state.get("gate1Confirmed"):
        return False, state
    return True, state
