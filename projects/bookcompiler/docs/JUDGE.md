# 独立九维盲评（Judge）

## 1. 它解决什么问题

`auto_proxy` 是根据引用数、书数、lens 覆盖等结构信号算出来的**分诊分数**。它便宜、可重复，但它不能证明答案真的读懂了书。它不能被叫做“盲评”。

`bookcompiler judge` 调用一个独立的模型，在**看不到 auto_proxy 分数、看不到历史评分**的情况下，只看问题、选中的书、框架、结论、反例、引用原文和确定性引用审计结果，然后给九个维度打分。

## 2. 运行

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m bookcompiler --db .bookcompiler\library.db judge `
  --analysis 49d7c5f76c4d7ed4 `
  --provider ollama `
  --model qwen2.5:7b-instruct-q4_K_M `
  --out docs\judge-eval-49d7c5f76c4d7ed4.json
```

只看 prompt、不调用模型：

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db judge `
  --analysis 49d7c5f76c4d7ed4 --dry-run --prompt-out docs\judge-prompt.txt
```

默认拒绝对 `status=draft` 的分析评分；确实要评草稿时必须显式 `--allow-draft`。

## 3. 结果写到哪里

写进主库 `.bookcompiler\library.db` 的 `reading_evaluations` 表，`evaluator` 形如：

```text
llm_judge:qwen2.5:7b-instruct-q4_K_M
```

同时保存 prompt hash、response hash、原始响应、耗时、strongest/weakest part。`reading-report` 只要存在独立评分，headline 就使用独立评分；没有独立评分时才回退到 `auto_proxy`，并明确写 `basis=auto_proxy`。

## 4. 真实样本（2026-10-18）

对真实分析 `49d7c5f76c4d7ed4` 使用 `qwen2.5:7b-instruct-q4_K_M` 跑了一次真实独立盲评：

- evaluator：`llm_judge:qwen2.5:7b-instruct-q4_K_M`
- 总分：**81.4 / 100**
- 九维：原文忠实 10、检索覆盖 9、框架适配 8、跨书综合 7、跨学科整合 6、冲突处理 8、置信校准 9、可行动性 7、失败模式 8
- 耗时：约 139 秒
- 与 auto_proxy 的偏差：`cross_lens_integration -4.0`、`cross_book_synthesis -3.0`、`actionability -3.0`，说明代理分明显高估了跨书/跨镜头整合。
- 错误标签：`retrieval_miss`、`framework_misapplication`

这是一次**独立 LLM 盲评**，不是人类专家盲评，也不是统计意义上的 benchmark。它证明链路真实可用，样本量仍然只有 1。

## 5. 失败行为

- 模型不可用、超时、返回非 JSON、缺维度：抛错，**不写评分**。
- 绝不把 `auto_proxy` 改名为 judge。
- `evolution-propose` 只接受 `llm_judge` / `human` / `mixed` 的评分，不再让 auto_proxy 驱动进化提案。

## 6. MCP / GUI

- MCP：`book_reading_eval` 的 `action=judge / judge_status / calibration`。
- GUI：分析结果里的「独立盲评」卡片，可以选 provider/model、跑真实评分或只看 prompt。