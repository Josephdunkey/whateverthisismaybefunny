# 人类学习方法论：哪些能用到 BookCompiler

> 这是一份工程导向的研究笔记，不是系统综述。结论是：**能借鉴，但不能把“学习术语”直接当功能**。真正能落地的是把学习方法变成 agent 的工作流、评分维度、复习队列和多角色协作。

## 1. 一句话结论

BookCompiler 现在已经有“读、编译、检索、引用、分析、评分、受控进化”的骨架。  
人类学习研究里最值得补的四块是：

1. **先回忆再查书**（retrieval practice），而不是一上来就 RAG；
2. **间隔复习**（spacing），让书卡和 claim 不只用一次；
3. **交错练习**（interleaving），强制多书、多学科对照；
4. **多角色互评**（multi-agent），让出题者、解释者、反方、引用审计者和 judge 分开。

费曼学习法很有用，但它不是“让 agent 说人话”这么简单。它的关键是：**先用大白话解释 → 暴露卡壳处 → 回原文补证据 → 再解释一次**。

## 2. 主要学习框架与项目映射

| 学习框架 | 核心做法 | 在 BookCompiler 里对应什么 | 现状 |
|---|---|---|---|
| 费曼式自我解释 | 用简单语言解释，卡住就回查 | `book_analyze` 后要求“用大白话解释结论”，再用 `book_recall` 回查引用 | 可人工/提示词实现，未做成固定命令 |
| Retrieval practice | 闭卷先回忆/答题，再查资料 | 先让 agent 不看书写答案，再 `book_recall` 对照；`reading-eval` 评差距 | 评分已有，闭卷流程未固化 |
| Spaced repetition | 按遗忘曲线复习 | 给书卡、框架、claim 加复习队列和下次复习时间 | 未实现，Obsidian 可先手工承载 |
| Interleaving | 混合不同主题/书/题型 | 多书选择、多镜头分析、跨书冲突 | 选择层已有，练习层未固化 |
| Deliberate practice | 针对弱项重复练，不是泛读 | `reading-report` 的 `next_actions` + `review_reading_dimension` 提案 | 已有弱项→建议链路 |
| Bloom 分类 | 记忆→理解→应用→分析→评价→创造 | `reading-eval` 的九个维度覆盖理解、应用、分析、评价 | 部分覆盖 |
| SOLO 分类 | 单点→多点→关联→抽象扩展 | `cross_book_synthesis`、`cross_lens_integration` 评“多点/关联/扩展” | 已有维度，未显式标注 SOLO 层级 |
| ICAP | 被动→主动→建构→互动 | 要求 agent 生成假设、反例、冲突，而不是复述 | 提示词可做，未强制 |
| Cognitive load | 分层呈现，避免一次塞太多 | chunk → BookCard → FrameworkCard → AnalysisPacket | 架构已支持 |
| Generation effect | 自己出题/举例/反例 | 让 agent 生成检索题、反例题、跨书对照题 | 未实现 |
| Transfer | 把学到的东西用到新情境 | 用当天新闻/新案例触发分析 | 已有主场景 |
| Zettelkasten | 原子笔记 + 双向链接 | Obsidian 导出 Book/Framework/Claim/Entity/Analysis 笔记 | 已有单向导出 |
| Cognitive apprenticeship | 示范→辅导→逐步撤掉提示 | skill 里的工作流、检查点、人工确认 | 部分有 |
| Mastery learning | 未掌握不推进 | `learned` 只认 verified/complete + framework | 已有 |
| Double-loop learning | 质疑目标/假设本身 | 跨镜头冲突、进化提案、失败模式 | 部分有 |
| Kirkpatrick 四层评估 | 反应→学习→行为→结果 | 评分目前偏“学习/行为”，还没有真实结果追踪 | 未完整 |

## 3. 最适合 BookCompiler 的五步学习循环

### 第一步：先出题，不先查书

在检索之前，让 agent 根据问题写出：

- 我认为答案可能是什么；
- 我需要哪几类证据；
- 哪些书/框架可能相关；
- 哪些地方我不确定。

这一步对应 retrieval practice 和 pretesting。它会让后面的检索更有目标，也能暴露“其实不会，只是会搜”。

### 第二步：带引用地读和编译

用 `book_ingest` → `book_export_text` → `book_compile` → `book_validate`。  
要求：

- 每条关键主张有逐字 quote；
- 书卡写假设、局限、适用/不适用；
- 框架卡写输入、步骤、输出、失败模式、反例。

这一步对应 cognitive load 分层：原文 chunk 是一层，书卡是一层，框架卡是一层，分析包是一层。

### 第三步：费曼式复述

让 agent 不看原文，用大白话回答：

1. 这本书到底在说什么？
2. 它为什么这样想？
3. 它什么时候会错？
4. 如果用它看今天的新闻，会得出什么条件性判断？
5. 我刚才哪里卡住了？

卡住的地方就是下一轮要回查的章节。对应 self-explanation 和 generation effect。

### 第四步：迁移到新事件

用当天新闻、政策、市场事件或案例做 `book_analyze`。  
不要只问“书里怎么说”，要问：

- 这个事件改变了哪个约束？
- 哪个框架适用，哪个不适用？
- 经济、政治、法律三个镜头在哪里冲突？
- 什么新证据会推翻结论？

