import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "commands" / "wf.md"
AGENT = ROOT / "agent" / "wf-agent.md"


def split_frontmatter(text: str) -> tuple[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    assert match, "缺少 YAML frontmatter"
    return match.group(1), match.group(2)


def test_commands_declare_two_human_gates():
    frontmatter, body = split_frontmatter(COMMAND.read_text(encoding="utf-8"))
    assert "AskUserQuestion" in frontmatter
    assert "需求确认" in body
    assert "需求理解" in body
    assert "/wf-plan" in body

    plan_frontmatter, plan_body = split_frontmatter(
        (ROOT / "commands" / "wf-plan.md").read_text(encoding="utf-8")
    )
    assert "AskUserQuestion" in plan_frontmatter
    assert "方案确认" in plan_body
    assert "需求对照表" in plan_body
    assert "/wf-report" in plan_body


def test_command_stays_read_only():
    text = COMMAND.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)

    for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        assert tool not in frontmatter
    assert "把脚本输出原样返回" not in body
    assert "不写文件" in body


def test_agent_body_is_not_empty_and_has_no_single_shot_rule():
    text = AGENT.read_text(encoding="utf-8")
    _, body = split_frontmatter(text)

    assert body.strip(), "agent 正文为空"
    assert "可选研究后端" in body
    assert "等待确认" not in body
    assert "一次运行 = 一次回复" not in body
    assert "研究结果包" in body
