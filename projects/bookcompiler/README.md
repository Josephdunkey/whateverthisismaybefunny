# BookCompiler

把书编译成可引用的判断框架，再让 agent 用这些框架分析新事件。

它不是“书籍摘要聊天机器人”，也不是“读完一本书就自动变成领域专家”。它是一个可审计的中间层：

```text
书 -> 章节/证据 -> BookCard -> FrameworkCard -> 选择 -> AnalysisPacket -> 反馈 -> 受控演化
```

当前第一落地场景是政策/监管冲击分析，使用三个镜头：

- 经济学：激励、价格、约束、外部性、分配、二阶效应
- 政治学：权力、联盟、否决者、合法性、执行能力
- 法学：权限、管辖、程序、权利、责任、先例、可执行性

文学批评、金融分析等只是同一套架构的不同书库和镜头组合，不是硬编码的领域。

> **完整使用说明书（零基础图文版）**：[docs/tutorial.html](docs/tutorial.html)  
> 包含 BookCompiler、Hermes Agent、Hindsight、Ollama 的启动、对接、云端/本地模型分工、一键切模型、Obsidian 受控双向同步、记忆位置、数据库、读书评分和验收清单。

## 它不是什么

- 不是把整本书塞进上下文。
- 不是只做向量检索。
- 不是让模型自由编造“某本书说过”。
- 不是自动下载书、自动改自己的核心规则。
- 不是已经能读 100 本书就稳定成为专家。当前是可运行的 V2 参考实现，质量取决于编译出的卡片和评测。

## 四层架构

1. **RAG/证据层**
   - SQLite + FTS5 检索原文 chunk。
   - 每条证据必须有 `book_id`、`chapter`、`page`（可用时）和逐字 `quote`。
   - `validation.py` 会在原文中逐字匹配引用，找不到就报错。

2. **框架层**
   - `BookCard`：这本书主张什么、假设什么、局限是什么、适合/不适合什么。
   - `FrameworkCard`：什么时候用、输入什么、步骤是什么、输出什么、什么时候会失败。
   - 这是“怎么想”的层，不是“原文是什么”的层。

3. **记忆/反馈层**
   - 记录评分、错误类型、缺失证据、偏好的书/框架、结果备注。
   - `recall_memory()` 在新问题到来时回忆相关教训。
   - 借鉴 Hindsight 的 retain / recall / reflect 思路，但只存决策和教训，不把整本书塞进 memory。

4. **分析层**
   - 根据问题选择书和框架。
   - 生成 `AnalysisPacket`：多个假设、反证、跨镜头冲突、条件性结论、不确定性、下一步检查、引用。
   - 不把三个镜头写成三篇互不相干的文章，也不把冲突平均掉。

## 已实现的 V2 能力

- 三种选择模式：`auto`、`direction`、`books`。
- 权威信息源缺口提示：问题需要某部法律/监管规则而书库没有时，返回可执行的下载与入库提示。
- 两层约束：书 + FrameworkCard，不只是书。
- 模式 2/3 的同意门：`specified`、`specified+recommended`、`recommended`。
- 精确引用校验：框架、书卡、分析引用都逐字回查原文。
- 结构化反馈：评分、错误标签、缺失证据、偏好书/框架、结果。
- 偏好加权：明确偏好的书/框架会在后续选择中获得有限加权。
- Hindsight 式回忆：新分析会带回相关历史反馈。
- 自演化提案：从反馈中生成有证据、有风险、有回滚方案的 proposal。
- 结构化 replay：批量跑案例，检查选择、引用、镜头覆盖和结构有效性。
- 可观测性：`dashboard`、`graph`、`coverage`、`show`。
- 分析 provenance：analysis -> book / framework / chunk 的边会写入图。

## 领域能力包（Capability Packs）

对宿主只暴露一个 `book-library` 技能；内部用少量领域能力包组织已读书籍，而不是每本书生成一个技能。新书增量合并进已有包，包内保留框架、claims、跨书争议、边界条件与评测集。

