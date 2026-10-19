# RAG 技术全景与 BookCompiler 的取舍

> 调研快照：2026-10-18。GitHub 星数会变，原始结果保存在 `docs/_research/rag-repos.json`、`rag-github.json`、`arxiv-papers.json`、`repo-readmes.json`。这不是“全互联网穷举”，而是围绕本地书库、长文档、多跳、记忆、图检索、自校正检索做的定向扫描。

## 1. 先给结论

BookCompiler 现在不是“裸 RAG”，但回答链路仍然以 RAG 为主：

```text
书 -> chunk -> FTS5 + embedding + entity + claim -> 选书 -> AnalysisPacket -> 引用校验
```

它比普通 RAG 多了：

- 逐字引用校验；
- BookCard / FrameworkCard；
- claim graph；
- 多镜头冲突；
- 反馈、评分和受控进化；
- Hindsight 记忆。

但它还缺几块高级 RAG 能力：

1. **检索充分性自检**：证据不够时主动补检索，而不是硬答；
2. **RRF/多路融合**：词法、向量、实体、claim 的融合还可以更稳；
3. **查询分解与多跳**：复杂问题拆成子问题；
4. **层级摘要**：长书需要章节树，而不是只靠 chunk；
5. **图扩展**：实体/claim 关系还没有充分用于召回；
6. **真实评测**：目前的检索评测和读书评分还不足以证明“高级 RAG 一定更好”。

**不建议直接替换成 GraphRAG。** 更稳的做法是把高级 RAG 当作“候选生成器”和“自检器”，逐字引用校验仍然是最终真值门。

## 2. RAG 的主要流派

| 流派 | 代表 | 解决什么 | 主要风险 |
|---|---|---|---|
| Naive / vector RAG | 向量库 + top-k | 语义相似召回 | 召回表面相似、缺多跳、引用弱 |
| Hybrid RAG | BM25 + dense + RRF | 词法精确匹配 + 语义泛化 | 权重难调，延迟上升 |
| GraphRAG | Microsoft GraphRAG、LightRAG、nano-graphrag | 实体/社区/关系、多跳、全局问题 | 构图贵、实体错、图噪声、未必优于简单 RAG |
| Hierarchical RAG | RAPTOR、PageIndex | 长文档、章节级摘要、树状检索 | 摘要幻觉、引用回溯难 |
| Agentic RAG | 查询分解、工具调用、迭代检索 | 复杂问题、多步推理 | 成本高、容易跑偏、需要停止条件 |
| Self-correcting RAG | Self-RAG、CRAG | 判断“要不要检索/证据够不够/要不要重查” | 自评偏差、额外模型调用 |
| Memory-centric RAG | HippoRAG、Cognee、Graphiti、mem0 | 长期记忆、跨文档整合、个性化 | 记忆污染、过期、隐私、评测难 |
| Structured / metadata RAG | 书/章/页/实体/claim 过滤 | 精确定位、可审计 | 依赖抽取质量 |
| Vectorless / reasoning-based | PageIndex | 用文档结构+推理导航，而非纯向量 | 依赖文档结构质量，生态较新 |

## 3. BookCompiler 已经有什么

| 能力 | 现状 | 说明 |
|---|---|---|
| 词法检索 | 有 | SQLite FTS5 |
| 向量检索 | 有 | BGE-small-zh 512 维，带 fallback |
| 混合检索 | 有 | lexical + embedding + entity，带权重 |
| 引用校验 | 有 | 逐字 quote 回查，找不到报错 |
| 书卡/框架卡 | 有 | BookCard / FrameworkCard |
| claim graph | 有基础 | claims、claim_relations、冲突检测 |
| 实体图 | 有基础 | 92 个实体、9,905 mentions、300 条 co_occurs |
| 多镜头 | 有 | 经济/政治/法律等 lens |
| 记忆 | 有接口 | Hindsight retain/recall/reflect 思路 |
| 评分 | 有 | 九维 reading-effectiveness rubric |
| 受控进化 | 有 | proposal 状态机、replay/shadow/promote/rollback |
| 图检索 | 未有 | 实体/claim 还没有充分进入召回排序 |
| 层级摘要 | 未有 | 没有 RAPTOR 式摘要树 |
| 自校正检索 | 未有 | 没有 CRAG/Self-RAG 式充分性门 |
| 查询分解 | 部分 | 主要靠选书和关键词，没有系统子问题分解 |

## 4. GitHub 项目扫描

截至调研快照，值得关注的项目：

