# 第一阶段执行记录

日期：2026-10-27  
位置：`D:/claude-code/workflow/wf-mode/`

## 一句话

最小垂直链路已经落地：`wf-tool → 适配器 → wf-run → 账本 → gates → 结果`。对方四个模块未交付前，用 `tools/mocks/` 占位；交付后按接口替换。

## 目录与注释

```text
workflow/wf-mode/
  registry.yaml                     # 电话簿：登记 3 个能力槽 + ledger
  contracts/
    tool-envelope.schema.json       # 所有工具返回的统一 JSON
    adapter-manifest.schema.json    # 每个适配器必须声明什么
    registry.schema.json            # 电话簿格式
    pipeline.schema.json            # 工序单格式
    run.schema.json                 # run.json 格式
    evidence.schema.json            # evidence.json 格式
    gate-contract.md                # gates 检查项与错误码

  tools/
    wf-tool.py                      # 唯一工具入口：list/health/<slot> <action>
    wf-run.py                       # 执行 wf-retrieval/verify（手动端到端/测试）
    errors.py                       # 统一 ToolError
    http_client.py                  # 薄 HTTP 客户端，不记录密钥
    util.py                         # UTC 时间、JSON 写入、截断
    mocks/
      ledger.py                     # 假账本：只写 .wf/runs/<run>/ 三文件
      render_prompt.py              # 假拼装器：拼 prompt blocks
      gates.py                      # 假质检：evidence/source-tier/ledger/prompt
    adapters/
      web_search/                   # Tavily 主、Exa 备
      web_extract/                  # Firecrawl 主、Jina 备
      project_search/               # GitHub API

  pipelines/wf-retrieval/
    pipeline.yaml                   # 1 条管线：minTools=2，gates=4

  prompt-blocks/
    core.md
    domain/retrieval.md
    output/retrieval.md
    tools/web_search.md
    tools/web_extract.md

  agents/wf-retrieval.md            # 已改为通过 wf-tool 调工具；不再直接 Write
  workflow/hooks/wf_pipeline_gate.py# wf-retrieval 只放行 wf-tool

  tests/
    fixtures/                       # 合法/非法信封、run、evidence
    integration/                    # 30 个测试
```

## 已实现的行为

- `wf-tool list`：列出槽、动作、主备、manifest 版本。
- `wf-tool health`：检查密钥/provider 状态；`web_extract` 在 Firecrawl 缺密钥时显示 `degraded`（Jina 可用）。
- `wf-tool web_search search`：Tavily 主、Exa 备；主失败自动降级并写 `degradation`。
- `wf-tool web_extract extract`：Firecrawl 主、Jina 备。
- `wf-tool project_search search/lookup`：GitHub API，无 token 也可用。
- `wf-tool ledger commit`：只写 `.wf/runs/<run>/{run.json,evidence.json,result.md}`。
- `wf-tool gates check`：缺来源、缺原文、verified 缺日期、conflict 少于两个来源时拒绝。
- `wf-run`：搜索 → 抓正文 → 生成证据 → gates → 写账本 → 输出一次结果；gates 失败时只输出拒绝说明。
- hook：`wf-retrieval` 只允许 `python .../tools/wf-tool.py ...`；拒绝 curl/git/Write/越权路径。

## 验收结果

| 项 | 结果 |
|---|---|
| contracts + schema | 6 个 schema + gate 契约已落地 |
| 集成测试 | `30 passed` |
| 真实 Tavily 搜索 | 成功：返回 3 条结果 |
| 真实 Firecrawl 抽取 | 成功：example.com 正文 |
| 真实 GitHub 项目搜索 | 成功（`searxng/searxng`，38911 stars，带 token） |
| 真实正例管线 | 成功跑通：4 次工具调用，gates 全过，写三文件；状态 `partial`，3 条证据均因页面无发布日期标 `unverified` |
| 真实负例管线 | 成功：无密钥 → `blocked`，仍写三文件账本 |
| hook 越权 | 测试覆盖 curl/git/Write/错误路径/未注册动作 |
| 无密钥入账本 | 测试覆盖 |

环境变量兼容：`TAVILY` / `EXA` / `FIRECRAWL` / `JINA` / `GITHUB_MCP_TOKEN` 这些短名称已被适配器识别，同时继续支持 `*_API_KEY` 形式。

## 命令

```bash
cd D:/claude-code/workflow/wf-mode

python tools/wf-tool.py list
python tools/wf-tool.py health
python tools/wf-tool.py project_search search --query "searxng" --max-results 3
python tools/wf-tool.py web_extract extract --url "https://example.com"
python tools/wf-tool.py web_search search --query "searxng" --max-results 5

python tools/wf-run.py --task "SearXNG 最新版本" --run-dir ".wf/runs/demo" --json
python -m pytest tests/integration -q
```

## 对方模块替换方式

1. 对方交付 `ledger.py` → 放到 `tools/ledger.py`，`wf-tool` 会优先加载它，不存在时回退 `tools/mocks/ledger.py`。
2. 对方交付 `render_prompt.py` → 放到 `tools/render_prompt.py`。
3. 对方交付 `gates.py` → 放到 `tools/gates.py`。
4. 接口保持：`ledger.commit/validate`、`render_prompt.check/write/render`、`gates.check`。
5. 替换后跑同一组 `tests/integration`，管线代码不改。

## 未做（按计划后置）

- 其余 4 条管线、9 模式；
- 剩余 14 个能力槽；
- 索引层；
- 面板联调；
- 安装/健康/卸载/回滚；
- eval/analyze/build/deploy；
- 流程自动化与记忆。

## 下一步

1. 提升证据质量：当前 `wf-run` 是机械执行器，页面元数据没有日期时只能标 `unverified`；下一步让 agent 从正文中提取发布日期，并选择更像证据的原文片段（而不是页面导航）。
2. 对方交付后按模块替换 mock：`ledger.py`、`render_prompt.py`、`gates.py` 放到 `tools/`，复跑同一组测试。
3. 建立 golden set：固定几个查询，比较真实搜索 + 抽取的覆盖度、日期命中率和 gates 拒绝率。
4. 再进入后续阶段：其余管线、剩余能力槽、索引层。