```powershell
bookcompiler --db .bookcompiler\library.db capability build --domain political-economy
bookcompiler --db .bookcompiler\library.db capability route --query "地方债化债与银行信贷" --lenses economics politics
bookcompiler --db .bookcompiler\library.db capability eval --domain political-economy
```

MCP 侧对应工具：`book_capability`。路由分数接近或问题高风险时会返回 `requires_confirmation=true`，必须先让用户选择，最多加载两个包。详见 [docs/CAPABILITIES.md](docs/CAPABILITIES.md)。

## 安装

```powershell
cd C:\Users\mybea\projects\bookcompiler
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pytest -q
```

## 快速开始

```powershell
bookcompiler --db .bookcompiler/demo.db init

bookcompiler --db .bookcompiler/demo.db ingest examples\sample_book.md `
  --title "Policy Shocks" --author "Tester" `
  --discipline economics --discipline politics --discipline law

bookcompiler --db .bookcompiler/demo.db books
bookcompiler --db .bookcompiler/demo.db compile <book_id>
bookcompiler --db .bookcompiler/demo.db analyze --mode auto `
  --query "Central bank cuts reserve requirements" `
  --lenses economics politics law --render
```

`compile` 不带 `--patch` 时只会跑启发式 demo 编译器，产物标记为 `heuristic`。真实书不要把这个结果当专家编译。

## 完整演示（编译 -> 分析 -> 引用）

```powershell
python examples\golden_demo.py
```

它会新建 `.bookcompiler\golden-demo.db`，把示例书编译成 3 个框架卡，自动选题，生成一份带逐字引用的三镜头分析，并输出：

- `.bookcompiler\golden-analysis.md`
- `.bookcompiler\golden-dashboard.md`

示例书是原创测试材料，不是真实出版物；它用来验证管线，不用来证明领域专家水平。

## 编译一本真实书

```powershell
bookcompiler --db library.db export-text <book_id> --out .bookcompiler/books/<book_id>
```

让 agent 读导出的章节，按 `skills/book-compiler/references/compilation-patch.schema.json` 写 `compilation.json`，然后：

```powershell
bookcompiler --db library.db compile <book_id> --patch compilation.json
bookcompiler --db library.db validate --book <book_id>
```

如果出现 `unsupported_quote`，说明引用没有在原文中逐字找到。不要绕过校验，改引用或删掉该主张。

## 三种选择模式

### 1. auto

agent 自己从书库选书和框架，不需要确认。

```powershell
bookcompiler plan --mode auto --query "<event>" --lenses economics politics law
```

### 2. direction

用户给方向，不指定具体书。agent 给出方向匹配能力和跨学科补充，然后必须询问同意。

```powershell
bookcompiler plan --mode direction --query "<event>" `
  --direction "legal authority and credit regulation" `
  --lenses economics politics law --format text
```

### 3. books

用户指定书，也可以指定具体 FrameworkCard。agent 检查覆盖缺口并给建议。

```powershell
bookcompiler plan --mode books --query "<event>" `
  --books <book_id> --frameworks <framework_id> `
  --lenses economics politics law --format text
```

模式 2/3 必须选择：

- `specified`：只用用户指定范围
- `specified+recommended`：用户范围 + agent 推荐
- `recommended`：只用 agent 推荐

## 信息源缺口提示

选书不只判断“有没有某个学科的书”，还要判断“有没有支撑这个具体判断的权威原文”。例如书库里有中央银行教材，但没有《中华人民共和国中国人民银行法》，系统不会假装法律镜头已经完整覆盖，而会在选择卡、analysis memo 和 MCP 返回值里给出：

- 缺哪一部法律/监管文件；
- 为什么这个问题需要它；
- 命中了哪些问题词；
- 建议入库到哪些学科；
- 去哪里核对现行有效版本；
- 一条可以直接复制修改的 `bookcompiler ingest` 命令。

```powershell
bookcompiler --db .bookcompiler/library.db source-gaps `
  --query "央行降准后银行信贷是否必然扩张？" `
  --lenses economics politics law `
  --format text
