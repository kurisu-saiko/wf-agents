"""Tier 4 黄金场景质量评估（Eval Benchmarks）：

端到端模拟真实生产需求：
为一个带 Git 历史与 src_layout 的本地 Python 项目，通过 AST 切片复用上游多文件限流器组件，
检验：
1. 证据与四问 DecisionBrief 完备度（100% 非空核验）
2. AST 闭包完整率（100% 关联内部依赖抽取且剔除无关文件）
3. 组装后真实 Python 导入与函数调用一次通过（py_compile + pytest + 实际业务调用）
4. 合规追溯率（SPDX 文件头 + THIRD_PARTY_NOTICES.md + ADR 决策文档）
5. 零污染回滚率（回滚后 Git 工作区业务源码与配置 100% 干净还原）
"""

from __future__ import annotations

import importlib
import subprocess
import sys

from tools import envelope, ledger
from tools.assembly import checkpoint, contract, patcher, profiler, slicer, strategy, verifier


def _git(cwd, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return proc.stdout.strip()


def test_golden_benchmark_slice_assemble_verify_and_rollback(tmp_path):
    # 1. 构建真实 git 托管的本地 src_layout Python 项目
    local_repo = tmp_path / "billing_service"
    (local_repo / "src" / "billing").mkdir(parents=True)
    (local_repo / "tests").mkdir(parents=True)
    (local_repo / "pyproject.toml").write_text(
        '[project]\nname = "billing"\nversion = "0.1.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    (local_repo / ".gitignore").write_text(".wf/\n__pycache__/\n", encoding="utf-8")
    (local_repo / "src" / "billing" / "__init__.py").write_text("", encoding="utf-8")
    (local_repo / "src" / "billing" / "app.py").write_text("def health():\n    return 'ok'\n", encoding="utf-8")
    (local_repo / "tests" / "test_health.py").write_text(
        "def test_health_ok():\n    assert True\n",
        encoding="utf-8",
    )

    _git(local_repo, "init")
    _git(local_repo, "config", "user.name", "eval-bot")
    _git(local_repo, "config", "user.email", "eval@example.com")
    _git(local_repo, "add", ".")
    _git(local_repo, "commit", "-m", "initial commit")

    # 2. 构建模拟开源上游多文件仓库
    upstream = tmp_path / "py_rate_guard"
    (upstream / "src" / "rateguard").mkdir(parents=True)
    (upstream / "src" / "rateguard" / "__init__.py").write_text("", encoding="utf-8")
    (upstream / "src" / "rateguard" / "bucket.py").write_text(
        "class TokenBucket:\n"
        "    def __init__(self, capacity: int) -> None:\n"
        "        self.capacity = capacity\n"
        "        self.tokens = capacity\n\n"
        "    def consume(self, amount: int = 1) -> bool:\n"
        "        if self.tokens >= amount:\n"
        "            self.tokens -= amount\n"
        "            return True\n"
        "        return False\n",
        encoding="utf-8",
    )
    (upstream / "src" / "rateguard" / "limiter.py").write_text(
        "from .bucket import TokenBucket\n\n"
        "def create_limiter(limit: int = 2) -> TokenBucket:\n"
        "    return TokenBucket(capacity=limit)\n",
        encoding="utf-8",
    )
    (upstream / "src" / "rateguard" / "heavy_cli.py").write_text(
        "# 不应被切片抽入的重 CLI 文件\nimport click\n",
        encoding="utf-8",
    )

    sid = "eval-rate-guard"

    # Step 1~3: 画像 + 策略评估
    prof = profiler.profile_local_project(local_repo)
    assert prof["layout"] == "src_layout"
    assert prof["adapterDir"] == "src/billing/adapters"

    strat = strategy.evaluate_strategies(
        candidate={
            "name": "py-rate-guard",
            "language": "Python",
            "license": "MIT",
            "publishedPackage": False,
            "targetFilesCount": 2,
            "estimatedLoc": 30,
        },
        local_profile=prof,
        intent={"preferZeroDependencies": True},
    )
    assert strat["recommendedStrategy"] == "CODE_SLICE"
    ok_s, _ = envelope.validate_decision_brief(strat["decision_brief"])
    assert ok_s is True

    # 记录 Gates 1~3
    ledger.commit_gate(local_repo, gate="GATE_1", summary="确认限流需求", session_id=sid)
    ledger.commit_gate(local_repo, gate="GATE_2", selected_candidate="example/py-rate-guard", summary="MIT 合规且零 CVE", session_id=sid)
    ledger.commit_gate(local_repo, gate="GATE_3", strategy="CODE_SLICE", rationale="仅抽取最小限流闭包", session_id=sid)

    # Step 4: AST 闭包与本地对接契约设计
    closure = slicer.compute_slice_closure(upstream, ["src/rateguard/limiter.py"])
    assert closure["closureComplete"] is True
    assert "src/rateguard/bucket.py" in closure["closureFiles"]
    assert "src/rateguard/heavy_cli.py" not in closure["closureFiles"]

    ct = contract.design_integration_contract(
        project_path=local_repo,
        strategy="CODE_SLICE",
        candidate={
            "name": "py-rate-guard",
            "repo": "example/py-rate-guard",
            "license": "MIT",
            "version": "abc1234",
        },
        adapter_name="rate_limiter",
        source_path=upstream,
        slice_files=["src/rateguard/limiter.py"],
    )
    ok_c, _ = envelope.validate_decision_brief(ct["decision_brief"])
    assert ok_c is True

    ledger.commit_gate(local_repo, gate="GATE_4", summary="批准薄 Adapter 契约与 Diff", session_id=sid)

    # Step 5: 原子落盘
    applied = patcher.apply_assembly_contract(
        project_path=local_repo,
        contract=ct,
        session_id=sid,
        require_gate_approval=True,
    )

    # 验证 SPDX 头与 THIRD_PARTY_NOTICES.md
    sliced_limiter = local_repo / "src" / "billing" / "adapters" / "vendor_rate_limiter" / "src" / "rateguard" / "limiter.py"
    assert "# SPDX-License-Identifier: MIT" in sliced_limiter.read_text(encoding="utf-8")
    assert "abc1234" in (local_repo / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    # Step 6: 运行真实闭环验证 + 验证适配器真实运行效果
    verify = verifier.run_verification(project_path=local_repo, contract=ct, run_project_tests=True)
    assert verify["passed"] is True
    ok_v, _ = envelope.validate_decision_brief(verify["decision_brief"])
    assert ok_v is True

    # 真实导入生成的适配器并运行其中的业务逻辑
    src_dir = str(local_repo / "src")
    sys.path.insert(0, src_dir)
    try:
        adapter_mod = importlib.import_module("billing.adapters.rate_limiter_adapter")
        bucket = adapter_mod.create_limiter(limit=2)
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True
        assert bucket.consume(1) is False
    finally:
        if src_dir in sys.path:
            sys.path.remove(src_dir)
        sys.modules.pop("billing.adapters.rate_limiter_adapter", None)
        sys.modules.pop("billing.adapters", None)
        sys.modules.pop("billing", None)
        sys.modules.pop("rateguard.limiter", None)
        sys.modules.pop("rateguard.bucket", None)
        sys.modules.pop("rateguard", None)

    ledger.commit_gate(local_repo, gate="GATE_6", status="approved", summary="全部验证通过", session_id=sid)
    assert "全部验证通过" in (local_repo / ".wf" / "decisions" / f"ADR-{sid}.md").read_text(encoding="utf-8")

    # 零污染回滚评估：回滚后 git status --porcelain 必须完全为空！
    rb = checkpoint.rollback_checkpoint(local_repo, applied["checkpointId"])
    assert rb["status"] == "rolled_back"
    assert _git(local_repo, "status", "--porcelain") == ""
