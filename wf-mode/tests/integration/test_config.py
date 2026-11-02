import importlib.util
import json
from pathlib import Path

import pytest

from tools import config as wf_config
from tools.util import first_env

ROOT = Path(__file__).resolve().parents[2]


def load_wf_tool():
    path = ROOT / "tools" / "wf-tool.py"
    spec = importlib.util.spec_from_file_location("wf_tool_config_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wf_tool = load_wf_tool()


def write_config(tmp_path, monkeypatch, data: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("WF_CONFIG", str(path))
    return path


def test_panel_secret_wins_over_environment(tmp_path, monkeypatch):
    write_config(
        tmp_path,
        monkeypatch,
        {"version": 1, "secrets": {"TAVILY_API_KEY": "panel-key"}},
    )
    monkeypatch.setenv("TAVILY_API_KEY", "env-key")
    value, name = first_env("TAVILY_API_KEY", "TAVILY")
    assert value == "panel-key"
    assert name == "TAVILY_API_KEY"


def test_environment_is_fallback_when_panel_empty(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {"version": 1, "secrets": {}})
    monkeypatch.setenv("EXA", "env-key")
    value, name = first_env("EXA_API_KEY", "EXA")
    assert value == "env-key"
    assert name == "EXA"


def test_provider_order_is_merged_into_catalog(tmp_path, monkeypatch):
    write_config(
        tmp_path,
        monkeypatch,
        {"version": 1, "providers": {"web_search": ["exa", "tavily"]}},
    )
    entry = wf_tool.load_catalog()["capabilities"]["web_search"]
    assert entry["primary"] == "exa"
    assert entry["alternate"] == "tavily"
    assert entry["fallback"] == []


def test_cli_path_is_merged_into_catalog(tmp_path, monkeypatch):
    write_config(
        tmp_path,
        monkeypatch,
        {
            "version": 1,
            "cli_paths": {"repo_ingest": {"gitingest": "C:/fake/gitingest.exe"}},
        },
    )
    entry = wf_tool.load_catalog()["capabilities"]["repo_ingest"]
    assert entry["exec"]["gitingest"][0] == "C:/fake/gitingest.exe"


def test_invalid_provider_is_rejected(tmp_path, monkeypatch):
    write_config(
        tmp_path,
        monkeypatch,
        {"version": 1, "providers": {"web_search": ["not-a-provider"]}},
    )
    from tools.errors import ToolError

    with pytest.raises(ToolError):
        wf_tool.load_catalog()


def test_invalid_version_is_rejected(tmp_path, monkeypatch):
    path = write_config(tmp_path, monkeypatch, {"version": 2})
    with pytest.raises(wf_config.ConfigError):
        wf_config.load_config(path)


def test_redact_and_mask():
    assert wf_config.mask("abcdefgh") == "••••efgh"
    assert wf_config.mask("abc") == "••••"


def test_save_config_backs_up_and_replaces(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("WF_CONFIG", str(path))
    monkeypatch.setattr(wf_config, "BACKUP_DIR", tmp_path / "backups")
    wf_config.save_config({"version": 1, "secrets": {"TAVILY_API_KEY": "first"}})
    wf_config.save_config({"version": 1, "secrets": {"TAVILY_API_KEY": "second"}})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["secrets"]["TAVILY_API_KEY"] == "second"
    assert list((tmp_path / "backups").glob("config-*.json"))
