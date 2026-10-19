# BookCompiler 改进研究报告

日期：2026-10-18
范围：代码、真实数据库、检索性能、评测、Hermes/Hindsight 对接、GitHub 同类方案
说明：本轮只做研究，没有修改业务代码、没有重新 ingest、没有 commit。

---

## 0. 一句话结论

现在已经是一个能跑通的「书库 + 框架卡 + 混合检索 + 引用 + 受控演化」原型，
但**回答链路仍然主要是 RAG**：真正花了很多功夫抽出来的 claims、实体关系，
还没有进入 `book_plan / book_analyze`。所以它目前是「加强版 RAG」，
而不是「读过的书变成 agent 可自调用的能力」。

最该修的不是再换一个更花的 RAG 算法，而是三件地基：

1. 状态语义可信（导入 ≠ 学会）；
2. 知识层真正接入回答（claims / 关系 / 冲突）；
3. 数据质量、评测、性能。

---

## 1. 本次实际验证到的现状

数据库 `C:\Users\mybea\projects\bookcompiler\.bookcompiler\library.db`：

- books: 12
  - compiled: 4（卡片状态均为 verified）
  - ingested: 8
- chunks: 5,500
- chunk_embeddings: 11,000
  - `D:\models\bge-small-zh-v1.5`: 5,500 条，512 维
  - `local-hash-ngram-v1`: 5,500 条，768 维
- frameworks: 12
- claims: 640
- claim_relations: 0
- entities: 92
- entity_mentions: 9,905
- entity_relations: 300，全部是 `co_occurs`
- entity_merge_candidates: 5 pending
- feedback: 0
- evolution_proposals: 0

测试与评测：

- 项目自带 48 个测试全部通过。
- 检索评测（12 条，k=3）：
  - lexical: hit@3=1.0, MRR=1.0, book_hit@3=1.0, 平均 218ms
  - hybrid: hit@3=1.0, MRR=1.0, book_hit@3=1.0, 平均 1,572ms
  - hybrid+rerank: hit@3=1.0, MRR=1.0, book_hit@3=0.9167, 平均 3,546ms
- `search_chunks` 实测：冷启动约 19 秒，热查询约 6 秒（开了 rerank）。
- `get_embedder()` 连续调用两次返回的不是同一个对象，说明每次都可能重新加载 BGE。

Hindsight：

- 服务健康。
- `hermes` bank: 1 条 fact。
- `bookcompiler` bank: 1 条 fact。
- 说明记忆通路是通的，但几乎没有真实沉淀。

---

## 2. P0：正确性问题（先修，成本低，收益大）

### P0-1 heuristic / draft 会被标成 compiled

位置：`src/bookcompiler/store.py` 约 473-478 行

```python
card_status = str(card.get("status", "draft"))
book_status = "compiled" if card_status in {"draft", "verified", "complete", "heuristic"} else "ingested"
```

问题：

- `draft`、`heuristic` 也会把书变成 `compiled`。
- `learned_book_ids()` 只认 `status='compiled'` 且有 framework 的书。
- 结果：一个很浅的启发式编译，也能进入「已学会」集合，被自动选书和回答使用。
- 这与 `docs/CODE-REVIEW.md` 里「heuristic compile 保持 ingested」的说法矛盾。

当前 4 本 compiled 书的卡片都是 `verified`，所以**现有数据没有被污染**；
但下一次 heuristic 编译就会破坏「导入 ≠ 学会」的可信度。

建议：

- 只有 `verified` / `complete` 才允许 `compiled`。
- `draft` / `heuristic` 保持 `ingested`，或单独状态 `heuristic`。
- 加回归测试：heuristic 编译后，`learned_book_ids()` 不包含该书。

### P0-2 重建 claims 会删掉人工复核结果

位置：

- `src/bookcompiler/claims.py` 的 `build_claims()`
- `src/bookcompiler/store.py` 约 994-1019 行 `replace_claims()`

当前逻辑：

```sql
DELETE FROM claims WHERE book_id = ?
```

然后重新插入。

后果：

- 人工标记的 `superseded`
- `dismiss_conflict`
- `claim_relations`
- 复核结论
- 后续 agent 的修正

