# 多智能体能不能用到这里

> 结论：**能，而且很适合做“读书质量”的对抗性检查**。但多智能体的价值不是“多开几个模型”，而是把不同认知职责分开：出题、检索、解释、反方、引用审计、综合、盲评、进化。  
> 如果只是让几个 agent 互相夸，成本会上升，结论不会更可靠。

## 1. 为什么适合 BookCompiler

读书并回答问题，天然包含几种互相拉扯的任务：

- 先判断问题需要哪些书和证据；
- 从不同书、不同学科镜头找材料；
- 把材料解释成自己的话；
- 找反例和失败条件；
- 核对引用是否逐字来自原文；
- 合成条件性结论；
- 判断这次回答到底好不好；
- 把重复弱项变成改进提案。

一个 agent 同时做这些，容易出现：

- 自己检索、自己解释、自己评分，偏向自己的答案；
- 为了连贯而抹平冲突；
- 只看支持自己结论的证据；
- 把“听起来合理”当成“原文支持”。

多智能体可以把这些职责拆开，形成真正的检查链。

## 2. 推荐的角色分工

| 角色 | 只负责什么 | 不应该做什么 | 对应工具/数据 |
|---|---|---|---|
| Planner / 出题者 | 拆子问题、列需要的证据和镜头 | 不写最终答案 | `book_plan`、`book_recall` |
| Retriever / 检索者 | 按子问题召回 chunk、claim、实体 | 不编造证据 | `book_recall`、混合检索 |
| Reader / 编译者 | 写书卡、框架卡、章节摘要 | 不跳过原文 | `book_export_text`、`book_compile` |
| Feynman explainer | 不看原文，用大白话解释 | 不能新增事实 | 只给问题 + 书卡/框架卡 |
| Red team / 反方 | 找反例、失败条件、被忽略的镜头 | 不负责给最终结论 | `book_analyze`、claim 冲突 |
| Citation auditor | 逐字核对 quote、章节、页码 | 不接受“意思差不多” | `book_validate` |
| Synthesizer / 综合者 | 合并镜头，写条件结论 | 不平均冲突 | `analysis-apply` |
| Judge / 盲评者 | 按九维 rubric 打分 | 不能看作者的解释 | `book_reading_eval` |
| Evolver / 进化管理员 | 把重复弱项变成提案，跑 replay/shadow | 不能自动晋升 | `book_evolution` |

## 3. 三种编排方式

### 3.1 顺序流水线（最稳，先做这个）

```text
Planner -> Retriever -> Reader -> Feynman -> Red team -> Citation auditor -> Synthesizer -> Judge -> Evolver
```

优点：

- 每一步输入输出清楚；
- 容易定位错误；
- 成本可控；
- 适合落到 `AnalysisPacket`。

缺点：

- 延迟高；
- 前一步错了会往后传；
- 需要检查点。

### 3.2 并行 fan-out / fan-in（适合多镜头）

```text
             -> 经济镜头检索/分析 ->
Planner ->   -> 政治镜头检索/分析 ->   -> Synthesizer -> Judge
             -> 法律镜头检索/分析 ->
```

优点：

- 三个镜头不会互相污染；
- 适合经济/政治/法律跨学科分析；
- 可以分别检查证据覆盖。

缺点：

- 综合者容易把三篇短文拼在一起；
- 需要强制冲突表，而不是简单合并。

### 3.3 辩论/投票（高成本，谨慎用）

```text
Proposer <-> Critic <-> Judge
```

适合：

- 高风险判断；
- 两种解释都很有道理；
- 需要明确反证条件。

不适合：

- 普通事实问答；
- 书库很小、证据不足；
- 没有停止条件的开放式辩论。

关键：辩论必须有**停止条件**和**结构化输出**，否则会变成无限互喷。

## 4. 最小可行多智能体闭环

建议先做 4 个角色，不要一上来做 9 个：

### 角色 A：Retriever

输入：问题、镜头、方向。  
输出：

```json
{
  "subquestions": ["..."],
  "queries": ["..."],
  "evidence": [{"book_id": "...", "chunk_id": "...", "quote": "..."}],
  "coverage_gaps": ["..."]
}
```

