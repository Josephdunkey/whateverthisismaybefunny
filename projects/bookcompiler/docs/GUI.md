# BookCompiler Web GUI

## 启动

```powershell
cd C:\Users\mybea\projects\bookcompiler
python -m bookcompiler.cli --db .bookcompiler\library.db gui --host 127.0.0.1 --port 8765 --open
```

打开 <http://127.0.0.1:8765/>。

GUI 使用 Python 标准库 `ThreadingHTTPServer`，没有 Node/npm 构建步骤；前端是原生 HTML/CSS/JS。

每个 tab 都有 hash 深链接，便于直接打开：

```text
http://127.0.0.1:8765/#overview
http://127.0.0.1:8765/#library
http://127.0.0.1:8765/#analyze
http://127.0.0.1:8765/#memory
http://127.0.0.1:8765/#evolution
http://127.0.0.1:8765/#inspect
```

## 页面

- **Overview**：书库覆盖、框架数、分析数、最近活动。
- **Library**：书卡、框架卡、章节、引用抽屉、合订本状态。
- **Analyze**：三种选书模式 + 同意门 + 分析草稿 + patch 应用 + 引用展示。
- **Memory**：按问题和 lens 召回 feedback/教训。
- **Evolution**：生成 proposal、查看状态、执行 accept/shadow/promote/rollback、结构 replay。
- **Inspect**：provenance graph、实体索引、跨书提及/共现、混合检索探针和近似重复审计。

## 三种选择模式与同意

- `auto`：agent 自动匹配，不需要额外同意。
- `direction`：用户给领域/方向，agent 给出“指定的 + 推荐的”选择卡，必须选择：
  - `specified`：只用用户指定范围；
  - `specified+recommended`：指定 + agent 推荐；
  - `recommended`：只用 agent 推荐。
- `books`：用户指定书/框架，同样必须经过上述三选一。

同意状态只对当前查询有效。修改 query、direction、lens、书或框架后，GUI 会清空同意并隐藏同意条，防止旧同意被新问题复用。

## 主要 API

```text
GET  /api/status
GET  /api/books
GET  /api/books/<book_id>
GET  /api/frameworks
GET  /api/analyses
GET  /api/analysis/<analysis_id>
GET  /api/memory?query=...&lenses=...
GET  /api/evolution
GET  /api/graph?node=...
GET  /api/entities?query=...&cross_book=true
GET  /api/entities/audit?limit=50
GET  /api/entities/<entity_id>
POST /api/entities/align
POST /api/embeddings/backfill
POST /api/plan
POST /api/analyze
POST /api/analysis-patch
POST /api/feedback
POST /api/evolution/propose
POST /api/evolution/decide
POST /api/replay
POST /api/ingest
POST /api/compile
```

`POST /api/analyze` 在需要同意但未提供 choice 时返回 `409 confirmation_required`，并附上 selection proposal。

`GET /api/entities/audit` 返回 `review_only=true` 的近似重复候选；它不会修改实体图。
实体页的“重新对齐”会重建实体、提及和共现关系，“近似重复审计”只读。

## 安全边界

- 默认只绑定 `127.0.0.1`，没有登录/权限系统。
- 不要将端口暴露到公网或不可信局域网。
- `/api/ingest` 可以读取本机路径；只应在受信任的本地环境使用。
- 请求体上限 20 MB。
- `Cache-Control: no-store`，避免浏览器缓存敏感分析。

## 已知限制

- GUI 不是 LLM：它不会自动写出完整分析；分析 patch 需要由 agent/用户提供，再由 GUI 校验和落库。
- 进化 replay 是结构检查，不是盲评。
- OCR 书库的页码和章节标题来自扫描页，不是出版社原始目录。
- 法律相关输出必须注明“不构成法律意见”，并核对最新法规。
