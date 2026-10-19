# 混合检索与跨书实体对齐

## 1. 为什么加 embedding

原来的检索是 FTS5 + 词项计数，优点是透明、可解释，缺点是 OCR 文本里同一个概念
经常被断行、错字、空格或不同叫法打断。混合检索用两种信号互补：

- **BM25**：精确词、术语、数字、专名。可解释性最好。
- **embedding 余弦相似度**：字符 n-gram 与词级向量的模糊相似，容忍 OCR 噪声。
- **实体扩展**：问题里出现“降准”时，把“存款准备金率/央行/流动性”等跨书实体
  相关 chunk 加一点分。

默认后端是零依赖的 `local-hash-ngram-v1`（768 维，字符 2/3/4-gram + 英文词）。
它不是神经语义模型，不会理解反讽、隐喻或远距离同义关系；它的作用是稳定处理
OCR 噪声和中文分词缺失。需要真正语义向量时，可配置 OpenAI 兼容后端：

```powershell
$env:BOOKCOMPILER_EMBED_BASE_URL="http://127.0.0.1:11434/v1"
$env:BOOKCOMPILER_EMBED_MODEL="nomic-embed-text"
$env:BOOKCOMPILER_EMBED_API_KEY="..."
$env:BOOKCOMPILER_EMBED_DIM="768"

bookcompiler --db .bookcompiler/library.db embed --rebuild
```

远程失败时 `embed_pending()` 会回退到本地后端，并在返回结果里标记
`fallback=true` 和 `fallback_error`，不会静默假装远程成功，也不会把两套
向量混在同一个空间里。

### 1.1 只补当前检索需要的 chunk

`hybrid_search()` 发现目标 book 里有缺向量时，只对这次要扫的 chunk 调
`embed_pending(chunk_ids=...)`，不会因为少量缺向量重建整个书库。`embedding_stats(active_model)`
会按“检索实际使用的模型”报告 `embedded_chunks`、`missing_chunks` 和 `coverage`；
如果数据库里同时有本地 fallback 和远程模型的向量，不会拿最大表冒充当前模型。

## 2. 打分与可审计性

每条结果都返回 `score_breakdown`：

```json
{
  "bm25_raw": 91.92,
  "bm25": 1.0,
  "embedding": 0.3226,
  "entity": 0.7833,
  "quality": 1.0,
  "base_score": 0.71,
  "weights": {"bm25": 0.55, "embedding": 0.35, "entity": 0.10}
}
```

总分是归一化后的加权和，再乘以 `quality`。权重存放在
`evolution_state.retrieval_config`，只能通过受控进化提案修改，改动有快照和回滚。
`mode="lexical"` 可随时对比纯词法结果。

三个容易混淆的点：

1. **实体扩展是“多实体覆盖”而不是“有就加分”**。问题里检测到 3 个实体时，
   只命中 1 个的段落得到约 `0.35 + 0.65/3 = 0.5667`，命中 2 个得到约 `0.7833`，
   命中 3 个才得到 `1.0`。这样“债务 + 银行 + 准备金率”同时出现的段落会优先。
2. **词法扩展**：检测到的实体别名会以较低权重加入 BM25，所以“降准”可以召回
   明确写“存款准备金率”的段落；扩展词权重由 `lexical_expansion_weight` 控制。
3. **质量降权**：索引页（`参见/索引/index` 密集）和目录页（`专栏/目录/第X章` 密集）
   会被乘上 `quality < 1`。它们仍然保留在结果里，只是不会因为词多而排第一。

## 3. 跨书实体对齐

`entities align` 做四件事：

1. 从 agent-authored `BookCard.key_concepts`、`FrameworkCard.name/inputs/outputs`
   收集候选概念；
2. 先载入保守的别名组（央行/中国人民银行/PBoC、融资平台/城投平台/LGFV 等），
   再把候选合并到规范实体；
3. 扫描全部 chunk，记录 `entity_id -> chunk_id/book_id/surface/confidence`；
4. 在同一 chunk 内共现的实体之间写 `co_occurs` 关系，并写
   `book -> entity` 的 `discusses` 边。

实体合并只做三种保守匹配：完全同名、别名组、长度比例 >= 0.72 的包含关系。
它不会把“地方政府债务”和“地方政府债务风险”自动合并，也不会用 LLM 猜同义词。
这是有意的：错合并比不合并更难发现。

当前真实库（12 本书、5500 chunks）的结果（2026-10-18 重新对齐后）：

- 92 个规范实体
- 69 个跨书实体
- 9905 次原文提及
- 300 条共现关系
- 63 个别名组

`entities audit` 当前给出 5 个候选，全部是 `review_only`：

- 资产负债表 ↔ 央行资产负债表
- 土地出让 ↔ 土地出让收入
- 基础货币 ↔ 基础货币变动
- 影子银行 ↔ 影子银行监管
- 法治 ↔ 依法治国

这些是“ broader/narrower ”或近似重复的复核提示，不是自动合并结果。错合并会破坏
两个概念的出处，所以系统宁可把它们摆出来让人/agent 确认，也不猜。

## 4. 命令与 GUI

```powershell
bookcompiler --db .bookcompiler/library.db embed --local
bookcompiler --db .bookcompiler/library.db entities align
bookcompiler --db .bookcompiler/library.db entities audit --limit 10
bookcompiler --db .bookcompiler/library.db entities list --cross-book
bookcompiler --db .bookcompiler/library.db entities show <entity_id>
bookcompiler --db .bookcompiler/library.db retrieval --query "降准与地方债务" --diagnostics
```

GUI 的“实体”页可以搜索实体、查看别名/跨书提及/共现关系，跑混合检索探针，
并点“近似重复审计”查看 `review_only` 候选。“补齐嵌入”只补缺失 chunk，
不会重复计算已存在的向量。

## 5. 已知限制

- 本地 embedding 不是语义模型，不能替代 LLM 判断。
- 实体对齐是规则 + 别名，不是完整本体；新领域需要补充别名组或人工确认。
- `co_occurs` 只表示同一 chunk 出现，不是因果；`discusses` 也只表示书里提到该实体。
- 目录/索引降权是启发式，不能保证所有 OCR 结构页都被识别。
- 共现不是因果关系，`co_occurs` 只表示同一 chunk 出现。
- 目前没有“旧结论被新证据取代”的自动 supersession；这需要版本化的主张级结构。
- OCR 重复列和乱码仍会影响提及计数；引用校验只能证明“原文里有这句话”，
  不能证明 OCR 识别语义完全正确。
