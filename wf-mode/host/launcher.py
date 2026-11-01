"""统一启动入口：按探测选择 Haha / claude / dsh，运行 wf-agent 研究后端。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host import claude, direct, dsh, haha  # noqa: E402
from host.common import HostError  # noqa: E402

HOSTS = {"haha": haha, "claude": claude, "dsh": dsh}


def _write(text: str) -> None:
    # 统一 UTF-8 字节输出，避免 Windows 控制台默认编码破坏中文。
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _write_raw(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def _write_err(text: str) -> None:
    sys.stderr.buffer.write((text + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()


def choose(host: str) -> str:
    if host != "auto":
        return host
    for name in ("haha", "claude", "dsh"):
        if HOSTS[name].detect():
            return name
    raise HostError("没有检测到可用宿主：Haha sidecar / claude / dsh。请检查安装或显式指定 --host。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="wf-agent 启动器（计划模式）")
    parser.add_argument("--task", default="", help="任务文本")
    parser.add_argument(
        "--host",
        default="auto",
        choices=["auto", "haha", "claude", "dsh"],
        help="宿主；auto 按 Haha → claude → dsh 探测",
    )
    parser.add_argument(
        "--mode",
        default="agent",
        choices=["auto", "direct", "agent"],
        help="agent 运行研究后端（默认）；direct 显式直连读取；auto 等同 agent",
    )
    parser.add_argument("--list-hosts", action="store_true", help="只列出宿主探测结果")
    args = parser.parse_args(argv)

    if args.list_hosts:
        for name, module in HOSTS.items():
            _write(f"{name}: {'detected' if module.detect() else 'missing'}")
        return 0

    task = args.task.strip()
    if not task:
        _write_err("wf: 需要任务文本：--task \"<任务>\"")
        return 2

    try:
        if args.mode == "direct":
            result = direct.run(task)
            if result is not None:
                _write(result)
                return 0
            _write("未找到可直连的仓库或路径；请给出 owner/repo 或本地路径。")
            return 0

        name = choose(args.host)
        streamed = [False]

        def on_text(chunk: str) -> None:
            if not chunk:
                return
            streamed[0] = True
            _write_raw(chunk)

        def on_tool(tool: str) -> None:
            _write_err(f"[wf] 工具 {tool}")

        output = HOSTS[name].run(
            task,
            stream=True,
            on_text=on_text,
            on_tool=on_tool,
        )
        if output and not streamed[0]:
            _write(output)
        return 0
    except HostError as exc:
        _write_err(f"wf: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
