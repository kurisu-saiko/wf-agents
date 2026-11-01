import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "wf_agent_gate.py"
TOOL = ROOT / "tools" / "wf-tool.py"


def decide(tool_name: str, command: str | None = None) -> str:
    payload = {"agent_type": "wf-agent", "cwd": str(ROOT), "tool_name": tool_name}
    if command is not None:
        payload["tool_input"] = {"command": command}
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(proc.stdout)
    return result["hookSpecificOutput"]["permissionDecision"]


def test_allows_registered_capability():
    assert decide("Bash", f'python "{TOOL}" call project_search search --query "x"') == "allow"


def test_allows_read_only_commands():
    assert decide("Bash", f'python "{TOOL}" list') == "allow"
    assert decide("Bash", f'python "{TOOL}" doctor') == "allow"


def test_denies_arbitrary_commands():
    assert decide("Bash", "curl https://example.com") == "deny"
    assert decide("Bash", "git status") == "deny"


def test_denies_write_tools():
    assert decide("Write") == "deny"
    assert decide("Edit") == "deny"


def test_denies_pending_capability():
    assert decide("Bash", f'python "{TOOL}" call code_graph query --path .') == "deny"


def test_denies_write_capability_in_plan_mode():
    assert (
        decide("Bash", f'python "{TOOL}" call scaffold render --template x --destination y')
        == "deny"
    )


def test_denies_shell_operators():
    assert decide("Bash", f'python "{TOOL}" list; whoami') == "deny"
