"""受控分块组装落地执行器（Step 5）。

强制执行人类闸口校验（必须先经 Gate 4 或 Gate 5 批准），
先自动创建安全检查点，再落盘写入经评审的 Chunk A/B/C 文件变更，
并将检查点与变更清单同步登记到 `.wf/decisions/` 账本。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tools import ledger as wf_ledger
from tools.assembly import checkpoint as wf_checkpoint
from tools.errors import ToolError


def _safe_target(project_root: Path, rel_path: str) -> Path:
    cleaned = rel_path.replace("\\", "/").lstrip("./")
    if not cleaned or ".." in Path(cleaned).parts:
        raise ToolError("INVALID_INPUT", f"禁止非法目标路径: {rel_path}")
    target = (project_root / cleaned).resolve()
    try:
        target.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ToolError("INVALID_INPUT", f"写入路径越界: {rel_path}") from exc
    return target


def apply_assembly_contract(
    *,
    project_path: str | Path,
    contract: dict[str, Any],
    session_id: str | None = None,
    require_gate_approval: bool = True,
) -> dict[str, Any]:
    """执行经过人类闸口确认的组装契约（Chunk A/B/C），并落盘安全检查点。"""
    project_root = Path(project_path).expanduser().resolve()
    if not project_root.is_dir():
        raise ToolError("INVALID_INPUT", f"目标项目目录不存在: {project_path}")

    if require_gate_approval:
        g4 = wf_ledger.is_gate_approved(project_root, "GATE_4", session_id)
        g5 = wf_ledger.is_gate_approved(project_root, "GATE_5", session_id)
        if not (g4 or g5):
            raise ToolError(
                "GATE_REQUIRED",
                "尚未通过 Gate 4（对接契约评审）或 Gate 5（细粒度 Diff 批准），禁止向本地项目写入组装代码。请先调用 wf_gate_commit。",
                details={"requiredGates": ["GATE_4", "GATE_5"]},
            )

    chunks = contract.get("chunks")
    if not isinstance(chunks, dict):
        raise ToolError("INVALID_INPUT", "contract 缺少 chunks 结构")

    operations: list[dict[str, Any]] = []
    for chunk_name in ("A_dependency_and_config", "B_code_and_provenance", "C_adapter_and_smoke_test"):
        entries = chunks.get(chunk_name) or []
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, dict) and item.get("path"):
                operations.append({**item, "chunk": chunk_name})

    if not operations:
        raise ToolError("INVALID_INPUT", "contract 中没有可执行的文件变更项")

    planned_files = [str(op["path"]) for op in operations]
    ck = wf_checkpoint.create_checkpoint(
        project_root,
        label=f"assemble-{contract.get('adapterName') or 'component'}",
        planned_files=planned_files,
    )

    written: list[dict[str, str]] = []
    for op in operations:
        rel = str(op["path"])
        target = _safe_target(project_root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = str(op.get("content") or "")
        tmp = target.with_name(target.name + ".wf_tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
        written.append(
            {
                "path": rel,
                "chunk": str(op["chunk"]),
                "role": str(op.get("role") or ""),
                "action": str(op.get("action") or "write"),
            }
        )

    wf_ledger.commit_gate(
        project_root,
        gate="GATE_5",
        status="approved",
        summary=f"已创建安全检查点 {ck['checkpointId']} 并应用 {len(written)} 个分块变更文件",
        selected_candidate=str(contract.get("adapterName") or ""),
        strategy=str(contract.get("strategy") or ""),
        checkpoint_id=ck["checkpointId"],
        evidence=[f"{w['action']}: {w['path']} ({w['chunk']})" for w in written],
        session_id=session_id,
    )

    return {
        "projectRoot": str(project_root),
        "checkpointId": ck["checkpointId"],
        "strategy": contract.get("strategy"),
        "adapterFile": contract.get("adapterFile"),
        "smokeTestFile": contract.get("smokeTestFile"),
        "writtenFiles": written,
        "writtenCount": len(written),
    }
