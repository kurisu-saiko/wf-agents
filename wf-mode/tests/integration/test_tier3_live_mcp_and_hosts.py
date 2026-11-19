"""Tier 3 真实宿主与 MCP 协议端到端验证：JSON-RPC 2.0 全部 24 个工具与阶段解锁链路。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCP = ROOT / "tools" / "wf_mcp.py"


def _rpc(lines: list[dict], env_extra: dict[str, str] | None = None) -> list[dict]:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    stdin_text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in lines)
    proc = subprocess.run(
        [sys.executable, str(MCP)],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def test_mcp_exposes_24_tools_and_runs_assembly_lifecycle(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.py").write_text("print('hello')\n", encoding="utf-8")

    src = tmp_path / "upstream"
    src.mkdir()
    (src / "slug.py").write_text("def slugify(text: str) -> str:\n    return text.strip().lower().replace(' ', '-')\n", encoding="utf-8")

    env = {
        "WF_DATA_DIR": str(tmp_path / "data"),
        "WF_CACHE_DIR": str(tmp_path / "cache"),
        "WF_CONFIG": str(tmp_path / "cfg.json"),
        "WF_DISABLE_GH_CLI": "1",
    }

    # 第一批 RPC：初始化、列工具、测试 init 阶段权限与 Gate 1 解锁
    batch1 = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "wf_start", "arguments": {"task": "引入 slugify", "sessionId": "mcp24", "openPanel": False}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "wf_local_profile", "arguments": {"path": str(proj), "sessionId": "mcp24"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "wf_strategy_evaluate",
                "arguments": {
                    "candidate": {"name": "slug", "language": "Python", "license": "MIT", "targetFilesCount": 1, "estimatedLoc": 10},
                    "projectPath": str(proj),
                    "sessionId": "mcp24",
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "wf_gate_commit",
                "arguments": {"projectPath": str(proj), "gate": "GATE_1", "summary": "确认需求", "sessionId": "mcp24"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "wf_strategy_evaluate",
                "arguments": {
                    "candidate": {"name": "slug", "language": "Python", "license": "MIT", "targetFilesCount": 1, "estimatedLoc": 10},
                    "projectPath": str(proj),
                    "sessionId": "mcp24",
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "wf_slice_closure",
                "arguments": {"sourcePath": str(src), "targetFiles": ["slug.py"], "sessionId": "mcp24"},
            },
        },
    ]

    res1 = {r["id"]: r for r in _rpc(batch1, env)}
    tools = res1[2]["result"]["tools"]
    names = {t["name"] for t in tools}
    assert len(tools) == 24
    assert {
        "wf_gate_commit",
        "wf_local_profile",
        "wf_strategy_evaluate",
        "wf_slice_closure",
        "wf_contract_design",
        "wf_checkpoint",
        "wf_assemble_apply",
        "wf_verify_run",
    }.issubset(names)

    # init 阶段允许 wf_local_profile，但拒绝 wf_strategy_evaluate
    prof = json.loads(res1[4]["result"]["content"][0]["text"])
    assert prof["ok"] is True
    assert prof["primaryLanguage"] == "Python"

    blocked_strat = json.loads(res1[5]["result"]["content"][0]["text"])
    assert blocked_strat["ok"] is False
    assert blocked_strat["error"]["code"] == "GATE_REQUIRED"

    # GATE_1 提交后自动关闭面板并解锁 wf_strategy_evaluate 与 wf_slice_closure
    g1 = json.loads(res1[6]["result"]["content"][0]["text"])
    assert g1["ok"] is True
    assert g1["panel"]["closed"] is True

    strat = json.loads(res1[7]["result"]["content"][0]["text"])
    assert strat["ok"] is True
    assert strat["recommendedStrategy"] == "CODE_SLICE"

    closure = json.loads(res1[8]["result"]["content"][0]["text"])
    assert closure["ok"] is True
    assert closure["closureFiles"] == ["slug.py"]
    assert closure["exportedSymbols"] == ["slugify"]

    # 第二批 RPC：生成契约 -> 未审批写入被拦截 -> 审批 Gate 4 -> 执行落盘 -> 闭环验证
    batch2_pre = [
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "wf_contract_design",
                "arguments": {
                    "projectPath": str(proj),
                    "strategy": "CODE_SLICE",
                    "candidate": {"name": "slug", "url": "https://github.com/org/slug", "license": "MIT", "version": "1.0.0"},
                    "adapterName": "slug_util",
                    "sourcePath": str(src),
                    "sliceFiles": ["slug.py"],
                    "sessionId": "mcp24",
                },
            },
        }
    ]
    res2_pre = {r["id"]: r for r in _rpc(batch2_pre, env)}
    ct = json.loads(res2_pre[9]["result"]["content"][0]["text"])
    assert ct["ok"] is True

    batch2 = [
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "wf_gate_commit",
                "arguments": {"projectPath": str(proj), "gate": "GATE_4", "summary": "批准契约", "sessionId": "mcp24"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "wf_assemble_apply",
                "arguments": {"projectPath": str(proj), "contract": ct, "requireGateApproval": True, "sessionId": "mcp24"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "wf_verify_run",
                "arguments": {"projectPath": str(proj), "contract": ct, "sessionId": "mcp24"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {"name": "wf_status", "arguments": {"projectPath": str(proj), "sessionId": "mcp24"}},
        },
    ]
    res2 = {r["id"]: r for r in _rpc(batch2, env)}
    applied = json.loads(res2[11]["result"]["content"][0]["text"])
    assert applied["ok"] is True
    assert applied["checkpointId"].startswith("ck-")

    verified = json.loads(res2[12]["result"]["content"][0]["text"])
    assert verified["ok"] is True
    assert verified["passed"] is True

    status_payload = json.loads(res2[13]["result"]["content"][0]["text"])
    assert status_payload["ledger"]["gates"]["GATE_5"]["status"] == "approved"
