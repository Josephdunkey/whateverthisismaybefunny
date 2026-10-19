# GraphRAG sidecar

## 1. 定位

这是**轻量、确定性的 GraphRAG**，不是 Microsoft 的全量 LLM GraphRAG。它复用主库已有的实体、实体提及、claim、claim 关系、框架和 chunk，生成一个独立 SQLite：

```text
.bookcompiler\library.graph.db
```

构建过程不修改 `library.db` 的任何书、chunk、claim 或 embedding。

## 2. 图里有什么

- 节点：book / framework / claim / entity / chunk
- 边：`has_framework`、`has_chunk`、`supported_by`、`mentions`、`about_subject`、`about_object`、claim 关系、实体关系、`co_mentions`、`about`
- 社区：
  - 每本书的实体社区（书内共现）
  - 跨书桥接实体社区（出现在 2 本以上书的实体）

社区是上下文地图，不是因果断言。

## 3. 查询

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db graphrag build
& $py -m bookcompiler --db .bookcompiler\library.db graphrag status
& $py -m bookcompiler --db .bookcompiler\library.db graphrag query `
  --query "央行降准、地方财政与银行信贷扩张" --mode hybrid --limit 8
& $py -m bookcompiler --db .bookcompiler\library.db graphrag communities
```

`--mode hybrid` 返回三个通道：

- `hybrid`：BM25 + BGE embedding + 实体扩展
- `graph`：以 hybrid 的 top chunks 为锚点，沿实体/claim/框架边做 2-hop 扩散；返回的是邻居 chunk，不重复 hybrid 自己的命中
- `fused`：RRF（默认 k=60，graph 权重 0.9（略低于 hybrid，避免图邻居压过直接命中））

主分析链路 `create_analysis` 已经使用 fused retrieval；graph 缺失或损坏时自动回退 hybrid，不会让分析失败。

## 4. 什么时候重建

`graphrag status` 会返回 `stale`。以下情况会 stale：

- 新书 ingest
- claim / entity / entity_relation 变化
- chunk 变化

`create_analysis` 会在图不存在或 stale 时自动重建；也可以显式 `graphrag build`。当前 16 本书、8,741 chunks 的图包含 10,689 nodes / 29,407 edges / 17 communities。

## 5. 边界

- 不是 LLM 自动抽取实体；实体来自现有的实体对齐/claim 流程。
- 不是全图神经网络；社区是确定性的书内共现 + 跨书桥接。
- 不是替代 hybrid；它是第二召回通道，最终仍由 RRF 融合。