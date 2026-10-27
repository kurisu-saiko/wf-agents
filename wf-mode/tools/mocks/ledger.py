"""假账本。

接口与对方交付的 ledger 模块一致：
- commit(payload) -> {"files": [...], "runDir": "..."}
- validate(payload) -> {"ok": bool, "errors": [...]}
- handle(action, payload) 供 wf-tool 调用

只写本次运行目录下的三个文件，拒绝写到 .wf/runs/<run> 之外。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tools.errors import ToolError

RUN_FILES = ("run.json", "evidence.json", "result.md")
RUN_META_KEYS = ("pipeline", "status", "degradation", "startedAt", "finishedAt")
EVIDENCE_KEYS = ("pipeline", "items", "limitations", "gaps")
STATUSES = {"complete", "partial", "blocked"}


def _resolve_run_dir(payload: dict[str, Any]) -> Path:
    raw = payload.get("run_dir") or payload.get("runDir")
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("LEDGER_INVALID", "run_dir 必须提供")
    cwd = Path(str(payload.get("cwd") or os.getcwd())).resolve()
    target = Path(raw)
    if not target.is_absolute():
        target = cwd / target
    try:
        target = target.resolve()
    except OSError as exc:
        raise ToolError("LEDGER_INVALID", "run_dir 无法解析") from exc
    runs = (cwd / ".wf" / "runs").resolve()
    try:
        rel = target.relative_to(runs)
    except ValueError as exc:
        raise ToolError("LEDGER_INVALID", "run_dir 必须位于 .wf/runs/<本次运行>") from exc
    if len(rel.parts) != 1 or rel.parts[0] in {".", ".."}:
        raise ToolError("LEDGER_INVALID", "run_dir 必须是 .wf/runs 下的单层运行目录")
    return target


def _as_dict(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise ToolError("LEDGER_INVALID", f"{name} 不是合法 JSON") from exc
        if isinstance(parsed, dict):
            return parsed
    raise ToolError("LEDGER_INVALID", f"{name} 必须是对象或 JSON 字符串")


def _validate_objects(run: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for key in RUN_META_KEYS:
        if key not in run:
            errors.append({"code": "LEDGER_RUN_FIELD", "message": f"run.json 缺少 {key}"})
    if run.get("status") not in STATUSES:
        errors.append({"code": "LEDGER_RUN_STATUS", "message": "run.status 非法"})
    if not isinstance(run.get("degradation"), list):
        errors.append({"code": "LEDGER_RUN_DEGRADATION", "message": "run.degradation 必须是数组"})
    for key in EVIDENCE_KEYS:
        if key not in evidence:
            errors.append({"code": "LEDGER_EVIDENCE_FIELD", "message": f"evidence.json 缺少 {key}"})
    if not isinstance(evidence.get("items"), list):
        errors.append({"code": "LEDGER_EVIDENCE_ITEMS", "message": "evidence.items 必须是数组"})
    return errors


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    run = _as_dict(payload.get("run"), "run")
    evidence = _as_dict(payload.get("evidence"), "evidence")
    errors = _validate_objects(run, evidence)
    return {"ok": not errors, "errors": errors}


def commit(payload: dict[str, Any]) -> dict[str, Any]:
    run_dir = _resolve_run_dir(payload)
    run = _as_dict(payload.get("run"), "run")
    evidence = _as_dict(payload.get("evidence"), "evidence")
    result = payload.get("result")
    if not isinstance(result, str):
        raise ToolError("LEDGER_INVALID", "result 必须是字符串")
    errors = _validate_objects(run, evidence)
    if errors:
        raise ToolError(
            "LEDGER_INVALID",
            "账本对象不合规，拒绝写入",
            details={"errors": errors},
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for name, obj in (("run.json", run), ("evidence.json", evidence)):
        path = run_dir / name
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files.append(str(path))
    result_path = run_dir / "result.md"
    result_path.write_text(result.rstrip() + "\n", encoding="utf-8")
    files.append(str(result_path))
    return {"files": files, "runDir": str(run_dir)}


def handle(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "validate":
        return validate(payload)
    if action == "commit":
        return commit(payload)
    raise ToolError("UNKNOWN_ACTION", f"ledger 不支持动作: {action}")
