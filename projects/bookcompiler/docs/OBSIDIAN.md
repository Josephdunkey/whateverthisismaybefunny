# 接入 Obsidian：能做什么，怎么做

> 结论：**能接，而且很适合**。当前实现是“受控双向”：BookCompiler 把书卡、框架、claim、实体和分析写成 Markdown；手改会保留并生成 `*.generated.md`，不再静默覆盖。用户批注走 `BookCompiler Inbox/` 导入 SQLite。Hindsight 的 `world` / `experience` 记忆可直接编辑并 PATCH 回 Hindsight，`observation` 只读。

## 1. 为什么值得接

Obsidian 是本地 Markdown + 双向链接 + 图谱视图。它刚好适合承载 BookCompiler 的“知识层”：

- 一本书一个笔记；
- 一个 FrameworkCard 一个笔记；
- 一条 claim 一个笔记；
- 一个实体一个笔记；
- 一次分析一个笔记；
- 自动生成 `[[wikilink]]`，可以在图谱里看到书、框架、claim、实体之间的关系；
- 用 Dataview 做书库看板、弱项看板、待复习看板。

它不负责检索和推理。检索仍然由 BookCompiler 的 SQLite/FTS/embedding/claim graph 做，Obsidian 是**阅读、浏览、复盘、写作**的界面。

## 2. 安装与创建 vault

1. 安装 Obsidian：<https://obsidian.md/>
2. 打开 Obsidian，选择 “Create new vault” 或 “Open folder as vault”。
3. 选一个本地目录，例如：

```text
D:\MyVault
```

4. 记住这个目录，它就是下面的 `<vault>`。

## 3. 导出命令

在项目目录运行：

```powershell
cd C:\Users\mybea\projects\bookcompiler
.\.venv\Scripts\python.exe -m bookcompiler --db .bookcompiler\library.db obsidian-export --vault "D:\MyVault"
```

默认只写：

```text
D:\MyVault\BookCompiler\
```

不会碰 vault 里 `BookCompiler` 之外的其他笔记。

常用参数：

```powershell
# 只导出某本书
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-export `
  --vault "D:\MyVault" --book <book_id>

# 换子目录
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-export `
  --vault "D:\MyVault" --subdir "Research/Books"

# 不导出 claims / entities / analyses
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-export `
  --vault "D:\MyVault" --no-claims --no-entities --no-analyses

# 已存在的文件不覆盖
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-export `
  --vault "D:\MyVault" --no-overwrite
```

## 4. 导出后的目录

```text
<vault>\BookCompiler\
  BookCompiler MOC.md
  .bookcompiler-export.json
  Books\
    <书名>.md
  Frameworks\
    <框架名>.md
  Claims\
    claim-<id>.md
  Entities\
    <实体名>.md
  Analyses\
    analysis-<id>.md
```

`BookCompiler MOC.md` 是总入口，包含书、分析、Dataview 示例和计数。  
`.bookcompiler-export.json` 是导出清单，记录生成了哪些文件、计数和时间，便于以后做增量导出。

## 5. 笔记里有什么

### 书笔记

YAML frontmatter 示例：

```yaml
---
generator: "bookcompiler"
type: "book"
book_id: "..."
title: "..."
author: "..."
status: "compiled"
learned: true
disciplines: ["economics", "politics", "law"]
frameworks: 3
claims: 160
tags: ["bookcompiler/book", "discipline/economics"]
---
```

正文包含：

- 一句话主张；
- 核心问题、关键概念、假设、局限；
- 适用/不适用；
- 框架列表；
- claims 列表；
- 实体列表；
- 章节覆盖与逐字引用；
- 返回 MOC 的链接。

### 框架笔记

包含：适用条件、输入、步骤、输出、失败模式、反例、相关框架、原文引用。

### claim 笔记

包含：主语/谓语/宾语、状态、置信度、极性、条件、resolution、逐字 quote、来源书、主体实体、claim 关系。

### 实体笔记

