import json
from pathlib import Path

from host import install

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent

ALLOWED_ANTIGRAVITY_PLUGIN_KEYS = {
    "name",
    "displayName",
    "version",
    "description",
    "logo",
    "suggestedPrompts",
    "author",
    "homepage",
    "repository",
    "disabled",
}


def test_root_antigravity_plugin_manifest_schema():
    data = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
    assert set(data.keys()).issubset(ALLOWED_ANTIGRAVITY_PLUGIN_KEYS)
    assert data["name"] == "wf-agents"
    assert (REPO_ROOT / data["logo"]).is_file()
    assert len(data["suggestedPrompts"]) == 3


def test_install_antigravity_apply(tmp_path):
    target = tmp_path / "wf-agents"
    rc = install.main(["--host", "antigravity", "--target", str(target), "--apply"])
    assert rc == 0
    assert (target / "plugin.json").is_file()
    assert (target / "assets" / "logo.svg").is_file()
    assert (target / "rules" / "AGENTS.md").is_file()
    assert (target / "agents" / "wf-researcher.md").is_file()
    assert (target / "skills" / "wf" / "SKILL.md").is_file()
    assert (target / "skills" / "wf-plan" / "SKILL.md").is_file()
    assert (target / "skills" / "wf-report" / "SKILL.md").is_file()
    assert (target / "wf-mode" / "tools" / "wf_mcp.py").is_file()
    assert not (target / "wf-mode" / ".venv").exists()
    assert not (target / "wf-mode" / "tests").exists()

    mcp_cfg = json.loads((target / "mcp_config.json").read_text(encoding="utf-8"))
    srv = mcp_cfg["mcpServers"]["wf-agents"]
    assert srv["args"][0].endswith("wf-mode/tools/wf_mcp.py")
    assert srv["env"]["WF_ROOT"].endswith("wf-mode")


def test_install_other_hosts_apply(tmp_path):
    for host in ("cursor", "codex", "gemini", "opencode", "generic", "claude"):
        target = tmp_path / host
        rc = install.main(["--host", host, "--target", str(target), "--apply"])
        assert rc == 0

    assert (tmp_path / "cursor" / "mcp.json").is_file()
    assert (tmp_path / "cursor" / "skills" / "wf" / "SKILL.md").is_file()
    assert (tmp_path / "codex" / "wf-agents" / "codex-mcp.toml").is_file()
    assert (tmp_path / "gemini" / "gemini-extension.json").is_file()
    assert (tmp_path / "opencode" / "wf-agents" / "opencode-mcp.json").is_file()
    assert (tmp_path / "generic" / "mcp_config.json").is_file()
    assert (tmp_path / "claude" / "commands" / "wf.md").is_file()
