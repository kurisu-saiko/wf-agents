# wf-agent-workflow 第一版最终计划（全形态）

> 日期：2026-10-26
> 状态：第一版最终计划；结构、契约、验收已定；工具最终选型在开发阶段完成。
> 延期：流程自动化、记忆能力。
> 本文件为计划正文；`PLAN.md` 只保留索引。

---

## 一、目标

把 Claude Code 的 agent 工作方式扩展成一套可安装的工作流插件：

- 普通模式保持原版；
- 工作流模式由用户显式进入；
- 索引层作为主模型，负责需求对接、方案沟通、按需取证；
- 全部管线由现成工具驱动；
- 第一版实现全部管线、全部能力槽、完整面板、安装与隔离；
- 流程自动化与记忆能力延期。

---

## 二、最终定义

> 一个可安装的 agent 工作流插件：安装后不改变原版；进入后由索引层与用户对接需求，按需调用管线取证，形成可验收方案；执行管线单趟运行、工具优先、账本可审计；新增能力只加声明与适配器，不改内核。

四层终态：

1. **交付终态**：安装/卸载/回滚完整的插件包。
2. **运行终态**：普通模式/工作流模式双轨隔离。
3. **能力终态**：检索、项目搜寻与评估、解读、拆分、复用、组装、部署全链路。
4. **演进终态**：新增管线/工具不改核心；自动化与记忆后续接入。

---

## 三、范围与计划刚性

### 3.1 第一版实现

- 5 条管线 / 9 个模式；
- 17 个能力槽 + ledger；
- 全部适配器接线；每个槽位在交付时至少有一个 measured active 适配器；
- 完整 Streamlit 面板；
- 安装/health/卸载/回滚；
- 提示词块 + render-prompt；
- 账本 + gates；
- agent 级 hook；
- golden set、shadow、失败注入；
- 索引层：需求对接、方案表达、`wf-run` 取证、catalog、recommend、decision ledger。

### 3.2 延期

- **流程自动化**：自动选管线、自动串管线、自动重试编排。
- **记忆能力**：用户偏好、术语、历史决策；第一版只留接口。

### 3.3 冻结与推迟

**计划冻结：**

- 模块边界；
- 接口契约：`wf-tool` 信封、`ledger commit`、`wf-run`、`render-prompt`、`wf-index` 输入输出；
- 不变量：工具优先、minTools、一主一备、agent 无 Write、双轨隔离、hook 只放行 `wf-tool`/`wf-run`；
- 账本与 gates 字段；
- 权限与批准规则；
- Expectation Spec 与验收映射。

**开发时再决定：**

- 每个槽位最终用哪个工具；
- 适配器内部实现；
- 面板布局与文案；
- 提示词具体措辞；
- 管线实现顺序；
- 部署平台与托管账号。

---

## 四、原则与硬约束

### 五条根原则

1. **组装优先**：使用/组装现成项目、API、技能、工具；适配器只做胶水；缺工具登记与降级。
2. **可复现单趟**：执行管线一次调用、一次回复；固定流程；`blocked/partial` 是合法终态。
3. **双轨隔离**：普通模式原版，仅移除 `Workflow`；wf 资产独立配置/进程；入口用户显式触发。
4. **结构强制**：agent 正文 = 提示词；tools = 物理白名单；agent 级 hook；普通模式零 hook；规范内嵌，不做全局 skill 注册。
5. **人对齐授权**：凭据/账号/配置归用户；安装/卸载/升级由用户执行；apply/deploy 必须批准。

### 两条新增硬约束

6. **不写业务代码**：不实现搜索、抓取、索引、依赖分析、漏洞扫描、部署逻辑。
7. **工具优先**：每模式达到 `minTools`；主工具可用时禁止用 `Read/Grep/WebFetch` 当主流程；每槽位一主一备。

---

## 五、质量标准对照

