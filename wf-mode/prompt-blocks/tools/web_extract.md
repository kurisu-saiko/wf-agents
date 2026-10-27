# 工具：web_extract

调用：

```text
python "D:/claude-code/workflow/wf-mode/tools/wf-tool.py" web_extract extract --url "https://..."
```

输入：

- `url`：http/https URL。

输出 `data`：

```json
{
  "url": "https://...",
  "title": "...",
  "text": "正文，最多保留前 20000 字符",
  "metadata": {"provider": "firecrawl|jina", "fetchedAt": "..."}
}
```

规则：

- 只抓正文，不写文件；
- 主适配器不可用时自动走备选；
- 抓不到正文时标 `blocked` 或换等价已知来源，不能用摘要补位。
