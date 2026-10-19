# 代码审查记录（0.3.0 + 0.4 复核）

审查范围：`src/bookcompiler/`、`tests/`、`examples/`、GUI 静态资源与真实书库 patch。
测试状态：`60 passed`（2026-10-18，追加 reading/Obsidian 测试后复核）。

## 已修复的关键问题

### Critical

1. **中文长文本切分错误**
   - 原实现按空白切句，中文整段可能只有一个“句子”，导致 chunk 过大或无法引用。
   - 修复：中文标点切句；长段落有硬上限；章节正文保留段落结构。

2. **重新 ingest 会删除已编译产物**
   - 原实现使用 `INSERT OR REPLACE`，可能级联删除 book card / framework / edges。
   - 修复：文本未变化时保留已编译卡片和框架；文本变化时才失效并重置为 `ingested`。

3. **引用 provenance 不够严格**
   - 原实现允许 chunk / chapter 不匹配只报警告，分析可能引用“看起来对但定位错”的证据。
   - 修复：analysis 校验中 chunk/chapter 不匹配为 error；page 不匹配在严格模式下也为 error。

### High

4. **proposal 重新生成丢失 promotion evidence**
   - 修复：已接管 proposal 的 promotion evidence 在重新 propose 时保留。

5. **heuristic compile 被错误标记为 compiled**
   - 修复：启发式卡片保持 `ingested` / `heuristic`，避免把低置信结果伪装成真实学习。

6. **GUI 同意状态可能被下一次查询复用**
   - 修复：查询、方向、lens、选书/选框架变化时清空 consent；分析成功后也清空。

7. **GUI 分析结果使用过期书名映射**
   - 修复：`runAnalysis()` 使用服务端返回的 `book_titles`。

### Medium

8. **元数据变化没有使编译产物失效**
   - 修复：title / author / disciplines 变化时，即使原文 chunk 未变，也会删除 book card / framework / edges，但保留 chunks，避免“lens 元数据变了、框架还是旧的”。

9. **空同意集合会静默扩大检索范围**
   - 修复：如果用户选择 `specified` 但解析后没有任何书/框架，`create_analysis()` 直接报错，不再回退到全库检索。

10. **analysis status 可被任意字符串绕过终检**
    - 修复：只接受 `draft` / `complete`，防止用 `verified` 等状态跳过法律免责声明和完整性检查。

11. **非法 page 值会抛异常而不是给校验错误**
    - 修复：`page="abc"` 现在返回 `invalid_citation_page`，按 provenance 严重级别处理。

12. **OCR 页码标记未利用**
   - 修复：识别 `≦ 12 ≧` 一类页码标记，生成 page-level source unit，并把标记从 chunk 文本中移除。

13. **模式输入未校验**
    - 修复：`direction` 必须有非空 direction；`books` 至少有一个 book_id 或 framework_id。

14. **选择顺序不确定，影响 replay 可复现性**
    - 修复：specified book ids 排序后再拼接，减少集合遍历带来的不确定性。

15. **GUI 静态资源与 API 缺少统一错误出口**
    - 修复：JSON 错误、404、请求体大小限制、`X-Content-Type-Options` 等。

## 审查后仍存在的限制

- OCR 原文有重复栏、错字和乱码；引用能校验“原文确实存在”，但不能保证 OCR 语义完全正确。
- 真实书库目前只有 4 本书做了深度编译；其余 8 本是 ingest 状态，不应描述为“已学会”。
- 深度编译 patch 由 agent 编写，GUI 本身不是 LLM；GUI 负责选择、展示、校验和记录，不负责自动生成高质量分析。
- replay gate 信任本地 JSON 报告；它是确定性的结构检查，但不是防伪证明。
- 0.3 审查时检索仍是词法/FTS；0.4 已加入 BM25 + embedding + 实体扩展，但本地 embedding 不是神经语义模型，也没有 cross-encoder 重排。
- GUI 无认证，只能绑定 localhost；不要暴露到公网。
- 法律 lens 的输出不是法律意见，具体法规必须核对最新有效文本。

## 0.4 复核补充

- `embedding_stats(active_model)` 改为按检索实际使用的模型统计，避免数据库里同时存在
  本地 fallback 和远程向量时，拿最大表掩盖当前模型覆盖不足。
- 实体别名拆分：`土地财政` / `土地出让` / `土地出让收入`、`影子银行` /
  `影子银行监管`、`银行体系` / `商业银行` 等不再被错误吞并；重新对齐后为
  92 实体 / 69 跨书 / 9905 提及 / 300 关系。
- `entities audit` 只输出 `review_only` 候选，不自动合并；GUI 增加
  `GET /api/entities/audit` 和“近似重复审计”按钮。
- 检索增加目录页降权（`专栏/目录/第X章` 密集）和多实体覆盖奖励；新增对应回归测试。
- 修复测试文件里残留的 `???` 乱码字符串，恢复为真实中文语料。
- Hermes 侧修复 `requires_toolsets` 误用；DeepSeek 自定义端点增加
  `reasoning_overrides: {deepseek-v4-pro: low}`，避免 medium 推理吃掉输出预算。

## 结论

0.3.0 的重点不是“让 agent 看起来更聪明”，而是把“可引用、可回滚、可观察”做扎实。当前实现适合本地原型和真实书库试验，不适合直接作为生产级法律/投资建议系统。