```

`plan` / `analyze` / MCP `book_plan` 也会自动带上 `source_recommendations`。首批目录覆盖中国央行、商业银行、银行业监管、预算法、立法法、地方政府债务、银行资本与流动性规则。它是“提示下载”，不会自动联网下载，也不会把没入库的法规算作证据。若书库已有同名法规（包括只是 ingested、尚未编译的版本），不会重复提示下载。

## 生成分析

```powershell
bookcompiler analyze --mode auto --query "<event>" `
  --lenses economics politics law --render
```

这会生成 draft `AnalysisPacket`。然后让 agent 按 `analysis-patch.schema.json` 补齐：

- 竞争性假设
- 反证
- 跨镜头冲突及处理
- 条件性结论
- 不确定性
- 下一步可观察检查
- 管辖地
- 法律非建议声明

```powershell
bookcompiler analysis-apply <analysis_id> --patch analysis-patch.json
bookcompiler validate --analysis <analysis_id>
bookcompiler render <analysis_id> --out analysis.md
```

`analysis-apply` 会在保存前做完整校验；有 error 时不会写入。

## 反馈与自进化

```powershell
bookcompiler feedback --analysis <analysis_id> --rating 2 `
  --error lens_omission --error overconfidence `
  --prefer-book <book_id> --prefer-framework <framework_id> `
  --missing-evidence "需要一本关于法定授权的书" `
  --note "法学镜头没有被显式处理"

bookcompiler memory --query "reserve requirements and legal authority"
bookcompiler evolution-propose
bookcompiler evolution-list
bookcompiler evolution-decide <proposal_id> --status accepted --note "reviewed"
bookcompiler evolution-decide <proposal_id> --status shadow --note "run in shadow"
bookcompiler evolution-decide <proposal_id> --status promoted `
  --replay-report replay-report.json --note "clean structural replay"
```

V2 的自进化是**受控演化**，不是模型随便改自己：

- 证据门槛：proposal 必须引用具体 feedback。
- 版本化：变更要记录目标、风险、回滚方案。
- replay 门槛是代码强制的：`promoted` 只能从 `shadow` 进入，且必须提供结构回放全通过的 `--replay-report`。
- 晋级证据写回 `promotion_evidence`；任何已晋级 proposal 都可以 `rolled_back`。
- 人工/显式决策：`accepted`、`shadow`、`promoted`、`rolled_back`。
- 真值契约不可自动修改：引用校验规则不能被“学掉”。

## 读书评分、Obsidian 与多智能体

### 九维读书评分

每次最终回答后，可以给它打一次“读书有效性”分，而不是只看文笔：

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m bookcompiler --db .bookcompiler\library.db reading-eval `
  --analysis <analysis_id> --evaluator llm_judge `
  --score source_fidelity=8 --score retrieval_coverage=7 `
  --note "只真正用了两本书"

& $py -m bookcompiler --db .bookcompiler\library.db reading-report --format markdown
& $py -m bookcompiler --db .bookcompiler\library.db reading-propose --min-support 3
```

九个维度：原文忠实度、检索覆盖、框架适配、跨书综合、跨学科整合、冲突处理、置信校准、可行动性、失败模式意识。自动代理分只用于分诊，不能冒充人工或盲评。低分维度会生成 `review_reading_dimension` 提案，但晋升仍需 replay、shadow/canary 和人工确认。

MCP 工具：`book_reading_eval`，支持 `score / list / report / propose`。

详细说明见 `docs/READING-SCORE.md`。

### Obsidian：读书成果 + Hindsight 记忆

现在有两个受控目录：

```text
<vault>\BookCompiler\       书卡、框架、claim、实体、分析
<vault>\Hindsight\          Hindsight 的 world / experience / observation 记忆
<vault>\BookCompiler Inbox\ 你手写的新读书笔记，导入 SQLite
<vault>\Hindsight Inbox\    你手写的新记忆，retain 到 Hindsight
```

一键同步：

```powershell
.\sync-obsidian.bat
```

等价命令：

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-sync-all
& $py -m bookcompiler --db .bookcompiler\library.db hindsight-obsidian-sync --direction both
& $py -m bookcompiler --db .bookcompiler\library.db hindsight-obsidian-status
```

