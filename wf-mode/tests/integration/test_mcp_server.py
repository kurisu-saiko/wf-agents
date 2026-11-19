import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCP = ROOT / "tools" / "wf_mcp.py"


def _rpc(lines: list[dict], env_extra: dict[str, str] | None = None) -> list[dict]:
    import os

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
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def test_mcp_handshake_gate_and_stage_transitions(tmp_path):
    env = {
        "WF_DATA_DIR": str(tmp_path / "data"),
        "WF_CACHE_DIR": str(tmp_path / "cache"),
        "WF_CONFIG": str(tmp_path / "cfg.json"),
        "WF_DISABLE_GH_CLI": "1",
    }
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "wf_start", "arguments": {"task": "评估 MCP", "sessionId": "s1", "openPanel": False}},
        },
        # init 阶段：允许本地分析，拦截外部搜索
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "wf_project_analyze", "arguments": {"path": str(ROOT / "tools")}},
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "wf_web_search", "arguments": {"query": "mcp", "sessionId": "s1"}},
        },
        # 进入计划模式：解锁调研 & 自动关闭面板
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "wf_enter_plan", "arguments": {"requirements": "Must work offline", "sessionId": "s1"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "wf_status", "arguments": {"sessionId": "s1"}},
        },
    ]

    responses = {item["id"]: item for item in _rpc(requests, env)}

    assert responses[1]["result"]["serverInfo"]["name"] == "wf-agents"
    tool_names = {t["name"] for t in responses[2]["result"]["tools"]}
    assert {"wf_start", "wf_enter_plan", "wf_enter_report", "wf_repo_health", "wf_package_security", "wf_project_analyze"}.issubset(tool_names)

    start_payload = json.loads(responses[3]["result"]["content"][0]["text"])
    assert start_payload["ok"] is True
    assert start_payload["session"]["stage"] == "init"

    local_payload = json.loads(responses[4]["result"]["content"][0]["text"])
    assert local_payload["ok"] is True
    assert "Python" in local_payload["data"]["languages"]

    blocked_payload = json.loads(responses[5]["result"]["content"][0]["text"])
    assert blocked_payload["ok"] is False
    assert blocked_payload["error"]["code"] == "GATE_REQUIRED"

    plan_payload = json.loads(responses[6]["result"]["content"][0]["text"])
    assert plan_payload["ok"] is True
    assert plan_payload["stage"] == "plan"
    assert plan_payload["panel"]["closed"] is True

    status_payload = json.loads(responses[7]["result"]["content"][0]["text"])
    assert status_payload["session"]["gate1Confirmed"] is True
    assert status_payload["session"]["requirements"] == "Must work offline"