| 历史标准 | 本设计 |
|---|---|
| 单体优先，不拆服务 | 一个插件、一个进程；索引层、管线、适配器都是模块 |
| 深模块，小接口 | `wf-tool`、`ledger`、`render-prompt`、`wf-run` 都是深模块 |
| 最小接缝 | 只在外部工具留适配器；不提前拆契约/子进程/事件总线 |
| 重复优于错误抽象 | 17 槽按真实能力划分；未出现第二消费者不拆契约 |
| 抽象会泄漏 | 保留 `wf-tool --verbose` 与 `health` 诊断路径 |
| 故障隔离 | 适配器超时/熔断/隔舱；账本 fail closed；管线不因单工具崩溃 |
| 模块化单体 | 管线、索引、面板共享一个部署；内部显式契约 |
| 选择无聊技术 | Python、Node、YAML、JSON、文件账本、Streamlit；不上 DB/消息队列/插件加载器 |
| 简单而非熟悉 | 三个深模块，不用“层数”代替简单 |
| 证据先于结论 | 索引层事实断言引用管线账本 |
| 可复现 | 执行管线单趟；Expectation Spec/Work Order/Decision Ledger 落盘 |
| 不写业务代码 | 适配器只做认证/调用/归一化 |
| 人对齐 | 需求确认、写/部署批准、凭据归用户 |

---

## 六、架构

```text
用户
  ↔ 索引层（主模型：需求对接、方案沟通、按需取证）
       ├─ wf-run（只读管线）
       ├─ catalog / health
       ├─ work-order / expectation-spec / decision-ledger
       └─ 后续：memory

Kernel（一个进程）
  - 原则与边界
  - pipeline manifests
  - wf-tool（深模块）
  - ledger（深模块）
  - hooks
  - gates

Adapters（外部工具）
  - 17 个能力槽

Periphery
  - prompt blocks / render-prompt
  - Streamlit 面板
  - install / health / uninstall / rollback
  - golden set / lessons / shadow
```

深模块：

| 模块 | 对外接口 | 隐藏实现 |
|---|---|---|
| `wf-tool` | `<slot> <action>` | registry、调用、超时、熔断、错误归一、降级 |
| `ledger` | `commit` | schema、路径、原子写入 |
| `render-prompt` | `--check/--write` | 块组合、manifest 校验、生成 agent |
| `wf-run` | `<pipeline> <mode> --task` | 管线调度、结果聚合、证据摘要 |

---

## 七、索引层：主模型与需求对接

### 7.1 定位

索引层不是分配器，而是**和用户交流的主模型**：

```text
理解需求 → 对接确认 → 方案设计 → 按需调管线取证 → 反馈方案 → 记录决策
```

它不做：

- 自动路由；
- 自动串管线；
- 直接调工具/适配器；
- 写业务代码。

### 7.2 能力

| 能力 | 作用 |
|---|---|
| 需求对接 | 把用户预期整理成 Expectation Spec |
| 方案设计 | 问题、约束、备选、取舍、推荐 |
| 证据调用 | 通过 `wf-run` 调只读管线 |
| 能力索引 | 管线/模式/槽位/健康/额度/许可 |
| 交流表达 | 完整、可读、符合用户预期 |
| 决策记录 | Work Order → 选择 → 结果 → 经验 |
| 记忆（延期） | 用户偏好、术语、历史决策 |

### 7.3 Expectation Spec（项目预期规范）

用于回答：

- 用户需要一个什么样的项目？
- 项目实现后是什么模样？
- 能实现什么功能？
- 使用起来是什么体验？

模板：

```text
# 项目预期规范

## 1. 项目画像
- 项目类型
- 一句话描述
- 参考产品/参考体验

## 2. 用户与场景
- 谁使用、谁受益
- 使用场景
- 触发点

## 3. 成品形态
- 最终形态：插件/网站/CLI/服务/桌面应用
- 用户最终拿到什么
- 入口
- 可见产物

## 4. 功能清单
- 每个功能：编号、名称、用户故事、可观察行为、must/should/won't、验收
- 明确不做什么

## 5. 使用体验
- 第一步、第二步、最后一步
- 系统反馈
- 错误体验
- 语言与语气
- 交互约束

## 6. 约束与红线
- 技术约束
- 业务约束
- 合规/安全红线
- 已有资产
- 绝不能发生的事

## 7. 验收证据
- 每条预期对应什么证据
- 演示场景
- 可观察结果
- 谁判断“符合预期”

## 8. 未知与决策
- 未确定问题
- 当前假设
- 需要用户拍板的事项

## 9. 非目标
- 明确不做什么
```

