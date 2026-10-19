# 真实书库状态（D:\fanshu → .bookcompiler/library.db）

## 总览

- 已 ingest：16 本 OCR 书（`.txt`），**16 本全部 `compiled`**。
- FrameworkCard：97 个；全部 16 本 `validate` 为 **0 error / 0 warning**。
- 实体：155 个规范实体、108 个跨书实体、14,740 次提及、300 条关系、63 个别名组。
- 片段：8,741 个 chunk；Embedding 8,741/8,741 已建本地 512 维向量，`missing_chunks=0`、`coverage=1.0`。
- 命题：1,680 条 claims（14 本书抽出；2 本因文本结构未产出可用 claim）。
- GraphRAG sidecar：10,689 nodes、29,407 edges、17 communities。
- 读书方式：`book_learn` / `compile-llm` 从全书均匀抽样 28–36 个证据块；引用逐字回源校验。**这是代表样本阅读，不是逐页精读。**
- 没有自动下载任何书；所有书来自用户本地 `D:\fanshu`。

## 已深度编译的书

| book_id | 书名 | 作者 | 框架数 |
|---|---|---|---|
| `976b3c244642d321` | 中央银行与货币供给 | 盛松成、翟春 | 3 |
| `24617d60273da367` | 以利为利：财政关系与地方政府行为 | 周飞舟 | 3 |
| `a7086a05970476d8` | 稳定不稳定的经济：一种金融不稳定视角 | 海曼·P·明斯基 | 3 |
| `03576cf3e546ced0` | 当代中国政府与政治 | 景跃进、陈明明、肖滨 | 3 |

每个框架都带 exact quote、chunk_id、chapter、page；`validate --book <book_id>` 返回 `[]`。

深度编译 patch 位于：

```text
examples/real_library/976b3c244642d321.json
examples/real_library/24617d60273da367.json
examples/real_library/a7086a05970476d8.json
examples/real_library/03576cf3e546ced0.json
```

## 已 ingest 但未深度编译的书

- 伟大的博弈：华尔街金融帝国的崛起 — 约翰·S·戈登
- 中国的经济制度 — 张五常
- 宏观经济学二十五讲：中国视角 — 徐高
- 货币数量、利率调控与政策转型 — 伍戈、李斌
- 信用创造、货币供求与经济结构 — 李斌、伍戈
- 这次不一样：八百年金融危机史 — 莱因哈特、罗格夫
- 货币、银行信贷与经济周期 — 赫苏斯·韦尔塔·德索托
- Principles for Navigating Big Debt Crises — Ray Dalio

这些书只完成 ingest，没有经过 agent 深度编译成框架。它们可以被底层检索/GUI 探针搜到，
但 `book_recall` / `book_analyze` 不会把它们当作“已学会”的证据；回答时不能引用它们
冒充读过的书。

## 真实分析样例

- analysis_id：`42450cb02344ffe7`
- 问题：假设央行降准释放流动性，同时地方政府通过融资平台和土地出让维持基建投资，并要求银行支持地方债务化解。分析风险是否从财政转移到银行体系。
- 模式：`books`，选择 `specified`（4 本书 + 12 个框架）
- 状态：`complete`
- 引用：17 条，全部通过 `validate --analysis`，返回 `[]`
- 渲染文件：`.bookcompiler/real-analysis.md`

## 如何自己检查

```powershell
bookcompiler --db .bookcompiler\library.db books
bookcompiler --db .bookcompiler\library.db validate --book 976b3c244642d321
bookcompiler --db .bookcompiler\library.db validate --analysis 42450cb02344ffe7
bookcompiler --db .bookcompiler\library.db show 24617d60273da367
bookcompiler --db .bookcompiler\library.db dashboard --out .bookcompiler\library-dashboard.md
```

## 诚实说明

OCR 文本存在重复栏、错字和断行。当前校验能证明“这句话确实出现在源文本中”，但不能证明 OCR 的每个字都正确。深度编译的框架是 agent 基于这些引用写的，属于 medium confidence；不应把 GUI 或框架卡当成自动生成的法律/投资结论。

## 当前权威信息源缺口

书库有中央银行、财政、政治法律教材，但没有以下几部一手法规。对“央行降准后银行信贷是否必然扩张”这类问题，`source-gaps` 会提示：

- 《中华人民共和国中国人民银行法》
- 《中华人民共和国商业银行法》
- 《中华人民共和国银行业监督管理法》

它只给下载与入库提示，不会自动下载，也不会把提示写成引用。拿到官方现行有效文本后，按提示的 `bookcompiler ingest` 命令入库，再走 `export-text → compile → validate`，下一轮分析才能把这些法规作为证据使用。