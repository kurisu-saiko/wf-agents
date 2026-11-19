# Changelog

## 2.0.0

- **定位演进：人机协同的开源复用与工程组装流水线**：从“只读调研报告工具”全面演进为覆盖 **发现候选 → 合规/健康评估 → 5 选 1 复用策略 → 本地对接契约 → 检查点与分块落盘 → 闭环验证/回滚**（`GATE_1`～`GATE_6`）的工程闭环系统。
- **决策账本与四问输出协议**：新增 `.wf/decisions/` 持久化账本与 `ADR-<session>.md` 自动渲染（`ledger.py`）；引入决策导向四问协议 `DecisionBrief`（`envelope.py`）。
- **5 选 1 策略评估与工程组装内核（`wf-mode/tools/assembly/`）**：
  - `strategy.py`：量化对比 `PACKAGE_DEP` / `CODE_SLICE` / `VENDORING` / `SIDECAR` / `PATTERN_REF`。
  - `profiler.py` & `slicer.py`：本地项目画像 + Python/JS/TS AST 最小传递依赖闭包提取，原生支持**远程 GitHub 仓库免克隆按需切片**。
  - `contract.py` & `verifier.py`：支持 Python 及 TypeScript/JavaScript 原生 Adapter 生成，并补齐 `SIDECAR`（`docker-compose.sidecar.yml` + `SidecarClient`）与 `PATTERN_REF`（Clean-Room 规约 + 骨架）。
  - `checkpoint.py` & `patcher.py` & `provenance.py`：强制校验 `GATE_4/5` 批准，自动备份 `.wf/checkpoints/` 快照以支持 1 秒精确回滚，幂等注入 SPDX 头并维护 `THIRD_PARTY_NOTICES.md`。
- **24 工具零依赖 Stdio MCP 服务（`wf_mcp.py`）与统一安装器（`install.py`）**：统一分发 4 个标准 Skills（`wf`、`wf-plan`、`wf-assemble`、`wf-report`），适配 Antigravity、Claude Code、Cursor、Codex、Gemini CLI、OpenCode 与 Generic 宿主。
- **严格且人性化的面板生命周期**：内置 `ThreadingHTTPServer` 面板（`panel/server.py` + `ui.html`）冷启动 `<150ms`；仅首次互动弹出，过 `GATE_1` / `wf_enter_plan` 时自动优雅关闭。
- **四层测试体系**：建立 L1 模块测试、L2 闸口/回滚集成测试、L3 真实 MCP 握手验证与 L4 端到端评估基准。

## 1.0.0

- 初始 `wf-mode` 主会话双人工闸口与基础适配器框架。