### 角色 B：Feynman explainer

只看问题和书卡/框架卡，不看原文。  
输出：

```json
{
  "plain_explanation": "...",
  "uncertain_points": ["..."],
  "questions_to_check": ["..."]
}
```

### 角色 C：Red team

只看证据和草稿。  
输出：

```json
{
  "counterexamples": ["..."],
  "missing_lenses": ["..."],
  "overclaims": ["..."],
  "what_would_change_the_conclusion": ["..."]
}
```

### 角色 D：Judge

只看最终答案、九维 rubric 和证据，不看作者自评。  
输出：

```json
{
  "scores": {"source_fidelity": 8, "...": 0},
  "error_labels": ["retrieval_miss"],
  "note": "..."
}
```

这四个角色已经能覆盖“检索是否够、解释是否清楚、反方是否被忽略、引用是否可信”。

## 5. 共享状态怎么设计

不要让 agent 只在聊天记录里传话。要有一个结构化黑板：

```json
{
  "question": "...",
  "lenses": ["economics", "politics", "law"],
  "selection": {...},
  "evidence": [...],
  "claims": [...],
  "conflicts": [...],
  "draft": "...",
  "feynman": {...},
  "red_team": {...},
  "citation_audit": {...},
  "final": "...",
  "reading_evaluation": {...}
}
```

原则：

1. 每个角色只写自己负责的字段。
2. 证据必须带 `book_id`、`chunk_id`、`quote`。
3. 综合者只能引用黑板里的证据，不能凭记忆补。
4. Judge 看不到作者的解释和自评分。
5. 所有产物最后落回 `AnalysisPacket` 和 SQLite，才能复盘。

## 6. 多智能体的风险

| 风险 | 表现 | 对策 |
|---|---|---|
| 群体思维 | 几个 agent 很快达成一致 | 保留独立反方；先各自写，再合并 |
| 错误放大 | 一个 agent 编造，后面都信 | 引用审计员逐字回查 |
| 上下文污染 | judge 看到了作者的解释 | 盲评：只给答案和证据 |
| 成本爆炸 | 9 个角色 × 每轮多次调用 | 只在高风险/低置信时启用完整链路 |
| 延迟过高 | 用户等几分钟 | 并行 fan-out；缓存检索；小模型做路由 |
| 假共识 | 辩论后折中，冲突被抹平 | 强制输出冲突表和条件结论 |
| 提示注入 | 书里的文本包含恶意指令 | 把书内容当数据，不当系统指令 |
| 评分偏差 | judge 偏爱长答案/自信语气 | 九维 rubric + 配对盲评 + 多 judge |
| 责任不清 | 出问题不知道谁错 | 每个角色结构化日志和证据 ID |

## 7. 和现有 BookCompiler 怎么接

现有 MCP 工具已经能支撑多智能体：

- `book_plan`：Planner/Retriever
- `book_recall`：证据召回
- `book_analyze`：分析包
- `book_validate`：引用审计
- `book_reading_eval`：Judge
- `book_evolution`：Evolver
- `book_memory`：跨轮记忆
- `book_library`：书库状态

缺口不是工具，而是**编排层**：

1. 谁在什么时候调用哪个工具；
2. 角色之间传什么结构化数据；
3. 什么时候停止；
4. 谁有权写最终答案；
5. 谁有权晋升进化提案。

这些可以先用 Hermes/Codex 的 subagent 或独立会话实现，不必马上写一个复杂框架。

## 8. 成本与收益

| 模式 | 相对成本 | 适合 |
|---|---:|---|
| 单 agent + 九维评分 | 1x | 日常问答、快速分析 |
| 3 角色（检索/反方/judge） | 2–3x | 重要分析、低置信回答 |
| 5 角色（加费曼/引用审计） | 3–5x | 对外报告、法律/金融高风险 |
| 9 角色完整链路 | 5–10x | 研究级复盘、重大决策 |
| 辩论/投票 | 更高 | 只有在错误代价很高时 |

建议默认：

- 普通问题：单 agent + `reading-eval`；
- 重要问题：Retriever + Red team + Judge；
- 对外交付：再加 Citation auditor + Feynman；
- 只有真正高风险才上完整链路。

