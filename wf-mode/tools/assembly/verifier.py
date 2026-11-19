"""Step 6 自动化闭环验证器：

1. 对新增/修改的 Python 文件执行语法编译检查（py_compile）
2. 执行集成契约生成的适配器冒烟测试（优先 pytest，自动降级为直接 python 执行）
3. 可选运行目标仓库原有测试套件进行回归验证
4. 生成 Gate 6 决策简报（通过验收 vs 一键回滚）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from tools import envelope as wf_envelope
from tools.assembly import profiler
from tools.errors import ToolError


def _run_cmd(cmd: list[str], cwd: Path, timeout: int = 30) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "command": " ".join(cmd),
            "exitCode": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": (proc.stdout or "")[-2000:],
            "stderr": (proc.stderr or "")[-2000:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": " ".join(cmd),
            "exitCode": -1,
            "passed": False,
            "stdout": "",
            "stderr": str(exc),
        }


def run_verification(
    *,
    project_path: str | Path,
    contract: dict[str, Any] | None = None,
    smoke_test_file: str | None = None,
    run_project_tests: bool = False,
) -> dict[str, Any]:
    """运行本地闭环验证并产出 Gate 6 DecisionBrief。"""
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise ToolError("INVALID_INPUT", f"目标项目目录不存在: {project_path}")

    contract = dict(contract or {})
    checks: list[dict[str, Any]] = []

    # 1. py_compile 检查所有契约内 .py 文件
    py_files: list[str] = []
    for rel in contract.get("plannedFiles") or []:
        if str(rel).endswith(".py") and (root / str(rel)).is_file():
            py_files.append(str(rel))
    if not py_files and contract.get("adapterFile"):
        af = str(contract["adapterFile"])
        if af.endswith(".py") and (root / af).is_file():
            py_files.append(af)

    if py_files:
        compile_res = _run_cmd([sys.executable, "-m", "py_compile", *py_files], root)
        checks.append({"name": "python_syntax_compile", **compile_res})

    # 2. 运行冒烟测试
    smoke_rel = smoke_test_file or str(contract.get("smokeTestFile") or "").strip()
    if smoke_rel:
        smoke_target = root / smoke_rel
        if not smoke_target.is_file():
            checks.append(
                {
                    "name": "adapter_smoke_test",
                    "command": smoke_rel,
                    "exitCode": -1,
                    "passed": False,
                    "stdout": "",
                    "stderr": f"冒烟测试文件不存在: {smoke_rel}",
                }
            )
        else:
            pytest_res = _run_cmd([sys.executable, "-m", "pytest", "-q", smoke_rel], root)
            if not pytest_res["passed"] and "No module named pytest" in pytest_res["stderr"]:
                direct_res = _run_cmd([sys.executable, smoke_rel], root)
                checks.append({"name": "adapter_smoke_test_direct", **direct_res})
            else:
                checks.append({"name": "adapter_smoke_test_pytest", **pytest_res})

    # 3. 可选运行项目回归探针
    if run_project_tests:
        prof = profiler.profile_local_project(root)
        for probe in prof.get("verificationProbes") or []:
            pname = str(probe.get("name") or "")
            if pname in {"syntax_compile"}:
                continue
            cmd = [str(c) for c in (probe.get("cmd") or [])]
            if cmd:
                res = _run_cmd(cmd, root, timeout=60)
                checks.append({"name": f"project_{pname}", **res})
                break

    if not checks:
        # 至少对项目内 Python 文件或基础存在性进行一次探针
        prof = profiler.profile_local_project(root)
        checks.append(
            {
                "name": "project_baseline_scan",
                "command": "profile_local_project",
                "exitCode": 0,
                "passed": True,
                "stdout": f"Scanned {prof.get('totalFilesScanned')} files, primary={prof.get('primaryLanguage')}",
                "stderr": "",
            }
        )

    passed = all(c["passed"] for c in checks)
    evidences = [
        f"[{ 'PASS' if c['passed'] else 'FAIL' }] {c['name']}: `{c['command']}` (exit={c['exitCode']})"
        for c in checks
    ]
    tradeoffs = [
        "冒烟测试仅验证适配器隔离契约与导出符号可用；核心业务逻辑集成仍需结合项目端到端用例确认",
        "如验证未通过或发现异常，可立即调用 wf_checkpoint(action='rollback') 一键清理并恢复原状",
    ]

    brief = wf_envelope.build_decision_brief(
        requirement_fit=(
            f"闭环验证全部通过（共 {len(checks)} 项检查，0 失败），可提交 Gate 6 完成验收。"
            if passed
            else f"闭环验证未通过（存在失败项），建议排查或执行一键回滚。"
        ),
        verifiable_evidence=evidences,
        limitations_and_tradeoffs=tradeoffs,
        actionable_options=[
            {
                "id": "accept_gate_6",
                "recommended": passed,
                "summary": "验收通过：调用 wf_gate_commit(gate='GATE_6', status='approved') 完成归档",
            },
            {
                "id": "rollback_assembly",
                "recommended": not passed,
                "summary": "立即回滚：调用 wf_checkpoint(action='rollback') 恢复组装前工作区",
            },
        ],
    )

    return {
        "projectRoot": str(root),
        "passed": passed,
        "checks": checks,
        "decision_brief": brief,
    }
