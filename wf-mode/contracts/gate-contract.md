# Gates 契约（Phase 1）

Gates 是管线的质检员：证据不够、来源不完整、账本不合规时，不允许输出结论。

## 接口

```text
gates.check(run, evidence, names) -> {
  "ok": true|false,
  "errors": [
    {"gate": "evidence", "code": "GATE_SOURCE_MISSING", "message": "...", "itemId": "E3"}
  ]
}
```

- `run`：`run.json` 的对象。
- `evidence`：`evidence.json` 的对象。
- `names`：要执行的 gate 名称列表；未知 gate 直接报错，不静默跳过。
- 返回 `ok=false` 时，管线必须把 `run.status` 设为 `blocked`，`result.md` 只输出拒绝说明，不得输出结论。

## Gate：evidence

| 错误码 | 条件 |
|---|---|
| `GATE_EVIDENCE_EMPTY` | `items` 为空 |
| `GATE_TOO_MANY_ITEMS` | `items` 超过 40 条 |
| `GATE_STATEMENT_EMPTY` | 命题为空 |
| `GATE_SOURCE_MISSING` | `verified` 条目没有来源 |
| `GATE_QUOTE_MISSING` | 来源的 `quote` 为空或超过 500 字符 |
| `GATE_DATE_MISSING` | `verified` 条目的外部 URL 来源没有 `date`；无日期只能标 `unverified` |
| `GATE_CONFLICT_SOURCES` | `conflict` 条目少于两个来源 |

## Gate：source-tier

| 错误码 | 条件 |
|---|---|
| `GATE_TIER_INVALID` | `tier` 不是 `primary` 或 `secondary` |
| `GATE_LOCATOR_MISSING` | 来源既没有 `url` 也没有 `path` |

## Gate：ledger

| 错误码 | 条件 |
|---|---|
| `GATE_LEDGER_INVALID` | `run`/`evidence` 缺少必需字段 |
| `GATE_LEDGER_FILES` | 运行目录缺少 `run.json`/`evidence.json`/`result.md`，或出现额外文件 |

## Gate：prompt

| 错误码 | 条件 |
|---|---|
| `GATE_PROMPT_MISSING` | 管线声明的 prompt block 文件不存在 |
| `GATE_PROMPT_EMPTY` | prompt block 是空文件 |

## 错误码汇总

```text
GATE_EVIDENCE_EMPTY
GATE_TOO_MANY_ITEMS
GATE_STATEMENT_EMPTY
GATE_SOURCE_MISSING
GATE_QUOTE_MISSING
GATE_DATE_MISSING
GATE_CONFLICT_SOURCES
GATE_TIER_INVALID
GATE_LOCATOR_MISSING
GATE_LEDGER_INVALID
GATE_LEDGER_FILES
GATE_PROMPT_MISSING
GATE_PROMPT_EMPTY
GATE_UNKNOWN
```

## 不变量

1. 未知 gate 名称 = 错误，不是“通过”。
2. 空来源、空原文、无日期 URL 不能算 `verified`。
3. 冲突必须并列，不允许 gates 替人裁决。
4. Gates 只读，不写账本；写账本由 `ledger` 槽负责。
5. Gates 失败时仍然写账本，便于审计；但结论必须被拒绝。
