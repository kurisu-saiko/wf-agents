import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "wf_agent_gate.py"
TOOL = ROOT / "tools" / "wf-tool.py"
STAGE = ROOT / "tools" / "wf_stage.py"


def decide_claude(tool_name: str, command: str | None = None) -> str:
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


def decide_antigravity(tool_name: str, command: str | None = None) -> str:
    payload = {
        "hookEventName": "PreToolUse",
        "cwd": str(ROOT),
        "toolCall": {"name": tool_name, "args": {"CommandLine": command} if command else {}},
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(proc.stdout)
    return result["decision"]


def test_allows_registered_capability():
    assert decide_claude("Bash", f'python "{TOOL}" call project_search search --query "x"') == "allow"
    assert decide_claude("Bash", f'python "{TOOL}" call package_security scan --path .') == "allow"
    assert decide_antigravity("run_command", f'python "{STAGE}" enter-plan') == "allow"
    assert decide_antigravity("run_command", f'python "{STAGE}" research repo_health analyze --repo a/b') == "allow"


def test_allows_read_only_commands():
    assert decide_claude("Bash", f'python "{TOOL}" list') == "allow"
    assert decide_claude("Bash", f'python "{TOOL}" doctor') == "allow"


def test_allows_only_valid_panel_modes():
    assert decide_claude("Bash", f'python "{TOOL}" panel --ensure') == "allow"
    assert decide_claude("Bash", f'python "{TOOL}" panel --ensure --once') == "allow"
    assert decide_claude("Bash", f'python "{TOOL}" panel --status') == "allow"
    assert decide_claude("Bash", f'python "{TOOL}" panel --close') == "allow"
    assert decide_claude("Bash", f'python "{TOOL}" panel') == "deny"


def test_denies_arbitrary_commands():
    assert decide_claude("Bash", "curl https://example.com") == "deny"
    assert decide_claude("Bash", "git status") == "deny"
    assert decide_antigravity("run_command", "rm -rf /tmp/x") == "deny"


def test_denies_write_tools():
    assert decide_claude("Write") == "deny"
    assert decide_claude("Edit") == "deny"
    assert decide_antigravity("write_file") == "deny"
    assert decide_antigravity("edit_file") == "deny"


def test_denies_pending_capability():
    assert decide_claude("Bash", f'python "{TOOL}" call code_graph query --path .') == "deny"


def test_denies_write_capability_in_plan_mode():
    assert (
        decide_claude("Bash", f'python "{TOOL}" call scaffold render --template x --destination y')
        == "deny"
    )


def test_denies_shell_operators_and_path_traversal():
    assert decide_claude("Bash", f'python "{TOOL}" list; whoami') == "deny"
    assert decide_claude("Bash", f'python "{TOOL}" call dependency_graph analyze --path ../secret') == "deny"
    # 查询内容中的 .. 不应被误杀
    assert decide_claude("Bash", f'python "{TOOL}" call structural_search search --pattern "a..b" --path .') == "allow"
