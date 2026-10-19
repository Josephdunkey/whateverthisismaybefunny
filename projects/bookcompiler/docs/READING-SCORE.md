# 读书效果评分与反馈进化

> 目标不是给 agent 戴高帽，而是把“这本书到底有没有被用起来”变成可评分、可复盘、可回滚的闭环。它借鉴达尔文技能的基本节奏：**评估 → 找弱项 → 做小改动 → 验证 → 人类确认 → 保留或回滚**，但评的是“读书后回答问题的效果”，不是 SKILL.md 的写作质量。

## 1. 评什么

`reading-eval` 评的是一次 `AnalysisPacket` 最终回答的“读书有效性”。它不是评文笔，也不是评模型参数，更不是评某本书本身好不好。

九个维度，单项 0–10 分，加权后总分 100：

| 维度 | 权重 | 核心问题 |
|---|---:|---|
| `source_fidelity` 原文忠实度 | 18 | 引用是否逐字来自原文，章节和页码是否可核验，是否存在编造或错配？ |
| `retrieval_coverage` 检索覆盖 | 14 | 是否召回了回答所需的关键章节、证据和框架，而不是只抓到表面相似的段落？ |
| `framework_fit` 框架适配 | 12 | 所用框架是否真的适用于当前问题，而不是只在套用书名或术语？ |
| `cross_book_synthesis` 跨书综合 | 12 | 是否让多本书真正互相补充或对照，而不是把几本书并列摘抄？ |
| `cross_lens_integration` 跨学科整合 | 12 | 经济、政治、法律等镜头是否形成相互制约的整体判断？ |
| `conflict_handling` 冲突处理 | 10 | 是否显式处理书与书、镜头与镜头之间的矛盾，而不是把冲突平均掉？ |
| `calibration` 置信校准 | 8 | 结论是否给出适用条件、不确定性和反证条件？ |
| `actionability` 可行动性 | 8 | 是否给出可观察指标、下一步检查或可执行建议？ |
| `failure_mode_awareness` 失败模式意识 | 6 | 是否说明框架何时会失效、有哪些反例和适用边界？ |

计算方式：

```text
总分 = Σ(单项分 / 10 × 权重)
```

例如 `source_fidelity=9` 贡献 `9/10×18=16.2` 分。满分 100。

## 2. 四种评分者

| evaluator | 含义 | 能不能当成真实质量结论 |
|---|---|---|
| `auto_proxy` | 从 packet 的结构信号自动生成：引用数、书数、镜头覆盖、冲突字段等 | **不能**。只用于分诊和发现明显空洞 |
| `human` | 人实际打分 | 可以，但要注意评分者偏差 |
| `llm_judge` | 独立 judge agent 按 rubric 打分 | 可以作参考，最好做盲评和多次比对 |
| `mixed` | 部分维度人工/LLM 打分，其余保留自动代理 | 只能逐维解释，不能把混合分当纯人工分 |

**重要诚实说明**：自动代理分不是盲评，也不是“agent 真的学会了”的证明。它只能告诉你“这份回答在结构上像不像认真用过书”。真正的质量结论需要人工或独立 LLM judge，最好再加同一 judge 的前后配对比较。

## 3. 命令行用法

先确保用项目 venv，避免 embedding 静默降级：

```powershell
cd C:\Users\mybea\projects\bookcompiler
$py = ".\.venv\Scripts\python.exe"
```

### 给一次分析打分

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db reading-eval `
  --analysis <analysis_id> `
  --evaluator llm_judge `
  --score source_fidelity=8 `
  --score retrieval_coverage=7 `
  --score cross_book_synthesis=4 `
  --note "只真正用了两本书，第三本只是列书名" `
  --error retrieval_miss `
  --error citation_error
```

也可以用 JSON 文件一次传完整分数：

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db reading-eval `
  --analysis <analysis_id> --evaluator llm_judge --scores-file scores.json
```

`scores.json` 示例：

```json
{
  "source_fidelity": 8,
  "retrieval_coverage": 7,
  "framework_fit": 7,
  "cross_book_synthesis": 4,
  "cross_lens_integration": 6,
  "conflict_handling": 5,
  "calibration": 6,
  "actionability": 5,
  "failure_mode_awareness": 4
}
```

不传的维度会保留自动代理分，并在 `overrides` 字段里记录哪些维度是真实判断。

### 查看单次与汇总

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db reading-eval-list --analysis <analysis_id>
& $py -m bookcompiler --db .bookcompiler\library.db reading-report --format markdown
& $py -m bookcompiler --db .bookcompiler\library.db reading-report --format json --out reading-report.json
```

`reading-report` 会给出：

- 评估次数、平均分、最近一次分数；
- 最近 5 次相对前 5 次的变化；
- 分数段分布；
- 九个维度的均值、最新值、最低值、最高值；
- 低于 6.0 的弱项；
- `next_actions`：每个弱项对应的下一步练习建议；
- 错误标签统计。