规则：

- `BookCompiler/` 的生成笔记默认受保护。你手改后，原文件保留，新生成版本写成 `*.generated.md`；不会静默覆盖。
- 想让手写笔记进入检索/记忆上下文，放到 `BookCompiler Inbox/`，同步后进入 `obsidian_notes`，但它不会被当成原文引用。
- `Hindsight/` 的 `world` / `experience` 可直接改正文、Context、state，并 PATCH 回 Hindsight；`observation` 是派生记忆，只读。
- 本地和远端都改过时，生成 `*.conflict-时间.md`，不自动替你选。
- 同步状态在 `.bookcompiler\hindsight-obsidian-state.json`；BookCompiler 导出清单在 vault 的 `.bookcompiler-export.json`。

详细说明见 `docs/OBSIDIAN.md`。

### 学习方法与多智能体

- `docs/LEARNING-METHODS.md`：费曼、检索练习、间隔复习、交错练习、Bloom/SOLO、ICAP、刻意练习、Zettelkasten 等如何映射到本项目。
- `docs/MULTI-AGENT.md`：出题者、检索者、费曼解释者、反方、引用审计员、独立 judge、进化管理员的分工、成本和风险。
- `docs/RAG-LANDSCAPE.md`：GraphRAG、LightRAG、HippoRAG、RAPTOR、Self-RAG、CRAG 等方案的适用性。

多智能体最划算的第一版不是“九个 agent”，而是：

```text
检索者 -> 反方 -> 盲评 judge
```

如果这三者不能稳定提升 `source_fidelity`、`retrieval_coverage` 和 `conflict_handling`，就不该继续加角色。

## 可观测性

```powershell
bookcompiler dashboard --out dashboard.md
bookcompiler coverage
bookcompiler show <book_id>
bookcompiler graph --node <analysis_id>
```

`dashboard` 会显示书库、书卡、框架、最近分析、反馈和演化提案。这样用户能看到 agent 到底“学了哪些书”。

## Replay

```json
[
  {
    "case_id": "case-1",
    "query": "Central bank cuts reserve requirements",
    "lenses": ["economics", "politics", "law"],
    "mode": "auto",
    "expected_book_ids": ["<book_id>"]
  }
]
```

```powershell
bookcompiler replay cases.json --out replay-report.json
```

当前 replay 是结构回归，不是盲评质量基准。真正质量评测仍需要：

- 20 个事件：10 个用户提供，10 个 agent 提议并经用户确认。
- 三个基线：裸模型、普通 RAG、本系统。
- 盲评 rubric：证据准确性、镜头覆盖、冲突处理、反证质量、校准、可执行性。

## 真值契约

- 引用必须逐字存在。
- 不确定的地方标 `unverified` 或删除，不编造。
- 不同镜头的冲突必须显式写出，不平均。
- 法学镜头必须声明“不是法律建议”。
- 缺失镜头要记录为 coverage gap，不能静默丢掉。
- 启发式编译永远标记为 `heuristic`，不能伪装成专家编译。

## 目录

```text
src/bookcompiler/
  models.py      数据模型
  parsing.py     TXT / Markdown / PDF / EPUB
  store.py       SQLite、FTS5、卡片、图、反馈、proposal
  validation.py  逐字引用与结构校验
  compiler.py    书卡/框架卡编译
  modes.py       三种选择模式和两层约束
  analysis.py    AnalysisPacket 创建与 patch
  reading_eval.py 九维读书评分、报告与弱项练习
  obsidian.py    Obsidian Markdown 导出（手改保护）
  evolution.py   memory recall、演化提案、replay
  render.py      memo / selection card / dashboard
  cli.py         命令行入口

skills/book-compiler/
  SKILL.md
  references/*.schema.json
  references/validation-rules.md
  references/self-evolution-v2.md

docs/V2-SELF-EVOLUTION.md
docs/READING-SCORE.md
docs/LEARNING-METHODS.md
docs/OBSIDIAN.md
docs/RAG-LANDSCAPE.md
docs/MULTI-AGENT.md
docs/tutorial.html
```

## 当前限制

