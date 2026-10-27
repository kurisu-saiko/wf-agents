"""wf-run：执行一条管线（Phase 1 只实现 wf-retrieval/verify）。

它是手动端到端与集成测试的执行器；最终 agent 仍然通过 wf-tool 调用适配器，
由提示词决定如何拆命题和写账本。

用法：
  python tools/wf-run.py --pipeline wf-retrieval --mode verify --task "SearXNG 最新版本"
  python tools/wf-run.py --task task.json --run-dir .wf/runs/demo --json
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from tools.errors import ToolError  # noqa: E402
from tools.util import truncate, utc_now  # noqa: E402


def _load_wf_tool() -> Any:
    path = ROOT / "tools" / "wf-tool.py"
    spec = importlib.util.spec_from_file_location("wf_tool_runtime", path)
    if spec is None or spec.loader is None:
        raise ToolError("INTERNAL", "无法加载 wf-tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wf_tool = _load_wf_tool()
PROMPT_ROOT = ROOT / "prompt-blocks"


def load_pipeline(pipeline_id: str, mode: str | None = None) -> dict[str, Any]:
    path = ROOT / "pipelines" / pipeline_id / "pipeline.yaml"
    if not path.is_file():
        raise ToolError("INVALID_INPUT", f"管线不存在: {pipeline_id}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ToolError("INTERNAL", "pipeline.yaml 顶层必须是对象")
    try:
        from jsonschema import Draft202012Validator

        schema = json.loads((ROOT / "contracts" / "pipeline.schema.json").read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
        if errors:
            raise ToolError("INTERNAL", f"pipeline.yaml 校验失败: {errors[0].message}")
    except ImportError:
        pass
    if mode and data.get("mode") != mode:
        raise ToolError("INVALID_INPUT", f"管线 {pipeline_id} 没有模式: {mode}")
    return data


def _task_queries(task: Any) -> list[str]:
    if isinstance(task, str):
        query = task.strip()
        return [query] if query else []
    if isinstance(task, dict):
        raw = task.get("queries")
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        for key in ("query", "task", "question"):
            value = task.get(key)
            if isinstance(value, str) and value.strip():
                return [value.strip()]
    return []


def _task_text(task: Any) -> str:
    queries = _task_queries(task)
    return "；".join(queries) if queries else "(空任务)"


def _degradation_from_envelope(env: dict[str, Any], level: int = 2) -> list[dict[str, Any]]:
    out = []
    for item in env.get("degradation") or []:
        out.append(
            {
                "slot": str(item.get("slot") or env.get("slot") or ""),
                "level": level,
                "reason": f"{item.get('from')}->{item.get('to')}: {item.get('reason')}",
            }
        )
    return out


def _gate_results(gates: list[str], errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for gate in gates:
        first = next((e for e in errors if e.get("gate") == gate), None)
        item = {"gate": gate, "ok": first is None}
        if first:
            item["code"] = str(first.get("code") or "")
            item["message"] = str(first.get("message") or "")
        results.append(item)
    return results


def _cell(value: Any, limit: int = 120) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
    return truncate(text, limit)


def _result_markdown(task_text: str, evidence: dict[str, Any], gate_errors: list[dict[str, Any]]) -> str:
    items = evidence.get("items") or []
    verified = sum(1 for i in items if i.get("status") == "verified")
    unverified = sum(1 for i in items if i.get("status") == "unverified")
    conflict = sum(1 for i in items if i.get("status") == "conflict")
    blocked = sum(1 for i in items if i.get("status") == "blocked")

    if gate_errors:
        lines = [
            f"任务：{task_text}",
            "",
            "结论摘要：被 gates 拒绝，未输出结论。",
            "",
            "gates 错误：",
        ]
        for error in gate_errors:
            item_id = f" ({error.get('itemId')})" if error.get("itemId") else ""
            lines.append(f"- [{error.get('gate')}/{error.get('code')}] {error.get('message')}{item_id}")
        lines.extend(
            [
                "",
                "证据缺口：",
                *[f"- {gap}" for gap in evidence.get("gaps") or []],
                "",
                "建议下一步：补来源、补原文片段与发布日期后重跑。",
            ]
        )
        return "\n".join(lines)

    lines = [
        f"任务：{task_text}",
        "",
        "结论摘要：",
        f"- 共 {len(items)} 条证据：verified {verified}，unverified {unverified}，conflict {conflict}，blocked {blocked}。",
        "",
        "证据表",
        "| # | 命题 | 结论 | 来源 | 原文 | 日期 | 适用范围/限制 |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in items:
        sources = item.get("sources") or []
        source = sources[0] if sources else {}
        lines.append(
            "| {id} | {statement} | {status} | {source} | {quote} | {date} | {note} |".format(
                id=_cell(item.get("id"), 8),
                statement=_cell(item.get("statement"), 80),
                status=_cell(item.get("status"), 12),
                source=_cell(source.get("url") or source.get("path"), 80),
                quote=_cell(source.get("quote"), 80),
                date=_cell(source.get("date"), 24),
                note=_cell(item.get("note"), 80),
            )
        )
    lines.extend(
        [
            "",
            "矛盾与分歧：",
            *[f"- {i.get('statement')}" for i in items if i.get("status") == "conflict"],
            "",
            "证据缺口：",
            *[f"- {gap}" for gap in evidence.get("gaps") or []],
            "",
            "来源发现限制（如有）：",
            *[f"- {limit}" for limit in evidence.get("limitations") or []],
            "",
            "建议下一步：对 unverified 条目补一手来源或发布日期；对 blocked 条目换等价已知来源。",
        ]
    )
    return "\n".join(lines)


def _build_evidence(
    query_blocks: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    gaps: list[str] = []
    limitations: list[str] = []
    index = 0
    for block in query_blocks:
        query = block["query"]
        for result in block["results"]:
            extracted = result.get("extracted") or {}
            text = str(extracted.get("text") or "")
            metadata = extracted.get("metadata") if isinstance(extracted.get("metadata"), dict) else {}
            date = str(metadata.get("publishedTime") or result.get("publishedAt") or "").strip()
            title = str(result.get("title") or "").strip() or str(result.get("url") or "")
            index += 1
            note_parts = []
            if not text:
                note_parts.append("正文抽取失败或为空")
            if text and not date:
                note_parts.append("页面未提供发布日期")
            if not text:
                note_parts.append(f"URL: {result.get('url')}")
            status = "verified" if text and date else "unverified"
            sources = []
            if text:
                sources.append(
                    {
                        "url": str(result.get("url") or ""),
                        "path": "",
                        "quote": truncate(text, 500),
                        "date": date,
                        "tier": "secondary",
                    }
                )
            items.append(
                {
                    "id": f"E{index}",
                    "statement": f"{query}：{title}",
                    "status": status,
                    "sources": sources,
                    "note": "；".join(note_parts),
                }
            )
            if text and not date:
                gaps.append(f"{result.get('url')} 缺少发布日期，只能标 unverified")
            if not text:
                gaps.append(f"{result.get('url')} 正文抽取失败，未作为证据")
    if not items:
        gaps.append("没有可用搜索结果")
    return (
        {"pipeline": "wf-retrieval", "items": items, "limitations": limitations, "gaps": gaps},
        items,
        gaps,
    )


def run_pipeline(
    *,
    pipeline_id: str = "wf-retrieval",
    mode: str = "verify",
    task: Any,
    run_dir: str | Path | None = None,
    cwd: str | Path | None = None,
    max_results: int = 5,
    extract_limit: int = 3,
) -> dict[str, Any]:
    if pipeline_id != "wf-retrieval" or mode != "verify":
        raise ToolError("NOT_IMPLEMENTED", f"Phase 1 只实现 wf-retrieval/verify，收到 {pipeline_id}/{mode}")

    pipeline = load_pipeline(pipeline_id, mode)
    cwd_path = Path(cwd or os.getcwd()).resolve()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_path = Path(run_dir) if run_dir else cwd_path / ".wf" / "runs" / run_id
    if not run_path.is_absolute():
        run_path = (cwd_path / run_path).resolve()
    run_id = run_path.name

    started = utc_now()
    queries = _task_queries(task)
    task_text = _task_text(task)
    degradation: list[dict[str, Any]] = []
    tool_count = 0
    gate_errors: list[dict[str, Any]] = []

    # 0. 提示词块必须存在；缺块直接 blocked。
    prompt_env = wf_tool.dispatch(
        "render_prompt",
        "check",
        {"blocks": pipeline.get("promptBlocks") or [], "root": str(PROMPT_ROOT)},
        run_id=run_id,
    )
    if not prompt_env.get("ok") or not (prompt_env.get("data") or {}).get("ok"):
        gate_errors = [
            {
                "gate": "prompt",
                "code": "GATE_PROMPT_MISSING",
                "message": f"prompt blocks 缺失: {prompt_env.get('data', {}).get('missing')}",
            }
        ]
        evidence = {"pipeline": "wf-retrieval", "items": [], "limitations": [], "gaps": ["prompt blocks 缺失"]}
    elif not queries:
        gate_errors = [
            {
                "gate": "evidence",
                "code": "GATE_EVIDENCE_EMPTY",
                "message": "任务没有 query",
            }
        ]
        evidence = {"pipeline": "wf-retrieval", "items": [], "limitations": [], "gaps": ["任务没有 query"]}
    else:
        # 1. 搜索
        query_blocks: list[dict[str, Any]] = []
        for query in queries:
            env = wf_tool.dispatch(
                "web_search",
                "search",
                {"query": query, "maxResults": max_results},
                run_id=run_id,
            )
            if env.get("ok"):
                tool_count += 1
                degradation.extend(_degradation_from_envelope(env, level=2))
                results = list((env.get("data") or {}).get("results") or [])
                query_blocks.append({"query": query, "results": results})
            else:
                reason = (env.get("error") or {}).get("message") or "unknown"
                degradation.append({"slot": "web_search", "level": 3, "reason": f"{query}: {reason}"})

        # 2. 抓正文（按 URL 去重，最多 extract_limit 条/查询）
        seen: set[str] = set()
        for block in query_blocks:
            selected = []
            for result in block["results"]:
                url = str(result.get("url") or "")
                if not url or url in seen:
                    continue
                if len(selected) >= extract_limit:
                    break
                seen.add(url)
                env = wf_tool.dispatch("web_extract", "extract", {"url": url}, run_id=run_id)
                if env.get("ok"):
                    tool_count += 1
                    degradation.extend(_degradation_from_envelope(env, level=2))
                    result["extracted"] = env.get("data") or {}
                else:
                    reason = (env.get("error") or {}).get("message") or "unknown"
                    degradation.append({"slot": "web_extract", "level": 2, "reason": f"{url}: {reason}"})
                    result["extracted"] = {}
                selected.append(result)
            # 只保留尝试过正文的条目，避免把纯摘要当证据。
            block["results"] = selected

        evidence, items, gaps = _build_evidence(query_blocks)

        # 3. gates（先检查对象；账本写入后仍保留 gate 结果）
        run_for_gate = {
            "pipeline": "wf-retrieval",
            "status": "partial",
            "degradation": degradation,
            "startedAt": started,
            "finishedAt": utc_now(),
        }
        gates_env = wf_tool.dispatch(
            "gates",
            "check",
            {
                "run": run_for_gate,
                "evidence": evidence,
                "names": pipeline.get("gates") or [],
                "promptBlocks": pipeline.get("promptBlocks") or [],
                "blocksRoot": str(PROMPT_ROOT),
            },
            run_id=run_id,
        )
        if gates_env.get("ok"):
            gate_errors = list((gates_env.get("data") or {}).get("errors") or [])
        else:
            gate_errors = [
                {
                    "gate": "ledger",
                    "code": "GATE_LEDGER_INVALID",
                    "message": (gates_env.get("error") or {}).get("message") or "gates 执行失败",
                }
            ]

    # 4. 判定状态与结果
    items = evidence.get("items") or []
    if gate_errors:
        status = "blocked"
    elif not items:
        status = "blocked"
        gate_errors = [
            {
                "gate": "evidence",
                "code": "GATE_EVIDENCE_EMPTY",
                "message": "没有可用证据",
            }
        ]
    elif all(item.get("status") == "verified" for item in items):
        status = "complete"
    else:
        status = "partial"

    result_text = _result_markdown(task_text, evidence, gate_errors)
    run = {
        "pipeline": "wf-retrieval",
        "status": status,
        "degradation": degradation,
        "startedAt": started,
        "finishedAt": utc_now(),
        "toolCount": tool_count,
        "gateResults": _gate_results(pipeline.get("gates") or [], gate_errors),
        "promptBlocks": pipeline.get("promptBlocks") or [],
        "runId": run_id,
    }

    ledger_env = wf_tool.dispatch(
        "ledger",
        "commit",
        {
            "run_dir": str(run_path),
            "cwd": str(cwd_path),
            "run": run,
            "evidence": evidence,
            "result": result_text,
        },
        run_id=run_id,
    )
    if not ledger_env.get("ok"):
        raise ToolError(
            "LEDGER_INVALID",
            "账本写入失败",
            details={"error": ledger_env.get("error")},
        )

    return {
        "ok": True,
        "pipeline": pipeline_id,
        "mode": mode,
        "status": status,
        "runDir": str(run_path),
        "result": result_text,
        "run": run,
        "evidence": evidence,
        "gateErrors": gate_errors,
        "toolCount": tool_count,
    }


def _task_from_cli(value: str) -> Any:
    path = Path(value)
    if path.is_file():
        raw = path.read_text(encoding="utf-8")
        try:
            parsed = json.loads(raw)
        except ValueError:
            return raw
        return parsed
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    return parsed


def _stderr(text: str) -> None:
    sys.stderr.buffer.write(text.encode("utf-8"))
    sys.stderr.buffer.flush()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        sys.stdout.buffer.write((__doc__ or "").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0
    options: dict[str, Any] = {}
    i = 0
    while i < len(argv):
        token = argv[i]
        if not token.startswith("--"):
            _stderr(f"无法解析参数: {token}\n")
            return 2
        key = token[2:]
        if key in {"json"}:
            options[key] = True
            i += 1
            continue
        if i + 1 >= len(argv):
            _stderr(f"{token} 缺少值\n")
            return 2
        options[key] = argv[i + 1]
        i += 2
    try:
        result = run_pipeline(
            pipeline_id=options.get("pipeline", "wf-retrieval"),
            mode=options.get("mode", "verify"),
            task=_task_from_cli(options.get("task", "")),
            run_dir=options.get("run-dir") or options.get("run_dir"),
            cwd=options.get("cwd"),
            max_results=int(options.get("max-results", 5)),
            extract_limit=int(options.get("extract-limit", 3)),
        )
    except ToolError as exc:
        payload = {"ok": False, "error": exc.to_dict()}
        sys.stdout.buffer.write(
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )
        sys.stdout.buffer.flush()
        return 1
    if "json" in options:
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    else:
        text = result["result"] + "\n"
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
