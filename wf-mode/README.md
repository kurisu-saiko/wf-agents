# wf-agent：项目探索与组装插件

一个可插拔的 agent + 能力面板。核心目标：**用社区已有项目和工具解决问题，不造轮子。**

`/wf` 按阶段拆成三条命令：调研、工具调用与阶段输出实时可见；两道闸口由“用户手动运行下一条命令”实现硬拦截；全程只读，不写文件、不装依赖、不部署。

## 工作方式

1. **`/wf <任务>`**：能力校准 → 需求理解 → 输出需求卡 → 闸口 1。本命令没有调研工具，确认后停止。
2. **用户确认需求卡后手动运行 `/wf-plan`**：候选调研、许可证与维护证据、装配步骤、需求覆盖表 → 闸口 2。本命令没有写文件工具。
3. **用户确认方案后手动运行 `/wf-report`**：只输出最终报告，不调用工具。

因为阶段之间用不同工具集隔离，模型即使想跳过闸口也没有对应工具；不保存运行档案或确认记录，需求卡与方案通过对话上下文传递。

运行任一时段都会尽力自动启动配置面板；面板只做配置与状态检查，不提供工作流入口。

sidecar 不再承担主流程，只作为可选研究后端：

```bash
python host/launcher.py --mode agent --task "..."
```

主会话模式下，工具调用与文字会随阶段自然显示。可选后端在设置 `WF_STREAM_PARTIAL=1` 时可以逐块转发 assistant 文本。

## 结构

```text
wf-mode/
├ capabilities.yaml          能力目录（16 项，active/pending）
├ agent/wf-agent.md          可选研究后端提示词（{{WF_ROOT}} 占位）
├ agents/wf-agent.md         渲染生成物（gitignore）
├ commands/
│   ├ wf.md                  阶段 1-3：校准、需求卡、闸口 1
│   ├ wf-plan.md             阶段 4-5：调研、方案、闸口 2
│   └ wf-report.md           阶段 6：最终报告
├ hooks/wf_agent_gate.py     研究后端权限闸门
├ tools/
│   ├ wf-tool.py             唯一能力入口（list/health/doctor/call/panel）
│   ├ wf_stage.py            分阶段只读包装器（calibrate/research）
│   ├ config.py              本地配置：密钥、provider 顺序、工具路径
│   └ adapters/              web_search / web_extract / project_search / cli_tool
├ panel/                     Streamlit 配置面板（不运行工作流）
├ .wf/config.example.json    本地配置模板（不含密钥）
├ host/                      宿主适配：haha / claude / dsh + launcher + install
├ tests/                     集成测试（协议、配置、面板、阶段隔离）
├ install.ps1                最小安装器
├ contracts/                 能力目录、适配器、信封 schema
├ runtime/                   宿主规则生成物（gitignore）
└ legacy/                    旧实现归档（gitignore）
```

## 快速开始

指令入口：

```text
/wf 找一个可用的开源 X 项目并给出采用方案
```

确认需求卡后手动运行 `/wf-plan`；确认方案后手动运行 `/wf-report`。

分阶段只读包装器：

```bash
python tools/wf_stage.py calibrate
python tools/wf_stage.py research project_search search --query "searxng" --maxResults 5
```

直接调用能力：

```bash
python tools/wf-tool.py list
python tools/wf-tool.py doctor
python tools/wf-tool.py call project_search search --query "searxng" --maxResults 5
python tools/wf-tool.py call web_search search --query "..." --maxResults 5
python tools/wf-tool.py call web_extract extract --url "https://..."
python tools/wf-tool.py call repo_ingest ingest --repo "owner/name"
python tools/wf-tool.py call structural_search search --pattern "def $A($$$)" --lang python --path .
python tools/wf-tool.py call dependency_graph graph --path .
python tools/wf-tool.py call package_security scan --path .
python tools/wf-tool.py call license_sbom scan --path .
```