- 没有自动联网找书/下载；`book_plan` 只能从已入库书里推荐，并标出覆盖缺口，外部书仍需你批准后手动 ingest。
- 真实书的高质量编译仍需要 agent 读完全文并写 patch；启发式编译器只是 demo。
- replay 目前是结构检查，不是完整的盲评质量评测；九维评分也还没有真实样本积累。
- 偏好加权是简单计数，不是训练；它受反馈质量影响，可能有回音室风险。
- 跨书框架融合、概念本体、时间有效性还没有完全解决。
- BookCompiler 生成笔记是“受保护导出”，不是任意字段回写 SQLite；要进入记忆/检索请走 Inbox。Hindsight 记忆是受控双向。GraphRAG 已接主链路，LightRAG/HippoRAG 仍未接入。
- 多智能体目前是研究文档与手工编排协议，不是运行时自动编排。
- 数据库是本地 SQLite，适合单机原型，不是多人服务。

## 0.3.0：网页 GUI 与真实书库

0.3.0 增加了本地网页 GUI，并用 `D:\fanshu` 的真实 OCR 书库做了一次端到端验证。

### 启动 GUI

```powershell
bookcompiler --db .bookcompiler\library.db gui --host 127.0.0.1 --port 8765 --open
```
### 一键启动（推荐）

双击项目根目录的 `start-bookcompiler.bat`。它会使用项目自带 `.venv`，启动 GUI 并自动打开浏览器。默认地址是 <http://127.0.0.1:8765/>；如果端口被占用，会自动往后找空闲端口。

Hermes 也有一键入口：双击项目根目录的 `start-hermes.bat`，或 `D:\hermes agent\start-hermes.bat`。

### 怎么切模型（三个模型槽 + 检索组件）

用户希望的分工是：**读书、分析、对话走云端大模型；Hindsight 记忆抽取走本地 Ollama**。这个分工已经落成三个独立槽位，不要用一个环境变量硬控全部：

| 槽位 | 管什么 | 配置位置 | 什么时候生效 |
| --- | --- | --- | --- |
| Hermes 对话模型 | 读书、分析、调用工具、最终回答 | `D:\hermes agent\config.yaml` | 退出重启 Hermes；会话内可用 `/model` 临时切 |
| BookCompiler 盲评模型 | 只影响独立九维盲评 | 项目 `.env` 的 `BOOKCOMPILER_JUDGE_*` | 保存后当前 GUI 进程立即生效 |
| Hindsight 记忆模型 | retain / recall / reflect 的记忆抽取 | `D:\hindsight\.env` 的 `HINDSIGHT_API_LLM_*` | 重启 `D:\hindsight\run_server.py` 后生效 |
| Embedding / Reranker | 检索向量与可选重排 | 项目 `.env` / Hindsight `.env` | 重启后；换 embedding 必须重建向量 |

#### 一键切换

双击项目根目录的 `switch-models.bat`，或：

```powershell
cd C:\Users\mybea\projects\bookcompiler
.\switch-models.bat
```

菜单里最常用的是：

- `2`：DeepSeek 云端对话/盲评 + MiMo 读书 + 本地 Ollama 记忆（读书槽位不会跟着切到 DeepSeek）
- `3`：全部切到本地 Ollama（离线）
- `8`：MiMo 云端阅读/盲评 + 本地 Ollama 记忆
- `9`：只切 BookCompiler 读书模型（DeepSeek 费用闸默认开启）

非交互命令：

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m bookcompiler.switch_models show
& $py -m bookcompiler.switch_models preset mimo
& $py -m bookcompiler.switch_models preset cloud
& $py -m bookcompiler.switch_models preset local
```

当前已实测接通 MiMo：

- Hermes：`provider: xiaomi`，模型 `mimo-v2.6-flash`，Base URL `https://token-plan-cn.xiaomimimo.com/v1`。
- BookCompiler 盲评：`openai-compatible`，同一模型与 Base URL。
- API key 不写进 README、不打印；BookCompiler 从 `MIMO_API_KEY` 或 `XIAOMI_API_KEY` 读取，Hermes 从自己的 `.env` 读取 `XIAOMI_API_KEY`。
- Hindsight 仍然是本地 `ollama / qwen2.5:7b-instruct-q4_K_M`，不会因为切云端阅读而被改走。