规则：

1. 每个功能必须有可观察行为。
2. 每个预期必须有验收证据。
3. 禁止空泛形容词；“优雅、健壮、可扩展、现代”必须换成可观察结果。
4. 必须写非目标。
5. 必须写“什么情况下算不对”。
6. 参考产品优先于抽象描述。
7. 质量/风险是底线，不是优先级；具体阈值写进约束。
8. 未确定就留空并提问。
9. 变更版本化。

### 7.4 Work Order

Work Order 只做执行工单，需求内容引用 Expectation Spec。

```json
{
  "workOrderId": "WO-20261026-001",
  "expectationSpecId": "ES-20261026-001",
  "requestedPipeline": null,
  "requestedMode": null,
  "risk": {"level": "low|medium|high", "approvalRequired": false},
  "status": "draft|confirmed|executed"
}
```

### 7.5 需求对接流程

```text
1. 用户用自己的话描述想要的项目
2. 索引层复述，并填 Expectation Spec
3. 缺项提问：每轮最多 3 个，附示例或默认假设
4. 用户确认 Spec
5. 索引层设计方案；需要事实时用 wf-run 调只读管线
6. 方案逐条映射到 Spec 的功能与验收
7. 执行管线；结果回填验收证据
8. 变更生成新 Spec 版本
```

对接问题只问四类：

1. **成品**：做完是什么样？用户拿到什么？
2. **功能**：必须能做什么？什么情况算不对？
3. **体验**：用户怎么用？失败时看到什么？
4. **边界**：什么绝不能发生？什么明确不做？

不再问“速度/成本/质量/风险哪个优先”。

### 7.6 方案表达规范

固定结构：

```text
1. 问题（用户视角）
2. 约束与优先级（仅记录用户明确提出的阈值/红线）
3. 方案 A / B / C（代价、风险、适用条件）
4. 推荐方案 + 为什么适合你
5. 明确假设
6. 需要你决定的事项
7. 验收标准
8. 下一步
```

规则：

- 先说结论；
- 不用黑话；
- 每个方案给代价；
- 不隐藏假设；
- 推荐不是唯一答案；
- 一段只讲一个判断；
- 事实性断言必须有管线账本出处；
- 禁止空泛词；
- 没有验收标准的方案不算完成；
- 方案必须引用 Spec 的功能编号与验收项。

### 7.7 证据调用 `wf-run`

```text
wf-run <pipeline> <mode> --task "..."
  → result + evidence 摘要 + run 路径
```

规则：

- 索引层只能调只读管线：retrieval、eval/search、eval/evaluate、analyze/read、build/reuse（计划）、deploy/plan；
- 写/部署管线必须用户明确要求 + 批准；
- 一次调用一个管线；多个调用先告诉用户计划；
- 调用前说明“我需要验证什么”；
- 失败 → 把 `blocked/partial` 作为事实反馈，不猜；
- 不允许绕过管线直接调适配器/工具。

### 7.8 能力索引、推荐、决策账本

- `catalog`：读 registry/manifests/health，输出管线/模式/槽位/适配器/状态/额度/许可；
- `recommend`：基于 Expectation Spec 推荐管线/模式与工具链；只推荐，不执行；
- `decision ledger`：append-only 记录 Spec、Work Order、选择、结果、失败分类、经验；
- 为后续流程自动化提供数据，不现在启用自动执行。

### 7.9 交流质量测试

