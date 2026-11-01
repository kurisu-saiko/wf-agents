import io
import json

from host import common


class FakeProc:
    def __init__(self, lines: list[str], err_lines: list[str], code: int = 0):
        self.stdin = io.StringIO()
        self.stdout = lines
        self.stderr = err_lines
        self._code = code

    def wait(self) -> int:
        return self._code


def install(monkeypatch, lines: list[str], err_lines: list[str] | None = None):
    proc = FakeProc(lines, err_lines or [])
    monkeypatch.setattr(common.subprocess, "Popen", lambda *args, **kwargs: proc)
    return proc


def event(kind: str, **payload):
    return json.dumps({"type": kind, **payload}, ensure_ascii=False)


def test_streams_text_deltas_without_duplicating_assistant_block(monkeypatch):
    lines = [
        event(
            "stream_event",
            event={
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "你好"},
            },
        ),
        event(
            "assistant",
            message={
                "content": [
                    {"type": "text", "text": "你好"},
                    {"type": "tool_use", "name": "mcp__plugin__search_code"},
                ]
            },
        ),
        event("result", result="你好"),
    ]
    install(monkeypatch, lines)

    chunks: list[str] = []
    tools: list[str] = []
    final = common.stream_agent(
        ["fake"], "task", on_text=chunks.append, on_tool=tools.append
    )

    assert chunks == ["你好"]
    assert tools == ["search_code"]
    assert final == "你好"


def test_falls_back_to_assistant_text_without_deltas(monkeypatch):
    lines = [
        event("assistant", message={"content": [{"type": "text", "text": "完整回复"}]}),
        event("result", result="完整回复"),
    ]
    install(monkeypatch, lines)

    chunks: list[str] = []
    final = common.stream_agent(["fake"], "task", on_text=chunks.append)

    assert chunks == ["完整回复"]
    assert final == "完整回复"


def test_stderr_does_not_contaminate_result(monkeypatch):
    lines = [event("result", result="结果")]
    install(monkeypatch, lines, err_lines=["warning: noisy"])

    chunks: list[str] = []
    final = common.stream_agent(["fake"], "task", on_text=chunks.append)

    assert chunks == []
    assert final == "结果"