**把模型填进 Windows 系统环境变量能不能切？** 能作为“默认值”，但只对之后新启动的进程生效。已经打开的 GUI、终端、Hermes 不会自动读取新值。项目内 `.env` 更清楚，单次 GUI/CLI 参数最直接。

Hermes 当前模型可以打开 GUI 的「模型」页查看；BookCompiler 也能从该页写入 Hermes 配置并自动备份。

打开 <http://127.0.0.1:8765/>。不需要 Node/npm，前端是原生 HTML/CSS/JS。

### 真实书库

- 16 本书已 ingest，且 16 本全部 `compiled`；共 97 个带逐字引用的 FrameworkCard；
- 覆盖：货币/银行/债务/危机、地方财政、中国经济制度、政治制度、中国近代史、文明冲突、自由与法治、逻辑学；
- 全部 16 本 `validate` 结果：**0 error / 0 warning**；
- 8,741 个 chunk；8,741 个 BGE 512 维向量；1,680 条 claims；155 个规范实体（108 个跨书实体）；
- GraphRAG sidecar：10,689 nodes / 29,407 edges / 17 communities；
- 真实分析样例：`42450cb02344ffe7`，17 条引用，`validate --analysis` 返回 `[]`；
- 读书使用 `book_learn` / `compile-llm`：全书均匀抽样 + 逐字溯源校验，属于“代表样本阅读”，不是逐页精读。

详见：

- [docs/REAL-LIBRARY.md](docs/REAL-LIBRARY.md)
- [docs/GUI.md](docs/GUI.md)
- [docs/GITHUB-REVIEW.md](docs/GITHUB-REVIEW.md)
- [docs/CODE-REVIEW.md](docs/CODE-REVIEW.md)

### 诚实边界

- GUI 本身不是 LLM；它负责选择、同意、展示、校验和落库，分析 patch 由 agent 编写。
- 0.3 当时检索是词法/FTS + 打分；0.4 已补上 BM25 + BGE 神经 embedding + 实体扩展的混合检索，reranker 默认关闭、按需开启。
- replay 是结构回归，不是盲评质量证明。
- 自进化是受控状态机，不是模型自动改自己。
- 法律 lens 的输出不是法律意见；具体规则必须核对最新有效文本。

## 下一步

1. 补一手法律/监管原文（如《中国人民银行法》《商业银行法》），教材不能替代法条。
2. 建立 20 个新闻/政策事件的 replay 集和盲评 rubric，不只做结构检查。
3. 用盲评校准 BGE 混合权重、reranker 和切块参数；当前固定 query 集只说明没有明显回归。
4. 把 claim-level 图谱继续做深：条件、时效、跨书冲突复核和显式 supersession。
5. 给实体审计加人工/agent 确认队列；把 `evolution-propose` 接到 shadow/canary 和自动回滚。

# 0.4：混合检索、跨书实体、Hermes 对接

0.4 在 0.3 的“书 -> 框架 -> 引用分析”之上补了四块。

## 1. 混合检索

- BM25（词法）+ BGE 神经 embedding（默认 bge-small-zh-v1.5，失败时回退本地 n-gram；也可配 OpenAI 兼容后端）
  + 跨书实体扩展；
- 实体扩展不只看“是否命中一个实体”，还奖励同时命中多个实体的段落。
  例如同时出现“地方政府债务 + 银行体系 + 存款准备金率”的段落，会比只出现一个词的段落得分更高；
- 每条结果返回 `score_breakdown`，可以看到 BM25、embedding、实体和 quality 各自贡献；
- 索引页和目录页会被质量降权（不是删除），避免 OCR 的目录/索引页因为词多而排到第一；
- 5500 个真实 chunk 已全部建好 512 维 BGE 向量：`coverage=1.0`、`missing_chunks=0`；另有本地 768 维 fallback 向量；
- 缺向量时只补当前检索会扫到的 chunk（chunk-scoped lazy backfill），不再因少量缺向量重建全库；
- 远程 embedding 失败时回退本地后端，并把实际模型和 `fallback_error` 写进返回值，不混用向量空间；
- 命令：`bookcompiler embed`、`bookcompiler retrieval`。