| 测试 | 判据 |
|---|---|
| 需求复述 | 每轮先复述目标与预期 |
| 问题数量 | 每轮 ≤3 个关键问题，附默认假设 |
| 非目标 | Spec 有非目标 |
| 成品/功能/体验/边界 | 四类信息齐全 |
| 方案结构 | 问题/约束/备选/推荐/假设/验收齐全 |
| 取舍 | 每方案有代价与风险 |
| 可读性 | 无未解释术语、无空泛词 |
| 证据 | 事实断言有账本出处 |
| 确认 | Spec 确认后才给最终方案 |
| 失败 | 管线 blocked 时继续对话并显式反馈 |

### 7.10 索引层约束

| ID | 条款 | 等级 |
|---|---|---|
| IDX-01 | MUST NOT 直接调用适配器/工具 | R0 |
| IDX-02 | MUST 通过 `wf-run` 调管线 | R0 |
| IDX-03 | MUST NOT 自动执行写/部署管线 | R0 |
| IDX-04 | MUST 先确认 Expectation Spec，再给最终方案 | R1 |
| IDX-05 | MUST 每轮 ≤3 个关键问题，附默认假设 | R2 |
| IDX-06 | MUST 方案包含备选、代价、假设、验收 | R1 |
| IDX-07 | MUST 事实断言有账本出处，否则标假设 | R1 |
| IDX-08 | MUST NOT 编造需求、对象、约束 | R0 |
| IDX-09 | MUST 记录 Spec/选择/结果到 decision ledger | R1 |
| IDX-10 | MUST NOT 输出无验收标准的方案 | R1 |
| IDX-11 | MUST 管线失败时继续对话并显式反馈 | R1 |
| IDX-12 | MUST NOT 把“推荐”写成“已决定” | R2 |
| IDX-13 | 流程自动化 MUST NOT 在第一版启用 | R0 |
| IDX-14 | 记忆写入 MUST 经用户确认（后续） | R1 |

### 7.11 记忆（延期）

接口先留：

```text
memory.read(kind, key)
memory.write(kind, key, value, evidence)
```

内容：用户偏好、项目术语、历史决策、反复约束。

规则：写入需用户确认；记忆不是事实来源；不存密钥/账号/隐私；失败不影响对话。

---

## 八、管线系统（5 管线 / 9 模式）

> 本节只描述目标、能力槽、输出契约与闸门；具体工具在开发阶段选定。

| 管线/模式 | 目标 | minTools | 能力槽 | 输出 | 闸门 | 写入/批准 |
|---|---|---:|---|---|---|---|
| `wf-retrieval/verify` | 查证事实、给出处 | 2 | web_search, web_extract | 证据表 | evidence, source-tier | 无 |
| `wf-project-eval/search` | 找候选项目 | 2 | project_search, package_meta | 候选表 | evidence | 无 |
| `wf-project-eval/evaluate` | 判断能否用、用哪个 | 3 | package_meta, package_security, repo_ingest | 采用建议 | evidence, license, security | 无 |
| `wf-project-analyze/read` | 读架构、入口、主流程、数据流 | 2 | repo_ingest, code_graph | 架构地图 | file-line, uncovered | 无 |
| `wf-project-analyze/split` | 找边界、依赖、影响面 | 3 | code_graph, dependency_graph, structural_search | 拆分方案 | file-line, boundary | 无 |
| `wf-project-build/reuse` | 提取可复用模块 | 3 | structural_search, repo_fetch, license_sbom | 复用账本 | license, provenance | 默认计划 |
| `wf-project-build/assemble` | 用模板/组件组装 | 2 | scaffold, toolchain | 组装方案 | license, approval | `--apply` + 批准 |
| `wf-project-deploy/plan` | 给出部署方案 | 2 | deploy_runtime, reverse_proxy | 部署方案 | environment, rollback | 无 |
| `wf-project-deploy/apply` | 执行部署 | 2 + 批准 | deploy_runtime, reverse_proxy/managed_platform | 执行结果 | approval, health | 批准 |

规则：

- 每模式达到 minTools；
- 主工具可用时不得用内置工具当主流程；
- 主备切换必须记录降级；
- 交付时每个槽位至少有一个 measured active 适配器。

---

## 九、能力槽