## 9. 调研到的框架与项目

原始数据：`docs/_research/multi-agent-repos.json`、`docs/_research/multi-agent-arxiv.xml`。  
截至 2026-10-18 的直接仓库查询：

| 项目 | Stars | 许可 | 用途 |
|---|---:|---|---|
| `microsoft/autogen` | 61k | CC-BY-4.0（GitHub 报告） | 多 agent 对话/编排，适合参考 |
| `langchain-ai/langgraph` | 43k | MIT | 状态图编排，适合做可恢复工作流 |
| `crewAIInc/crewAI` | 60k | MIT | 角色化 agent 团队，概念接近本文分工 |
| `openai/swarm` | 22k | MIT | 轻量 agent handoff，实验性 |
| `google/adk-python` | 22k | Apache-2.0 | 代码优先的 agent 开发/评估工具包 |
| `FoundationAgents/MetaGPT` | 71k | MIT | 软件公司式多角色协作 |
| `OpenBMB/ChatDev` | 35k | Apache-2.0 | 多角色协作/软件开发 |
| `Significant-Gravitas/AutoGPT` | 188k | NOASSERTION | 通用自主 agent，参考价值大于直接嵌入 |
| `ocean-luna/HMRAG` | 115 | 未确认 | 层级多 agent 多模态 RAG，论文配套实现 |

### 相关论文

- *A Collaborative Multi-Agent Approach to Retrieval-Augmented Generation Across Diverse Data* — arXiv:2412.05838。
- *HM-RAG: Hierarchical Multi-Agent Multimodal Retrieval Augmented Generation* — arXiv:2504.12330。
- *RAGentA: Multi-Agent Retrieval-Augmented Generation for Attributed Question Answering* — arXiv 检索结果。
- *SQuAI: Scientific Question-Answering with Multi-Agent Retrieval-Augmented Generation* — arXiv 检索结果。
- *MATRAG: Multi-Agent Transparent Retrieval-Augmented Generation for Explainable Recommendations* — arXiv 检索结果。

这些工作共同说明：多 agent 更适合**异构数据源、查询分解、证据归因、透明性和验证**，而不是无脑提升所有问答。

## 10. 推荐落地顺序

### P0：三角色协议

```text
Retriever -> Red team -> Judge
```

不改核心代码，先用 skill/提示词跑 20 个真实问题，比较单 agent 和三角色的 `reading-eval` 分数、延迟、成本。

### P1：加 Citation auditor

所有引用逐字回查。  
如果 `source_fidelity` 没有提升，说明多 agent 只是增加了成本。

### P2：加 Feynman explainer

检验“能不能用大白话讲清楚”，并把卡壳点回传给 Retriever。

### P3：加黑板和并行镜头

用结构化 JSON 共享证据，经济/政治/法律并行检索，综合者写冲突表。

### P4：盲评与提案

Judge 不看作者解释；连续多次低分才生成 `review_reading_dimension` 提案。

## 11. 一句话建议

**多智能体值得用，但应该先用在“检查”和“对抗”，而不是“生成更多文字”。**  
最划算的第一版不是九个 agent，而是：

```text
一个检索者 + 一个反方 + 一个盲评 judge
```

如果这三者不能稳定提升 `source_fidelity`、`retrieval_coverage` 和 `conflict_handling`，就不该继续加角色。

## V3：运行时自动编排（2026-10-18）

`create_analysis` 自动执行固定角色流水线，而不是只停留在文档协议：

```text
planner -> retriever -> reader -> feynman_explainer -> red_team
        -> citation_auditor -> lens_reviewer -> synthesizer -> judge -> evolver
```

- 每次分析把 trace 写入 `AnalysisPacket.orchestration`。
- `apply_analysis_patch` 后重新计算，citation auditor / synthesizer 状态会更新。
- 只有 judge 是额外独立模型调用；其他角色是确定性代码阶段。
- Reader notes 是 memory，不是 evidence/citation。
- `bookcompiler orchestrate --analysis <id>` 可以单独查看 trace。

边界：这不是多个模型自由辩论，也不是自动改写提示词的“智能体群体”。自由辩论版本需要真实评分样本和 replay 集之后再考虑。