这不是“向量数据库 + 神经语义检索”的替代品。默认本地向量是零依赖的
OCR 鲁棒层，不是 LLM 级语义理解；需要真正语义向量时可配置远程后端。

## 2. 跨书实体对齐

- 从书卡、框架卡和别名组抽取规范实体；
- 扫描所有 chunk，保留 `entity -> chunk/book/page` 提及；
- 同一 chunk 内的实体写 `co_occurs` 关系，书与实体写 `discusses` 边；
- 真实库结果：92 个实体、69 个跨书实体、9905 次提及、300 条关系、63 个别名组；
- `entities audit` 会列出 5 个“近似重复/包含关系”候选，例如
  “资产负债表 ↔ 央行资产负债表”“土地出让 ↔ 土地出让收入”；
  它们全部标记为 `review_only`，系统不会自动合并；
- `compile` 成功后会重新对齐实体，新书卡/框架卡里的概念会进入图谱；
- 命令：`bookcompiler entities align/audit/list/show/detect`，GUI 也有“近似重复审计”按钮。

实体对齐是保守的规则 + 别名合并，不会用 LLM 猜同义词。错合并比不合并更难发现，
所以没有把“地方政府债务”和“地方政府债务风险”强行合并。

## 3. Hermes Agent 对接

- 新增 stdio MCP server：`bookcompiler mcp`；
- 19 个工具覆盖书库、选书、召回、分析、导入、导出、LLM 读书、编译、校验、反馈、
  记忆、实体、进化和状态；
- Hermes 部署在 `D:\hermes agent`，`HERMES_HOME=D:\hermes agent`，
  通过 `config.yaml` 的 `mcp_servers` 接入；
- `hermes mcp test bookcompiler` 实测连接成功并发现 19 个工具；
- `skills/book-library/SKILL.md` 是一个书库路由器，不是一本书一个技能；
  描述里加入了中文自动触发场景，新闻/政策/市场问题会优先走书库；
- 已用本机 DeepSeek OpenAI 兼容端点打通端到端问答。实测问题
  “降准是否必然导致银行信贷扩张？”能自动调用书库，引用
  《中央银行与货币供给》第 277/298 页的逐字原文；
- 详细步骤见 `docs/HERMES-INTEGRATION.md`。

## 4. 自进化从“提案”变成“有界应用”

- 只允许三类可执行变更：检索权重、书偏好、框架偏好；
- 晋升前必须有结构回放报告；报告不一致或任一 case 失败会被拒绝；
- 应用前写配置快照，失败恢复；支持 rollback；
- 不自动改写书卡、框架、引用或代码；
- 这仍然是“受控演化”，不是模型半夜自己改自己。

## 5. 仍然没有做到的事

- 真实库 16/16 本都已 `compiled`、97 个 FrameworkCard、0 validation issue；`book_learn` 是全书均匀抽样的代表样本阅读 + 逐字溯源校验，不是逐页精读；
- OCR 文本有重复列、乱码和断行，引用校验只能证明原文存在；
- 默认 embedding 是 BGE 神经模型，失败时才回退本地 n-gram；跨书实体仍是规则对齐，不是完整本体；
- 实体关系是共现，不是因果；
- 还没有自动 supersession（旧主张被新证据取代）；
- 还没有 20 条事件级盲评集，replay 仍以结构回归为主；
- Hermes 集成是 MCP，不是 native plugin。

需求对照、证据和下一步优先级见 [docs/ASSESSMENT-0.4.md](docs/ASSESSMENT-0.4.md)。

## V3 更新（2026-10-18）：真实盲评、受控 Obsidian、自动编排、GraphRAG 主链路

这一版针对之前四个“还没真正做完”的缺口做了实现，并把边界写清楚。

