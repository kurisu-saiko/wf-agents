# wf-agents (v2.0 Open-Source Reuse & Assembly Pipeline)

一个跨 Agent 通用的**人机协同开源复用与工程组装流水线插件**——从“只读调研报告工具”，升级为最终交付**经过合规审查、适配本地架构、可安全回滚的可运行代码**。

支持 **Google Antigravity**、**Claude Code**、**Cursor**、**Codex**、**Gemini CLI**、**OpenCode** 以及任意支持 Stdio MCP / Agent Skills / CLI 的宿主。

## 核心工作流：6 步走 + 6 个人类闸口（一条底座串联两段链路）

```text
[前半段：证据与决策引擎（只读）]
1. 发现候选 ──► 2. 合规/健康评估 ──► 3. 决定5选1复用策略
     │                  │                     │
  [Gate 1]           [Gate 2]              [Gate 3]

[后半段：本地工程组装闭环（受控写盘 + 可回滚）]
──► 4. 本地画像与对接契约 ──► 5. 安全组装落地 ──► 6. 闭环验证
         │                          │                │
      [Gate 4]                   [Gate 5]         [Gate 6: 验收 / 一键回滚]
```

## 核心工程能力（24 个标准 Stdio MCP 工具）

- **统一 MCP 服务（`wf-mode/tools/wf_mcp.py`）**：零重型外部依赖（Python 3.10+ 标准库 + `PyYAML`），兼容 JSONL 与 Content-Length LSP 帧。
- **决策账本（`.wf/decisions/`）**：每过一个闸口自动持久化 JSON 状态机与可随 PR 提交的 `ADR-<sessionId>.md`。
- **决策导向输出协议（`envelope.py`）**：阶段输出附带 `decision_brief`，回答“是否命中需求 / 证据能否核验 / 局限与代价 / 可选拍板项”。
- **5 选 1 复用策略引擎（`strategy.py`）**：量化对比 `PACKAGE_DEP` / `CODE_SLICE` / `VENDORING` / `SIDECAR` / `PATTERN_REF`。
- **代码切片 AST 最小闭包（`slicer.py`）**：自动分析最小内部传递依赖闭包、导出符号与缺失引用。
- **本地对接契约 & 薄隔离适配层（`profiler.py` + `contract.py`）**：自动感知本地 `src/flat` 布局、包管理器与测试探针，生成 Adapter + 自包含冒烟测试 + 分块 unified diff。
- **安全检查点与合规追溯（`checkpoint.py` + `provenance.py` + `patcher.py` + `verifier.py`）**：
  - 写盘前强制校验 `GATE_4/5` 并于 `.wf/checkpoints/` 拍摄工作区/Git 快照，验证失败可 **1 秒一键回滚**；
  - 幂等注入 SPDX 版权头并维护 `THIRD_PARTY_NOTICES.md`。
- **严格面板生命周期（`panel/server.py`）**：`<150ms` 冷启动内置面板，仅首轮互动开启，Gate 1 确认即自动优雅关闭。

## 统一跨宿主安装

```bash
# 安装到 Google Antigravity (~/.gemini/config/plugins/wf-agents)
python install.py --host antigravity --apply

# 统一挂载其他宿主（claude / cursor / codex / gemini / opencode / generic）
python install.py --host claude --apply
python install.py --host cursor --apply
python install.py --host codex --apply
python install.py --host gemini --apply
```

Windows PowerShell 也可使用：`.\wf-mode\install.ps1 -HostName antigravity -Apply`。

## 仓库目录规划

```text
wf-agents/
├── plugin.json                # Antigravity 原生插件清单
├── mcp_config.json            # 跨宿主标准 MCP 配置模板
├── .claude-plugin/            # Claude Code 插件清单 & .mcp.json
├── skills/                    # 唯一真源 Agent Skills (/wf, /wf-plan, /wf-assemble, /wf-report)
├── rules/AGENTS.md            # 6 闸口、面板与证据规范
├── agents/wf-researcher.md    # 调研与工程分析子代理模板
├── install.py / install.sh    # 统一声明式跨宿主安装器
└── wf-mode/
    ├── tools/
    │   ├── wf_mcp.py          # 24 工具 Stdio MCP 统一入口
    │   ├── wf_stage.py        # 阶段包装器与 CLI 兜底入口
    │   ├── ledger.py          # .wf/decisions/ 决策账本 + ADR 生成
    │   ├── envelope.py        # 决策四问 DecisionBrief 协议
    │   ├── adapters/          # 前半段：搜索 / 读库 / 健康度 / OSV 安全 / SPDX / 依赖图
    │   └── assembly/          # 后半段：profiler / strategy / slicer / contract / provenance / checkpoint / patcher / verifier
    ├── panel/                 # 零依赖内置配置面板
    └── tests/integration/     # 四层测试体系（L1 模块 / L2 闸口集成 / L3 真服务与 MCP / L4 端到端评估）
```

## 四层测试运行

```bash
cd wf-mode
python -m pytest tests/integration -q
python tools/wf-tool.py doctor
```

## 安全与许可

- 全局配置、缓存、面板锁保存在 `WF_DATA_DIR`（默认 `~/.wf-agents`）；项目级决策账本与回滚快照落在 `.wf/`；所有第三方引用均注入 SPDX 并归档于 `THIRD_PARTY_NOTICES.md`。
- 凭据仅存本地配置文件或子进程环境，错误与日志均自动脱敏。详见 [SECURITY.md](SECURITY.md)。
- 基于 [MIT](LICENSE) 许可开源。
