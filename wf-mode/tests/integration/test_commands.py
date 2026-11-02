import re
from pathlib import Path

from host import install
from panel import gates

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ROOT / "commands"


def split_frontmatter(text: str) -> str:
    match = re.match(r"^---\n(.*?)\n---", text, re.S)
    assert match, "缺少 frontmatter"
    return match.group(1)


def read(name: str) -> tuple[str, str]:
    text = (COMMANDS / name).read_text(encoding="utf-8")
    return split_frontmatter(text), text


def test_three_stage_commands_exist():
    for name in ("wf.md", "wf-plan.md", "wf-report.md"):
        assert (COMMANDS / name).is_file()
    assert install.ENTRY_FILES == ("wf.md", "wf-plan.md", "wf-report.md")


def test_stage_one_has_no_research_tools():
    frontmatter, body = read("wf.md")
    assert "wf_stage.py\" calibrate" in frontmatter
    assert "wf-tool.py" not in frontmatter
    assert "mcp__" not in frontmatter
    assert "research" not in frontmatter
    assert "/wf-plan" in body


def test_stage_two_has_research_but_no_write():
    frontmatter, body = read("wf-plan.md")
    assert "wf_stage.py\" research" in frontmatter
    assert "mcp__plugin_office-github_service__search_repositories" in frontmatter
    for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        assert tool not in frontmatter
    assert "/wf-report" in body


def test_report_stage_is_text_only():
    frontmatter, body = read("wf-report.md")
    assert "allowed-tools: Read" in frontmatter
    assert "Bash" not in frontmatter
    assert "mcp__" not in frontmatter
    assert "未写入任何文件" in body


def test_gate_rules_cover_both_stages():
    assert len(gates.GATES) == 2
    ids = {gate["id"] for gate in gates.GATES}
    assert ids == {"gate-1", "gate-2"}
    assert gates.REQUIRED_CAPABILITIES["gate-1"] == []
    assert "web_search" in gates.REQUIRED_CAPABILITIES["gate-2"]


def test_panel_does_not_display_gates():
    text = (ROOT / "panel" / "app.py").read_text(encoding="utf-8")
    assert "GATES" not in text
    assert "render_gate" not in text
    assert '"闸口"' not in text