| 槽位 | 用途 | 必需 actions | I/O 契约 | 权限 | fallback |
|---|---|---|---|---|---|
| web_search | 通用搜索 | search | query → results[] | read-only | alternate search |
| web_extract | 正文抽取 | extract | url → text/metadata | read-only | alternate extract |
| project_search | 项目发现 | search, lookup | query/url → candidates[] | read-only | alternate project source |
| package_meta | 包/仓库元数据 | lookup | package/repo → metadata | read-only | alternate metadata |
| package_security | 许可/漏洞/健康 | score, scan | package/repo → security report | read-only | alternate scanner |
| repo_ingest | 仓库转上下文 | ingest | repo/path → context | read-only | Read/Glob |
| code_graph | 代码图/架构 | index, query, impact | repo → graph results | read-only | Grep/Glob |
| dependency_graph | 依赖与边界 | graph | repo → dependencies | read-only | Grep/Glob |
| structural_search | 结构搜索 | search, extract | pattern → matches | read-only | Grep |
| repo_fetch | 取仓库子集 | fetch | repo/subpath → files | write to run/temp | built-in git |
| license_sbom | 许可/SBOM | scan | repo → licenses/sbom | read-only | package-manager native |
| scaffold | 模板/脚手架 | render | template/params → project | write to project | manual template |
| toolchain | 工具链初始化 | init | project → toolchain files | write to project | native CLI |
| deploy_runtime | 运行时/服务 | plan, apply | project → service config | write/deploy | manual commands |
| reverse_proxy | 反向代理 | plan, apply | service → proxy config | write/deploy | manual config |
| managed_platform | 托管部署 | plan, apply | project → deployment | write/deploy | local deploy |
| ledger | 写账本 | commit, validate | run/evidence/result → files | write to run | none |

---

## 十、工具选型与适配

> 工具选择在开发阶段完成；计划只列候选池与选型标准。

### 10.1 候选池

| 槽位 | 候选池 |
|---|---|
| web_search | Tavily / Exa / Doubao |
| web_extract | Firecrawl / Jina |
| project_search | GitHub API / Exa / GitHub MCP |
| package_meta | GitHub API / ecosyste.ms / Libraries.io |
| package_security | OpenSSF Scorecard / OSV-Scanner / Syft / Trivy |
| repo_ingest | gitingest / code2prompt |
| code_graph | codebase-memory-mcp / xerj / CodeGraphContext |
| dependency_graph | dependency-cruiser / pydeps / import-linter / madge / go-arch-lint |
| structural_search | ast-grep / tree-sitter |
| repo_fetch | degit / git sparse-checkout |
| license_sbom | license-checker / pip-licenses / reuse / Syft |
| scaffold | copier / degit / cookiecutter |
| toolchain | uv / npm / pnpm |
| deploy_runtime | WinSW / Waitress / Caddy |
| reverse_proxy | Caddy |
| managed_platform | Vercel / Netlify / Cloudflare Wrangler / Azure CLI |
| ledger | internal |

### 10.2 选型标准

- 许可允许目标用法；
- Windows 可用；
- 免费额度/成本可接受；
- 凭据获取可行；
- 真实调用成功；
- 输出字段满足契约；
- 错误模式可映射；
- 有 fallback；
- 维护状态可接受；
- 安全评分可接受。

### 10.3 选型工作包

| 包 | 内容 | 量级 |
|---|---|---|
| WP5.0 选型与校准 | 候选、许可、OS、凭据、额度、实测、主备、落档 | L |
| WP5.1 适配器基座 | env、输入校验、超时/重试/熔断、信封、错误码、health | M |
| WP5.2 适配器开发 | 每槽位一个；认证、调用、归一化、写面 | L |
| WP5.3 适配器验证 | 正例/负例/失败注入/主备切换/密钥扫描 | L |
| WP5.4 registry/pending/panel | measured→active、待注册清单、健康矩阵 | M |

### 10.4 适配器 DoD

- manifest；
- 输入校验；
- 统一信封；
- 错误码；
- 超时/重试/熔断；
- health；
- 只写声明路径；
- 不泄漏密钥；
- 契约测试；
- TOOL.md。