都会在下一次 `claims build` 时被清掉。
`claim_evidence` / `claim_relations` 有 `ON DELETE CASCADE`，会一起丢。

建议：

- 重建时只替换「自动抽取且未复核」的 claims。
- 保留 `superseded` / `resolved` / 人工确认记录。
- 更稳的做法：claims 版本化，不物理删除。
- 加测试：重建后人工状态仍在。

### P0-3 用错 Python 会静默降级 embedding

这是本轮很关键的发现。

项目 venv 正常：

```text
C:\Users\mybea\projects\bookcompiler\.venv\Scripts\python.exe
numpy 1.26.4, scipy 1.13.1, sklearn 1.5.1, torch 2.5.1+cu121, transformers 4.57.3
BGE 可正常返回 512 维
```

系统 `python` 指向 `D:\anaconda`（numpy 2.5.3），会出现：

```text
ImportError: numpy.core.multiarray failed to import
```

`hybrid_search()` 捕获异常后会回退到 `local-hash-ngram-v1`：

- 不向用户报错；
- 检索悄悄换了向量空间；
- 同一个 query 的 top chunk 会变；
- 数据库里同时存在 BGE 512 和 hash 768 两套向量，掩盖问题。

这次 DB 里正好有 5,500 条 hash 向量，就是历史上某次降级留下的痕迹。

好消息：Hermes 的 MCP 配置已经写死项目 venv：

```yaml
command: 'C:\Users\mybea\projects\bookcompiler\.venv\Scripts\python.exe'
```

所以 Hermes 这条链路是安全的。风险在：

- 直接命令行 `python -m bookcompiler ...`
- GUI 启动脚本
- 其他集成
- 文档里没有写死解释器路径

建议：

- CLI / GUI / MCP / 文档全部固定项目 venv。
- 启动时检查 active embedding model 的覆盖率。
- fallback 必须显式警告，不能静默。
- 在 `retrieval` 返回里把 `embedding_model`、`embedding_covered`、`embedding_error` 展示到 GUI。
- 提供 `bookcompiler doctor`：检查解释器、numpy/torch、模型路径、向量覆盖率。

---

## 3. P1：知识层问题（决定它是不是「加强版 RAG」）

### P1-1 640 条 claims 质量很差

真实抽样：

```text
subject: 新编21世纪公共管理系列教材
predicate: condition
object: 当代中国政府与政治 Contemporary Chinese Government and Politics ...

subject: 授课教师
predicate: requires
object: 与本书 系/院主任: (系/院办公室章) 年 月 (签字)日

subject: 为了满足广大高校公共管理类专业的教学
predicate: requires
object: ,在历届教育部高等学校公共管理类学 科专业教学指导委员会...
```

统计：

```text
claims: 640
4 本书，每本恰好 160 条
entity_anchored: 264 / 640 (41%)
subject 长度中位数 5，最大 24
object 长度中位数 31，最大 224
object > 200: 2
包含目录/教材/出版社/签字/习题等表格痕迹: 14
subject 以「为了/本书/本教材/授课/教学/主编/著」开头: 8
predicate 只有 6 种：
  condition 221
  increase 133
  requires 117
  causes 109
  implies 44
  depends 16
claim_relations: 0
```

问题：

- subject 经常是半句话、OCR 断句、出版社/教材表格字段。
- object 经常是整句，不是可比较的短语。
- predicate 太粗，`condition` 占了三分之一。
- 教材表格、版权页、目录、习题、签字栏被当成知识。
- `_plausible()` 只过滤长度、数字比例和少量目录词，太弱。

建议：

- 规则抽取只做候选，不要直接入库为「知识」。
- 用 LLM + JSON Schema 做 claim 抽取/复核。
- 每条 claim 必须能逐字 quote 回查到 evidence chunk。
- subject 必须锚定到实体或明确短语。
- predicate 使用有限 schema：
  - causes
  - enables
  - constrains
  - increases
  - reduces
  - requires
  - depends_on
  - contradicts
  - supersedes
