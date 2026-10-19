# 信息源缺口提示（Source Gaps）

## 为什么需要它

普通选书逻辑只看“这个学科有没有书”。这会漏掉一类更危险的问题：书库里有中央银行教材，却没有《中华人民共和国中国人民银行法》；有财政学教材，却没有《预算法》或地方政府债务的正式文件。

教材能提供解释框架，但不能替代法条原文。对于“央行有没有这个权限”“地方债限额由谁决定”“监管机关能不能这样做”之类的问题，缺少一手信息源时，agent 应该说：

> 我现在的书库不足以给出可靠的法律判断。请先下载并入库这些权威原文。

而不是继续用二手材料写出一篇看起来完整的分析。

## 它怎么工作

1. 读取问题 `query` 和方向 `direction`。
2. 用内置的权威信息源目录做关键词匹配。
3. 检查书库中是否已经有同名或近同名文件（包括只 ingested、尚未编译的书）。
4. 对缺失项生成 `source_recommendations`，包含：
   - `title`：需要下载的标题；
   - `priority`：high / medium；
   - `source_type`：law / regulation / policy；
   - `why`：为什么这个问题需要它；
   - `matched_terms`：命中了问题里的哪些词；
   - `suggested_disciplines`：入库时建议打的学科标签；
   - `official_source`：去哪里核对官方现行有效版本；
   - `ingest_hint`：可直接复制修改的入库命令；
   - `next_check`：入库后应该复核什么。

它不会自动联网下载，也不会把未入库的法规写进引用或证据池。

## 在哪些地方出现

- CLI `plan` / `analyze` 的选择卡；
- CLI `source-gaps` 独立报告；
- `AnalysisPacket.selection.source_recommendations`；
- `AnalysisPacket.next_checks`；
- Markdown memo 的 `Suggested sources to download and ingest`；
- MCP `book_plan` / `book_analyze` 的返回值；
- Web GUI 的选择卡和已保存分析视图。

## 三种使用方式

### 1. 独立检查缺口

```powershell
bookcompiler --db .bookcompiler\library.db source-gaps `
  --query "如果中国央行降准，银行信贷是否必然扩张？请从货币政策、地方财政和金融监管三个角度分析。" `
  --lenses economics politics law `
  --format text
```

### 2. 在选择卡里看

```powershell
bookcompiler --db .bookcompiler\library.db plan `
  --mode auto `
  --query "央行降准后银行信贷是否必然扩张？" `
  --lenses economics politics law `
  --format text
```

输出里会有：

```text
## Suggested sources to download and ingest

- [HIGH] 中华人民共和国中国人民银行法 (law, 中国)
  - Why: ...
  - Matched terms: 央行, 降准, 货币政策
  - Suggested disciplines: law, finance
  - Ingest: bookcompiler ingest "PATH_TO_DOWNLOADED_FILE" ...
```

### 3. 让 agent 通过 MCP 看

Hermes / Codex 调用 `book_plan` 后，返回值中会出现：

```json
{
  "source_recommendations": [
    {
      "title": "中华人民共和国中国人民银行法",
      "priority": "high",
      "action": "download_and_ingest"
    }
  ]
}
```

工具描述已经要求调用方把这些项明确转告用户，不能静默忽略，也不能说成“已经读过”。

## 首批内置目录

| 信息源 | 类型 | 主要触发问题 |
|---|---|---|
| 中华人民共和国中国人民银行法 | 法律 | 央行、降准、货币政策、公开市场操作、流动性 |
| 中华人民共和国商业银行法 | 法律 | 商业银行、银行信贷、贷款、存款、信贷扩张 |
| 中华人民共和国银行业监督管理法 | 法律 | 金融监管、银行监管、宏观审慎、监管权限 |
| 中华人民共和国预算法 | 法律 | 预算、地方债、转移支付、财政赤字、债务限额 |
| 中华人民共和国预算法实施条例 | 行政法规 | 预算执行、预算调整、预算公开、地方债 |
| 中华人民共和国立法法 | 法律 | 立法权限、授权立法、法律依据、法定权限 |
| 国务院关于加强地方政府性债务管理的意见（国发〔2014〕43号） | 政策文件 | 地方政府债务、融资平台、城投、隐性债务、土地财政 |
| 商业银行资本管理办法 | 监管规章 | 资本充足率、风险加权资产、银行资本 |
| 商业银行流动性风险管理办法 | 监管规章 | 流动性覆盖率、净稳定资金比例、流动性风险 |

目录是保守的起点，不是穷尽所有法规。新增领域时，应该把“领域术语 → 权威文本”的映射加入 `src/bookcompiler/source_gaps.py`，而不是让模型自由编造文件名。

## 设计边界

- **不自动下载**：避免版权、版本失效和来源不可信问题。
- **同名不重复提示**：书已在库（哪怕还没编译）就不再让你下载。
- **不把提示当证据**：`source_recommendations` 只影响下一步建议，不进入 citations。
- **优先官方现行有效版本**：法规会修订，入库时应记录公布/修订日期。
- **版本信息仍需人工核对**：命中关键词只说明“这个问题可能需要它”，不代表当前版本一定适用。

## 一个完整闭环

```text
问题
  → 选书 / 选框架
  → 发现权威原文缺口
  → 提示下载并给出入库命令
  → 用户下载官方文本
  → bookcompiler ingest
  → export-text + compile + validate
  → 下一轮分析才能把该法规作为证据使用
```

这就是“读书作为 agent 能力”与“普通 RAG”的一个重要区别：系统不仅检索已有内容，还会知道自己缺什么，并把缺口变成下一步可执行动作。