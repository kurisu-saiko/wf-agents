import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def fake_streamlit(tmp_path, monkeypatch):
    """让 _panel_ensure 找到假的 streamlit，避免依赖本机 venv。"""
    fake = tmp_path / "streamlit.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        shutil, "which", lambda name: str(fake) if name == "streamlit" else None
    )


def load_wf_tool():
    path = ROOT / "tools" / "wf-tool.py"
    spec = importlib.util.spec_from_file_location("wf_tool_panel_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProc:
    pid = 4242

    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True


def test_ensure_returns_existing_panel_without_spawning(tmp_path, monkeypatch):
    wf = load_wf_tool()
    lock = tmp_path / "panel.lock.json"
    lock.write_text(json.dumps({"port": 8765, "url": "http://127.0.0.1:8765"}), encoding="utf-8")
    monkeypatch.setattr(wf, "PANEL_LOCK", lock)
    monkeypatch.setattr(wf, "_panel_health", lambda port, timeout=0.8: True)
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    opened = []
    monkeypatch.setattr(wf, "_open_panel", lambda url: opened.append(url) or True)

    result = wf._panel_ensure()
    assert result["already_running"] is True
    assert result["port"] == 8765
    assert result["opened"] is True
    assert opened == ["http://127.0.0.1:8765"]


def test_ensure_starts_once_and_writes_lock(tmp_path, monkeypatch):
    wf = load_wf_tool()
    monkeypatch.setattr(wf, "PANEL_LOCK", tmp_path / "panel.lock.json")
    monkeypatch.setattr(wf, "PANEL_LOG", tmp_path / "panel.log")
    monkeypatch.setattr(wf, "_free_port", lambda preferred: 8765)
    calls = {"health": 0}

    def health(port, timeout=0.8):
        calls["health"] += 1
        return calls["health"] > 1

    monkeypatch.setattr(wf, "_panel_health", health)
    proc = FakeProc()
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *a, **k: proc)
    opened = []
    monkeypatch.setattr(wf, "_open_panel", lambda url: opened.append(url) or True)

    result = wf._panel_ensure()
    assert result["started"] is True
    assert result["pid"] == 4242
    assert result["opened"] is True
    assert opened == ["http://127.0.0.1:8765"]
    saved = json.loads((tmp_path / "panel.lock.json").read_text(encoding="utf-8"))
    assert saved["port"] == 8765


def test_ensure_degrades_when_spawn_fails(tmp_path, monkeypatch):
    wf = load_wf_tool()
    monkeypatch.setattr(wf, "PANEL_LOCK", tmp_path / "panel.lock.json")
    monkeypatch.setattr(wf, "PANEL_LOG", tmp_path / "panel.log")
    monkeypatch.setattr(wf, "_free_port", lambda preferred: 8765)
    monkeypatch.setattr(wf, "_panel_health", lambda port, timeout=0.8: False)
    monkeypatch.setattr(
        wf.subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("spawn failed")),
    )

    result = wf._panel_ensure()
    assert result["degraded"] is True
    assert result["started"] is False
    assert "启动面板失败" in result["reason"]


def test_ensure_degrades_when_panel_never_ready(tmp_path, monkeypatch):
    wf = load_wf_tool()
    monkeypatch.setattr(wf, "PANEL_LOCK", tmp_path / "panel.lock.json")
    monkeypatch.setattr(wf, "PANEL_LOG", tmp_path / "panel.log")
    monkeypatch.setattr(wf, "_free_port", lambda preferred: 8765)
    monkeypatch.setattr(wf, "_panel_health", lambda port, timeout=0.8: False)
    clock = iter([0.0, 99.0])
    monkeypatch.setattr(wf.time, "time", lambda: next(clock, 99.0))
    proc = FakeProc()
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *a, **k: proc)

    result = wf._panel_ensure()
    assert result["degraded"] is True
    assert result["started"] is False
    assert proc.terminated is True