- object 限制为短语，不是整句。
- 增加质量分数和 review queue。
- 过滤教材表格、版权页、目录、习题、签字栏。
- 宁要 50-100 条高质量 claim，不要 640 条噪声。

### P1-2 claims / 实体关系没有进入回答链路

位置：`src/bookcompiler/analysis.py` 约 95-176 行

当前 `create_analysis()` 使用：

- frameworks
- `store.search_chunks(question, book_ids=..., limit=8)`
- framework citations
- 通用 `_conflicts()` 占位模板

**没有使用 claims、claim_relations、entity_relations。**

后果：

- 640 条 claims 目前基本是死数据。
- 92 个实体、300 条 co_occurs 没有真正影响分析。
- `_conflicts()` 只是模板文字，不是实际冲突检测。
- 回答仍然是「框架 + 8 个 chunk」，所以像 RAG。

建议：

- `book_plan` / `book_analyze` 增加 claim 检索：
  - query 实体
  - predicate family
  - object embedding
- 把支持 / 反驳 / 条件差异放进 AnalysisPacket。
- 最终回答引用 claim 对应的逐字证据。
- `_conflicts()` 改成基于 claim/entity 的真实冲突候选。
- 输出结构建议：
  - 结论
  - 机制链（claim → claim）
  - 支持证据
  - 反例/边界条件
  - 跨书分歧
  - 不确定性

这是从「加强版 RAG」走向「知识系统」的关键一步。

### P1-3 实体关系只有共现，没有语义关系

当前：

```text
92 entities
69 cross-book
9,905 mentions
300 relations
全部 co_occurs
```

top entities：

```text
通货膨胀 1182 mentions / 10 books
中央银行 1109 / 11
货币政策 925 / 11
流动性 649 / 10
银行体系 440 / 9
商业银行 421 / 9
经济增长 398 / 12
信贷扩张 367 / 7
```

5 个 pending merge candidates：

```text
资产负债表 ↔ 央行资产负债表
土地出让 ↔ 土地出让收入
基础货币 ↔ 基础货币变动
影子银行 ↔ 影子银行监管
法治 ↔ 依法治国
```

问题：

- `co_occurs` 只表示同一 chunk 出现，不是因果、监管、融资、约束、替代。
- 不能直接当知识图谱用。
- 自动合并「影子银行」和「影子银行监管」会把上下位概念混在一起。

建议：

- 增加关系抽取：
  - regulates
  - finances
  - causes
  - constrains
  - depends_on
  - substitutes
- 关系必须带 evidence chunk/page。
- 跨书实体合并要有人/agent 确认。
- 不要自动合并上下位概念。

---

## 4. P2：检索、评测、性能

### P2-1 检索 benchmark 太简单，指标虚高

位置：`src/bookcompiler/eval_retrieval.py`

现状：

- 只有 12 条 case。
- 很多 expected_terms 直接出现在 query 里。
- `_contains()` 是 **any term**，命中一个词就算成功。
- 没有 answer-level 质量。
- 没有负样本。
- 没有跨书 multi-hop。
- 没有「应该回答没有证据」的案例。
- 没有中文改写/同义词/OCR 噪声。

所以 1.0 的 hit@k 不能证明「回答对」。

建议建 50-100 条中文事件级评测，至少包含：

- 原词查询
- 改写查询
- 只给新闻不给关键词
- 跨书多跳
- 负样本/无证据
- OCR 噪声
- 时间/版本冲突

评价指标：

- 证据召回
- 引用准确率
- 答案忠实度
- 冲突处理
- 校准
- 是否真的用了指定书

不要只用 hit@k；要做盲评 rubric。

### P2-2 性能问题

实测：

```text
get_embedder() 两次调用：same object = False
hybrid_search warm：约 1.5-1.8 秒（无 rerank）
hybrid_search warm：约 4.4-6.0 秒（有 rerank）
冷启动：12-19 秒
```

原因：

- `get_embedder()` 没有模块级单例，每次可能重新加载 BGE。
- `rerank_items()` 每次都 `CrossEncoderReranker()`。
- 每次 hybrid 检索读取全部 5,500 个 chunk。
- 解包全部向量。
- 重新算 BM25。
- 逐条算余弦。
- `select_books()` 对每本 learned book 各做一次 `search_chunks()`；4 本书就是 4 次全库扫描。书越多越慢，100 本时不可用。
- reranker 默认开启。

