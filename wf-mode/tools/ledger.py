"""项目级决策账本引擎（.wf/decisions/<session_id>.json + ADR-<session_id>.md）。

跟踪 6 步开源复用与组装流水线的每一步人类闸口确认、备选理由、复用策略、
安全检查点 ID 及审计追溯记录。支持跨对话/断点续接。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from tools import session as wf_session
from tools.errors import ToolError
from tools.util import utc_now

GATES: dict[str, dict[str, str]] = {
    "GATE_1": {"step": "1", "title": "候选与需求确认 (Discovery & Requirements)", "next": "GATE_2"},
    "GATE_2": {"step": "2", "title": "合规与健康度准入 (Compliance & Health Audit)", "next": "GATE_3"},
    "GATE_3": {"step": "3", "title": "5选1复用策略拍板 (Reuse Strategy Decision)", "next": "GATE_4"},
    "GATE_4": {"step": "4", "title": "本地对接契约评审 (Local Integration Contract)", "next": "GATE_5"},
    "GATE_5": {"step": "5", "title": "细粒度 Diff 与合规声明批准 (Granular Diff & Provenance Approval)", "next": "GATE_6"},
    "GATE_6": {"step": "6", "title": "闭环验证验收或一键回滚 (Verification Sign-off / Rollback)", "next": "DONE"},
}

GATE_ORDER = ("GATE_1", "GATE_2", "GATE_3", "GATE_4", "GATE_5", "GATE_6")
VALID_STATUSES = {"approved", "rejected", "pending", "rolled_back"}
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _clean_sid(session_id: str | None) -> str:
    raw = (session_id or wf_session.default_session_id() or "default").strip()
    cleaned = _SAFE_ID_RE.sub("_", raw).strip("._")
    return cleaned or "default"


def _decisions_dir(project_path: str | Path) -> Path:
    return Path(project_path).expanduser().resolve() / ".wf" / "decisions"


def ledger_path(project_path: str | Path = ".", session_id: str | None = None) -> Path:
    sid = _clean_sid(session_id)
    return _decisions_dir(project_path) / f"{sid}.json"


def adr_path(project_path: str | Path = ".", session_id: str | None = None) -> Path:
    sid = _clean_sid(session_id)
    return _decisions_dir(project_path) / f"ADR-{sid}.md"


def _empty_ledger(project_root: Path, sid: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "version": 1,
        "sessionId": sid,
        "projectRoot": str(project_root),
        "currentGate": "GATE_1",
        "selectedCandidate": "",
        "strategy": "",
        "lastCheckpointId": "",
        "gates": {
            g: {
                "step": GATES[g]["step"],
                "title": GATES[g]["title"],
                "status": "pending",
                "summary": "",
                "rationale": "",
                "evidence": [],
                "updatedAt": "",
            }
            for g in GATE_ORDER
        },
        "history": [],
        "createdAt": now,
        "updatedAt": now,
    }


def load_ledger(project_path: str | Path = ".", session_id: str | None = None) -> dict[str, Any]:
    project_root = Path(project_path).expanduser().resolve()
    sid = _clean_sid(session_id)
    path = ledger_path(project_root, sid)
    if not path.is_file():
        return _empty_ledger(project_root, sid)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_ledger(project_root, sid)
    if not isinstance(raw, dict):
        return _empty_ledger(project_root, sid)
    base = _empty_ledger(project_root, sid)
    base.update(raw)
    gates = dict(_empty_ledger(project_root, sid)["gates"])
    if isinstance(raw.get("gates"), dict):
        for gk, gv in raw["gates"].items():
            if gk in gates and isinstance(gv, dict):
                merged = dict(gates[gk])
                merged.update(gv)
                gates[gk] = merged
    base["gates"] = gates
    base["sessionId"] = sid
    base["projectRoot"] = str(project_root)
    return base


def render_adr_markdown(ledger: dict[str, Any]) -> str:
    """生成人类可读、可随 PR 提交的 Architecture Decision Record (ADR)。"""
    sid = ledger.get("sessionId") or "default"
    candidate = ledger.get("selectedCandidate") or "（待定）"
    strategy = ledger.get("strategy") or "（待定）"
    checkpoint_id = ledger.get("lastCheckpointId") or "无"
    lines = [
        f"# Architecture Decision Record — {sid}",
        "",
        f"- **Project Root**: `{ledger.get('projectRoot', '')}`",
        f"- **Selected Candidate**: `{candidate}`",
        f"- **Reuse Strategy**: `{strategy}`",
        f"- **Current Gate**: `{ledger.get('currentGate', 'GATE_1')}`",
        f"- **Last Safety Checkpoint**: `{checkpoint_id}`",
        f"- **Updated At**: `{ledger.get('updatedAt', '')}`",
        "",
        "## 人类闸口决策清单（Human Gates Ledger）",
        "",
        "| Gate | Step | 决策项 | 状态 | 摘要与理由 |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    gates = ledger.get("gates") or {}
    for g in GATE_ORDER:
        info = gates.get(g) or {}
        status = info.get("status", "pending")
        summary = (info.get("summary") or "").replace("\n", " ").strip()
        rationale = (info.get("rationale") or "").replace("\n", " ").strip()
        note = summary if not rationale else f"{summary} ({rationale})" if summary else rationale
        lines.append(f"| `{g}` | Step {info.get('step', '')} | {info.get('title', g)} | `{status}` | {note or '-'} |")

    lines.extend(["", "## 详细证据与审计轨迹（Audit History）", ""])
    history = ledger.get("history") or []
    if not history:
        lines.append("_尚无已提交的闸口记录。_")
    else:
        for idx, item in enumerate(history, start=1):
            lines.append(
                f"### {idx}. [{item.get('gate')}] status=`{item.get('status')}` @ `{item.get('timestamp')}`"
            )
            if item.get("selectedCandidate"):
                lines.append(f"- **Candidate**: `{item['selectedCandidate']}`")
            if item.get("strategy"):
                lines.append(f"- **Strategy**: `{item['strategy']}`")
            if item.get("checkpointId"):
                lines.append(f"- **Checkpoint**: `{item['checkpointId']}`")
            if item.get("summary"):
                lines.append(f"- **Summary**: {item['summary']}")
            if item.get("rationale"):
                lines.append(f"- **Rationale**: {item['rationale']}")
            ev_list = item.get("evidence") or []
            if ev_list:
                lines.append("- **Verifiable Evidence**:")
                for ev in ev_list:
                    lines.append(f"  - {ev}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _save_ledger(project_root: Path, sid: str, ledger: dict[str, Any]) -> dict[str, Any]:
    dec_dir = _decisions_dir(project_root)
    dec_dir.mkdir(parents=True, exist_ok=True)
    jpath = ledger_path(project_root, sid)
    tmp = jpath.with_name(jpath.name + ".tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, jpath)

    apath = adr_path(project_root, sid)
    atmp = apath.with_name(apath.name + ".tmp")
    atmp.write_text(render_adr_markdown(ledger), encoding="utf-8")
    os.replace(atmp, apath)
    return ledger


def _normalize_gate(gate: str) -> str:
    raw = (gate or "").strip().upper().replace("-", "_")
    if raw not in GATES:
        raise ToolError(
            "INVALID_INPUT",
            f"未知闸口名称: {gate}",
            details={"valid": list(GATE_ORDER)},
        )
    return raw


def commit_gate(
    project_path: str | Path = ".",
    *,
    gate: str,
    status: str = "approved",
    summary: str = "",
    selected_candidate: str = "",
    strategy: str = "",
    rationale: str = "",
    evidence: list[str] | None = None,
    checkpoint_id: str = "",
    session_id: str | None = None,
) -> dict[str, Any]:
    """提交一个人类闸口的决定，持久化 JSON + ADR Markdown，并同步会话阶段。"""
    gate_key = _normalize_gate(gate)
    norm_status = (status or "approved").strip().lower()
    if norm_status not in VALID_STATUSES:
        raise ToolError(
            "INVALID_INPUT",
            f"无效闸口状态: {status}",
            details={"valid": sorted(VALID_STATUSES)},
        )

    project_root = Path(project_path).expanduser().resolve()
    sid = _clean_sid(session_id)
    ledger = load_ledger(project_root, sid)
    now = utc_now()

    clean_evidence = [str(e).strip() for e in (evidence or []) if str(e).strip()]
    gate_entry = dict(ledger["gates"][gate_key])
    gate_entry["status"] = norm_status
    if summary.strip():
        gate_entry["summary"] = summary.strip()
    if rationale.strip():
        gate_entry["rationale"] = rationale.strip()
    if clean_evidence:
        gate_entry["evidence"] = clean_evidence
    gate_entry["updatedAt"] = now
    ledger["gates"][gate_key] = gate_entry

    if selected_candidate.strip():
        ledger["selectedCandidate"] = selected_candidate.strip()
    if strategy.strip():
        ledger["strategy"] = strategy.strip().upper()
    if checkpoint_id.strip():
        ledger["lastCheckpointId"] = checkpoint_id.strip()

    if norm_status == "approved":
        ledger["currentGate"] = GATES[gate_key]["next"]
    elif norm_status in {"rejected", "rolled_back"}:
        ledger["currentGate"] = gate_key

    ledger["updatedAt"] = now
    ledger.setdefault("history", []).append(
        {
            "gate": gate_key,
            "status": norm_status,
            "timestamp": now,
            "selectedCandidate": selected_candidate.strip(),
            "strategy": strategy.strip().upper() if strategy.strip() else "",
            "checkpointId": checkpoint_id.strip(),
            "summary": summary.strip(),
            "rationale": rationale.strip(),
            "evidence": clean_evidence,
        }
    )

    saved = _save_ledger(project_root, sid, ledger)

    # 同步全局轻量会话阶段标记
    if norm_status == "approved":
        if gate_key == "GATE_1":
            wf_session.transition_to_plan(sid, requirements=summary.strip() or None)
        elif gate_key == "GATE_2":
            st = wf_session.load_session(sid)
            st["gate1Confirmed"] = True
            st["gate2Confirmed"] = True
            wf_session.save_session(st, sid)

    return {
        "ledger": saved,
        "ledgerPath": str(ledger_path(project_root, sid)),
        "adrPath": str(adr_path(project_root, sid)),
    }


def is_gate_approved(
    project_path: str | Path,
    gate: str,
    session_id: str | None = None,
) -> bool:
    gate_key = _normalize_gate(gate)
    ledger = load_ledger(project_path, session_id)
    entry = (ledger.get("gates") or {}).get(gate_key) or {}
    return entry.get("status") == "approved"