包含：实体类型、别名、摘要、出现过的书、实体关系、mentions（章节/页码）。

### 分析笔记

包含：问题、镜头、状态、`reading_score`（如果做过评分）、完整 memo、九维分数、返回 MOC 的链接。

## 6. Dataview 看板示例

Obsidian 需要安装 Dataview 社区插件。以下查询放在任意笔记里即可。

### 书库看板

```dataview
TABLE status, learned, frameworks, claims, author
FROM "BookCompiler/Books"
SORT learned DESC, title ASC
```

### 只看已学会的书

```dataview
TABLE author, frameworks, claims
FROM "BookCompiler/Books"
WHERE learned = true
SORT title ASC
```

### claim 状态看板

```dataview
TABLE book_id, status, confidence
FROM "BookCompiler/Claims"
SORT status ASC, confidence DESC
```

### 最近分析及评分

```dataview
TABLE status, reading_score
FROM "BookCompiler/Analyses"
SORT updated_at DESC
LIMIT 20
```

### 实体出现次数

```dataview
TABLE entity_type, book_count, mentions
FROM "BookCompiler/Entities"
SORT mentions DESC
LIMIT 30
```

## 7. 图谱视图怎么用

打开 Obsidian 的 Graph View，能看到：

- 书 → 框架；
- 书 → claim；
- claim → 实体；
- 分析 → 书；
- 实体 → 实体。

这适合发现“同一实体在多本书里反复出现”“某本书的 claim 全挂在少数实体上”“某个框架没有被任何分析使用”等问题。

## 8. 推荐的 Obsidian 工作流

### 8.1 读书笔记与书卡分离

生成的 `BookCompiler/Books` 笔记当作**只读视图**。  
自己的批注、问题、复习记录放到另一个目录，例如：

```text
<vault>\ReadingNotes\
```

用 `[[BookCompiler/Books/书名]]` 链接回去。这样重新导出不会覆盖你的手写笔记。

### 8.2 用 Obsidian 做复习队列

当前导出没有自动写 `next_review_at`。你可以先手工加属性：

```yaml
review_due: 2026-10-25
mastery: 2
```

生成笔记是**受保护导出**：你手改的原文件会被保留，新版本写 `*.generated.md`，不会静默覆盖；但这些手改不会回写 SQLite。要让复习属性进入队列，请放在独立的 `ReadingNotes` 笔记或 `BookCompiler Inbox/`，再用 Dataview 或 `obsidian-review` 查询。

### 8.3 用 MOC 做入口

每天打开 `BookCompiler MOC.md`，看：

- 哪些书已学会；
- 哪些分析分数低；
- 哪些 claim 是 conflicted；
- 哪些实体跨书最多。

### 8.4 写作与输出

Obsidian 里可以直接基于书卡和 claim 写文章、报告、课程大纲。  
但引用仍然要回到 `Books/...` 笔记里的逐字 quote，不要只引用 Obsidian 里的摘要。

## 9. 当前限制

1. **生成笔记不是任意字段回写**：BookCompiler 生成笔记手改会保留，但不会自动改写 SQLite 的 book/framework/claim；要进入记忆/检索请走 `BookCompiler Inbox/`。
2. **默认受保护**：手改后原文件保留，新版本写 `*.generated.md`；不会静默覆盖。
3. **不是实时同步**：需要每次手动运行 `obsidian-sync-all` 或 `sync-obsidian.bat`。
4. **没有增量 diff 引擎**：目前按书/全库重新写，manifest 只是记录。
5. **复习调度器是基础版**：有 `review_due` 和 0–5 评分，但不是完整 SM-2/FSRS。
6. **wikilink 依赖文件名**：改名后旧链接会失效；导出器会做文件名清洗和重名加 ID。
7. **大库文件多**：真实库导出过约 760 个 Markdown 文件、5,395 个 wikilink；书越多，Obsidian 索引越慢。

## 10. 许可证与插件注意事项