这一步对应 transfer 和 ICAP 的“建构/互动”层。

### 第五步：评分、练弱项、间隔复习

用 `reading-eval` 打分，`reading-report` 找弱项，`reading-propose` 形成建议。  
弱项不要只写成“多读点”，要变成具体练习：

- `source_fidelity` 低：做引用回查练习；
- `retrieval_coverage` 低：做查询分解和多跳检索；
- `cross_book_synthesis` 低：做两本书对同一事件的对照表；
- `conflict_handling` 低：做“冲突不平均”练习；
- `calibration` 低：写反证条件；
- `failure_mode_awareness` 低：给每个框架写失效案例。

然后把这些练习排进间隔复习队列。当前项目还没有 scheduler，可以先用 Obsidian 的复习属性或外部工具承载。

## 4. 多智能体怎么用

多智能体不是“多开几个模型让它热闹”，而是把**不同认知职责**分开，减少自说自话。适合 BookCompiler 的角色：

| 角色 | 职责 | 对应工具 |
|---|---|---|
| 出题者 | 先根据问题生成检索题/反例题 | `book_plan`、`book_recall` |
| 读者/编译者 | 读书、写书卡和框架卡 | `book_export_text`、`book_compile` |
| 费曼解释者 | 不看原文，用大白话解释 | 只给问题和书卡，不给原文 |
| 反方/红队 | 专门找反例、失败条件、被忽略的镜头 | `book_analyze` + claim 冲突 |
| 引用审计员 | 逐字核对 quote、章节、页码 | `book_validate`、`reading-eval` |
| 综合者 | 合并多镜头，写条件结论 | `analysis-apply` |
| 独立 judge | 按九维 rubric 盲评最终答案 | `book_reading_eval` |
| 进化管理员 | 把重复弱项变成提案，跑 replay/shadow | `book_evolution` |

推荐顺序：

```text
出题者 -> 读者/编译者 -> 费曼解释者 -> 反方 -> 引用审计员 -> 综合者 -> 独立 judge -> 进化管理员
```

关键纪律：

1. **judge 不能看作者的解释**，否则不是盲评。
2. 反方只负责找问题，不负责给最终答案。
3. 引用审计员只认原文，不接受“听起来对”。
4. 综合者不能把冲突平均掉。
5. 多智能体的结论仍然要落回 `AnalysisPacket` 和 `reading_evaluations`，否则无法复盘。

这条路比“一个 agent 反复自我反思”更可靠，因为不同角色有不同目标，能形成真正的对抗性检查。代价是成本、延迟和编排复杂度更高。

## 5. 现在就能做 vs 需要开发

### 现在就能做

- 用提示词固定“先闭卷回答，再查书”的流程；
- 每轮分析后强制跑九维评分；
- 用 `reading-report` 的 `next_actions` 做弱项练习；
- 导出 Obsidian，用 Dataview 做书卡/claim/评分看板；
- 用 Codex/Hermes 的 subagent 或独立会话扮演反方和 judge。

### 需要开发

- `reading-practice`：从弱项和书卡自动生成练习题；
- 复习队列：给书、框架、claim 加 `next_review_at` 和掌握度；
- 盲评协议：隐藏版本、配对比较、多 judge 多数决；
- 多智能体编排：角色、权限、共享证据、冲突记录；
- 结果追踪：不只评回答，还记录用户后来做了什么（Kirkpatrick 第四层）。

## 6. 研究来源

### 学习科学

- Roediger & Karpicke, *Test-Enhanced Learning: Taking Memory Tests Improves Long-Term Retention* (2006).
- Dunlosky et al., *Improving Students' Learning With Effective Learning Techniques* (2013).
- Ericsson, Krampe & Tesch-Römer, *The Role of Deliberate Practice in the Acquisition of Expert Performance* (1993).
- Anderson & Krathwohl, *A Taxonomy for Learning, Teaching, and Assessing* (2001).
- Biggs & Collis, *Evaluating the Quality of Learning: The SOLO Taxonomy* (1982).
- Chi & Wylie, *The ICAP Framework: Linking Cognitive Engagement to Active Learning Outcomes* (2014).
- Sweller, *Cognitive Load During Problem Solving* (1988).
- Collins, Brown & Newman, *Cognitive Apprenticeship: Teaching the Crafts of Reading, Writing, and Mathematics* (1989).
- Argyris & Schön, *Organizational Learning: A Theory of Action Perspective* (1978).
- Kirkpatrick, *Evaluating Training Programs* (1959/1994).
- Ahrens, *How to Take Smart Notes* (2017).

### 近期论文/预印本

- *Enhancing Student Learning with LLM-Generated Retrieval Practice Questions* — arXiv:2507.05629.
- *Unbounded Human Learning: Optimal Scheduling for Spaced Repetition* — arXiv:1602.07032.
- *Learning by Self-Explanation, with Application to Neural Architecture Search* — arXiv:2012.12899.
- *Do Gains from Generative AI-Enabled Adaptive Pretesting Persist?* — arXiv:2606.22328.

### 说明

这些来源支持的是“这些方法在人类学习中有证据/有理论”，不等于“接进 agent 就一定提升”。BookCompiler 必须用自己的 `reading-evaluations` 做前后对比，才能知道某个方法对这个书库、这类问题是否真的有效。
