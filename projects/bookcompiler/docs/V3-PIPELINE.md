# V3 运行时流水线

## 1. 一次分析实际发生什么

```text
planner -> retriever -> reader -> feynman_explainer -> red_team
        -> citation_auditor -> lens_reviewer -> synthesizer -> judge -> evolver
```

这是一条**自动执行的确定性角色流水线**，不是多个模型自由聊天。每个角色都有显式输入/输出，trace 存在 `AnalysisPacket.orchestration`。

- `planner`：拆子问题、列证据需求
- `retriever`：hybrid + GraphRAG + RRF
- `reader`：召回 Obsidian reader notes，只作 memory
- `feynman_explainer`：生成大白话草稿，不伪造结论
- `red_team`：从 failure_modes、claim 冲突、覆盖缺口生成攻击
- `citation_auditor`：确定性引用审计
- `lens_reviewer`：每个 lens 的框架/claim/引用覆盖矩阵
- `synthesizer`：等待调用方写最终结论
- `judge`：等待独立盲评，不在流水线里伪造分数
- `evolver`：只在存在独立评分时准备进化提案

## 2. 自动编排的边界

- 只有 judge 是额外的独立 LLM 调用。
- 其他角色是确定性代码阶段，不是“十个 agent 开会”。
- `apply_analysis_patch` 后会重新计算 orchestration，citation auditor / synthesizer 状态会更新。
- reader notes 永远进 `reader_notes` / `memory_context`，绝不进 `citations`。

## 3. 查看

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db orchestrate --analysis <analysis_id>
```

MCP `book_analyze` 的返回里也直接包含 `analysis.orchestration`、`analysis.retrieval.channels`、`analysis.reader_notes`。

## 4. 为什么不做“自由多智能体辩论”

自由辩论成本高、不可复现、容易互相强化幻觉。当前版本优先做可审计的角色分离；等有真实样本和 replay 集后，再考虑让 red_team 或 lens_reviewer 调用独立模型。