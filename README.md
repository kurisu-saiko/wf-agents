# wf-agents (v2.0 Universal Plugin)

一个跨 Agent 通用的**开源探索、仓库深度分析、依赖漏洞与许可证审计工作流插件**，核心目标：**用真实证据复用社区成熟方案，不盲目造轮子**。

支持 **Google Antigravity**、**Claude Code**、**Cursor**、**Codex**、**Gemini CLI**、**OpenCode** 以及任意支持 Stdio MCP 或 Agent Skills / CLI 的宿主。

## 核心特性

- **开箱即用，核心零重型依赖**：基于 Python 3.10+ 标准库 + `PyYAML`，无需 `httpx` / `streamlit` / 外部 Rust 二进制即可运行全部调研、网页抓取、仓库分析与内置配置面板。
- **内置 Stdio MCP 服务（`wf-mode/tools/wf_mcp.py`）**：暴露 16 个结构化工具（流程控制 + 搜索 + 免克隆读库 + 维护健康度 + OSV 漏洞扫描 + 许可证/SBOM + 多语言架构分析）。
- **人性化单流程 + 双人工闸口**：
  ```text
  /wf <任务> ─▶ 能力校准 + 首次打开面板 ─▶ 需求卡 ─▶ [闸口 1：需求确认]
             ─▶ 自动关闭面板 + 进入计划/调研模式 ─▶ 真实取证 + 方案对比 + 需求对照表 ─▶ [闸口 2：方案确认]
             ─▶ 只读交付报告（未修改工作区、未安装依赖）
  ```
- **面板生命周期严格可控**：
  - 仅在工作流**第一次交互**时启动并打开本地配置面板（`<150ms` 冷启动，`127.0.0.1` 隔离）；
  - Gate 1 修改需求不重复弹窗；
  - 进入计划模式（`wf_enter_plan` / `/wf-plan`）或终止时**自动优雅关闭面板**。
- **更强的搜索、读库与分析能力**：
  - **网页搜索**：`Tavily → Exa → Brave → SearXNG → DuckDuckGo`（零密钥可用）；
  - **正文抽取**：`Firecrawl → Jina → Direct`（内置 HTML→Markdown，自动将 GitHub `blob` 转为 `raw`）；
  - **项目与代码发现**：GitHub 仓库高级过滤搜索 + `search_code`（自动复用本机 `gh auth token`）；
  - **免克隆仓库读取（`repo_ingest`）**：远程 GitHub API 或本地目录的文件树、按行读取、README 与 token 预算摘要；
  - **维护健康度（`repo_health`）**：近 30/90 天提交、作者集中度、最新发布、风险标记（归档/陈旧/高传染许可/单点维护）；
  - **包元数据 & 安全 & 合规**：`PyPI / npm / crates.io` 元数据、`OSV.dev` 实时 CVE 扫描、SPDX 许可证分类与多语言 SBOM；
  - **多语言架构与符号分析**：内置 Python AST / JS-TS / Go / Rust 依赖图、循环依赖检测、核心枢纽与符号大纲。

## 一键安装

```bash
# 安装到 Google Antigravity (~/.gemini/config/plugins/wf-agents)
python install.py --host antigravity --apply

# 其他宿主（claude / cursor / codex / gemini / opencode / generic / haha / dsh）
python install.py --host cursor --apply
python install.py --host codex --apply
python install.py --host gemini --apply
```

Windows PowerShell 也可使用：

```powershell
.\wf-mode\install.ps1 -HostName antigravity -Apply
```

## 目录结构

```text
wf-agents/
├── plugin.json                # Antigravity 原生插件清单
├── mcp_config.json            # MCP 服务配置模板
├── gemini-extension.json      # Gemini CLI 扩展清单
├── .claude-plugin/            # Claude Code 插件清单 & .mcp.json
├── assets/logo.svg            # 插件图标
├── skills/                    # 跨宿主标准 Agent Skills (/wf, /wf-plan, /wf-report)
├── rules/AGENTS.md            # 插件级规则
├── agents/wf-researcher.md    # 只读研究子代理模板
├── install.py / install.sh    # 跨宿主安装入口
└── wf-mode/                   # 能力运行时、适配器、内置配置面板与集成测试
```

## 开发与测试

```bash
cd wf-mode
python -m pytest tests/integration -q
python tools/wf-tool.py list
python tools/wf-tool.py doctor
```

## 安全与许可

- 所有本地配置、面板锁与缓存默认写入 `WF_DATA_DIR`（已安装插件为 `~/.wf-agents`），绝不污染被分析项目的代码仓库。
- 凭据只进本地配置文件或子进程环境，错误与日志均自动脱敏。详见 [SECURITY.md](SECURITY.md)。
- 基于 [MIT](LICENSE) 许可开源。