---

## 十一、提示词系统

```text
prompt-blocks/
  core.md
  domain/<mode>.md
  output/<mode>.md
  tools/<slot>.md
  index/intake.md
  index/design.md
  index/communication.md
```

`render-prompt.py`：

- manifest + blocks → agent；
- `--check` 漂移；
- `--write` 备份后写入；
- 禁止手改 agent。

约束：

- 规范只存一份；
- 不做全局 skill 注册；
- 普通模式技能列表不变。

---

## 十二、账本与 gates

```text
.wf/runs/<run>/
  run.json
  evidence.json
  result.md
```

agent 无 Write/Edit；`wf-tool ledger commit` 写入。

gates：ledger-schema、evidence、source-tier、file-line、license、security、budget、approval。

---

## 十三、面板（完整版）

1. 管线/模式编辑；
2. 提示词编辑 + 预览 + render；
3. 工具流程编辑：槽位、主备、actions、minTools；
4. 待注册工具清单：URL、env、额度、是否要卡、状态；
5. 能力索引：管线×模式×槽位×适配器×健康×额度×许可；
6. 索引层页面：Expectation Spec、Work Order、Catalog、Recommendation、Decision Ledger；
7. 健康矩阵与渲染检查；
8. 安全：不存密钥、不执行管线、不自动安装、不自动改普通配置、写前校验+备份。

---

## 十四、插件包与安装

```text
wf-agent-workflow/
  plugin.json
  install.ps1
  health.ps1
  uninstall.ps1
  rollback.ps1
  commands/wf.md
  commands/wf-index.md
  agents/
  workflows/
  pipelines/
  capabilities/
  tools/
  prompt-blocks/
  panel/
  guardrails/
  schemas/
  golden-set/
  lessons/
  docs/
```

安装契约：

- 独立 configDir；
- 正常配置只写 `commands/wf.md` + `permissions.deny:["Workflow"]`；
- 普通配置无 wf-*；
- agent hook 只绑 wf agent；
- 安装/卸载/升级由用户运行。

---

## 十五、权限与隔离

- 双轨；
- agent 正文 = 提示词；
- tools = 物理白名单；
- agent 级 PreToolUse hook；普通模式零 hook；
- hook 只放行 `wf-tool` / `wf-run`（按 agent 角色）；
- agent 无 Write/Edit/Task/Workflow；
- 凭据只从环境变量读；
- apply/deploy 批准。

---

## 十六、失败隔离与诊断

| 故障 | 隔离 |
|---|---|
| 搜索 provider 挂 | 主→备→blocked |
| 代码图缺失 | fallback/blocked |
| 适配器崩溃 | dispatcher 捕获，错误信封 |
| 账本写入失败 | fail closed，不输出 |
| hook 解析失败 | deny |
| 面板崩溃 | 不影响 Kernel |
| registry 损坏 | 启动拒绝 |
| 提示词漂移 | render --check 失败 |
| 索引层调管线失败 | 对话继续，反馈 blocked/partial |

诊断：`wf-tool --verbose`，仅人工/health。

---

## 十七、能力目标与指标

七类领域能力：获取、解读、评估、拆分、复用、组装、部署。

系统能力：需求对接、方案表达、证据、工具插拔、权限、失败降级、可演进。

指标：

- 选择准确率（手工选择记录）；
- 需求复述与确认率；
- 方案完整率；
- 证据完整率；
- 工具成功率/降级率；
- 账本合格率；
- 人工纠正次数；
- 隔离/插拔/安全测试；
- 交流质量测试通过率。

---

## 十八、工作分解与分工

