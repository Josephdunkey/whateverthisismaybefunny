# 宏观金融分析 · 评测

## 两种评测，不要混为一谈

1. **覆盖率评测（结构）**：检查期望的书/框架/镜头/冲突是否在包内。零模型调用，适合每次更新后跑。
2. **答案深度评测（judge）**：让独立模型按下面 rubric 打分。它不能替代人工盲评。

## Rubric（0–10）

- `source_fidelity`：Every factual claim is grounded in an exact book quote; no invented source.
- `retrieval_coverage`：The relevant books, chapters and frameworks were actually retrieved.
- `framework_fit`：The chosen frameworks genuinely fit the event and their inputs are available.
- `cross_book_synthesis`：At least two books are integrated, not merely listed side by side.
- `cross_lens_integration`：Economics, politics and law are combined without flattening their differences.
- `conflict_handling`：Cross-book contradictions are stated and not silently averaged away.
- `calibration`：Confidence matches the evidence; uncertainty and falsifiers are explicit.
- `actionability`：The answer gives conditional implications or decisions, not just description.
- `failure_mode_awareness`：The framework's failure modes and boundary conditions are applied.
- `causal_depth`：The answer traces mechanisms and transmission channels, not just correlations.
- `counterargument`：A serious rival explanation is stated and tested.
- `boundary_conditions`：The answer says when the conclusion would stop holding.
- `falsifiability`：Concrete indicators or observations that would change the judgment are named.

## 通过线

- 总分 ≥ 7.0。
- 任一维度不得低于 5。
- 引用必须可回到原文；发现编造引用直接判失败。
- 只引用一本书时，`cross_book_synthesis` 不得高于 3。
- 没有可证伪条件时，`calibration` 不得高于 5。

## 运行

```powershell
bookcompiler capability eval --domain macro-finance
```

Golden set 使用 JSONL，每行一个事件，字段见 `eval/golden.jsonl`。
