import json

from panel import service


def use_config(tmp_path, monkeypatch, data: dict):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("WF_CONFIG", str(path))
    return path


def test_probe_uses_real_search_call(monkeypatch):
    seen = {}

    def fake_run_tool(args):
        seen["args"] = args
        return {"ok": True, "data": {"results": []}}

    monkeypatch.setattr(service, "_run_tool", fake_run_tool)
    result = service.probe("web_search")
    assert result["ok"] is True
    assert seen["args"][:4] == ["call", "web_search", "search", "--query"]


def test_probe_cli_uses_health(monkeypatch):
    monkeypatch.setattr(
        service,
        "list_capabilities",
        lambda: {"capabilities": {"repo_ingest": {"kind": "cli", "primary": "gitingest"}}},
    )
    seen = {}
    monkeypatch.setattr(
        service,
        "_run_tool",
        lambda args: seen.update({"args": args}) or {"ok": True, "data": {}},
    )
    service.probe("repo_ingest")
    assert seen["args"] == ["health", "repo_ingest"]


def test_probe_mcp_reports_unavailable(monkeypatch):
    monkeypatch.setattr(
        service,
        "list_capabilities",
        lambda: {"capabilities": {"package_meta": {"kind": "mcp", "primary": "github-mcp"}}},
    )
    result = service.probe("package_meta")
    assert result["ok"] is True
    assert "MCP" in result["data"]["note"]


def test_masked_secrets_never_leak_plaintext(tmp_path, monkeypatch):
    use_config(
        tmp_path,
        monkeypatch,
        {"version": 1, "secrets": {"TAVILY_API_KEY": "super-secret-key"}},
    )
    masked = service.masked_secrets()
    assert masked["Tavily"]["source"] == "panel"
    assert masked["Tavily"]["present"] is True
    assert "super-secret-key" not in json.dumps(masked)
    assert masked["Tavily"]["masked"] == "••••-key"


def test_save_secret_updates_uses_canonical_name(tmp_path, monkeypatch):
    path = use_config(tmp_path, monkeypatch, {"version": 1, "secrets": {}})
    service.save_secret_updates({"Tavily": "new-key"}, set())
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["secrets"]["TAVILY_API_KEY"] == "new-key"


def test_save_provider_orders_rejects_unknown(tmp_path, monkeypatch):
    use_config(tmp_path, monkeypatch, {"version": 1})
    try:
        service.save_provider_orders({"web_search": ["nope"]})
    except ValueError as exc:
        assert "未登记" in str(exc)
    else:
        raise AssertionError("应当拒绝未登记 provider")