### 1. 独立九维盲评

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m bookcompiler --db .bookcompiler\library.db judge `
  --analysis 49d7c5f76c4d7ed4 --provider ollama `
  --model qwen2.5:7b-instruct-q4_K_M `
  --out docs\judge-eval-49d7c5f76c4d7ed4.json
```

- 真实样本已经跑过：`llm_judge:qwen2.5:7b-instruct-q4_K_M`，总分 **81.4**。
- 评审 prompt 不包含 auto_proxy 分数和历史评分。
- 失败、超时、非法 JSON、缺维度都不会写评分，也不会回退成 auto_proxy。
- `reading-report` 优先使用独立评分；没有独立评分时才明确标注 `basis=auto_proxy`。
- `evolution-propose` 不再用 auto_proxy 驱动提案。

详见 `docs/JUDGE.md`。

### 2. Obsidian：读书成果受保护 + Hindsight 记忆双向

- 生成目录 `<vault>\BookCompiler\` 默认受保护：手改后保留原文件，新版本写 `*.generated.md`，不静默覆盖。
- 用户自己的读书笔记放在 `<vault>\BookCompiler Inbox\`，通过 `obsidian-sync` 导入主库 `obsidian_notes`；它只作为记忆上下文，不进入 citations。
- Hindsight 的 `<vault>\Hindsight\Memories\world|experience\*.md` 可直接编辑并 PATCH 回 Hindsight；`Observations/` 只读。
- 双方都改会产生 `*.conflict-时间.md`；同步状态在 `.bookcompiler\hindsight-obsidian-state.json`。
- 找不到目标的笔记标记 `orphaned`；从 inbox 删除的笔记标记 `missing`，不销毁历史。
- `review_due` 进入复习队列，`obsidian-review --grade 0..5` 更新 mastery 和下次到期时间。

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-sync-all
& $py -m bookcompiler --db .bookcompiler\library.db hindsight-obsidian-sync --direction both
& $py -m bookcompiler --db .bookcompiler\library.db obsidian-review
```

### 3. 多智能体自动编排

`create_analysis` 现在自动运行 10 个确定性角色：planner、retriever、reader、feynman_explainer、red_team、citation_auditor、lens_reviewer、synthesizer、judge、evolver。trace 存在 `AnalysisPacket.orchestration`。

这不是多个 LLM 自由辩论；只有独立 judge 是额外模型调用。详见 `docs/V3-PIPELINE.md`。

### 4. GraphRAG 接入主链路

- 新增独立 sidecar：`.bookcompiler\library.graph.db`。
- 图包含 book / framework / claim / entity / chunk 节点、claim 与实体关系、书内实体社区和跨书桥接社区。
- 分析检索改为 hybrid + graph + RRF 融合；图失败自动回退 hybrid。
- 不修改主库。

```powershell
& $py -m bookcompiler --db .bookcompiler\library.db graphrag build
& $py -m bookcompiler --db .bookcompiler\library.db graphrag status
& $py -m bookcompiler --db .bookcompiler\library.db graphrag query `
  --query "央行降准、地方财政与银行信贷扩张" --mode hybrid
```

详见 `docs/GRAPHRAG.md`。

### 5. MCP 与 GUI

- MCP 现在有 **19 个工具**：`book_reading_eval` 增加 judge/judge_status/calibration；新增 `book_graphrag`、`book_obsidian`、`book_learn`（MiMo/Ollama 读书 + 逐字溯源校验 + 入库）。
- GUI 分析页增加独立盲评卡；溯源页增加 GraphRAG 状态/重建/融合检索；记忆页增加 Obsidian 同步/状态/到期复习。

### 6. 仍然存在的边界

- 独立盲评样本目前只有 1 个，而且是小模型；不是人类专家盲评，也不是统计 benchmark。
- Obsidian 是“受控双向”，不是任意生成笔记实时回写。
- 多智能体是确定性角色流水线，不是自由辩论。
- GraphRAG 是轻量 sidecar，不是 Microsoft 全量 LLM GraphRAG。
- 真实库 16 本都已 learned（compiled），但“learned”指有可调用框架且引用通过机器逐字校验，不等于逐页精读或人类专家盲评。