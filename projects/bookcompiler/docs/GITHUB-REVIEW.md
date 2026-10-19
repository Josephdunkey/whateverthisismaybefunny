# GitHub 方案审阅（2026-10）

目标：在造轮子之前，确认哪些现成项目已经解决了“把书变成可调用能力”“记忆”“图检索”“自进化”的一部分问题，并明确本项目应该借鉴什么、拒绝什么。

## 审阅清单

| 仓库 | 它主要解决什么 | 本项目借鉴 | 本项目不采用 |
|---|---|---|---|
| [apple-ouyang/book-to-skill](https://github.com/apple-ouyang/book-to-skill) | 把书蒸馏成可导入的 AI 技能 | “书 → 可执行工作流”的方向；先提炼方法论，而不是做摘要 | 不把每本书直接塞成一个巨大 skill；不把无引用的总结当知识 |
| [zhimaAi/BookToSkill](https://github.com/zhimaAi/BookToSkill) | 书 → skill 的工程化尝试 | 输入解析、目录结构、技能产物的可移植形态 | 不依赖其运行时；不让技能脱离原文引用 |
| [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) | agent 的 retain / recall / reflect 记忆循环 | 记忆存“教训、偏好、失败模式”，不存原文；反馈驱动召回 | 不把记忆当成本体知识库；memory 不能替代 citation |
| [liliang-cn/cortexdb](https://github.com/liliang-cn/cortexdb) | 面向 agent 的图记忆、supersession | provenance graph、节点/边、旧结论被新证据取代的思路 | 不引入其数据库依赖；当前用 SQLite 边表即可验证原型 |
| [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) | 轻量 graph RAG / 混合检索 | “实体—关系—社区”检索是后续方向；保留 source unit 边界 | 当前不引入其索引管线，避免原型阶段增加不可控依赖 |
| [microsoft/graphrag](https://github.com/microsoft/graphrag) | 面向全局问题的 Graph RAG | 全局主题/社区摘要、跨文档关系检索的评估方法 | 当前数据规模与 OCR 质量不足以支撑其成本 |
| [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) | 代码/知识图谱可视化与检查 | GUI 中的 graph / provenance 检查视图 | 不作为运行时依赖；本项目图谱节点是书、框架、chunk、analysis |

以上仓库在 2026-10 通过 GitHub API 确认可访问（HTTP 200）。审阅以 README、目录结构与核心概念为主，不是逐行代码审计。

## 关键技术判断

### RAG 用在哪里

本项目把 RAG 用在**证据层**，不是把检索到的段落直接拼成答案：

- 原文 chunk 存在 SQLite，使用 FTS5 + 词项打分检索；
- 每个引用必须能通过 `find_quote()` 回到原文；
- chunk、chapter、page 不匹配会被标记，analysis 中 chunk/chapter/page 不匹配是错误；
- 生成的分析必须区分 `evidence`、`hypothesis`、`counterevidence`、`cross_lens_conflicts`。

0.4 已加入混合检索：BM25 + embedding（默认本地字符 n-gram，可配置 OpenAI 兼容后端）+ 跨书实体扩展。它不是神经语义模型的替代品，但能在 OCR 噪声下稳定召回；每条结果保留分数拆解。

跨书实体对齐也已落地：规范实体、别名、chunk 级提及和共现关系。尚未引入 LightRAG/GraphRAG 的社区摘要与全局查询，因为当前 12 本书、5500 chunks 的规模还不足以证明其成本合理。

### Hindsight 用在哪里

借鉴 retain / recall / reflect：

- retain：feedback 写入偏好、错误标签、缺失证据和结果；
- recall：`recall_memory()` 在新问题中召回相关教训；
- reflect：`propose_evolutions()` 把重复反馈聚合成受控的 evolution proposal。

记忆只影响选书、选框架和提示，不直接改写原文事实，也不能绕过 citation 校验。

### 自进化用在哪里

V2 的自进化是**受控演化**，不是模型半夜自己改自己：

- proposal 必须有证据、风险、回滚方案；
- 状态机：`proposed → accepted → shadow → promoted → rolled_back`；
- `promoted` 必须有结构 replay 全通过的证据；
- 任何已接管 proposal 都可以回滚；
- replay 当前只证明结构和引用没有回归，不证明盲评质量。

## 结论

- 借鉴概念，不引入重型依赖；
- 保留“精确 source unit + 引用校验 + provenance graph”这三个骨架；
- 0.4 已完成：混合检索（BM25 + embedding + 实体扩展）、跨书实体对齐 + audit、
  MCP/Hermes 对接、有界自进化；
- 下一阶段优先做：claim-level supersession、20 条事件级盲评 replay、神经 embedding/reranker、
  实体审计确认队列；
- 不把 GraphRAG / LightRAG 直接接进来，直到真实书库和评测集足够大。
