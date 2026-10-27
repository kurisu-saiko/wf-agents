import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "workflow" / "hooks" / "wf_pipeline_gate.py"
WF_TOOL = ROOT / "tools" / "wf-tool.py"


def run_hook(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    data = json.loads(proc.stdout.decode("utf-8"))
    return data["hookSpecificOutput"]


def test_allows_wf_tool(tmp_path):
    out = run_hook(
        {
            "agent_type": "wf-retrieval",
            "tool_name": "Bash",
            "cwd": str(tmp_path),
            "tool_input": {
                "command": f'python "{WF_TOOL}" web_search search --query "searxng" --max-results 3'
            },
        }
    )
    assert out["permissionDecision"] == "allow"


def test_denies_curl(tmp_path):
    out = run_hook(
        {
            "agent_type": "wf-retrieval",
            "tool_name": "Bash",
            "cwd": str(tmp_path),
            "tool_input": {"command": "curl https://example.com"},
        }
    )
    assert out["permissionDecision"] == "deny"


def test_denies_git(tmp_path):
    out = run_hook(
        {
            "agent_type": "wf-retrieval",
            "tool_name": "Bash",
            "cwd": str(tmp_path),
            "tool_input": {"command": "git clone https://github.com/foo/bar"},
        }
    )
    assert out["permissionDecision"] == "deny"


def test_denies_shell_operator_after_wf_tool(tmp_path):
    out = run_hook(
        {
            "agent_type": "wf-retrieval",
            "tool_name": "Bash",
            "cwd": str(tmp_path),
            "tool_input": {
                "command": f'python "{WF_TOOL}" list; curl https://example.com'
            },
        }
    )
    assert out["permissionDecision"] == "deny"


def test_denies_write(tmp_path):
    out = run_hook(
        {
            "agent_type": "wf-retrieval",
            "tool_name": "Write",
            "cwd": str(tmp_path),
            "tool_input": {"file_path": str(tmp_path / ".wf" / "runs" / "r1" / "result.md")},
        }
    )
    assert out["permissionDecision"] == "deny"


def test_denies_wrong_wf_tool_path(tmp_path):
    out = run_hook(
        {
            "agent_type": "wf-retrieval",
            "tool_name": "Bash",
            "cwd": str(tmp_path),
            "tool_input": {"command": 'python "C:/tmp/evil/wf-tool.py" list'},
        }
    )
    assert out["permissionDecision"] == "deny"


def test_denies_unregistered_action(tmp_path):
    out = run_hook(
        {
            "agent_type": "wf-retrieval",
            "tool_name": "Bash",
            "cwd": str(tmp_path),
            "tool_input": {"command": f'python "{WF_TOOL}" web_search delete --query "x"'},
        }
    )
    assert out["permissionDecision"] == "deny"