建议：

- `get_embedder()` 用模块级单例 / `lru_cache`。
- `CrossEncoderReranker` 单例。
- 缓存 query embedding。
- 缓存 chunk 向量矩阵（numpy float32，约 11MB）。
- 用 FTS / BM25 先召回 200-500 个候选，再算 embedding。
- `select_books()` 改成一次批量检索 + 按 book_id 聚合，不要每本书扫一遍。
- 大数据量再考虑 `sqlite-vec` / FAISS / LanceDB。
- 目标：warm query < 500ms，至少先做到 < 1 秒。
- reranker 默认关闭，先做 A/B 盲评。

### P2-3 reranker 默认开启，但证据不足

`.env`：

```text
BOOKCOMPILER_RERANK=1
BOOKCOMPILER_RERANK_MODEL=D:\models\bge-reranker-base
```

但：

- k=3 评测中 reranker 让 book_hit 从 1.0 降到 0.9167。
- 延迟从 1.57 秒增加到 3.55 秒。
- 没有证明答案质量变好。

建议：

- 默认关闭。
- 或只在 hybrid top 分数差距很小时 rerank。
- 先做 A/B 盲评。
- 不要因为「模型更大」就默认它是增益。

---

## 5. P3：自进化与 Hindsight

### P3-1 自进化闭环实际上没有跑起来

当前：

```text
feedback = 0
memory = 0
evolution_proposals = 0
claim_relations = 0
```

说明：

- 反馈表单存在。
- proposal 状态机存在。
- shadow/canary 代码存在。
- 但没有任何真实数据流过。

现在的「自进化」是：

> 有界配置演化 + replay gate

不是：

> 模型自己读书、自己发现知识、自己长出新能力。

建议：

- 先积累 30-50 条真实反馈。
- 覆盖不同错误类型：选错书、引用不相关、结论过度、忽略反例、答非所问。
- 跑一次 `evolution-propose`，看 proposal 是否有证据。
- 再跑 shadow/canary。
- 不要在没有反馈数据时宣称「自进化已生效」。
- 进化对象应该是：选书权重、框架排序、检索权重、claim 抽取提示词，而不是核心规则。

### P3-2 Hindsight 记忆没有被自动沉淀

当前：

```text
hermes bank: 1 条
bookcompiler bank: 1 条
```

BookCompiler 只在：

- `feedback`
- `hindsight-retain`

时写入。

Hermes 聊天里的用户纠正不会自动进入 BookCompiler 的 Hindsight bank。

实测：

- Hindsight server 健康。
- 用新 bank 写入中文偏好，可以 retain。
- 但 Hindsight 的 LLM 抽取会把中文事实整理成英文。
- 同步 retain 较慢，约几十秒。
- 现有 `bookcompiler` bank 里那条中文记忆在 API 中显示为乱码，需要复核。

建议：

- 增加「记住这条纠正」工具/技能指令。
- 当用户说「以后回答宏观问题时必须区分基础货币和信贷扩张」时，Hermes 调 `book_hindsight` 写入。
- 分析完成后，把「用户不接受的点」变成结构化 feedback。
- 不要让 Hindsight 存原文，只存教训/偏好/错误模式。
- 默认 async，不要阻塞回答。
- 检查并修复已有乱码记忆。

---

## 6. 架构层面：怎么才算「书是 agent 可自调用的能力」

建议把每本书做成三层，按需展开：

### L0 能力卡（路由层）

200-400 字，回答：

- 这本书能解决什么问题？
- 什么情况下该调用它？
- 什么情况下不该调用？
- 核心机制是什么？
- 与哪些书互补/冲突？
- 关键概念是什么？

用途：选书、选框架。不直接拿来回答。

### L1 结构化知识（推理层）

- claims（带逐字证据）
- 带类型的关系（causes / constrains / regulates ...）
- 时间有效性（valid_from / valid_to / supersedes）
- 跨书冲突候选

用途：机制链、冲突检测、跨书综合。

