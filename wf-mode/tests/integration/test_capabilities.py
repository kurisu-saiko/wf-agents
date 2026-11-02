import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def load_wf_tool():
    path = ROOT / "tools" / "wf-tool.py"
    spec = importlib.util.spec_from_file_location("wf_tool_capability_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wf = load_wf_tool()


def test_catalog_has_16_capabilities():
    data = wf.list_capabilities()
    caps = data["capabilities"]
    assert len(caps) == 16
    assert caps["web_search"]["kind"] == "adapter"
    assert caps["repo_ingest"]["kind"] == "cli"
    assert caps["package_meta"]["kind"] == "mcp"
    assert caps["code_graph"]["status"] == "pending"
    assert caps["package_security"]["status"] == "pending"
    assert caps["license_sbom"]["status"] == "pending"


def test_health_reports_pending_and_active():
    data = wf.health()
    assert "capabilities" in data
    assert "code_graph" in data["pending"]
    assert data["capabilities"]["web_search"]["status"] in {"active", "degraded", "missing"}


def test_doctor_reports_runtime_and_hosts(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"version": 1, "runtime": {"bin": str(tmp_path), "venv": ""}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WF_CONFIG", str(config))
    data = wf.doctor()
    assert "runtime" in data
    assert data["runtime"]["binExists"] is True
    assert set(data["hosts"]) == {"haha", "claude", "dsh"}


def test_pending_capability_is_rejected():
    envelope = wf.dispatch("code_graph", "query", {"path": "."})
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "CAPABILITY_PENDING"


def test_unknown_capability_is_rejected():
    envelope = wf.dispatch("not_a_capability", "run", {})
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "UNKNOWN_CAPABILITY"


def test_unknown_action_is_rejected():
    envelope = wf.dispatch("web_search", "delete", {"query": "x"})
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "UNKNOWN_ACTION"
