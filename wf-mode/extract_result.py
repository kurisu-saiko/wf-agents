import json, re, sys
from pathlib import Path

MAX_ITEMS = 40
MAX_QUOTE = 500
PIPELINES = {"wf-retrieval", "wf-project-eval", "wf-project-reading"}
STATUSES = {
    "verified", "unverified", "conflict", "blocked",
    "included", "excluded",
}


def emit(text):
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def resolve_run_dir(value):
    if not value:
        return None
    p = Path(str(value).replace("\\", "/"))
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        return p.resolve()
    except OSError:
        return None


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"__error__": str(exc)}


def validate_evidence(obj, pipeline):
    errors = []
    if not isinstance(obj, dict):
        return ["evidence.json 不是 JSON 对象"]
    if obj.get("pipeline") != pipeline:
        errors.append(f"evidence.pipeline 与本次管线不一致：{obj.get('pipeline')!r}")
    items = obj.get("items")
    if not isinstance(items, list):
        return errors + ["evidence.items 缺失或不是数组"]
    if len(items) > MAX_ITEMS:
        errors.append(f"证据条目 {len(items)} 条，超过上限 {MAX_ITEMS}")
    seen = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f"第 {index} 条不是对象")
            continue
        item_id = str(item.get("id") or "").strip()
        statement = str(item.get("statement") or "").strip()
        status = str(item.get("status") or "").strip()
        sources = item.get("sources")
        if not item_id:
            errors.append(f"第 {index} 条缺少 id")
        elif item_id in seen:
            errors.append(f"id 重复：{item_id}")
        else:
            seen.add(item_id)
        if not statement:
            errors.append(f"第 {index} 条缺少 statement")
        if status not in STATUSES:
            errors.append(f"{item_id or index} 的 status 非法：{status!r}")
            continue
        if not isinstance(sources, list):
            sources = []
        if status == "verified":
            if pipeline == "wf-project-reading":
                ref = str(item.get("file") or "")
                if not re.search(r":\d+", ref):
                    errors.append(f"{item_id} 为 verified，但缺少 file:line")
            else:
                if not sources:
                    errors.append(f"{item_id} 为 verified，但没有来源")
                for src in sources:
                    if not isinstance(src, dict):
                        errors.append(f"{item_id} 的来源不是对象")
                        continue
                    loc = str(src.get("url") or src.get("path") or "").strip()
                    quote = str(src.get("quote") or "").strip()
                    if not loc:
                        errors.append(f"{item_id} 的来源缺少 url/path")
                    if not quote:
                        errors.append(f"{item_id} 的来源缺少 quote")
                    if len(quote) > MAX_QUOTE:
                        errors.append(f"{item_id} 的 quote 超过 {MAX_QUOTE} 字符")
                    if src.get("url") and not str(src.get("date") or "").strip():
                        errors.append(f"{item_id} 的外部来源缺少 date")
        if status == "conflict" and len(sources) < 2:
            errors.append(f"{item_id} 标记 conflict，但来源少于 2 个")
        if pipeline == "wf-project-eval" and status in {"included", "excluded"}:
            if not sources:
                errors.append(f"{item_id} 为 {status}，但没有来源")
            if status == "excluded" and not str(item.get("reason") or "").strip():
                errors.append(f"{item_id} 被淘汰，但缺少 reason")
    return errors


def validate_run(res):
    pipeline = str(res.get("pipeline") or "")
    if pipeline not in PIPELINES:
        return [f"未知管线：{pipeline!r}"]
    run_dir = resolve_run_dir(res.get("runDir"))
    if run_dir is None:
        return ["缺少 runDir"]
    evidence_path = run_dir / "evidence.json"
    run_path = run_dir / "run.json"
    result_path = run_dir / "result.md"
    errors = []
    for path in (run_path, evidence_path, result_path):
        if not path.is_file():
            errors.append(f"缺少账本文件：{path.name}")
    if errors:
        return errors
    run = load_json(run_path)
    if "__error__" in run:
        errors.append(f"run.json 解析失败：{run['__error__']}")
    elif run.get("pipeline") != pipeline:
        errors.append(f"run.pipeline 与本次管线不一致：{run.get('pipeline')!r}")
    if not result_path.read_text(encoding="utf-8").strip():
        errors.append("result.md 为空")
    evidence = load_json(evidence_path)
    if "__error__" in evidence:
        errors.append(f"evidence.json 解析失败：{evidence['__error__']}")
    else:
        errors.extend(validate_evidence(evidence, pipeline))
    return errors


def emit_workflow_result(res):
    if not isinstance(res, dict):
        return False
    status = res.get("status")
    if status == "ok":
        deliverable = str(res.get("deliverable") or "")
        errors = validate_run(res)
        if errors:
            emit("wf: 账本校验未通过，拒绝输出本次结果。")
            emit("")
            for err in errors:
                emit(f"- {err}")
            sys.exit(1)
        emit(deliverable)
        return True
    if status == "needs_clarification":
        q = str(res.get("question") or "")
        opts = res.get("options") or []
        emit(q + ("\n\n选项：\n" + "\n".join(f"- {o}" for o in opts) if opts else ""))
        return True
    if status == "out_of_domain":
        emit(str(res.get("reason") or res.get("message") or ""))
        return True
    return False


def main(path):
    last_final = ""
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "result":
            last_final = str(d.get("result") or "")
        if d.get("type") != "user":
            continue
        for c in d.get("message", {}).get("content", []):
            if c.get("type") != "tool_result":
                continue
            s = c.get("content")
            if isinstance(s, list):
                s = "\n".join(x.get("text", "") for x in s if isinstance(x, dict))
            if not isinstance(s, str) or "status" not in s:
                continue
            m = re.search(r"<output>\s*(\{.*?\})\s*</output>", s, re.S)
            if m:
                try:
                    obj = json.loads(m.group(1))
                    res = obj.get("result")
                    if emit_workflow_result(res):
                        return
                except Exception:
                    pass
            # 也处理直接返回的工作流 JSON
            start, end = s.find("{"), s.rfind("}")
            if start >= 0 and end > start:
                try:
                    obj = json.loads(s[start:end + 1])
                    if emit_workflow_result(obj):
                        return
                except Exception:
                    pass
    if last_final:
        emit(last_final)
        return
    emit("wf: workflow returned no result.")
    sys.exit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1])
