import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_wf_run():
    path = ROOT / "tools" / "wf-run.py"
    spec = importlib.util.spec_from_file_location("wf_run_secret_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wf_run = load_wf_run()


def test_env_secret_never_enters_run_files(tmp_path, monkeypatch):
    secret = "TEST_SECRET_VALUE_123456"
    monkeypatch.setenv("TAVILY_API_KEY", secret)
    monkeypatch.setenv("EXA_API_KEY", secret)

    # 用假 dispatch 跑完整账本链路；真实适配器不会把密钥写进账本。
    def fake_dispatch(slot, action, payload, run_id=None):
        from tools.mocks import gates as real_gates
        from tools.mocks import ledger as real_ledger

        if slot == "render_prompt":
            return {"ok": True, "data": {"ok": True}, "meta": {"ms": 1}}
        if slot == "web_search":
            return {
                "ok": True,
                "data": {"results": [{"title": "t", "url": "https://example.com", "snippet": "s"}]},
                "degradation": [],
                "meta": {"ms": 1},
            }
        if slot == "web_extract":
            return {
                "ok": True,
                "data": {"text": "body", "metadata": {"publishedTime": "2026-10-01"}},
                "degradation": [],
                "meta": {"ms": 1},
            }
        if slot == "gates":
            return {"ok": True, "data": real_gates.check(payload), "meta": {"ms": 1}}
        if slot == "ledger":
            return {"ok": True, "data": real_ledger.handle(action, payload), "meta": {"ms": 1}}
        raise AssertionError(slot)

    monkeypatch.setattr(wf_run.wf_tool, "dispatch", fake_dispatch)
    result = wf_run.run_pipeline(
        task="x",
        run_dir=tmp_path / ".wf" / "runs" / "r1",
        cwd=tmp_path,
    )
    run_dir = Path(result["runDir"])
    for name in ["run.json", "evidence.json", "result.md"]:
        text = (run_dir / name).read_text(encoding="utf-8")
        assert secret not in text
