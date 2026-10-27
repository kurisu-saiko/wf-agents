import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_wf_tool():
    path = ROOT / "tools" / "wf-tool.py"
    spec = importlib.util.spec_from_file_location("wf_tool_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wf_tool = load_wf_tool()


def test_list_contains_phase1_slots():
    data = wf_tool.list_slots()
    for slot in ["web_search", "web_extract", "project_search", "ledger"]:
        assert slot in data["slots"]
    assert data["slots"]["web_search"]["primary"] == "tavily"
    assert data["slots"]["web_search"]["alternate"] == "exa"


def test_unknown_slot_returns_envelope_error():
    env = wf_tool.dispatch("nope", "search", {})
    assert env["ok"] is False
    assert env["error"]["code"] == "UNKNOWN_SLOT"


def test_unknown_action_is_rejected():
    env = wf_tool.dispatch("web_search", "nope", {})
    assert env["ok"] is False
    assert env["error"]["code"] == "UNKNOWN_ACTION"


def test_missing_keys_do_not_silently_return_empty(monkeypatch):
    for name in ("TAVILY_API_KEY", "TAVILY", "EXA_API_KEY", "EXA"):
        monkeypatch.delenv(name, raising=False)
    env = wf_tool.dispatch("web_search", "search", {"query": "searxng"})
    assert env["ok"] is False
    assert env["error"]["code"] in {"AUTH_MISSING", "FALLBACK_EXHAUSTED"}
    assert env["degradation"], "主备切换应写入 degradation"


def test_ledger_commit_writes_three_files(tmp_path):
    run_dir = tmp_path / ".wf" / "runs" / "r1"
    run = {
        "pipeline": "wf-retrieval",
        "status": "complete",
        "degradation": [],
        "startedAt": "2026-10-27T00:00:00Z",
        "finishedAt": "2026-10-27T00:00:05Z",
    }
    evidence = {"pipeline": "wf-retrieval", "items": [], "limitations": [], "gaps": []}
    env = wf_tool.dispatch(
        "ledger",
        "commit",
        {
            "run_dir": str(run_dir),
            "cwd": str(tmp_path),
            "run": run,
            "evidence": evidence,
            "result": "# result",
        },
    )
    assert env["ok"] is True, env
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "evidence.json").is_file()
    assert (run_dir / "result.md").read_text(encoding="utf-8").strip() == "# result"


def test_ledger_rejects_path_outside_runs(tmp_path):
    env = wf_tool.dispatch(
        "ledger",
        "commit",
        {
            "run_dir": str(tmp_path / "outside"),
            "cwd": str(tmp_path),
            "run": {},
            "evidence": {},
            "result": "x",
        },
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "LEDGER_INVALID"


def test_gates_reject_verified_without_source():
    run = {
        "pipeline": "wf-retrieval",
        "status": "complete",
        "degradation": [],
        "startedAt": "x",
        "finishedAt": "y",
    }
    evidence = {
        "pipeline": "wf-retrieval",
        "items": [
            {
                "id": "E1",
                "statement": "没有来源",
                "status": "verified",
                "sources": [],
                "note": "",
            }
        ],
        "limitations": [],
        "gaps": [],
    }
    env = wf_tool.dispatch("gates", "check", {"run": run, "evidence": evidence, "names": ["evidence"]})
    assert env["ok"] is True
    assert env["data"]["ok"] is False
    assert any(e["code"] == "GATE_SOURCE_MISSING" for e in env["data"]["errors"])


def test_render_prompt_check_actual_blocks():
    env = wf_tool.dispatch(
        "render_prompt",
        "check",
        {
            "blocks": [
                "core.md",
                "domain/retrieval.md",
                "output/retrieval.md",
                "tools/web_search.md",
                "tools/web_extract.md",
            ],
            "root": str(ROOT / "prompt-blocks"),
        },
    )
    assert env["ok"] is True
    assert env["data"]["ok"] is True, env["data"]