| 包 | 内容 | 依赖 | 量级 |
|---|---|---|---|
| WP0 | 契约与 schema | 无 | M |
| WP1 | dispatcher + registry | WP0 | M |
| WP2 | ledger + gates | WP0 | M |
| WP3 | hooks/权限 | WP0, WP1 | S–M |
| WP4 | prompt blocks + render | WP0 | M |
| WP5.0 | 工具选型与校准 | WP0 | L |
| WP5.1 | 适配器基座 | WP0, WP1 | M |
| WP5.2 | 17 槽适配器 | WP5.0, WP5.1 | L |
| WP5.3 | 适配器验证 | WP5.2 | L |
| WP6 | 5 管线/9 模式集成 | WP1–WP5 | L |
| WP7 | 索引层 | WP0, WP1, WP6 | L |
| WP8 | 面板完整版 | WP1, WP2, WP7 | L |
| WP9 | 安装/health/uninstall/rollback | WP1–WP8 | M |
| WP10 | 测试/golden set/shadow/失败注入 | 全部 | L |
| WP11 | 文档 | 全部 | S–M |
| WP12 | 流程自动化 | 延期 | — |
| WP13 | 记忆 | 延期 | — |

波次：

```text
Wave 1: WP0
Wave 2: WP1, WP2, WP4
Wave 3: WP5.0, WP5.1, WP3
Wave 4: WP5.2, WP5.3
Wave 5: WP6, WP7
Wave 6: WP8, WP9
Wave 7: WP10, WP11
```

文件所有权：

- 内核：capabilities/tools/ledger/hooks/schemas；
- 选型：registry/pending-tools；
- 适配器：tools/<slot>/，一人一目录；
- 管线/提示词：pipelines/prompt-blocks/agents；
- 索引层：index/；
- 面板：panel/；
- 安装：install/health/uninstall/rollback；
- 测试：tests/golden-set。

---

## 十九、验收

| 验收 | 判据 |
|---|---|
| 全管线 | 5 管线/9 模式端到端 |
| 全工具槽 | 17 槽 registry + 主备 |
| 工具选型 | 每槽有选型记录、实测、fallback |
| 适配器 | manifest/信封/错误码/health/测试 |
| 工具优先 | minTools；无内置主流程 |
| 组装优先 | 无新业务实现 |
| 账本 | 三文件 + gates |
| 权限 | agent hook；普通模式零 hook |
| 提示词 | render --check 全绿 |
| 面板 | 编辑/待注册/健康/索引页完整 |
| 安装 | install/health/uninstall/rollback |
| 隔离 | 普通模式无痕 |
| 失败隔离 | 单适配器失败不拖垮管线 |
| 索引层 | Expectation Spec/Work Order/方案/证据/决策记录 |
| 交流质量 | 复述/≤3问/非目标/备选/验收/出处 |
| 成本 | 额度可见；耗尽降级 |
| 记忆 | 不实现，接口预留 |
| 自动化 | 不实现 |

---

## 二十、风险

| 风险 | 缓解 |
|---|---|
| 范围大 | 契约先冻结、波次并行、每槽位至少一个实测适配器 |
| 工具不可用 | 主备/阻塞/待注册清单 |
| 索引层变万能层 | IDX 约束、只读管线、无自动执行 |
| 交流规范不可测 | 交流质量测试 |
| 面板配置漂移 | schema + 备份 + render check |
| 单点故障 | 适配器隔舱/熔断/账本 fail closed |
| 过度抽象 | 17 槽按真实能力；未出现第二消费者不拆契约 |
| 过度优雅 | 深模块 + 显式账本 + 失败可归因 |
| 托管部署账号 | 本地 Windows 先行；托管适配器待定 |

---

## 二十一、延期与开放决策

### 延期

- 流程自动化；
- 记忆能力。

### 开放决策（开发阶段）

- 每槽位最终工具；
- package_meta 首选；
- code_graph 首选；
- deploy_runtime 首选；
- managed_platform 是否首批；
- project_search REST vs MCP；
- minTools 校准。

`✶ Insight ─────────────────────────────────────`
- 需求对接的核心是“成品/功能/体验/边界”，不是“速度/成本/质量/风险”；后者是底线或约束。
- 计划只冻结接口与不变量；工具选型与适配是开发阶段的第一等工作量。
- 索引层是主模型与需求编译器；它通过 `wf-run` 获取证据，不直接调工具，不自动执行。
`─────────────────────────────────────────────────`
