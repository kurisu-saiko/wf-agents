# Changelog

## 2.0.0

- **跨宿主通用插件架构**：新增 `plugin.json`、`mcp_config.json`、`.claude-plugin/`、`gemini-extension.json`、标准化 `skills/wf*`、`rules/AGENTS.md`、`agents/wf-researcher.md` 与 `assets/logo.svg`。
- **零依赖 Stdio MCP 服务 (`wf_mcp.py`)**：暴露 16 个结构化工具，原生支持 Antigravity、Claude Code、Cursor、Codex、Gemini CLI 与 OpenCode。
- **严格且人性化的面板生命周期**：内置轻量 HTTP 配置面板（`panel/server.py` + `panel/ui.html`）冷启动 `<150ms`；仅在首轮交互开启，进入计划模式（`wf_enter_plan` / `enter-plan`）自动优雅关闭。
- **核心零依赖与稳定性增强**：`http_client.py` 支持 `urllib` 自动回退、指数退避重试与限流诊断；`config.py` 支持 `WF_DATA_DIR` 隔离与 `gh auth token` 自动复用；`cache.py` 移出工作区。
- **能力全面增强**：新增 DuckDuckGo 零密钥搜索、Direct HTML→Markdown 抽取、免克隆 `repo_ingest`、`repo_health` 维护度与总线因子分析、`package_meta`、`package_security` (OSV CVE 批量扫描)、`license_sbom`、多语言 `dependency_graph` 与 `structural_search` 符号大纲。
- **双协议 Hook 与跨宿主安装器**：`wf_agent_gate.py` 同时支持 Antigravity 与 Claude Code；`host/install.py` 支持 9 类宿主一键预览与安装。

## 1.0.0

- 初始 `wf-mode` 主会话双人工闸口与基础适配器框架。
