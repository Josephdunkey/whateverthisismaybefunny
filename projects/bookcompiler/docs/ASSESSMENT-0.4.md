# BookCompiler 0.4 需求评估

日期：2026-10-18  
范围：`C:\Users\mybea\projects\bookcompiler` + `D:\hermes agent`

> 追加说明（2026-10-18 晚些）：新增九维读书评分、Obsidian 导出和 `book_reading_eval` 后，MCP 工具为 **16 个**，测试为 **60 passed**。下面表格保留 0.4 评估时的原始快照。

## 一句话结论

**核心链路已经打通：书库可以作为 agent 的可自调用能力，能读、能检索、能带逐字引用分析新闻，并且已经接进 Hermes。**
但“12 本书都学会了”不成立：目前是 **4 本深度编译 + 8 本仅 ingest**。  
它也不是“读一本书就自动变成领域专家”的魔法，而是“证据层 + 框架层 + 引用校验 + 受控进化”的可审计系统。

## 需求对照

| 你的要求 | 状态 | 证据 / 说明 |
|---|---|---|
| 读过的书作为 agent 的一个能力，而不是一本书一个 skill | **已达到** | 一个 `bookcompiler` MCP server + 一个 `book-library` 路由器技能；15 个工具共享同一书库 |
| agent 读书、学习 | **部分达到** | 12 本 ingest；4 本深度编译为 12 个 FrameworkCard；其余 8 本只是 `ingested` |
| 给新闻/事件后，像真人一样参照读过的一本或几本书回答 | **结构上达到** | `book_plan -> book_recall/book_analyze -> 逐字引用 -> validate`；Hermes 实测能引用第 277/298 页原文 |
| 经济 + 政治 + 法律多镜头 | **结构上达到** | 三 lens 的选书、冲突提示、法律免责声明都有；但法律类书覆盖很薄，不能当法律意见 |
| 自动推荐适合的书 | **已达到** | `book_plan` 三种模式：`auto` / `direction` / `books`，附推荐理由和覆盖缺口 |
| 展示学过哪些书、为什么选 | **已达到** | `book_library` 区分 learned/ingested；`book_plan` 返回 selection 和 rationale |
| 三种模式 + 用户同意门 | **已达到** | `direction` / `books` 必须先让用户选 `specified` / `specified+recommended` / `recommended` |
| 不人工校对 | **已达到但有边界** | 自动校验 quote/chunk/chapter/page；OCR 的语义错字仍无法自动证明 |
| 通用 agent 插件 | **已达到** | 标准 stdio MCP，不绑死 Hermes；Codex/Claude Desktop 等 MCP 宿主也能接 |
| 自进化 | **部分达到但真实** | 有界配置补丁 + replay gate + 快照/回滚；不改书卡、引用、prompt 或代码 |
| embedding 混合检索 | **技术达到** | BM25 + BGE bge-small-zh-v1.5（512 维）+ 实体扩展 + 质量降权；失败时回退本地 768 维 hash |
| 跨书实体对齐 | **保守达到** | 规则 + 别名组 + 共现；92 实体 / 69 跨书；5 个 `review_only` 审计候选，不自动合并 |
| Hermes 部署与对接 | **已达到** | `D:\hermes agent`，v0.22.2；MCP 15 工具；技能 enabled；DeepSeek 端到端实测 |

## 这一版实际做了什么

### 1. 混合检索真正接进分析链路

- `hybrid_search()` 默认使用 BM25 + embedding + 跨书实体扩展，返回
  `score_breakdown`：`bm25`、`embedding`、`entity`、`quality`、`base_score`、`weights`。
- `create_analysis()` 的补充证据也走 `store.search_chunks()`，默认是 hybrid，
  不是只走旧的 FTS。
- **多实体覆盖奖励**：问题检测到 3 个实体时，命中 1 个约 0.5667，命中 2 个约
  0.7833，命中 3 个才 1.0。这样“地方政府债务 + 银行体系 + 存款准备金率”同时出现的
  段落会排在只出现一个词的段落前面。
- **目录/索引降权**：OCR 的目录页（`专栏/目录/第X章` 密集）和索引页
  （`参见/索引/index` 密集）会被乘上 `quality < 1`，但不会从结果里消失。