### 把弱项变成进化提案

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db reading-propose --min-support 3
```

`min-support=3` 表示至少要有 3 次评估支持同一个弱项，才比较容易形成稳定建议。提案类型是 `review_reading_dimension`，它只**建议**检查某个维度，不会自动改书卡、提示词或检索权重。

## 4. 评分怎样进入受控进化

现有闭环：

```text
最终回答
  -> reading-eval 打分
  -> reading-report 找弱项
  -> reading-propose 生成 review_reading_dimension 提案
  -> proposed
  -> accepted
  -> shadow
  -> promoted（需要 replay + shadow/canary + 人工确认）
  -> rolled_back（如有问题）
```

约束：

1. 提案必须带评估证据 ID。
2. 提案必须写风险和回滚方式。
3. 状态变更不等于自动应用。
4. 不允许削弱逐字引用校验、法律免责声明、冲突处理。
5. 晋升必须经过 replay 和用户确认；当前代码不会自动把弱项变成“永久规则”。

### 和达尔文技能的对照

| 达尔文技能 | 本项目的读书评分 |
|---|---|
| 9 维 rubric 评 SKILL.md | 9 维 rubric 评“读书后回答” |
| 独立 judge agent | `llm_judge` / `human` / `mixed` |
| 测试 prompt 实测 | `AnalysisPacket` 的真实回答 |
| 只保留改进的棘轮 | `proposed → accepted → shadow → promoted` 状态机 |
| 人在回路 | 晋升需要用户确认 |
| 自动回滚 | 提案带 rollback，可回滚到快照 |

**还没做到的部分**：盲评、同一 judge 的配对比较、多个 judge 多数决、自动生成对照答案、自动做大规模回归。这些是下一阶段，而不是现在已经完成的能力。

## 5. 数据存在哪里

默认数据库：

```text
C:\Users\mybea\projects\bookcompiler\.bookcompiler\library.db
```

评分表：

```sql
CREATE TABLE reading_evaluations (
  evaluation_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL,
  evaluator TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  total REAL NOT NULL,
  scores TEXT NOT NULL,
  data TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

- `scores` 是九维分数的 JSON。
- `data` 是完整评估 JSON，包括权重、自动代理分、人工覆盖、诊断、错误标签。
- 进化提案在 `evolution_proposals` 表。
- 当前真实库还没有真实评分和真实提案；已有代码路径和测试，需要你实际跑分析后积累。

## 6. 推荐使用纪律

1. **只评最终回答**，不要评草稿脚手架。
2. 一次回答至少让独立 judge 按九维打一遍；有条件就做盲评。
3. 同一维度连续 3 次低于 6.0，再考虑提案。
4. 先修 `source_fidelity` 和 `retrieval_coverage`，再谈文风。
5. 不要把 `auto_proxy` 分数写进对外报告冒充人工结论。
6. 评分后看 `next_actions`，用它决定下一轮读什么、练什么，而不是只追求总分。

## 7. 下一步路线图

- **P0：真实评分积累**：先把 20–50 次最终回答跑完九维评分，形成基线。
- **P1：配对盲评**：同一问题生成 A/B 两版，隐藏版本，让同一 judge 比较，减少换尺噪声。
- **P1：检索充分性自检**：在回答前判断“现有证据够不够”，不够就补检索或明确说不够。
- **P2：间隔复习队列**：按书、claim、框架安排复习，而不是只在被问到时才回忆。
- **P2：按书评分**：区分“书本身没读好”和“这次回答没用上书”。
- **P3：自动生成针对性练习**：从低分维度生成费曼解释题、反例题、跨书对照题。

## 8. 相关文档

- `docs/LEARNING-METHODS.md`：人类学习方法论如何映射到本项目。
- `docs/OBSIDIAN.md`：把书卡、框架、claim、实体和分析导出到 Obsidian。
- `docs/RAG-LANDSCAPE.md`：GraphRAG、LightRAG、HippoRAG、RAPTOR 等方案的适用性。

## V3 实现状态（2026-10-18）

- 已有的 `auto_proxy` 明确只是分诊，不再被当作盲评。
- 新增 `bookcompiler judge`：独立模型盲评，prompt 不含 auto_proxy 和历史分。
- 新增 evaluator kind：`llm_judge` / `human` / `mixed` / `auto_proxy`。
- `reading-report` 有独立评分时用独立评分做 headline，并返回 `proxy_calibration`。
- `evolution-propose` 只从独立评分生成阅读维度提案。
- 真实样本：分析 `49d7c5f76c4d7ed4`，`qwen2.5:7b-instruct-q4_K_M`，总分 81.4；详细分数见 `docs/JUDGE.md`。