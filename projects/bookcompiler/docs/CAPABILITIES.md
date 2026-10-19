# 领域能力包（Capability Packs）

## 一句话

**对宿主只暴露一个 `book-library` 技能；内部维护少量领域能力包。** 新书增量合并进已有包，不按书生成技能。

这样做的原因：

- 每本书一个技能会导致路由爆炸：书越多，宿主越难选，上下文也越碎。
- 领域包能跨书对照、保留冲突、沉淀可执行框架，而不是把书压成一段摘要。
- 一个包可以按需渐进加载：先 `PACK.md`，再 1–3 个框架，再证据与争议。

## 四层结构

| 层 | 作用 | 主要文件 |
| --- | --- | --- |
| 证据层 | 原文、claims、实体、GraphRAG | `sources.md` / `pack.json` / `library.db` / `library.graph.db` |
| 程序层 | 可执行框架与推理协议 | `frameworks.md` / `PACK.md` |
| 经验层 | 反馈、偏好、长期记忆 | `LOCAL.md` / Hindsight |
| 评测层 | 覆盖率、独立 judge、回归 | `eval.md` / `eval/golden.jsonl` / `eval/last-run.json` |

这不是“加强版 RAG”。RAG 只解决“找到哪段话”；能力包还规定“用哪个框架、按什么顺序推理、冲突怎么处理、什么条件下结论失效”。

## 目录

```text
skills/book-library/
  SKILL.md                         # 唯一入口，告诉 agent 如何路由
  references/packs/
    index.json                     # 所有包的索引
    political-economy/
      pack.json                    # 机器可读的事实来源
      PACK.md                      # 何时用、推理协议、覆盖缺口
      sources.md                   # 书、claims、实体、原文引用
      frameworks.md                # 框架的输入/步骤/输出/失效模式
      debates.md                   # reviewed 冲突与 candidate 冲突
      boundaries.md                # 书的假设/局限 + 框架失效模式
      eval.md                      # 评测说明与 rubric
      eval/golden.jsonl            # 事件型 golden set
      eval/last-run.json           # 最近一次覆盖率结果
      LOCAL.md                     # 用户所有；重建不会覆盖
      CHANGELOG.md                 # 版本历史
```

## 路由策略

先调用：

```json
book_capability {"action":"route","query":"2024年地方债化债推进，城投和银行信贷会怎样？","lenses":["economics","politics"]}
```

返回：

- `selected`：明确胜出的包；`requires_confirmation=false` 时可直接加载。
- `requires_confirmation=true`：弱匹配、两个包分数接近、或高风险问题。此时必须把候选、分数和理由展示给用户，让用户选。
- 最多加载两个包，避免把多个领域混成一锅。

自动选择的门槛：

- 第一名分数 `>= 5`；
- 与第二名差距 `>= 2`；
- 否则询问用户。

如果明确胜出且第二名分数也 ≥ 5，返回里会出现 `secondary`，可作为第二个包加载；仍然最多两个包。若两个包会给出不同结论，必须在回答里说明，而不是合并成一句模糊的话。

`book_capability` 决定“用哪个领域能力”，`book_plan` 决定“这个领域里具体用哪几本书/框架”。两者不一致时，明确说明不一致，不要偷偷合并。

## 回答协议（8 步，必须按顺序）

1. **事件拆解**：主体、约束、机制、时间尺度。
2. **选择镜头**：经济学/政治学/法律等，并说明为什么需要。
3. **选择框架**：从 `frameworks.md` 选 1–3 个，写出适用条件。
4. **执行步骤**：按 inputs → steps → outputs 真走一遍，不能只引用结论。
5. **跨书对照**：至少一本支持、一本限制或反对；没有就明说书库缺反对来源。
6. **冲突处理**：并列呈现，不取平均，不为了顺滑而抹平。
7. **边界与证伪**：结论在什么条件下失效，哪些指标会改变判断。
8. **引用**：每个事实句给书名、章节/页码、原文引用；推断与建议单独标注。

## 新书如何进入能力包

只允许 **learned/verified** 的书进入；仅 ingest 的书会被拒绝。

```powershell
# 1. 看这本书会影响哪些包
bookcompiler --db .bookcompiler\library.db capability impact --book-id <book_id>

# 2. 先出 diff，不写文件
bookcompiler --db .bookcompiler\library.db capability update `
  --domain political-economy --books <book_id>

# 3. 确认后应用
bookcompiler --db .bookcompiler\library.db capability update `
  --domain political-economy --books <book_id> --apply

# 4. 重新评测
bookcompiler --db .bookcompiler\library.db capability eval --domain political-economy
```

规则：

- 增量合并，保留包内旧书，不重写整包。
- 新增书 → minor 版本；只改框架/claim/触发词/描述 → patch 版本。
- 内容签名不变 → 版本不变，避免无意义抖动。
- `LOCAL.md` 永远保留；其他生成文件按设计覆盖。

## 评测的三个层次

1. **覆盖率（`capability eval`）**：零模型，检查期望的书、框架、镜头、主题、冲突是否在包内。它是结构检查，不是质量分。
2. **独立 judge（`book_reading_eval action="judge"`）**：独立模型按 rubric 打分。仍不等于人工盲评。
3. **调用方自评（`evaluator="llm_judge"`）**：是调用 agent 自己给的分数，必须如实标注。

`auto_proxy` 只能用于分诊，不能冒充人工盲评或盲测。

## 常用命令

```powershell
# 预设与列表
bookcompiler --db .bookcompiler\library.db capability presets
bookcompiler --db .bookcompiler\library.db capability list

# 构建（默认使用预设书目）
bookcompiler --db .bookcompiler\library.db capability build --domain political-economy

# 自定义
bookcompiler --db .bookcompiler\library.db capability build `
  --domain macro-finance --title "宏观金融" --lenses economics finance `
  --books "中央银行与货币供给" "这次不一样：八百年金融危机史"

# 路由
bookcompiler --db .bookcompiler\library.db capability route `
  --query "美联储降息、人民币汇率与资本流动" --lenses economics finance

# 状态与评测
bookcompiler --db .bookcompiler\library.db capability status --domain political-economy
bookcompiler --db .bookcompiler\library.db capability eval --domain political-economy
```

MCP 侧只增加了一个工具 `book_capability`，支持
`presets/list/status/route/build/impact/update/eval`。写操作默认只出 diff，`apply=true` 才落盘。

## 与环境的关系

- `BOOKCOMPILER_CAPABILITY_ROOT` 可覆盖默认包目录。
- 包默认写在项目 `skills/book-library/references/packs/`；Hermes 通过 BookCompiler MCP 读取，不需要复制一份包。
- Obsidian 导出与 Hindsight 记忆不受能力包影响；`LOCAL.md` 是包内的人工补充，不是长期记忆库。