- **chunk-scoped lazy backfill**：只补当前检索会扫到的缺失向量，不因少量缺向量重建全库。
- **按 active model 统计**：`embedding_stats(active_model)` 不再拿最大向量表冒充当前模型。
- **失败不混向量空间**：远程 embedding 失败时回退本地，并返回 `fallback_error`。

### 2. 跨书实体对齐 + 审计

- 从 BookCard / FrameworkCard / 别名组抽规范实体，扫描全部 chunk 记录
  `entity -> chunk/book/page`。
- 同 chunk 共现写 `co_occurs`；书与实体写 `discusses`。
- 别名拆分避免错误吞并：`土地财政` / `土地出让` / `土地出让收入`、
  `影子银行` / `影子银行监管`、`银行体系` / `商业银行` 等。
- `entities audit` 只给 `review_only` 候选，不自动合并。当前 5 个：
  资产负债表 ↔ 央行资产负债表；土地出让 ↔ 土地出让收入；基础货币 ↔ 基础货币变动；
  影子银行 ↔ 影子银行监管；法治 ↔ 依法治国。
- GUI 新增 `GET /api/entities/audit` 和“近似重复审计”按钮。
- `compile` 成功后会重新对齐实体，新概念自动进入图谱。

### 3. Hermes 对接

- 安装：`D:\hermes agent`，源码 `D:\hermes agent\hermes-agent`，
  launcher `D:\hermes agent\bin\hermes.exe`，`HERMES_HOME` 已设为该目录。
- MCP：`hermes mcp test bookcompiler` 实测连接成功，发现 15 个工具。
- 技能：`book-library` enabled；描述加入中文触发场景；不是一本书一个技能。
- 模型：DeepSeek OpenAI 兼容端点；`reasoning_overrides: {deepseek-v4-pro: low}`，
  避免 medium 推理吃掉输出预算导致“reply was cut off”。
- 端到端：问“降准是否必然导致银行信贷扩张？”，Hermes 自动走书库，引用
  《中央银行与货币供给》第 277/298 页逐字原文，并回答“不必然”。

### 4. 自进化

- 只允许三类可执行变更：检索权重、书偏好、框架偏好。
- `proposed -> accepted -> shadow -> promoted -> rolled_back` 状态机。
- 晋升必须有结构 replay 报告；报告不一致或任一 case 失败会被拒绝。
- 应用前写快照，失败恢复；支持 rollback。
- **不会**自动改写 BookCard、FrameworkCard、引用、prompt 或代码。

## 真实验证数据

| 指标 | 当前值 |
|---|---|
| 书 | 12 本 ingest |
| 深度编译 | 4 本 / 12 个 FrameworkCard |
| 分析 | 2 条；`42450cb02344ffe7`（17 引用）和 `6bfb0a97403a4b92`（36 引用）均 `validate` 返回 `[]` |
| chunks | 5,500 |
| embedding | BGE `bge-small-zh-v1.5`，512 维，5,500/5,500，coverage 1.0，missing 0；本地 768 维 fallback 也在库 |
| 实体 | 92 规范 / 69 跨书 / 9,905 提及 / 300 关系 / 63 别名组 |
| 实体审计 | 5 个 `review_only` 候选 |
| 检索权重 | BM25 0.55 / embedding 0.35 / entity 0.10；lexical expansion 0.35 |
| 测试 | 55 passed |
| Hermes | v0.22.2，MCP 15 工具，skill enabled，端到端 chat 已验证 |

## 没有达到 / 不能吹的地方

1. **不是“12 本都学会了”**。8 本只是 `ingested`，`book_recall` / `book_analyze`
   会拒绝把它们当已学习证据。
2. **不是神经语义检索**。本地 embedding 是字符 n-gram hash，擅长 OCR 鲁棒和
   词形近似，不理解反讽、隐喻、远距离同义。需要真正语义向量时配置 OpenAI 兼容后端。
3. **不是完整本体**。实体对齐是规则 + 别名 + 保守包含；`co_occurs` 是共现，
   不是因果；`discusses` 只表示书里提到。
4. **不是 claim-level 知识图谱**。还没有“同一主张在不同书/不同年份的冲突、取代、
   适用条件”的版本化结构。
5. **不是人类式思考**。系统提供证据包、框架、冲突提示和条件结论；最终综合仍由
   调用它的 LLM 完成。
6. **OCR 边界**。引用校验只能证明“这句话在 OCR 文本里存在”，不能证明 OCR 每个字
   都对；目录/索引降权也只是启发式。
