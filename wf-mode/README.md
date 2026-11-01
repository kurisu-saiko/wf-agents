# wf-agent：项目探索与组装插件

一个可插拔的 agent + 能力面板。核心目标：**用社区已有项目和工具解决问题，不造轮子。**

agent 只读：不写文件、不装依赖、不部署。

## 结构

```text
wf-mode/
├ capabilities.yaml          能力目录（16 项，active/pending）
├ agent/wf-agent.md          唯一 agent 提示词（{{WF_ROOT}} 占位）
├ hooks/wf_agent_gate.py     agent 级权限闸门
├ tools/
│   ├ wf-tool.py             唯一能力入口（list/health/doctor/call）
│   └ adapters/              web_search / web_extract / project_search / cli_tool
├ panel/                     Streamlit 能力面板
├ host/                      宿主适配：haha / claude / dsh + launcher + install
├ commands/wf.md             指令入口源
├ install.ps1                最小安装器
└ contracts/                 能力目录、适配器、信封 schema
```

## 快速开始

指令入口：

```text
/wf 找一个可用的开源 X 项目并给出采用方案
```

直接调用：

```bash
python tools/wf-tool.py list
python tools/wf-tool.py doctor
python tools/wf-tool.py call project_search search --query "searxng" --maxResults 5
python tools/wf-tool.py call web_search search --query "..." --maxResults 5
python tools/wf-tool.py call repo_ingest ingest --repo "owner/name"
python tools/wf-tool.py call structural_search search --pattern "def $A($$$)" --lang python --path .
python tools/wf-tool.py call dependency_graph graph --path .
python tools/wf-tool.py call package_security scan --path .
python tools/wf-tool.py call license_sbom scan --path .
```

启动器：

```bash
python host/launcher.py --list-hosts
python host/launcher.py --task "找一个可用的开源 X 项目并给出采用方案" --host auto
```

面板：

```bash
python tools/wf-tool.py panel
# 或
streamlit run panel/app.py --server.headless true
```

面板四块：提示词、装配工具、API 接入、状态测试。启停只写 `panel/state.json`；停用的能力会拒绝调用。

## 能力目录

`capabilities.yaml` 是单一真相源，登记 16 项能力：

- **active**：web_search、web_extract、project_search、package_meta、repo_ingest、dependency_graph、structural_search、scaffold。
- **pending**：code_graph、repo_fetch、package_security、license_sbom、toolchain、deploy_runtime、reverse_proxy、managed_platform。

`kind`：`adapter`（内部适配器）、`cli`（本地工具）、`mcp`（宿主 MCP）、`pending`（未验证）。
`status`：`active` / `pending` / `missing`。

## 宿主

宿主最小契约（满足任意两条即可接入）：

1. 能执行命令（调用 `wf-tool`）；
2. 能注入提示词/规则文件；
3. 能收窄工具面。

| 宿主 | 形态 | 状态 |
|---|---|---|
| Claude Code Haha | sidecar + `--agent wf-agent` | 已实现 |
| 通用 Claude Code CLI | `--append-system-prompt` + 工具白名单 | 已实现（需本机有 `claude`） |
| DeepSeek Harness（dsh/dsh-next） | 规则文件 + CLI-only | 适配骨架；扩展点待验证 |

### DeepSeek Harness 说明

本机尚未验证 dsh 的扩展点，因此 `--host dsh` 只做探测并生成规则文件（`runtime/dsh/wf-agent.md`），不会假装启动。

推荐接入顺序：

1. **CLI-only（最可移植）**：让 dsh 的 agent 通过 `wf-tool` 调用能力；把规则文件作为系统提示/规则注入。
2. **规则文件 + 工具白名单**：确认 dsh 的规则文件与工具限制方式后，渲染 `wf-agent` 并收窄工具面。
3. **原生插件/技能**：如 dsh 提供插件机制，注册为插件，能力仍走同一 `wf-tool`。

## 安装

```powershell
# 预览
.\install.ps1 -HostName haha -ConfigDir "D:/claude-code/data"

# 写入 agent、入口与 settings deny Workflow
.\install.ps1 -HostName haha -ConfigDir "D:/claude-code/data" -Apply
```

安装器只写声明的路径，写入前备份；不复制宿主配置、会话、凭据。

## 开源边界

不包含：`.claude.json`、`cc-haha/`、`sessions/`、`projects/`、`telemetry/`、`backups/`、任何密钥或 OAuth 配置。

## 能力真实状态

`active` 必须在实施时实测通过。运行 `wf-tool health` 与 `doctor` 查看实际状态；未通过的项应降为 `pending`，不虚标。