调研到的 Obsidian/AI 相关项目里，有些是 AGPL-3.0，例如：

- `basicmachines-co/basic-memory`
- `khoj-ai/khoj`
- `logancyang/obsidian-copilot`

AGPL 对网络服务和衍生作品有额外义务。当前 BookCompiler **没有嵌入这些插件**，只通过中立的 Markdown 文件对接 Obsidian。这是风险最低的方式。

如果以后要接 Obsidian 插件，优先考虑：

- 只读 Markdown 导出（当前方案）；
- MIT/Apache-2.0 的插件；
- 或者把插件放在独立进程，通过文件/API 通信，避免许可证污染。

## 11. 下一步可以做什么

- **增量导出**：用 manifest 做 diff，只重写变化的书/claim；
- **稳定 ID 链接**：用 `book_id`/`claim_id` 做别名，减少改名坏链；
- **复习队列**：导出 `next_review_at`、`mastery`、`last_reviewed_at`；
- **更广的双向同步**：V3 已支持 Inbox 批注与 Hindsight 记忆回写；仍未支持“任意生成笔记字段反向改写 SQLite 书卡/框架卡”；
- **Canvas**：把跨书冲突和多镜头分析导出成 Obsidian Canvas；
- **Dataview 模板包**：提供书库、弱项、复习、冲突四个看板模板。

## 12. 相关文档

- `docs/READING-SCORE.md`：九维评分和反馈进化。
- `docs/LEARNING-METHODS.md`：间隔复习、检索练习、Zettelkasten 等学习方法。
- `docs/RAG-LANDSCAPE.md`：为什么 Obsidian 不是检索后端。

## V3：受控双向同步（2026-10-18）

现在的实现不是“任意笔记双向同步”，而是：

1. `<vault>\BookCompiler\` 生成目录：导出 + 手改保护；原文件保留，新版本写 `*.generated.md`。
2. `<vault>\BookCompiler Inbox\` 用户 inbox：导入 SQLite；BookCompiler 不编辑它。
3. 导入表：`obsidian_notes`、`review_queue`、`obsidian_sync_runs`。
4. 支持 frontmatter：`note_id`、`target_type`、`target_id`、`title`、`tags`、`rating`、`mastery`、`review_due`。
5. 支持 `[[Books/...]]` wikilink 推断目标。
6. 幂等导入：同一路径 + 内容 hash 不重复写。
7. 无效目标 -> `orphaned`；inbox 删除 -> `missing`，不销毁历史。
8. `review_due` -> 复习队列 -> `obsidian-review --grade 0..5`。
9. Reader notes 只进 `reader_notes` / memory，绝不进 `citations`。

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-sync `
  --vault "D:\notes" --direction both
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-notes --query "储备"
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-review
```

## V4：Hindsight 记忆镜像（2026-10-18）

`<vault>\Hindsight\` 是 Hindsight 记忆的可编辑镜像：

```text
Hindsight/
  Memories/world/*.md
  Memories/experience/*.md
  Observations/observation/*.md   # 只读
Hindsight Inbox/                   # 新建记忆
```

- `world` / `experience`：改正文、Context、state 后运行 `hindsight-obsidian-sync --direction both`，会 PATCH 回 Hindsight。
- `observation`：派生记忆，只读；改了也会跳过。
- `state` 改成 `invalidated` 可软失效，改回 `valid` 可恢复。
- 本地和远端都改过：生成 `*.conflict-YYYYMMDD-HHMMSS.md`，不自动选。
- 同步状态：`.bookcompiler/hindsight-obsidian-state.json`。
- 新记忆：在 `Hindsight Inbox/` 新建 Markdown，不带 `hindsight_id`，同步时 retain。

一键：

```powershell
.\sync-obsidian.bat
# 或
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-sync-all
& $py -m bookcompiler --db .bookcompiler\library.db hindsight-obsidian-sync --direction both
& $py -m bookcompiler --db .bookcompiler\library.db hindsight-obsidian-status
```
