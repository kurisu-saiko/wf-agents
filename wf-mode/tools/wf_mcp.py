"""零依赖 Stdio MCP Server（JSON-RPC 2.0，纯 Python 标准库）。

兼容 Antigravity、Claude Code、Cursor、Codex、Gemini CLI、OpenCode 等所有支持 MCP 的宿主。
同时支持换行符分隔 JSON 与 Content-Length 帧格式。
暴露 24 个原子工具，完整覆盖 6 步开源复用与工程组装流水线（前半段发现评估 11 + 生命周期控制 5 + 后半段组装闭环 8）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import ledger as wf_ledger  # noqa: E402
from tools import session as wf_session  # noqa: E402
from tools import wf_stage  # noqa: E402
from tools.assembly import (  # noqa: E402
    checkpoint as wf_checkpoint,
    contract as wf_contract,
    patcher as wf_patcher,
    profiler as wf_profiler,
    slicer as wf_slicer,
    strategy as wf_strategy,
    verifier as wf_verifier,
)
from tools.errors import ToolError  # noqa: E402

_WF_TOOL: Any = None


def _wf_tool() -> Any:
    global _WF_TOOL
    if _WF_TOOL is None:
        path = ROOT / "tools" / "wf-tool.py"
        spec = importlib.util.spec_from_file_location("wf_tool_mcp", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载 wf-tool: {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _WF_TOOL = mod
    return _WF_TOOL


TOOLS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # 1. 生命周期与决策账本控制（7 个）
    # ------------------------------------------------------------------
    {
        "name": "wf_start",
        "description": (
            "初始化 wf 工作流第 1 阶段（能力校准 + 首次交互自动打开配置面板）。"
            "同会话重复调用不会重复打开浏览器弹窗。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "用户任务描述"},
                "sessionId": {"type": "string", "description": "可选会话 ID，默认 default"},
                "openPanel": {"type": "boolean", "description": "是否首次打开配置面板，默认 true"},
            },
        },
    },
    {
        "name": "wf_enter_plan",
        "description": (
            "在用户确认需求（Gate 1）后进入计划/调研模式。"
            "会自动关闭配置面板并解锁全部外部调研工具。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "requirements": {"type": "string", "description": "已确认的需求卡摘要"},
                "sessionId": {"type": "string", "description": "可选会话 ID"},
            },
        },
    },
    {
        "name": "wf_enter_report",
        "description": "在用户确认方案后进入报告/交付摘要模式，确保配置面板已关闭。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "已确认的方案摘要"},
                "sessionId": {"type": "string", "description": "可选会话 ID"},
            },
        },
    },
    {
        "name": "wf_gate_commit",
        "description": (
            "提交 6 步流水线任意人类闸口（GATE_1 ~ GATE_6）的确认/拒绝记录到项目决策账本 "
            "`.wf/decisions/<sessionId>.json` 与 `ADR-<sessionId>.md`。当 GATE_1 获批时自动关闭配置面板。"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["gate"],
            "properties": {
                "projectPath": {"type": "string", "default": "."},
                "gate": {
                    "type": "string",
                    "enum": ["GATE_1", "GATE_2", "GATE_3", "GATE_4", "GATE_5", "GATE_6"],
                },
                "status": {
                    "type": "string",
                    "enum": ["approved", "rejected", "pending", "rolled_back"],
                    "default": "approved",
                },
                "summary": {"type": "string", "description": "本闸口决策摘要"},
                "selectedCandidate": {"type": "string", "description": "选中的开源候选项目/包"},
                "strategy": {"type": "string", "description": "选定的复用策略"},
                "rationale": {"type": "string", "description": "选择或拒绝理由"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "checkpointId": {"type": "string"},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_close",
        "description": "结束或终止 wf 工作流并关闭配置面板。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sessionId": {"type": "string", "description": "可选会话 ID"},
            },
        },
    },
    {
        "name": "wf_status",
        "description": "查看当前 wf 工作流阶段状态、面板状态，以及（如提供 projectPath）.wf/decisions/ 决策账本进度。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectPath": {"type": "string", "description": "可选项目根目录，传入则返回该项目的决策账本"},
                "sessionId": {"type": "string", "description": "可选会话 ID"},
            },
        },
    },
    {
        "name": "wf_panel",
        "description": "手动控制配置面板：status（查看状态）、open（打开面板）、close（关闭面板）。",
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["status", "open", "close"]},
            },
        },
    },
    # ------------------------------------------------------------------
    # 2. 前半段：发现候选、读取与合规评估（10 个）
    # ------------------------------------------------------------------
    {
        "name": "wf_web_search",
        "description": "多引擎网页搜索（Tavily -> Exa -> Brave -> SearXNG -> DuckDuckGo 零密钥兜底）。",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "maxResults": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "days": {"type": "integer", "description": "可选时间范围（天数）"},
                "includeDomains": {"type": "array", "items": {"type": "string"}},
                "excludeDomains": {"type": "array", "items": {"type": "string"}},
                "provider": {"type": "string", "enum": ["tavily", "exa", "brave", "searxng", "duckduckgo"]},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_web_extract",
        "description": "抽取网页/文档/GitHub 文件正文为干净 Markdown（Firecrawl -> Jina -> Direct 内置抽取）。",
        "inputSchema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "http/https 目标 URL"},
                "maxChars": {"type": "integer", "default": 24000},
                "provider": {"type": "string", "enum": ["firecrawl", "jina", "direct"]},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_project_search",
        "description": "GitHub 开源项目搜索（search）、单仓详情（lookup）与代码片段搜索（search_code）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "lookup", "search_code"], "default": "search"},
                "query": {"type": "string"},
                "repo": {"type": "string", "description": "owner/name 或 GitHub URL"},
                "language": {"type": "string"},
                "minStars": {"type": "integer"},
                "license": {"type": "string"},
                "topic": {"type": "string"},
                "pushedAfter": {"type": "string", "description": "YYYY-MM-DD"},
                "sort": {"type": "string", "enum": ["stars", "updated", "forks"]},
                "path": {"type": "string", "description": "search_code 时的路径过滤"},
                "maxResults": {"type": "integer", "default": 5},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_repo_inspect",
        "description": "免克隆读取 GitHub 仓库或本地项目的文件树（tree）、指定文件行范围（read）、README（readme）或智能上下文摘要（ingest）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["ingest", "tree", "read", "readme"], "default": "ingest"},
                "repo": {"type": "string", "description": "GitHub owner/name 或 URL"},
                "path": {"type": "string", "description": "本地项目目录或文件路径"},
                "file": {"type": "string", "description": "action=read 时的相对文件路径"},
                "ref": {"type": "string", "description": "可选 Git 分支或 tag"},
                "startLine": {"type": "integer", "default": 1},
                "endLine": {"type": "integer", "default": 300},
                "maxChars": {"type": "integer", "default": 24000},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_repo_health",
        "description": "评估 GitHub 仓库维护健康度（近 30/90 天提交、作者集中度、最新发布、许可证类别与风险标记）。",
        "inputSchema": {
            "type": "object",
            "required": ["repo"],
            "properties": {
                "repo": {"type": "string", "description": "owner/name 或 GitHub URL"},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_package_meta",
        "description": "查询或搜索 PyPI / npm / crates.io / GitHub 包版本、下载量、许可证与仓库链接。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["lookup", "search"], "default": "lookup"},
                "package": {"type": "string", "description": "包名"},
                "query": {"type": "string", "description": "search 关键词"},
                "ecosystem": {"type": "string", "enum": ["auto", "pypi", "npm", "crates", "github"]},
                "maxResults": {"type": "integer", "default": 5},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_package_security",
        "description": "基于 OSV.dev 实时漏洞库扫描本地项目、GitHub 仓库或单个软件包的已知 CVE/GHSA 漏洞。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["scan", "query"], "default": "scan"},
                "path": {"type": "string", "description": "本地目录路径"},
                "repo": {"type": "string", "description": "GitHub owner/name"},
                "package": {"type": "string", "description": "action=query 时的包名"},
                "ecosystem": {"type": "string", "description": "PyPI / npm / crates.io / Go"},
                "version": {"type": "string"},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_license_scan",
        "description": "识别本地目录或 GitHub 仓库的开源许可证类别（宽松/弱传染/强传染）并提取完整多生态依赖 SBOM。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "本地目录路径"},
                "repo": {"type": "string", "description": "GitHub owner/name"},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_project_analyze",
        "description": "分析本地多语言项目（Python / JS-TS / Go / Rust）语言分布、入口文件、模块依赖图、核心枢纽与循环依赖。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "本地目录路径，默认 .", "default": "."},
            },
        },
    },
    {
        "name": "wf_structural_search",
        "description": "本地代码结构/模式搜索（search）或提取文件/目录的符号大纲（symbols，支持 Python AST / TS / JS / Go / Rust）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["search", "symbols"], "default": "search"},
                "path": {"type": "string", "default": "."},
                "pattern": {"type": "string", "description": "action=search 时的搜索模式"},
                "lang": {"type": "string", "description": "可选语言过滤 python/ts/js/go/rust"},
                "maxResults": {"type": "integer", "default": 30},
            },
        },
    },
    # ------------------------------------------------------------------
    # 3. 后半段：复用策略与本地工程组装闭环（7 个）
    # ------------------------------------------------------------------
    {
        "name": "wf_local_profile",
        "description": "Step 3/4：扫描本地目标仓库的技术栈、包管理器、目录布局（src/flat）、推荐 Adapter 目录与验证命令探针。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "本地项目根目录，默认 .", "default": "."},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_strategy_evaluate",
        "description": (
            "Step 3 / Gate 3：结合候选项目画像、本地仓库画像与复用意图，量化评估 5 种复用策略"
            "（PACKAGE_DEP / CODE_SLICE / VENDORING / SIDECAR / PATTERN_REF）并生成决策简报。"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["candidate"],
            "properties": {
                "candidate": {"type": "object", "description": "候选项目信息（name/language/license/publishedPackage/loc 等）"},
                "localProfile": {"type": "object", "description": "可选，wf_local_profile 输出；若省略且传了 projectPath 则自动扫描"},
                "projectPath": {"type": "string", "description": "可选本地项目路径"},
                "intent": {"type": "object", "description": "复用意图（commercialClosedSource/needsSourceModification/preferZeroDependencies 等）"},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_slice_closure",
        "description": "Step 4：通过 AST 解析计算目标切片文件的最小内部传递依赖闭包（支持本地 sourcePath 或远程 GitHub repo 免克隆拉取）。",
        "inputSchema": {
            "type": "object",
            "required": ["targetFiles"],
            "properties": {
                "sourcePath": {"type": "string", "description": "上游源仓库本地目录（与 repo 二选一）"},
                "repo": {"type": "string", "description": "远程 GitHub owner/name 或 URL（免克隆按需拉取切片闭包）"},
                "ref": {"type": "string", "description": "可选 Git 分支、tag 或 commit SHA"},
                "targetFiles": {"type": "array", "items": {"type": "string"}, "description": "核心切片入口文件相对路径列表"},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_contract_design",
        "description": (
            "Step 4 / Gate 4 & 5：设计本地对接契约（支持全 5 策略及 Python/TS/JS 原生适配），"
            "生成分块变更列表（Chunk A/B/C）及每文件 unified diff 预览。"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["strategy", "candidate", "adapterName"],
            "properties": {
                "projectPath": {"type": "string", "default": "."},
                "strategy": {
                    "type": "string",
                    "enum": ["PACKAGE_DEP", "CODE_SLICE", "VENDORING", "SIDECAR", "PATTERN_REF"],
                },
                "candidate": {"type": "object"},
                "adapterName": {"type": "string"},
                "sourcePath": {"type": "string"},
                "repo": {"type": "string", "description": "可选远程 GitHub owner/name"},
                "ref": {"type": "string", "description": "可选 Git 分支或 tag"},
                "sliceFiles": {"type": "array", "items": {"type": "string"}},
                "fileContents": {"type": "object"},
                "exportedSymbols": {"type": "array", "items": {"type": "string"}},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_checkpoint",
        "description": "Step 5/6 安全边界管理：创建工作区/Git 快照（create）、一键精确回滚（rollback）或查看历史检查点（list）。",
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["create", "rollback", "list"]},
                "projectPath": {"type": "string", "default": "."},
                "checkpointId": {"type": "string"},
                "label": {"type": "string", "default": "assembly"},
                "plannedFiles": {"type": "array", "items": {"type": "string"}},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_assemble_apply",
        "description": (
            "Step 5：执行经人类闸口（Gate 4/5）批准的组装契约，先自动创建安全检查点，"
            "再原子落盘分块文件与 THIRD_PARTY_NOTICES.md。"
        ),
        "inputSchema": {
            "type": "object",
            "required": ["contract"],
            "properties": {
                "projectPath": {"type": "string", "default": "."},
                "contract": {"type": "object", "description": "wf_contract_design 返回的契约对象"},
                "requireGateApproval": {"type": "boolean", "default": True},
                "sessionId": {"type": "string"},
            },
        },
    },
    {
        "name": "wf_verify_run",
        "description": "Step 6 / Gate 6：运行 py_compile 语法编译、生成的适配器冒烟测试及可选项目回归测试，产出验收或回滚决策简报。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectPath": {"type": "string", "default": "."},
                "contract": {"type": "object"},
                "smokeTestFile": {"type": "string"},
                "runProjectTests": {"type": "boolean", "default": False},
                "sessionId": {"type": "string"},
            },
        },
    },
]


def _gate_blocked(tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    sid = str(args.get("sessionId") or "") or None
    allowed, state = wf_session.is_research_allowed(sid)
    if allowed:
        return None

    # 在 init 阶段允许本地只读检查以理解用户项目，拦截外部网络/GitHub 调研与写组装操作直到闸口 1 确认
    local_only_tools = {"wf_project_analyze", "wf_structural_search", "wf_local_profile"}
    if tool_name in local_only_tools:
        return None
    if tool_name in {"wf_repo_inspect", "wf_license_scan", "wf_package_security"}:
        has_remote = bool(args.get("repo") or args.get("url") or args.get("package"))
        if not has_remote and args.get("path"):
            return None

    return {
        "ok": False,
        "error": {
            "code": "GATE_REQUIRED",
            "message": (
                "当前工作流仍处于阶段 1（需求确认 / init），尚未通过 Gate 1。"
                "请先向用户确认需求，再调用 wf_enter_plan 或 wf_gate_commit(gate='GATE_1')（将自动关闭配置面板并解锁后续能力）。"
            ),
            "retryable": False,
            "details": {"stage": state.get("stage"), "tool": tool_name},
        },
    }


def _handle_assembly_or_gate(
    name: str,
    args: dict[str, Any],
    sid: str | None,
    wf: Any,
) -> tuple[dict[str, Any], bool] | None:
    if name == "wf_gate_commit":
        gate = str(args.get("gate") or "")
        status = str(args.get("status") or "approved")
        project_path = str(args.get("projectPath") or ".")
        res = wf_ledger.commit_gate(
            project_path,
            gate=gate,
            status=status,
            summary=str(args.get("summary") or ""),
            selected_candidate=str(args.get("selectedCandidate") or ""),
            strategy=str(args.get("strategy") or ""),
            rationale=str(args.get("rationale") or ""),
            evidence=[str(x) for x in (args.get("evidence") or [])],
            checkpoint_id=str(args.get("checkpointId") or ""),
            session_id=sid,
        )
        panel_res: dict[str, Any] = {}
        if gate.strip().upper() == "GATE_1" and status.strip().lower() == "approved":
            panel_res = wf._panel_close()
        return {"ok": True, **res, **({"panel": panel_res} if panel_res else {})}, False

    if name == "wf_local_profile":
        res = wf_profiler.profile_local_project(str(args.get("path") or "."))
        return {"ok": True, **res}, False

    if name == "wf_strategy_evaluate":
        local_prof = args.get("localProfile")
        if local_prof is None and args.get("projectPath"):
            local_prof = wf_profiler.profile_local_project(str(args["projectPath"]))
        res = wf_strategy.evaluate_strategies(
            candidate=args.get("candidate") or {},
            local_profile=local_prof,
            intent=args.get("intent"),
        )
        return {"ok": True, **res}, False

    if name == "wf_slice_closure":
        res = wf_slicer.compute_slice_closure(
            args.get("sourcePath"),
            [str(x) for x in (args.get("targetFiles") or [])],
            repo=args.get("repo"),
            ref=args.get("ref"),
        )
        return {"ok": True, **res}, False

    if name == "wf_contract_design":
        res = wf_contract.design_integration_contract(
            project_path=str(args.get("projectPath") or "."),
            strategy=str(args.get("strategy") or ""),
            candidate=args.get("candidate") or {},
            adapter_name=str(args.get("adapterName") or ""),
            source_path=args.get("sourcePath"),
            repo=args.get("repo"),
            ref=args.get("ref"),
            slice_files=args.get("sliceFiles"),
            file_contents=args.get("fileContents"),
            exported_symbols=args.get("exportedSymbols"),
        )
        return {"ok": True, **res}, False

    if name == "wf_checkpoint":
        action = str(args.get("action") or "list")
        project_path = str(args.get("projectPath") or ".")
        if action == "create":
            res = wf_checkpoint.create_checkpoint(
                project_path,
                label=str(args.get("label") or "assembly"),
                planned_files=args.get("plannedFiles"),
            )
            return {"ok": True, **res}, False
        if action == "rollback":
            res = wf_checkpoint.rollback_checkpoint(
                project_path,
                checkpoint_id=args.get("checkpointId"),
            )
            return {"ok": True, **res}, False
        if action == "list":
            items = wf_checkpoint.list_checkpoints(project_path)
            return {"ok": True, "checkpoints": items}, False
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": f"未知检查点动作: {action}"}}, True

    if name == "wf_assemble_apply":
        res = wf_patcher.apply_assembly_contract(
            project_path=str(args.get("projectPath") or "."),
            contract=args.get("contract") or {},
            session_id=sid,
            require_gate_approval=bool(args.get("requireGateApproval", True)),
        )
        return {"ok": True, **res}, False

    if name == "wf_verify_run":
        res = wf_verifier.run_verification(
            project_path=str(args.get("projectPath") or "."),
            contract=args.get("contract"),
            smoke_test_file=args.get("smokeTestFile"),
            run_project_tests=bool(args.get("runProjectTests", False)),
        )
        return {"ok": True, **res}, False

    return None


def handle_tool_call(name: str, raw_args: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    args = dict(raw_args or {})
    sid = str(args.pop("sessionId", "") or "") or None
    wf = _wf_tool()

    if name == "wf_start":
        data = wf_stage._calibrate_core(
            session_id=sid,
            task=str(args.get("task") or ""),
            open_panel_if_needed=bool(args.get("openPanel", True)),
            reset=True,
        )
        return data, False

    if name == "wf_enter_plan":
        panel_res = wf._panel_close()
        state = wf_session.transition_to_plan(sid, requirements=str(args.get("requirements") or "") or None)
        return {"ok": True, "stage": "plan", "session": state, "panel": panel_res}, False

    if name == "wf_enter_report":
        panel_res = wf._panel_close()
        state = wf_session.transition_to_report(sid, plan_summary=str(args.get("summary") or "") or None)
        return {"ok": True, "stage": "report", "session": state, "panel": panel_res}, False

    if name == "wf_close":
        panel_res = wf._panel_close()
        state = wf_session.close_session(sid)
        return {"ok": True, "stage": "closed", "session": state, "panel": panel_res}, False

    if name == "wf_status":
        payload: dict[str, Any] = {
            "ok": True,
            "session": wf_session.load_session(sid),
            "panel": wf._panel_status(),
        }
        if args.get("projectPath"):
            payload["ledger"] = wf_ledger.load_ledger(str(args["projectPath"]), sid)
        return payload, False

    if name == "wf_panel":
        action = str(args.get("action") or "status")
        if action == "status":
            return {"ok": True, "panel": wf._panel_status()}, False
        if action == "open":
            return {"ok": True, "panel": wf._panel_ensure(open_browser=True, once=False)}, False
        if action == "close":
            return {"ok": True, "panel": wf._panel_close()}, False
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": f"未知面板动作: {action}"}}, True

    if name != "wf_gate_commit":
        blocked = _gate_blocked(name, {**args, **({"sessionId": sid} if sid else {})})
        if blocked is not None:
            return blocked, False

    try:
        handled = _handle_assembly_or_gate(name, args, sid, wf)
        if handled is not None:
            return handled
    except ToolError as exc:
        return {"ok": False, "error": exc.to_dict()}, True

    dispatch_map: dict[str, tuple[str, str]] = {
        "wf_web_search": ("web_search", "search"),
        "wf_web_extract": ("web_extract", "extract"),
        "wf_repo_health": ("repo_health", "analyze"),
        "wf_license_scan": ("license_sbom", "scan"),
        "wf_project_analyze": ("dependency_graph", "analyze"),
    }

    if name in dispatch_map:
        cap, act = dispatch_map[name]
        env = wf.dispatch(cap, act, args)
        return env, not bool(env.get("ok"))

    if name == "wf_project_search":
        act = str(args.pop("action", "search") or "search")
        env = wf.dispatch("project_search", act, args)
        return env, not bool(env.get("ok"))

    if name == "wf_repo_inspect":
        act = str(args.pop("action", "ingest") or "ingest")
        env = wf.dispatch("repo_ingest", act, args)
        return env, not bool(env.get("ok"))

    if name == "wf_package_meta":
        act = str(args.pop("action", "lookup") or "lookup")
        env = wf.dispatch("package_meta", act, args)
        return env, not bool(env.get("ok"))

    if name == "wf_package_security":
        act = str(args.pop("action", "scan") or "scan")
        env = wf.dispatch("package_security", act, args)
        return env, not bool(env.get("ok"))

    if name == "wf_structural_search":
        act = str(args.pop("action", "search") or "search")
        env = wf.dispatch("structural_search", act, args)
        return env, not bool(env.get("ok"))

    return {"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": f"未知工具: {name}"}}, True


def handle_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = str(msg.get("method") or "")
    req_id = msg.get("id")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}

    # 通知类消息无需响应
    if req_id is None:
        return None

    if method == "initialize":
        proto = str(params.get("protocolVersion") or "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": proto,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "wf-agents", "version": "2.0.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            payload, is_error = handle_tool_call(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
                    ],
                    "isError": is_error,
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"ok": False, "error": {"code": "INTERNAL", "message": str(exc)}},
                                ensure_ascii=False,
                            ),
                        }
                    ],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _read_message(stream: Any) -> tuple[dict[str, Any] | None, str]:
    while True:
        line = stream.readline()
        if not line:
            return None, "jsonl"
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(b"content-length:"):
            length = int(stripped.split(b":", 1)[1].strip())
            while True:
                hdr = stream.readline()
                if not hdr or hdr in (b"\r\n", b"\n"):
                    break
            body = stream.read(length)
            if not body:
                return None, "lsp"
            return json.loads(body.decode("utf-8")), "lsp"
        return json.loads(stripped.decode("utf-8")), "jsonl"


def _write_message(stream: Any, payload: dict[str, Any], framing: str) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if framing == "lsp":
        header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
        stream.write(header + raw)
    else:
        stream.write(raw + b"\n")
    stream.flush()


def main() -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        try:
            msg, framing = _read_message(stdin)
        except Exception:
            continue
        if msg is None:
            break
        resp = handle_message(msg)
        if resp is not None:
            _write_message(stdout, resp, framing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
