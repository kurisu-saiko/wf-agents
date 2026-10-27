# web_extract

网页正文抽取。Firecrawl 主，Jina Reader 备。

## 动作

### extract

输入：

```json
{"url": "https://..."}
```

输出：

```json
{
  "url": "https://...",
  "title": "页面标题（可能为空）",
  "text": "正文前 20000 字符",
  "metadata": {
    "provider": "firecrawl|jina",
    "fetchedAt": "...",
    "publishedTime": "可选"
  }
}
```

### health

输入：无。输出 provider 是否配置。

## 凭据

- `FIRECRAWL_API_KEY` 或 `FIRECRAWL`（主）
- `JINA_API_KEY` 或 `JINA`（备，可省略；Jina Reader 有免费额度）

## 失败

- Firecrawl 无密钥 → 自动尝试 Jina；
- 两者都失败 → `FALLBACK_EXHAUSTED`；
- 不把网页原文写入文件，只返回给调用方。

## 边界

- 只读；不写文件；
- 不把 HTML 原样塞进账本，正文截断到 20000 字符。
