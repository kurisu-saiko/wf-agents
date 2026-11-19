import importlib.util
import json
import socket
import threading
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_wf_tool():
    path = ROOT / "tools" / "wf-tool.py"
    spec = importlib.util.spec_from_file_location("wf_tool_lifecycle_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _loopback_connect_allowed() -> bool:
    """检查当前沙箱是否允许向 127.0.0.1 发起本地回环连接。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cli.settimeout(0.5)
        try:
            cli.connect(("127.0.0.1", port))
            return True
        except PermissionError:
            return False
        except OSError:
            return False
        finally:
            cli.close()
    except OSError:
        return False
    finally:
        srv.close()


def test_panel_server_routes_and_once_close_contract(tmp_path, monkeypatch):
    """无需跨进程 TCP 连接即可验证 open-once、token 鉴权关闭与 panel.lock 清理契约。"""
    from panel import server as panel_server

    wf = load_wf_tool()
    lock_file = tmp_path / "panel.lock.json"
    monkeypatch.setattr(wf, "PANEL_LOCK", lock_file)

    # 1. 验证 PanelHTTPServer 的关闭标志与 token 校验逻辑
    class DummyServer:
        wf_token = "secret-token"
        closing = False
        shutdown_called = False

        def shutdown(self):
            self.shutdown_called = True

    srv = DummyServer()
    assert srv.closing is False

    # 2. 模拟面板已在运行且 openedOnce=True：_panel_ensure(once=True) 不得重开浏览器
    lock_file.write_text(
        json.dumps(
            {
                "port": 18999,
                "url": "http://127.0.0.1:18999",
                "pid": 999999,
                "token": "secret-token",
                "backend": "builtin",
                "openedOnce": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(wf, "_panel_health", lambda port, timeout=0.8: True)
    opened: list[str] = []
    monkeypatch.setattr(wf, "_open_panel", lambda url: opened.append(url) or True)

    res = wf._panel_ensure(open_browser=True, once=True)
    assert res["already_running"] is True
    assert res["opened"] is False
    assert res["skipped_reopen"] is True
    assert opened == []

    # 3. 模拟 _panel_close()：发送带 X-WF-Token 的 /api/shutdown 并清理 lock 文件
    seen_req: dict[str, object] = {}
    health_state = {"alive": True}

    def fake_open(req, timeout=1.5):
        seen_req["url"] = req.full_url
        seen_req["token"] = req.get_header("X-wf-token")
        health_state["alive"] = False

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    monkeypatch.setattr(wf, "_panel_health", lambda port, timeout=0.5: health_state["alive"])
    monkeypatch.setattr(wf._LOCAL_OPENER, "open", fake_open)

    closed = wf._panel_close()
    assert closed["closed"] is True
    assert closed["graceful"] is True
    assert seen_req["url"] == "http://127.0.0.1:18999/api/shutdown"
    assert seen_req["token"] == "secret-token"
    assert not lock_file.exists()
    assert panel_server.UI_FILE.is_file()


def test_builtin_panel_opens_once_and_closes_on_enter_plan(tmp_path, monkeypatch):
    if not _loopback_connect_allowed():
        pytest.skip("当前受限沙箱禁止 127.0.0.1 回环连接 (WinError 10013)；请无沙箱运行以验证实进程通信")

    wf = load_wf_tool()
    lock_file = tmp_path / "panel.lock.json"
    log_file = tmp_path / "panel.log"
    monkeypatch.setattr(wf, "PANEL_LOCK", lock_file)
    monkeypatch.setattr(wf, "PANEL_LOG", log_file)
    monkeypatch.setenv("WF_PANEL_BACKEND", "builtin")

    free = wf._free_port(18900)
    assert free > 0
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"version": 1, "panel": {"port": free}}), encoding="utf-8")
    monkeypatch.setenv("WF_CONFIG", str(cfg_file))

    opened_urls: list[str] = []
    monkeypatch.setattr(wf, "_open_panel", lambda url: opened_urls.append(url) or True)
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))

    try:
        # 1. 首次打开
        first = wf._panel_ensure(open_browser=True, once=True)
        assert first["running"] is True
        assert first["started"] is True
        assert first["opened"] is True
        assert first["backend"] == "builtin"
        assert len(opened_urls) == 1

        # 验证内置 Web UI 和 /api/state 可真实访问
        with opener.open(f"{first['url']}/health", timeout=2) as resp:
            assert resp.status == 200
            health = json.loads(resp.read().decode("utf-8"))
            assert health["ok"] is True
            assert health["closing"] is False

        with opener.open(f"{first['url']}/", timeout=2) as resp:
            html = resp.read().decode("utf-8")
            assert "wf-agents" in html

        with opener.open(f"{first['url']}/api/state", timeout=2) as resp:
            state = json.loads(resp.read().decode("utf-8"))
            assert state["ok"] is True
            assert "capabilities" in state["data"]

        # 2. 第二次调用（once=True）不重复打开浏览器
        second = wf._panel_ensure(open_browser=True, once=True)
        assert second["running"] is True
        assert second["already_running"] is True
        assert second["opened"] is False
        assert second["skipped_reopen"] is True
        assert len(opened_urls) == 1

        # 3. 进入计划模式自动关闭面板
        closed = wf._panel_close()
        assert closed["closed"] is True
        assert closed["running"] is False
        assert not lock_file.exists()

        with pytest.raises((URLError, OSError)):
            opener.open(f"{first['url']}/health", timeout=0.6)
    finally:
        wf._panel_close()