| 项目 | Stars | 许可 | 判断 |
|---|---:|---|---|
| `microsoft/graphrag` | 36k | MIT | 研究项目，README 明确说“largely in maintenance mode”，不建议作为新系统底座 |
| `HKUDS/LightRAG` | 40k | MIT | 轻量图检索，值得借鉴实体/关系检索和增量更新 |
| `OSU-NLP-Group/HippoRAG` | 4k | MIT | 记忆型多跳检索，和“读书变成长期能力”方向接近 |
| `topoteretes/cognee` | 32k | Apache-2.0 | AI memory 平台，可参考记忆分层和 pipeline |
| `getzep/graphiti` | 32k | Apache-2.0 | 时序知识图谱，适合事件/关系随时间变化 |
| `infiniflow/ragflow` | 92k | Apache-2.0 | 重型 RAG 平台，功能全，但不适合直接嵌进当前轻量项目 |
| `NirDiamant/RAG_Techniques` | 30k | NOASSERTION | 高级 RAG 技术教程集合，适合查漏补缺，不适合直接依赖 |
| `stanford-futuredata/ColBERT` | 3.9k | MIT | 后期交互检索，效果强但索引/算力成本高 |
| `AkariAsai/self-rag` | 2.4k | MIT | Self-RAG 原实现，适合借鉴“检索/批评/反思”门控 |
| `mem0ai/mem0` | 67k | Apache-2.0 | 通用 agent memory，可参考记忆抽取/更新 |
| `letta-ai/letta` | 25k | Apache-2.0 | 有状态 agent 平台，记忆和自改进思路可参考 |
| `VectifyAI/PageIndex` | 39k | MIT | vectorless、reasoning-based 文档索引，适合长书结构导航 |
| `gusye1234/nano-graphrag` | 4k | MIT | 轻量 GraphRAG，适合读代码而不是直接上生产 |
| `circlemind-ai/fast-graphrag` | 4k | MIT | 自适应 GraphRAG，值得看查询路由 |
| `DEEP-PolyU/Awesome-GraphRAG` | 2.7k | MIT | GraphRAG 论文/基准索引 |
| `deepset-ai/haystack` | 27k | Apache-2.0 | 生产级编排框架，适合参考 pipeline 设计 |
| `parthsarthi03/raptor` | 1.8k | MIT | 层级摘要树原实现 |
| `HKUDS/RAG-Anything` | 24k | MIT | 多模态/一体化 RAG，当前项目暂不需要 |
| `langchain-ai/langchain` | 148k | MIT | 通用编排，生态大；不适合把核心逻辑绑死 |
| `run-llama/llama_index` | 53k | MIT | 文档处理/索引生态，可参考，但当前自研 SQLite 更可控 |
| `basicmachines-co/basic-memory` | 4.3k | AGPL-3.0 | Obsidian/Markdown 记忆方案，许可证需注意 |
| `khoj-ai/khoj` | 38k | AGPL-3.0 | 个人第二大脑，功能参考，不建议直接嵌入 |
| `logancyang/obsidian-copilot` | 7.8k | AGPL-3.0 | 把 Codex/Claude 等带进 Obsidian，许可证需注意 |

### 许可证提醒

AGPL-3.0 项目不适合直接复制进闭源/网络服务而不评估义务。当前 BookCompiler 对 Obsidian 只做 Markdown 文件导出，不嵌入 AGPL 插件，这是低风险路径。

## 5. 关键论文与结论

| 论文 | arXiv | 对本项目的意义 |
|---|---|---|
| GraphRAG under Fire | 2501.14050 | 图 RAG 不是天然更强，成本和复杂度必须用评测证明 |
| LightRAG | 2410.05779 | 轻量图检索 + 增量更新，适合借鉴 |
| HippoRAG | 2405.14831 | 用知识图谱 + Personalized PageRank 做多跳记忆检索 |
| HippoRAG 2 | 2502.14802 | 持续整合跨文档知识，接近“读很多书后形成长期记忆” |
| RAPTOR | 2401.18059 | 递归摘要树，适合长书；但摘要可能引入幻觉，必须能回原文 |
| Self-RAG | 2310.11511 | 让模型判断要不要检索、证据是否支持、回答是否可靠 |
| Corrective RAG | 2401.15884 | 检索质量差时纠正查询或换检索源 |
| Adaptive RAG / Retriever Portfolios | 2605.31176 | 不同问题用不同检索器，不必一条链路打天下 |
| Spaced Repetition | 1602.07032 | 复习调度，可用于书卡/claim 的长期保持 |
| Retrieval Practice | 2507.05629 | 先回忆/出题再查资料，适合做读书练习 |

### 关于 GraphRAG 的谨慎结论

Microsoft GraphRAG 的 README 已经写明项目“largely in maintenance mode”，不再接受新功能 PR。它仍然是重要的研究参考，但不适合作为新系统的长期底座。  
更重要的是，*GraphRAG under Fire* 这类工作提醒我们：图结构会增加构图成本、实体噪声和延迟，**必须和简单 hybrid RAG 做同条件对比**，不能因为“图更高级”就默认更好。

## 6. 对 BookCompiler 的推荐架构

### 6.1 保留真值门

无论前面用多少高级检索，最终仍然要：

1. 找回原文 chunk；
2. 逐字匹配 quote；
3. 校验 book_id / chapter / page；
4. 找不到就删掉或标成推断。

这是 BookCompiler 和普通 RAG 最大的区别，不能为了“图检索”放弃。

### 6.2 加一个检索充分性门

在生成最终回答前，让一个独立检查器回答：

- 现有证据是否覆盖了问题的每个子问题？
- 有没有只找到一本相关书？
- 有没有镜头完全缺证据？
- 有没有 claim 冲突未解释？
- 如果不够，应该补什么查询？