7. **法律 lens 不是法律意见**。书库缺具体法条时，正确行为是标注推断和缺口，而不是
   假装有法律依据。
8. **自进化仍是有界配置演化**。没有自动改卡片、prompt、代码，也没有真正的
   shadow/canary 流量和盲评。
9. **GUI 无认证**。只能绑定 `127.0.0.1`，不要暴露公网。
10. **Hermes 验证是 one-shot CLI**。不是长期生产压测；并发、长会话压缩、网关入口
    尚未验证。

## 下一步优先级

1. **覆盖率**：把剩余 8 本编译完，优先补法律/监管类书；没有学过的书不进入证据池。
2. **评测集**：建立 20 个新闻/政策事件的 query + 期望证据 + 盲评 rubric；
   现在的 replay 只证明结构没回归，不证明答案更好。
3. **神经检索**：接真正的 embedding 和 reranker；用固定 query 集比较
   lexical / hybrid / hybrid+rerank 的 hit@k、MRR 和引用命中率。
4. **claim-level 图谱**：把“主张”作为一等节点，记录书、页、年份、条件、
   反例和 supersession。
5. **实体确认队列**：把 `review_only` 候选接到 GUI/agent 的确认流程；确认后才合并。
6. **更强自进化**：shadow/canary、质量 rubric、自动回滚触发器；仍然不允许改真值校验。

## 快速验收

```powershell
cd C:\Users\mybea\projects\bookcompiler
D:\anaconda\python.exe -m pytest -q
D:\anaconda\python.exe -m bookcompiler.cli --db .bookcompiler\library.db validate --book 976b3c244642d321
D:\anaconda\python.exe -m bookcompiler.cli --db .bookcompiler\library.db validate --analysis 42450cb02344ffe7
D:\anaconda\python.exe -m bookcompiler.cli --db .bookcompiler\library.db entities audit --limit 10
Invoke-RestMethod 'http://127.0.0.1:8765/api/status'
```

Hermes：

```powershell
$env:HERMES_HOME='D:\hermes agent'
& 'D:\hermes agent\bin\hermes.exe' mcp test bookcompiler
& 'D:\hermes agent\bin\hermes.exe' chat
```

## 2026-10-18 第二轮代码修复（未重建现有 claims）

这一轮只修代码和回归，不动真实书库数据，也不把启发式结果说成“已学会”。

- 备份：`C:\Users\mybea\Desktop\bookcompiler-backup-20261018-091034`，含源码、测试、`.env` 和 SQLite 一致性快照。
- `learned` 语义修好：只有 `verified/complete` 卡片且有 framework 的书才算 learned；启发式 compile 仍保持 `ingested`。
- `replace_claims()` 不再删除 `superseded/retracted` 或带人工 resolution 的 claim；重跑 claims build 不会把复核结果冲掉。
- `create_analysis()` 现在会检索 claim graph，把 claim 的逐字 quote 放进证据，并在 memo 里渲染 `Claim graph`；真实 claim 冲突优先于模板冲突提示。
- embedding/reranker 改为进程级缓存，避免每次检索重复加载模型；reranker 默认关闭，需要时用 `--rerank` 或环境变量开启。
- 检索增加 chunk/向量/质量缓存和 numpy 矩阵乘法；修复“lazy backfill 后仍用旧缓存，只覆盖一本书”的回归。
- `select_books()` 从“每本书各跑一次全库混合检索”改成一次批量检索再按书分组，书多时不会平方级变慢；方向模式复用选择理由，不再重复检索。
- 新增 `bookcompiler doctor`，检查 Python/venv、依赖、active embedding 模型与覆盖率、reranker、learned 数量和 Hindsight 连通性。
- 新增回归测试：启发式不算 learned、人工复核 claim 保留、claim 进入 analysis、批量选书、embedder 单例。当前 `55 passed`。
- 检索评测：12 个 case，lexical / hybrid / hybrid+rerank 的 `hit@3 = 1.0`，`strict_hit@3 = 0.75`，`strict_mrr = 0.7083`。这只说明固定集上没有明显回归，不等于答案正确。
- 真实库仍未改：12 本书、4 本 learned、8 本 ingested、5,500 chunks、640 claims、0 claim_relations、0 feedback、0 evolution proposals。没有重新 ingest、没有重建 claims、没有下载书、没有 commit。