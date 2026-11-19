import pytest

from tools import session as wf_session
from tools import wf_stage


def test_research_rejects_write_capability():
    with pytest.raises(wf_stage.StageError):
        wf_stage.research(["scaffold", "render"])


def test_research_rejects_pending_capability():
    with pytest.raises(wf_stage.StageError):
        wf_stage.research(["code_graph", "query"])


def test_research_rejects_unknown_action():
    with pytest.raises(wf_stage.StageError):
        wf_stage.research(["web_search", "delete"])


def test_research_allows_query_with_dots_but_rejects_path_traversal(monkeypatch):
    monkeypatch.setattr(wf_stage, "_run", lambda args: {"ok": True, "data": {}})
    monkeypatch.setattr(wf_stage, "_emit", lambda data, code=0: 0)
    assert wf_stage.research(["structural_search", "search", "--pattern", "a..b", "--path", "."]) == 0
    with pytest.raises(wf_stage.StageError):
        wf_stage.research(["structural_search", "search", "--pattern", "x", "--path", "../secret"])


def test_research_passes_allowed_call(monkeypatch):
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return {"ok": True, "data": {"results": []}}

    monkeypatch.setattr(wf_stage, "_run", fake_run)
    monkeypatch.setattr(wf_stage, "_emit", lambda data, code=0: 0)

    assert wf_stage.research(["web_search", "search", "--query", "x"]) == 0
    assert seen["args"] == ["call", "web_search", "search", "--query", "x"]


def test_calibrate_opens_panel_only_once_per_session(monkeypatch):
    calls = []
    responses = {
        ("health",): {
            "ok": True,
            "data": {
                "capabilities": {
                    "web_search": {"status": "active"},
                    "code_graph": {"status": "pending"},
                }
            },
        },
        ("doctor",): {"ok": True, "data": {"runtime": {}, "hosts": {}}},
        ("list",): {"ok": True, "data": {"capabilities": {}}},
        ("panel", "--ensure"): {"ok": True, "data": {"running": True, "opened": True}},
        ("panel", "--status"): {"ok": True, "data": {"running": True}},
    }

    def fake_run(args):
        calls.append(tuple(args))
        return responses[tuple(args)]

    monkeypatch.setattr(wf_stage, "_run", fake_run)
    captured = []
    monkeypatch.setattr(wf_stage, "_emit", lambda data, code=0: captured.append(data) or code)

    assert wf_stage.calibrate(session_id="once-check") == 0
    assert ("panel", "--ensure") in calls
    assert captured[-1]["capabilities"]["active"] == ["web_search"]
    assert captured[-1]["capabilities"]["pending"] == ["code_graph"]

    calls.clear()
    assert wf_stage.calibrate(session_id="once-check") == 0
    assert ("panel", "--ensure") not in calls
    assert ("panel", "--status") in calls
    assert captured[-1]["panel"]["opened"] is False
    assert captured[-1]["panel"]["skipped_reopen"] is True


def test_enter_plan_closes_panel_and_unlocks_stage(monkeypatch):
    seen = []

    def fake_run(args):
        seen.append(args)
        return {"ok": True, "data": {"running": False, "closed": True}}

    monkeypatch.setattr(wf_stage, "_run", fake_run)
    captured = {}
    monkeypatch.setattr(wf_stage, "_emit", lambda data, code=0: captured.update(data) or code)

    assert wf_stage.enter_plan(requirements="Must support Python 3.10+", session_id="plan-check") == 0
    assert seen == [["panel", "--close"]]
    assert captured["stage"] == "plan"
    state = wf_session.load_session("plan-check")
    assert state["stage"] == "plan"
    assert state["gate1Confirmed"] is True
    assert state["requirements"] == "Must support Python 3.10+"


def test_calibrate_rejects_extra_args(monkeypatch):
    monkeypatch.setattr(wf_stage, "_emit", lambda data, code=0: 1)
    assert wf_stage.main(["calibrate", "extra"]) == 1