### L2 原文证据（引用层）

- chunks
- page / chapter
- 逐字 quote

用途：最终引用和核验。

当前链路基本是「L0 框架一句话 → L2 chunk」，跳过了 L1。
所以它像 RAG。把 L1 接进去，才会像「读过书的人在推理」。

另外两个关键能力：

1. **跨书综合**：同一 subject/predicate 下不同 object、polarity、conditions 的比较，才是多书相对于单书 skill 的真正优势。
2. **能力路由**：先选能力（书/框架），再加载细节，而不是每次把所有书都检索一遍。

---

## 7. GitHub 参考（可借什么，不借什么）

- **HKUDS/LightRAG**
  - 图 + 向量
  - 增量更新
  - 选择性删除
  - dual-level retrieval
  - 可借：增量图更新、低层/高层双检索
  - 不建议：整体替换现有存储

- **getzep/graphiti**
  - 事实有有效期
  - 旧事实失效但不删除
  - episode / provenance
  - 增量建图
  - 可借：`valid_from / valid_to / supersedes` 的事实生命周期
  - 与当前 claims 设计很接近

- **volcengine/OpenViking**
  - knowledge / memory / skills 放进虚拟文件系统
  - L0 摘要 / L1 概览 / L2 原文
  - 目录级检索
  - 已内置 Hermes 集成
  - 可借：L0/L1/L2 渐进披露
  - 注意：主项目 AGPLv3，不要盲目引入

- **vectorize-io/hindsight**
  - world facts / experiences / observations / mental models
  - recall 并行做 semantic / keyword / graph / temporal
  - RRF + cross-encoder rerank
  - 适合存「教训/偏好」，不适合替代书库原文

- **microsoft/graphrag**
  - 12 本书规模可能过重
  - 社区摘要计算成本高
  - 现阶段不建议先上

- **asg017/sqlite-vec**
  - 5,500 chunks 现在没必要
  - 先用 numpy 缓存矩阵 + FTS 候选召回更简单

- **RAPTOR**
  - 章节/全书层级摘要的概念可借
  - 官方实现较旧，不建议直接依赖

---

## 8. 建议路线图

### 第 1 步：P0（半天到 1 天）

1. 修 `save_book_card()` 状态语义。
2. 修 `replace_claims()` 不覆盖人工复核。
3. `get_embedder()` / `CrossEncoderReranker()` 单例。
4. 启动时检查 embedding 覆盖率，fallback 显式警告。
5. 加对应回归测试。

### 第 2 步：性能（1-2 天）

1. 缓存 chunk 向量矩阵。
2. FTS/BM25 先召回候选，再算向量。
3. `select_books()` 批量检索。
4. reranker 默认关闭，做 A/B。
5. 目标 warm < 1 秒。

### 第 3 步：知识层接入（2-4 天）

1. claims 检索进入 `book_plan` / `book_analyze`。
2. 真实冲突检测，替换 `_conflicts()` 模板。
3. 输出机制链和反例/边界。
4. 实体关系增加语义类型。
5. 跨书实体合并加确认。

### 第 4 步：数据质量（2-4 天）

1. LLM + JSON Schema 重抽 claims。
2. 逐字 quote 回查。
3. 质量分数 + review queue。
4. 先做 50-100 条高质量 claim 验证链路，再扩量。

### 第 5 步：评测与自进化（持续）

1. 50-100 条中文事件级评测。
2. 负样本、跨书多跳、OCR 噪声。
3. 盲评 rubric。
4. 30-50 条真实反馈。
5. proposal → shadow → canary。
6. Hindsight 自动沉淀纠正。

---

## 9. 现在不建议做的事

- 不要为了「更 RAG」而直接上 GraphRAG。
- 不要在 5,500 chunks 时引入 FAISS / sqlite-vec，收益不大。
- 不要自动合并所有实体候选。
- 不要在 claims 质量没修好前重抽 640 条并当成知识。
- 不要把 Hindsight 当书库；它存教训，不存原文。
- 不要在没有反馈数据时宣称「自进化已生效」。
- 不要把 12 本书说成「都学会了」；目前只有 4 本进入 learned 集合。
