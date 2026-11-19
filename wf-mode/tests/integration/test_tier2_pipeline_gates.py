"""Tier 2 集成测试：.wf/decisions/ 决策账本流转、写盘闸口强拦截、安全检查点与一键精确回滚。"""

from __future__ import annotations

import pytest

from tools import ledger
from tools.assembly import checkpoint, contract, patcher
from tools.errors import ToolError


def test_ledger_commits_six_gates_and_renders_adr(tmp_path):
    res1 = ledger.commit_gate(
        tmp_path,
        gate="GATE_1",
        summary="确认引入轻量级限流算法",
        evidence=["Local: flat_layout Python"],
        session_id="s-ledger",
    )
    assert res1["ledger"]["currentGate"] == "GATE_2"
    assert ledger.is_gate_approved(tmp_path, "GATE_1", "s-ledger") is True
    assert ledger.is_gate_approved(tmp_path, "GATE_4", "s-ledger") is False

    res3 = ledger.commit_gate(
        tmp_path,
        gate="GATE_3",
        selected_candidate="org/limiter",
        strategy="CODE_SLICE",
        rationale="只需单个限流算法文件且避免重依赖",
        session_id="s-ledger",
    )
    assert res3["ledger"]["strategy"] == "CODE_SLICE"
    assert res3["ledger"]["selectedCandidate"] == "org/limiter"

    adr_file = tmp_path / ".wf" / "decisions" / "ADR-s-ledger.md"
    assert adr_file.is_file()
    adr_text = adr_file.read_text(encoding="utf-8")
    assert "org/limiter" in adr_text
    assert "CODE_SLICE" in adr_text
    assert "`GATE_1`" in adr_text
    assert "`GATE_3`" in adr_text


def test_patcher_enforces_gate_approval_and_checkpoint_rollbacks_cleanly(tmp_path):
    proj = tmp_path / "myproj"
    proj.mkdir()
    orig_pyproject = '[project]\nname = "myproj"\nversion = "0.1.0"\ndependencies = []\n'
    (proj / "pyproject.toml").write_text(orig_pyproject, encoding="utf-8")
    (proj / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")

    # 设计一个 PACKAGE_DEP 契约
    ct = contract.design_integration_contract(
        project_path=proj,
        strategy="PACKAGE_DEP",
        candidate={
            "name": "tenacity",
            "repo": "jd/tenacity",
            "license": "Apache-2.0",
            "version": "9.0.0",
            "packageName": "tenacity",
            "versionSpec": ">=9.0",
        },
        adapter_name="retry_helper",
    )
    assert len(ct["chunks"]["A_dependency_and_config"]) == 1
    assert "tenacity>=9.0" in ct["chunks"]["A_dependency_and_config"][0]["diff"]

    # 未过 Gate 4/5 时必须强拦截
    with pytest.raises(ToolError) as exc_info:
        patcher.apply_assembly_contract(
            project_path=proj,
            contract=ct,
            session_id="s-gate",
            require_gate_approval=True,
        )
    assert exc_info.value.code == "GATE_REQUIRED"
    assert (proj / "pyproject.toml").read_text(encoding="utf-8") == orig_pyproject

    # 通过 Gate 4 后放行组装
    ledger.commit_gate(proj, gate="GATE_4", status="approved", summary="批准适配器契约", session_id="s-gate")
    applied = patcher.apply_assembly_contract(
        project_path=proj,
        contract=ct,
        session_id="s-gate",
        require_gate_approval=True,
    )
    assert applied["writtenCount"] >= 3
    assert "tenacity>=9.0" in (proj / "pyproject.toml").read_text(encoding="utf-8")
    assert (proj / "THIRD_PARTY_NOTICES.md").is_file()
    assert (proj / "adapters" / "retry_helper_adapter.py").is_file()
    assert (proj / "tests" / "test_retry_helper_smoke.py").is_file()
    assert ledger.is_gate_approved(proj, "GATE_5", "s-gate") is True

    # 一键回滚后必须彻底恢复原状
    rb = checkpoint.rollback_checkpoint(proj, applied["checkpointId"])
    assert rb["status"] == "rolled_back"
    assert "pyproject.toml" in rb["restoredFiles"]
    assert (proj / "pyproject.toml").read_text(encoding="utf-8") == orig_pyproject
    assert not (proj / "THIRD_PARTY_NOTICES.md").exists()
    assert not (proj / "adapters").exists()
    assert not (proj / "tests").exists()
