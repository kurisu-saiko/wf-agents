"""假质检员。

接口与对方交付的 gates 模块一致：
- check(payload) -> {"ok": bool, "errors": [...]}
- handle(action, payload)

Gates 只读；不写账本。未知 gate 名称视为错误，不静默通过。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.errors import ToolError

KNOWN_GATES = {"evidence", "source-tier", "ledger", "prompt"}
RUN_META_KEYS = ("pipeline", "status", "degradation", "startedAt", "finishedAt")
EVIDENCE_KEYS = ("pipeline", "items", "limitations", "gaps")


def _err(gate: str, code: str, message: str, item_id: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"gate": gate, "code": code, "message": message}
    if item_id:
        item["itemId"] = item_id
    return item


def _check_evidence(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    items = evidence.get("items")
    if not isinstance(items, list) or not items:
        return [_err("evidence", "GATE_EVIDENCE_EMPTY", "evidence.items 为空")]
    if len(items) > 40:
        errors.append(_err("evidence", "GATE_TOO_MANY_ITEMS", "证据条目超过 40 条"))
    for item in items:
        if not isinstance(item, dict):
            errors.append(_err("evidence", "GATE_STATEMENT_EMPTY", "证据条目不是对象"))
            continue
        item_id = str(item.get("id") or "")
        statement = str(item.get("statement") or "").strip()
        if not statement:
            errors.append(_err("evidence", "GATE_STATEMENT_EMPTY", "命题为空", item_id))
        status = str(item.get("status") or "")
        sources = item.get("sources")
        if not isinstance(sources, list):
            sources = []
        if status == "verified" and not sources:
            errors.append(_err("evidence", "GATE_SOURCE_MISSING", "verified 条目没有来源", item_id))
        if status == "conflict" and len(sources) < 2:
            errors.append(_err("evidence", "GATE_CONFLICT_SOURCES", "conflict 条目少于两个来源", item_id))
        for source in sources:
            if not isinstance(source, dict):
                errors.append(_err("evidence", "GATE_QUOTE_MISSING", "来源不是对象", item_id))
                continue
            quote = str(source.get("quote") or "").strip()
            if not quote or len(quote) > 500:
                errors.append(_err("evidence", "GATE_QUOTE_MISSING", "来源缺原文片段或超过 500 字符", item_id))
            url = str(source.get("url") or "").strip()
            date = str(source.get("date") or "").strip()
            # 无日期的外部来源只能算 unverified，不应让整条管线被拒绝；
            # 只有声称 verified 的条目才强制要求日期。
            if status == "verified" and url and not date:
                errors.append(_err("evidence", "GATE_DATE_MISSING", "verified 的外部 URL 来源缺发布日期", item_id))
    return errors


def _check_source_tier(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for item in evidence.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        for source in item.get("sources") or []:
            if not isinstance(source, dict):
                continue
            tier = str(source.get("tier") or "")
            if tier not in {"primary", "secondary"}:
                errors.append(_err("source-tier", "GATE_TIER_INVALID", "tier 必须是 primary/secondary", item_id))
            if not str(source.get("url") or "").strip() and not str(source.get("path") or "").strip():
                errors.append(_err("source-tier", "GATE_LOCATOR_MISSING", "来源缺 url 或 path", item_id))
    return errors


def _check_ledger(run: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for key in RUN_META_KEYS:
        if key not in run:
            errors.append(_err("ledger", "GATE_LEDGER_INVALID", f"run.json 缺少 {key}"))
    for key in EVIDENCE_KEYS:
        if key not in evidence:
            errors.append(_err("ledger", "GATE_LEDGER_INVALID", f"evidence.json 缺少 {key}"))
    return errors


def _check_prompt(payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = payload.get("promptBlocks") or payload.get("prompt_blocks") or []
    if not isinstance(blocks, list):
        return [_err("prompt", "GATE_PROMPT_MISSING", "promptBlocks 必须是数组")]
    root = Path(str(payload.get("blocksRoot") or payload.get("blocks_root") or "")).resolve() if payload.get(
        "blocksRoot") or payload.get("blocks_root") else Path(__file__).resolve().parents[2]
    errors: list[dict[str, Any]] = []
    for block in blocks:
        path = (root / str(block)).resolve()
        if not path.is_file():
            errors.append(_err("prompt", "GATE_PROMPT_MISSING", f"prompt block 不存在: {block}"))
        elif not path.read_text(encoding="utf-8").strip():
            errors.append(_err("prompt", "GATE_PROMPT_EMPTY", f"prompt block 为空: {block}"))
    return errors


def check(payload: dict[str, Any]) -> dict[str, Any]:
    names = payload.get("names") or payload.get("gates") or []
    if isinstance(names, str):
        names = [x.strip() for x in names.split(",") if x.strip()]
    if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
        raise ToolError("INVALID_INPUT", "names 必须是字符串数组")
    run = payload.get("run") or {}
    evidence = payload.get("evidence") or {}
    if not isinstance(run, dict) or not isinstance(evidence, dict):
        raise ToolError("INVALID_INPUT", "run/evidence 必须是对象")
    errors: list[dict[str, Any]] = []
    for name in names:
        if name not in KNOWN_GATES:
            errors.append(_err(name, "GATE_UNKNOWN", f"未知 gate: {name}"))
        elif name == "evidence":
            errors.extend(_check_evidence(evidence))
        elif name == "source-tier":
            errors.extend(_check_source_tier(evidence))
        elif name == "ledger":
            errors.extend(_check_ledger(run, evidence))
        elif name == "prompt":
            errors.extend(_check_prompt(payload))
    return {"ok": not errors, "errors": errors, "gates": names}


def handle(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "check":
        return check(payload)
    raise ToolError("UNKNOWN_ACTION", f"gates 不支持动作: {action}")