启动器（可选研究后端）：

```bash
python host/launcher.py --list-hosts
python host/launcher.py --task "找一个可用的开源 X 项目并给出采用方案" --host auto
```

显式直连模式（不经过 agent）：

```bash
python host/launcher.py --task "查看当前仓库结构" --mode direct
```

面板：

```bash
python tools/wf-tool.py panel --ensure   # 幂等启动；已在运行则直接返回
python tools/wf-tool.py panel --status   # 只查看状态
```

面板页签：总览、能力与顺序、密钥、工具路径、闸口、提示词、诊断。它可以修改 API key、provider 主备顺序、能力启停和本地工具路径；密钥只显示掩码。面板不提供“运行工作流”入口。

本地配置保存在 `.wf/config.local.json`，优先级为“面板配置 > 环境变量 > capabilities.yaml”。面板值保存后立即生效；密钥写入本机文件，已加入 `.gitignore`，不要提交。

## 硬闸口与只读边界

- 闸口 1：`/wf` 只允许 `wf_stage.py calibrate`，没有调研工具；用户确认后必须手动运行 `/wf-plan`。
- 闸口 2：`/wf-plan` 没有写文件工具；用户确认后必须手动运行 `/wf-report`。
- 不保存运行档案、确认记录或历史；需求卡与方案通过对话上下文传递。
- `AskUserQuestion` 不可用时，降级为纯文本提问并停止本轮，不自动继续。
- 不授予 `Write/Edit/MultiEdit/NotebookEdit`；`/wf` 的 `Bash` 只用于 `wf_stage.py calibrate`，`/wf-plan` 只用于 `calibrate` 与 `research`。
- 不使用 `launcher.py` 的 `--mode direct` / `--mode auto` 自动分流。
- 外部能力只通过 `wf_stage.py research` 调用；GitHub 只使用只读 MCP 工具。

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
.\install.ps1 -HostName haha -ConfigDir "<config-dir>"

# 写入 agent、入口与 settings deny Workflow
.\install.ps1 -HostName haha -ConfigDir "<config-dir>" -Apply

# 同步 dsh 规则文件
.\install.ps1 -HostName dsh -Apply
```

## 工具路径与环境

`capabilities.yaml` 的 `runtime.bin` / `runtime.venv` 默认为空。可通过以下任一方式提供本机路径：

1. `.wf/config.local.json`（推荐，已被 gitignore）：
   ```json
   {"version": 1, "runtime": {"bin": "…/bin", "venv": "…/venv"}}
   ```
2. 环境变量 `WF_BIN` / `WF_VENV`。

`python tools/wf-tool.py doctor` 会报告实际解析到的路径与是否存在。

当前仅在 **Windows** 上验证；macOS/Linux 的 `install.ps1`、sidecar 与部分 CLI 能力尚未适配。

## 凭据读取

宿主的 GitHub token 只用于注入子进程环境，不落盘、不回显。读取顺序：`WF_CREDENTIALS` → `.wf/config.local.json` 的 `credentials` → `~/.claude/.credentials.json`。找不到时静默跳过。

安装器会把 `commands/` 下的 `wf.md`、`wf-plan.md`、`wf-report.md` 三个入口一起部署到 `<config-dir>/commands/`，逐文件写前备份；不复制宿主配置、会话、凭据。

## 开发与测试

```bash
python -m pytest tests/integration -q
```

测试覆盖：协议闸口与只读约束、流式解析、权限闸门、能力目录、缓存与降级。

## 开源边界

不包含：`.claude.json`、`cc-haha/`、`sessions/`、`projects/`、`telemetry/`、`backups/`、`runtime/`、`legacy/`、`plans/`、生成物、任何密钥或 OAuth 配置。

## 能力真实状态

`active` 必须在实施时实测通过。运行 `wf-tool health` 与 `doctor` 查看实际状态；未通过的项应降为 `pending`，不虚标。
