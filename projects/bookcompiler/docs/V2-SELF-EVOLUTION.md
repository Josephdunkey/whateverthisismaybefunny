# V2 自进化设计

## 1. 目标

V2 的目标不是让模型“自己改自己”，而是建立一个**受控、可审计、可回滚的学习闭环**：

```text
使用 -> 反馈 -> 归因 -> 提案 -> 回放 -> 影子/灰度 -> 晋升 -> 监控 -> 回滚
```

当前实现已经覆盖：

- 结构化反馈
- 反馈驱动的偏好加权
- Hindsight 式 memory recall
- 证据化 evolution proposal
- 结构 replay
- 版本化状态流转

尚未实现、但设计上预留：

- 自动生成 card/prompt/routing 的 diff
- 真正的 shadow / canary 运行
- 多模型盲评
- 自动回滚触发器

## 2. 为什么不能直接自动改

书籍分析系统的核心风险不是“回答不够聪明”，而是：

- 编造引用
- 把某本书的观点压缩成错误口号
- 把框架用在不适用的条件下
- 把经济、政治、法律三个镜头的冲突平均掉
- 用一次反馈过拟合
- 为了讨好评测而改掉真值校验

所以 V2 的原则是：

1. **证据门槛**：每个 proposal 必须引用具体 feedback。
2. **版本化**：卡片、prompt、ranking 规则都有版本。
3. **回放门槛**：结构回归 + 质量评测通过才允许晋升。
4. **可逆**：每个变更必须有 rollback。
5. **真值契约不可学习**：逐字引用校验、法律免责声明、冲突处理规则不能被“自进化”掉。

## 3. 数据层

### feedback

当前字段：

```text
feedback_id
analysis_id
rating 1-5
note
error_labels[]
preferred_book_ids[]
preferred_framework_ids[]
missing_evidence
outcome
created_at
```

### memory

```text
memory_id
kind
key
value
created_at
```

memory 只存偏好、教训、决策，不存整本书。书仍在 library 中，并通过 citation 回查。

### evolution_proposals

```text
proposal_id
version
target
change
rationale
support
evidence_feedback_ids[]
risk
rollback
gate
status
created_at
decided_at
decision_note
```

## 4. 错误分类

| label | 含义 | 主要修复层 |
|---|---|---|
| retrieval_miss | 相关书/段落存在但没被检索到 | retrieval |
| compilation_error | 书卡/框架卡误述原文 | compilation |
| framework_misapplication | 框架用在不适用条件 | framework_selection |
| citation_error | 引文、章节、页码、归属错误 | citation_validation |
| lens_omission | 请求的镜头被静默丢掉 | lens_coverage |
| conflict_suppression | 镜头冲突被平均掉 | analysis_prompt |
| overconfidence | 结论比证据更确定 | calibration |
| taste_mismatch | 风格/深度/格式不符合偏好 | ranking |

## 5. Hindsight 式记忆

借鉴 retain / recall / reflect：

- **retain**：`feedback` 和 `memory` 表保存决策、错误、偏好。
- **recall**：`recall_memory()` 根据新问题的词项和镜头，召回相关历史反馈。
- **reflect**：`propose_evolutions()` 把重复错误和偏好聚合成候选变更。

注意：

- 不把书的内容复制进 memory。
- 不把一次低分直接当成事实。
- 偏好加权有上限，避免回音室。
- memory 只影响选择和分析提示，不改变引用真值。

## 6. 自动偏好加权

当前实现：

- 用户显式 `--prefer-book` / `--prefer-framework` 会累计权重。
- `select_books()` 和 `select_frameworks()` 对偏好加有限分。
- 原因会出现在 selection card 的 `reason` 字段中。

风险：

- 偏好可能过拟合。
- 少数用户反馈可能压过更好的证据匹配。

缓解：

- 权重上限。
- 在 replay 中同时报告 hit rate 和多样性。
- 未来把偏好权重做成版本化配置，而不是永久写入卡片。

## 7. 演化提案

`evolution-propose` 会生成：

- 错误模式 proposal
- 偏好书/框架 proposal
- 缺失证据 proposal
- 低分分析 review proposal

每个 proposal 包含：

- target
- change
- rationale
- support
- evidence_feedback_ids
- risk
- rollback
- gate

`evolution-decide` 支持状态：

```text
accepted
rejected
shadow
promoted
rolled_back
```

状态流转是受控的，CLI 会拒绝非法跳步：

```text
proposed -> accepted -> shadow -> promoted -> rolled_back
     \-> rejected
```

`promoted` 不是随手可设的状态：必须先把 proposal 放进 `shadow`，并提供一份结构回放全通过的 `--replay-report`。报告会以 `promotion_evidence` 写回 proposal，晋升后仍可 `rolled_back`。目前回放门槛只证明“没有结构回归”，不证明质量一定更好；真正的 diff 应用、shadow 双跑和盲评仍在后续版本。


## 8. Replay

当前 `replay` 是结构回归：

- 能否选到预期书
- 能否选到预期框架
- 引用是否逐字有效
- 镜头覆盖是否完整
- 是否有结构 error
- 是否召回 memory

案例格式：

```json
[
  {
    "case_id": "case-1",
    "query": "Central bank cuts reserve requirements",
    "lenses": ["economics", "politics", "law"],
    "mode": "auto",
    "expected_book_ids": ["book-id"],
    "expected_framework_ids": ["framework-id"]
  }
]
```

质量评测仍应使用盲评 rubric：

- 证据准确性
- 引用可核验性
- 镜头覆盖
- 冲突处理
- 反证质量
- 校准
- 可执行性
- 是否真正用了指定书/框架

## 9. 基线

建议固定三类基线：

1. 裸模型
2. 普通 RAG
3. 本系统当前版本

候选变更作为第四组，和当前版本在同一批事件上比较。至少 20 个事件：

- 10 个用户提供
- 10 个 agent 提议并经用户确认

## 10. 晋升门槛

代码当前强制：

- 状态必须是 `shadow -> promoted`
- 必须提供 replay report
- report 至少包含 1 个 case
- `case_count == structural_pass_count == len(cases)`
- 每个 case 的 `structural_pass` 为真，且没有 severity=error 的 issue
- 报告中没有 `regressions`
- 晋升证据写入 `promotion_evidence`，之后可 `rolled_back`

代码尚未强制、但建议在真实上线前补上：

- 引用错误率不高于当前版本
- 镜头覆盖不低于当前版本
- 盲评总分显著不低于当前版本
- 至少一个目标指标有提升
- 没有引入新的高风险错误类型
- 有明确 rollback

- 结构回归全通过
- 引用错误率不高于当前版本
- 镜头覆盖不低于当前版本
- 盲评总分显著不低于当前版本
- 至少一个目标指标有提升
- 没有引入新的高风险错误类型
- 有明确 rollback

## 11. 后续实现顺序

1. 把 proposal 的 `change` 从描述升级为可执行的 diff。
2. 增加 prompt/card/ranking 版本表和 activate/deactivate。
3. 增加 shadow 模式：同一事件同时跑当前版本和候选版本。
4. 增加 canary：只对一部分事件启用候选版本。
5. 增加自动回滚：citation error 或结构 error 超阈值时回滚。
6. 增加跨领域迁移：换书库和镜头，复用同一演化闭环。
