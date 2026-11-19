"""分阶段只读包装器与工作流生命周期管理。

用法：
  python tools/wf_stage.py init [--task "..."] [--session <id>] [--no-open]
  python tools/wf_stage.py calibrate [--session <id>] [--no-open]
  python tools/wf_stage.py enter-plan [--requirements "..."] [--session <id>]
  python tools/wf_stage.py enter-report [--summary "..."] [--session <id>]
  python tools/wf_stage.py close [--session <id>]
  python tools/wf_stage.py status [--session <id>] [--project <dir>]
  python tools/wf_stage.py gate-commit --gate <GATE_1..GATE_6> [--project <dir>] [--summary "..."] [--session <id>]
  python tools/wf_stage.py local-profile [--path <dir>]
  python tools/wf_stage.py research <capability> <action> [--key value | --json "{...}"]

面板生命周期规则：
- `init` / `calibrate`：仅在本会话第一次交互时启动并打开配置面板；同会话后续调用不重复打开浏览器。
- `enter-plan` / `enter-report` / `close`：自动关闭配置面板（`panel --close`）并更新阶段状态。
- `research`：只放行只读调研/分析能力；写类、pending、未知能力一律拒绝。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import ledger as wf_ledger  # noqa: E402
from tools import session as wf_session  # noqa: E402
from tools.assembly import profiler as wf_profiler  # noqa: E402
from tools.errors import ToolError  # noqa: E402

TOOL = ROOT / "tools" / "wf-tool.py"

READ_ACTIONS: dict[str, set[str]] = {
    "project_search": {"search", "lookup", "search_code", "health"},
    "web_search": {"search", "health"},
    "web_extract": {"extract", "health"},
    "repo_ingest": {"ingest", "tree", "read", "readme", "health"},
    "repo_health": {"analyze", "health"},
    "package_meta": {"lookup", "search", "health"},
    "package_security": {"scan", "query", "health"},
    "license_sbom": {"scan", "health"},
    "dependency_graph": {"graph", "analyze", "health"},
    "structural_search": {"search", "symbols", "health"},
}

_PATH_TRAVERSAL_RE = re.compile(r"(?:^|[\\/])\.\.(?:$|[\\/])")
_PATH_FLAGS = {"--path", "--destination", "--template"}


class StageError(Exception):
    pass


def _run(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (proc.stdout or "").strip()
    if not text:
        raise StageError(f"wf-tool 没有输出；stderr: {(proc.stderr or '')[:400]}")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise StageError(f"wf-tool 输出不是 JSON: {text[:200]}") from exc


def _emit(data: dict[str, Any], code: int = 0) -> int:
    sys.stdout.buffer.write(
        (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    sys.stdout.buffer.flush()
    return code


def _parse_flags(args: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if not tok.startswith("--"):
            raise StageError(f"不识别的参数: {tok}")
        key = tok[2:]
        if "=" in key:
            k, v = key.split("=", 1)
            parsed[k] = v
            i += 1
            continue
        if key in {"no-open", "force-panel"}:
            parsed[key] = True
            i += 1
            continue
        if i + 1 >= len(args):
            raise StageError(f"参数缺少值: {tok}")
        parsed[key] = args[i + 1]
        i += 2
    return parsed


def _check_path_traversal(args: list[str]) -> None:
    for idx, token in enumerate(args):
        key = token.split("=", 1)[0]
        if key in _PATH_FLAGS:
            val = token.split("=", 1)[1] if "=" in token else (args[idx + 1] if idx + 1 < len(args) else "")
            if _PATH_TRAVERSAL_RE.search(val.strip()):
                raise StageError("禁止路径穿越（..）")
        if token == "--json" and idx + 1 < len(args):
            try:
                obj = json.loads(args[idx + 1])
            except ValueError:
                obj = {}
            if isinstance(obj, dict):
                for pk in ("path", "destination", "template"):
                    v = str(obj.get(pk) or "")
                    if v and _PATH_TRAVERSAL_RE.search(v):
                        raise StageError("禁止路径穿越（..）")


def _calibrate_core(
    *,
    session_id: str | None = None,
    task: str | None = None,
    open_panel_if_needed: bool = True,
    reset: bool = False,
) -> dict[str, Any]:
    health = _run(["health"])
    doctor = _run(["doctor"])
    listed = _run(["list"])

    sid = session_id or wf_session.default_session_id()
    if reset:
        current = wf_session.load_session(sid)
        # 如果是同一会话重开新任务且上一轮已关闭，重新允许首轮打开面板；否则保留 panelOpened 状态
        preserve = current.get("stage") == "init"
        state = wf_session.reset_session(sid, task or "", preserve_panel_opened=preserve)
    else:
        state = wf_session.load_session(sid)
        if task and not state.get("task"):
            state["task"] = task.strip()
            state = wf_session.save_session(state, sid)

    panel_data: dict[str, Any]
    if open_panel_if_needed and not state.get("panelOpened"):
        panel_res = _run(["panel", "--ensure"])
        panel_data = panel_res.get("data", {})
        wf_session.mark_panel_opened(sid)
        state = wf_session.load_session(sid)
    else:
        status_res = _run(["panel", "--status"])
        panel_data = dict(status_res.get("data", {}))
        panel_data["opened"] = False
        panel_data["skipped_reopen"] = bool(state.get("panelOpened"))

    statuses = health.get("data", {}).get("capabilities", {})
    buckets: dict[str, list[str]] = {
        "active": [],
        "degraded": [],
        "missing": [],
        "pending": [],
        "disabled": [],
    }
    for name, item in statuses.items():
        status = str(item.get("status") or "missing")
        buckets.setdefault(status, []).append(name)

    return {
        "ok": bool(health.get("ok")) and bool(doctor.get("ok")),
        "session": state,
        "runtime": doctor.get("data", {}).get("runtime", {}),
        "hosts": doctor.get("data", {}).get("hosts", {}),
        "capabilities": buckets,
        "sources": {
            name: item.get("envSources", {})
            for name, item in listed.get("data", {}).get("capabilities", {}).items()
            if item.get("envSources")
        },
        "panel": panel_data,
    }


def calibrate(session_id: str | None = None, open_panel_if_needed: bool = True) -> int:
    data = _calibrate_core(
        session_id=session_id,
        open_panel_if_needed=open_panel_if_needed,
        reset=False,
    )
    return _emit(data, 0 if data["ok"] else 1)


def init_workflow(
    task: str = "",
    session_id: str | None = None,
    open_panel: bool = True,
) -> int:
    data = _calibrate_core(
        session_id=session_id,
        task=task,
        open_panel_if_needed=open_panel,
        reset=True,
    )
    return _emit(data, 0 if data["ok"] else 1)


def enter_plan(requirements: str = "", session_id: str | None = None) -> int:
    sid = session_id or wf_session.default_session_id()
    panel_res = _run(["panel", "--close"])
    state = wf_session.transition_to_plan(sid, requirements=requirements or None)
    return _emit(
        {
            "ok": True,
            "stage": "plan",
            "session": state,
            "panel": panel_res.get("data", {}),
        },
        0,
    )


def enter_report(summary: str = "", session_id: str | None = None) -> int:
    sid = session_id or wf_session.default_session_id()
    panel_res = _run(["panel", "--close"])
    state = wf_session.transition_to_report(sid, plan_summary=summary or None)
    return _emit(
        {
            "ok": True,
            "stage": "report",
            "session": state,
            "panel": panel_res.get("data", {}),
        },
        0,
    )


def close_workflow(session_id: str | None = None) -> int:
    sid = session_id or wf_session.default_session_id()
    panel_res = _run(["panel", "--close"])
    state = wf_session.close_session(sid)
    return _emit(
        {
            "ok": True,
            "stage": "closed",
            "session": state,
            "panel": panel_res.get("data", {}),
        },
        0,
    )


def status_workflow(session_id: str | None = None, project_path: str | None = None) -> int:
    sid = session_id or wf_session.default_session_id()
    panel_res = _run(["panel", "--status"])
    state = wf_session.load_session(sid)
    payload: dict[str, Any] = {
        "ok": True,
        "session": state,
        "panel": panel_res.get("data", {}),
    }
    if project_path:
        payload["ledger"] = wf_ledger.load_ledger(project_path, sid)
    return _emit(payload, 0)


def gate_commit(flags: dict[str, Any]) -> int:
    gate = str(flags.get("gate") or "")
    if not gate:
        raise StageError("gate-commit 需要 --gate GATE_1..GATE_6")
    status = str(flags.get("status") or "approved")
    project_path = str(flags.get("project") or ".")
    sid = str(flags.get("session") or "") or None
    try:
        res = wf_ledger.commit_gate(
            project_path,
            gate=gate,
            status=status,
            summary=str(flags.get("summary") or ""),
            selected_candidate=str(flags.get("candidate") or ""),
            strategy=str(flags.get("strategy") or ""),
            rationale=str(flags.get("rationale") or ""),
            checkpoint_id=str(flags.get("checkpoint") or ""),
            session_id=sid,
        )
    except ToolError as exc:
        raise StageError(exc.message) from exc
    panel_data: dict[str, Any] = {}
    if gate.strip().upper() == "GATE_1" and status.strip().lower() == "approved":
        panel_data = _run(["panel", "--close"]).get("data", {})
    return _emit({"ok": True, **res, **({"panel": panel_data} if panel_data else {})}, 0)


def local_profile_cmd(path: str = ".") -> int:
    try:
        res = wf_profiler.profile_local_project(path)
    except ToolError as exc:
        raise StageError(exc.message) from exc
    return _emit({"ok": True, **res}, 0)


def research(args: list[str]) -> int:
    if len(args) < 2:
        raise StageError("需要 research <capability> <action>")
    capability, action = args[0], args[1]
    allowed = READ_ACTIONS.get(capability)
    if not allowed:
        raise StageError(f"阶段 4 不允许调用能力: {capability}")
    if action not in allowed:
        raise StageError(f"{capability} 不允许动作: {action}")
    _check_path_traversal(args[2:])

    envelope = _run(["call", capability, action, *args[2:]])
    return _emit(envelope, 0 if envelope.get("ok") else 1)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        sys.stdout.buffer.write((__doc__ or "").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0
    try:
        command = args[0]
        if command == "calibrate":
            # 保持严格参数校验：如有未知位置参数则报错，支持 --session / --no-open
            if len(args) > 1 and not args[1].startswith("--"):
                raise StageError("calibrate 不接受额外参数")
            flags = _parse_flags(args[1:])
            return calibrate(
                session_id=flags.get("session"),
                open_panel_if_needed=not bool(flags.get("no-open")),
            )
        if command == "init":
            flags = _parse_flags(args[1:])
            return init_workflow(
                task=str(flags.get("task") or ""),
                session_id=flags.get("session"),
                open_panel=not bool(flags.get("no-open")),
            )
        if command == "enter-plan":
            flags = _parse_flags(args[1:])
            return enter_plan(
                requirements=str(flags.get("requirements") or ""),
                session_id=flags.get("session"),
            )
        if command == "enter-report":
            flags = _parse_flags(args[1:])
            return enter_report(
                summary=str(flags.get("summary") or ""),
                session_id=flags.get("session"),
            )
        if command == "close":
            flags = _parse_flags(args[1:])
            return close_workflow(session_id=flags.get("session"))
        if command == "status":
            flags = _parse_flags(args[1:])
            return status_workflow(session_id=flags.get("session"), project_path=flags.get("project"))
        if command == "gate-commit":
            flags = _parse_flags(args[1:])
            return gate_commit(flags)
        if command == "local-profile":
            flags = _parse_flags(args[1:])
            return local_profile_cmd(str(flags.get("path") or "."))
        if command == "research":
            return research(args[1:])
        raise StageError(f"未知阶段命令: {command}")
    except StageError as exc:
        return _emit({"ok": False, "error": {"code": "STAGE_ERROR", "message": str(exc)}}, 1)


if __name__ == "__main__":
    raise SystemExit(main())
