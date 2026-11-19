# wf-mode：能力内核、MCP 服务与配置面板

`wf-mode` 是 `wf-agents` 插件的 Python 3.10+ 运行时内核（核心零外部重型依赖，仅需标准库 + `PyYAML`）。

## 主要命令

```bash
# 查看能力与健康状态
python tools/wf-tool.py list
python tools/wf-tool.py health
python tools/wf-tool.py doctor

# 直接调用能力
python tools/wf-tool.py call web_search search --query "python mcp" --maxResults 5
python tools/wf-tool.py call web_extract extract --url "https://example.com"
python tools/wf-tool.py call project_search search --query "mcp" --language python --minStars 100
python tools/wf-tool.py call repo_ingest ingest --repo "owner/name"
python tools/wf-tool.py call repo_health analyze --repo "owner/name"
python tools/wf-tool.py call package_meta lookup --package httpx
python tools/wf-tool.py call package_security scan --path .
python tools/wf-tool.py call license_sbom scan --path .
python tools/wf-tool.py call dependency_graph analyze --path .
python tools/wf-tool.py call structural_search symbols --path .

# 阶段包装器（含面板自动生命周期）
python tools/wf_stage.py init --task "调研任务"   # 首次打开面板，同会话不重复弹窗
python tools/wf_stage.py enter-plan              # 进入计划模式并自动关闭面板
python tools/wf_stage.py enter-report            # 进入交付报告阶段
python tools/wf_stage.py close                   # 终止并关闭面板

# 内置配置面板（127.0.0.1，毫秒级冷启动）
python tools/wf-tool.py panel --ensure --once
python tools/wf-tool.py panel --status
python tools/wf-tool.py panel --close

# 启动 Stdio MCP 服务
python tools/wf_mcp.py
```

## 环境变量说明

- `WF_DATA_DIR`：运行数据目录（保存 `config.local.json`、`sessions/`、`cache/`、`panel.lock.json`），不写进被调研的工作区。
- `WF_BIN` / `WF_VENV`：可选外部 CLI 工具目录（`ast-grep`、`gitingest`、`pydeps`、`scorecard`、`syft`）；未配置时自动从 `PATH` 或内置零依赖适配器回退。
- `WF_PANEL_BACKEND`：默认 `builtin`（内置零依赖 Web 面板）；如需旧版 Streamlit 可设为 `streamlit`。
- `WF_DISABLE_GH_CLI=1`：禁用自动读取本机 `gh auth token`。

## 测试

```bash
python -m pytest tests/integration -q
```
