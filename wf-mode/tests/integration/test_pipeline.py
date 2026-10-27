import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_wf_run():
    path = ROOT / "tools" / "wf-run.py"
    spec = importlib.util.spec_from_file_location("wf_run_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wf_run = load_wf_run()


def fake_dispatch_factory(*, gate_ok: bool = True, with_results: bool = True):
    from tools.mocks import gates as real_gates
    from tools.mocks import ledger as real_ledger

    def fake_dispatch(slot, action, payload, run_id=None):
        if slot == "render_prompt" and action == "check":
            return {"ok": True, "data": {"ok": True, "missing": [], "empty": [], "blocks": []}}
        if slot == "web_search" and action == "search":
            results = []
            if with_results:
                results = [
                    {
                        "title": "SearXNG",
                        "url": "https://example.com/searxng",
                        "snippet": "snippet",
                    }
                ]
            return {
                "ok": True,
                "slot": slot,
                "action": action,
                "adapter": "tavily",
                "data": {"query": payload.get("query"), "results": results},
                "error": None,
                "degradation": [],
                "meta": {"ms": 1},
            }
        if slot == "web_extract" and action == "extract":
            return {
                "ok": True,
                "slot": slot,
                "action": action,
                "adapter": "jina",
                "data": {
                    "url": payload.get("url"),
                    "title": "SearXNG",
                    "text": "SearXNG 是一个元搜索引擎。",
                    "metadata": {"provider": "jina", "fetchedAt": "x", "publishedTime": "2026-10-01"},
                },
                "error": None,
                "degradation": [],
                "meta": {"ms": 1},
            }
        if slot == "gates" and action == "check":
            if gate_ok:
                data = real_gates.check(payload)
            else:
                data = {
                    "ok": False,
                    "errors": [
                        {
                            "gate": "evidence",
                            "code": "GATE_SOURCE_MISSING",
                            "message": "人为注入的 gate 失败",
                            "itemId": "E1",
                        }
                    ],
                }
            return {"ok": True, "data": data, "error": None, "degradation": [], "meta": {"ms": 1}}
        if slot == "ledger" and action == "commit":
            return {
                "ok": True,
                "data": real_ledger.handle(action, payload),
                "error": None,
                "degradation": [],
                "meta": {"ms": 1},
            }
        raise AssertionError(f"unexpected dispatch: {slot}/{action}")

    return fake_dispatch


def test_pipeline_end_to_end_with_fake_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(wf_run.wf_tool, "dispatch", fake_dispatch_factory())
    result = wf_run.run_pipeline(
        task="SearXNG",
        run_dir=tmp_path / ".wf" / "runs" / "r1",
        cwd=tmp_path,
    )
    assert result["status"] == "complete"
    run_dir = tmp_path / ".wf" / "runs" / "r1"
    assert (run_dir / "run.json").is_file()
    assert (run_dir / "evidence.json").is_file()
    assert "证据表" in (run_dir / "result.md").read_text(encoding="utf-8")


def test_pipeline_gate_rejection_blocks_conclusion(tmp_path, monkeypatch):
    monkeypatch.setattr(wf_run.wf_tool, "dispatch", fake_dispatch_factory(gate_ok=False))
    result = wf_run.run_pipeline(
        task="SearXNG",
        run_dir=tmp_path / ".wf" / "runs" / "r2",
        cwd=tmp_path,
    )
    assert result["status"] == "blocked"
    assert "被 gates 拒绝" in result["result"]
    assert "证据表" not in result["result"]


def test_pipeline_without_results_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(wf_run.wf_tool, "dispatch", fake_dispatch_factory(with_results=False))
    result = wf_run.run_pipeline(
        task="SearXNG",
        run_dir=tmp_path / ".wf" / "runs" / "r3",
        cwd=tmp_path,
    )
    assert result["status"] == "blocked"