对应 CRAG / Self-RAG 的思路。可以先做成提示词 + 一个 `retrieval_sufficiency` 字段，再考虑训练/模型化。

### 6.3 加 RRF 融合

当前有权重融合。下一步可以加 Reciprocal Rank Fusion：

```text
score(d) = Σ 1 / (k + rank_i(d))
```

优点：

- 不需要精细调权重；
- 对词法/向量/实体/claim 多路召回更稳；
- 容易做离线评测。

建议先离线对比 `current weighted fusion` vs `RRF`，不要直接替换。

### 6.4 加层级摘要树（RAPTOR 风格）

适合：

- 长书；
- “这本书整体主张什么”；
- 跨章节综合；
- 多书主题对照。

做法：

```text
chunk -> section summary -> chapter summary -> book summary
```

但每条摘要必须能回溯到 chunk，不能让摘要成为新的“不可验证事实”。

### 6.5 加图扩展（LightRAG/HippoRAG 风格）

适合：

- 多跳问题；
- 实体关系；
- “这个事件和哪些书里的概念有关”；
- 跨书实体对齐。

前置条件：

- 实体质量要先过关；
- claim 关系不能大量为空；
- 图扩展结果必须回到原文引用。

当前真实库 `claim_relations=0`，实体关系全是 `co_occurs`。这意味着图检索的原料还很薄，先把实体对齐和 claim 关系做好，比接一个图数据库更重要。

### 6.6 加查询分解

复杂问题拆成：

- 事实子问题；
- 机制子问题；
- 冲突子问题；
- 反证子问题；
- 行动子问题。

每个子问题独立检索，再合并。这样可以减少“一个 query 抓所有东西”的漏检。

## 7. 不建议做的事

1. **不要直接用 GraphRAG 替换现有链路**：维护状态、成本、实体质量都不支持。
2. **不要嵌入 AGPL 项目**：除非明确接受许可证义务。
3. **不要上重型平台**：RAGFlow/LangChain/LlamaIndex 能力很强，但会把当前可控的 SQLite + 引用校验架构复杂化。
4. **不要用摘要替代原文**：摘要只能做导航，最终引用必须回 chunk。
5. **不要只看 hit@k**：还要看 strict citation validity、faithfulness、cross-book synthesis、延迟和成本。
6. **不要在 claim 质量差时做大规模图检索**：垃圾进，图也只是把垃圾连起来。

## 8. 评测指标

| 指标 | 说明 |
|---|---|
| recall@k | 相关 chunk 是否被召回 |
| book_hit@k | 是否召回到正确书 |
| strict_hit@k | 同一段是否包含全部期望词 |
| citation_validity | 逐字 quote 是否能回查 |
| retrieval_sufficiency | 证据是否覆盖子问题 |
| faithfulness | 回答是否只基于证据 |
| cross_book_synthesis | 是否真正跨书综合 |
| conflict_handling | 冲突是否显式处理 |
| latency / cost | 延迟和 token 成本 |
| reading_total | 九维读书评分总分 |

## 9. 实施优先级

| 优先级 | 改动 | 成本 | 风险 | 预期收益 |
|---|---|---|---|---|
| P0 | 检索充分性自检 | 低 | 低 | 减少“证据不够还硬答” |
| P0 | RRF 离线对比 | 低 | 低 | 更稳的多路融合 |
| P1 | 查询分解 | 中 | 中 | 复杂问题召回提升 |
| P1 | 层级章节摘要 | 中 | 中 | 长书整体问题提升 |
| P2 | 图扩展/多跳 | 高 | 高 | 跨书关系和多跳 |
| P2 | 记忆型检索 | 高 | 高 | 长期个性化 |
| P3 | 多模态 RAG | 高 | 高 | 当前场景不需要 |

## 10. 相关文档

- `docs/READING-SCORE.md`：九维评分与反馈进化。
- `docs/LEARNING-METHODS.md`：学习方法论与多智能体角色。
- `docs/OBSIDIAN.md`：Obsidian 作为阅读/复盘界面。
- `docs/IMPROVEMENT-RESEARCH-2026-10-18.md`：本轮更早的代码与真实库研究。

## V3：实际接入的 GraphRAG（2026-10-18）

当前主链路已经接入的是**轻量确定性 GraphRAG sidecar**：

- 图文件：`.bookcompiler\library.graph.db`
- 节点：book / framework / claim / entity / chunk
- 边：has_framework、has_chunk、supported_by、mentions、about_subject、about_object、claim 关系、实体关系、co_mentions、about
- 社区：书内实体社区 + 跨书桥接社区
- 查询：实体/claim/框架种子 + 2-hop 加权扩散
- 融合：hybrid + graph 使用 RRF（k=60，graph 权重 0.9（略低于 hybrid，避免图邻居压过直接命中））
- 失败回退：图缺失/损坏时分析仍使用 hybrid

没有接入的：Microsoft 全量 LLM GraphRAG、LightRAG、HippoRAG、RAPTOR、Self-RAG/CRAG 控制器。它们仍在评估列表里，不应在文档中宣称已使用。