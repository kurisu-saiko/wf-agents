import pytest

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


def test_research_passes_allowed_call(monkeypatch):
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return {"ok": True, "data": {"results": []}}

    monkeypatch.setattr(wf_stage, "_run", fake_run)
    monkeypatch.setattr(wf_stage, "_emit", lambda data, code=0: 0)

    assert wf_stage.research(["web_search", "search", "--query", "x"]) == 0
    assert seen["args"] == ["call", "web_search", "search", "--query", "x"]


def test_calibrate_summarizes_buckets(monkeypatch):
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
        ("panel", "--ensure"): {"ok": True, "data": {"running": True}},
    }
    monkeypatch.setattr(wf_stage, "_run", lambda args: responses[tuple(args)])
    captured = {}

    def fake_emit(data, code=0):
        captured["data"] = data
        captured["code"] = code
        return code

    monkeypatch.setattr(wf_stage, "_emit", fake_emit)
    assert wf_stage.calibrate() == 0
    assert captured["data"]["capabilities"]["active"] == ["web_search"]
    assert captured["data"]["capabilities"]["pending"] == ["code_graph"]


def test_calibrate_rejects_extra_args(monkeypatch):
    monkeypatch.setattr(
        wf_stage,
        "_emit",
        lambda data, code=0: 1,
    )
    assert wf_stage.main(["calibrate", "extra"]) == 1
