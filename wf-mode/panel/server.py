"""零依赖内置 HTTP 配置面板服务（仅绑定 127.0.0.1）。

支持毫秒级冷启动、状态检查与通过 token 安全关闭（用于进入计划模式时自动关闭面板）。
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for path in (HERE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import service  # noqa: E402

UI_FILE = HERE / "ui.html"


class PanelHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], token: str) -> None:
        self.wf_token = token
        self.closing = False
        super().__init__(server_address, PanelHandler)


class PanelHandler(BaseHTTPRequestHandler):
    server: PanelHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, code: int, payload: Any) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, code: int, html_text: str) -> None:
        raw = html_text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 1024 * 1024))
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ValueError("请求体不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _authorized(self) -> bool:
        expected = self.server.wf_token
        if not expected:
            return True
        provided = self.headers.get("X-WF-Token") or ""
        return secrets.compare_digest(provided, expected)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"/health", "/_stcore/health"}:
            self._send_json(
                200,
                {
                    "ok": True,
                    "closing": self.server.closing,
                    "pid": os.getpid(),
                },
            )
            return

        if path == "/":
            html_text = UI_FILE.read_text(encoding="utf-8").replace(
                "__WF_TOKEN_PLACEHOLDER__", self.server.wf_token
            )
            self._send_html(200, html_text)
            return

        if path == "/api/state":
            try:
                payload = {
                    "capabilities": service.list_capabilities(),
                    "doctor": service.doctor(),
                    "secrets": service.masked_secrets(),
                    "config": service.load_config(),
                    "disabled": service.load_state().get("disabled", []),
                    "session": service.session_info(),
                }
                self._send_json(200, {"ok": True, "data": payload})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/health":
            try:
                self._send_json(200, {"ok": True, "data": service.health()})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/doctor":
            try:
                self._send_json(200, {"ok": True, "data": service.doctor()})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
            return

        self._send_json(404, {"ok": False, "error": "Not Found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if not self._authorized():
            self._send_json(403, {"ok": False, "error": "Forbidden: invalid token"})
            return

        try:
            body = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return

        if path == "/api/shutdown":
            self.server.closing = True
            self._send_json(200, {"ok": True, "closing": True})
            threading.Timer(0.25, self.server.shutdown).start()
            return

        try:
            if path == "/api/capabilities":
                orders = body.get("orders") or {}
                disabled = set(body.get("disabled") or [])
                service.save_provider_orders(orders)
                service.save_state(disabled)
                self._send_json(200, {"ok": True})
                return

            if path == "/api/secrets":
                updates = body.get("updates") or {}
                clears = set(body.get("clears") or [])
                service.save_secret_updates(updates, clears)
                self._send_json(200, {"ok": True})
                return

            if path == "/api/paths":
                runtime = body.get("runtime") or {}
                cli_paths = body.get("cli_paths") or {}
                service.save_paths(runtime, cli_paths)
                self._send_json(200, {"ok": True})
                return

            if path == "/api/paths/reset":
                service.reset_paths()
                self._send_json(200, {"ok": True})
                return

            if path == "/api/probe":
                cap = str(body.get("capability") or "")
                result = service.probe(cap)
                self._send_json(200, result)
                return

            self._send_json(404, {"ok": False, "error": "Not Found"})
        except Exception as exc:  # noqa: BLE001
            self._send_json(400, {"ok": False, "error": str(exc)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="wf-agents 内置配置面板")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="")
    args = parser.parse_args(argv)

    server = PanelHTTPServer((args.host, args.port), args.token)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
