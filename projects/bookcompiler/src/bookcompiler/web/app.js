/* BookCompiler GUI — vanilla JS, no build step. */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  status: null,
  books: [],
  frameworks: [],
  analyses: [],
  currentProposal: null,
  currentAnalysis: null,
  currentBookTitles: {},
  entities: [],
  lastReplayReport: null,
  consentChoice: "",
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return esc(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}

function badge(status) {
  const value = String(status || "unknown");
  return `<span class="badge ${esc(value)}">${esc(value)}</span>`;
}

function tags(items, className = "tag") {
  if (!Array.isArray(items) || !items.length) return `<span class="hint">—</span>`;
  return items.map((item) => `<span class="${className}">${esc(item)}</span>`).join("");
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.className = "toast"; }, 4200);
}

async function api(path, options = {}) {
  const config = { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } };
  const response = await fetch(path, config);
  let data = {};
  try { data = await response.json(); } catch (_) { data = {}; }
  if (!response.ok) {
    const error = new Error(data.error || data.message || response.statusText);
    error.payload = data;
    error.status = response.status;
    throw error;
  }
  return data;
}

function switchTab(name) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${name}`));
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  if (name === "library") renderBookTable();
  if (name === "evolution") loadEvolution();
  if (name === "inspect") loadGraph();
  if (name === "entities") { loadEntities(); loadEntityCandidates(); }
  if (name === "claims") loadClaims();
  if (name === "memory") $("#memory-query").focus();
  if (name === "models") loadModels();
}

function renderBars(container, mapping, accent = "") {
  const entries = Object.entries(mapping || {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    container.innerHTML = `<p class="empty">还没有数据。导入并编译书之后这里会出现覆盖情况。</p>`;
    return;
  }
  const max = Math.max(...entries.map(([, value]) => Number(value) || 0), 1);
  container.innerHTML = entries.map(([label, value]) => `
    <div class="bar-row">
      <span class="bar-label" title="${esc(label)}">${esc(label)}</span>
      <span class="bar-track"><span class="bar-fill ${accent}" style="width:${Math.max(3, (Number(value) / max) * 100)}%"></span></span>
      <span class="bar-value">${esc(value)}</span>
    </div>
  `).join("");
}

function renderStatus() {
  const coverage = state.status?.coverage || {};
  $("#version").textContent = `v${state.status?.version || "0.3"}`;
  $("#db-path").textContent = state.status?.db || "";
  const items = [
    ["books", "入库书"],
    ["compiled_books", "已编译"],
    ["frameworks", "判断框架"],
    ["analyses", "分析"],
    ["feedback", "反馈"],
    ["evolution_proposals", "进化提案"],
  ];
  const embedding = state.status?.embedding || {};
  const entities = state.status?.entities || {};
  const extra = [
    [`${Math.round((embedding.coverage || 0) * 100)}%`, "嵌入覆盖"],
    [entities.entities ?? 0, "实体"],
    [entities.cross_book_entities ?? 0, "跨书实体"],
  ];
  $("#stats").innerHTML = items.map(([key, label]) => `
    <div class="stat"><div class="value">${esc(coverage[key] ?? 0)}</div><div class="label">${label}</div></div>
  `).join("") + extra.map(([value, label]) => `
    <div class="stat"><div class="value">${esc(value)}</div><div class="label">${label}</div></div>
  `).join("");
  renderBars($("#discipline-bars"), coverage.disciplines, "");
  renderBars($("#lens-bars"), coverage.lenses, "copper");
  renderHindsight();
}

function renderHindsight() {
  const el = $("#hindsight-status");
  if (!el) return;
  const info = state.status?.hindsight || {};
  const hint = $("#hindsight-hint");
  if (hint) {
    hint.textContent = info.reachable ? "已连接" : (info.enabled ? "未连接" : "未启用");
  }
  if (!info.enabled) {
    el.className = "list empty";
    el.innerHTML = `<p class="empty">Hindsight 未启用。它只存跨对话的长期经验，不影响书库和原文。</p>`;
    return;
  }
  el.className = "list";
  el.innerHTML = `
    <div class="list-item">
      <div class="card-head"><h4>${esc(info.base_url || "")}</h4><span class="badge ${info.reachable ? "active" : "conflicted"}">${info.reachable ? "healthy" : "unreachable"}</span></div>
      <div class="meta">bank：${esc(info.bank_id || "—")} · bank 存在：${info.bank_exists ? "是" : "否"}</div>
      <p class="hint">书库原文与页码在本地 SQLite；Hindsight 只保存用户偏好、纠正和跨任务教训。</p>
    </div>`;
}

function renderRecentAnalyses() {
  const rows = state.analyses.slice(0, 6);
  const el = $("#recent-analyses");
  if (!rows.length) {
    el.innerHTML = `<p class="empty">还没有分析。去“分析”页生成第一份草稿。</p>`;
    return;
  }
  el.innerHTML = rows.map((item) => `
    <div class="list-item" data-analysis-open="${esc(item.analysis_id)}" style="cursor:pointer">
      <h4>${esc(item.question || "(无问题)")}</h4>
      <p>${esc((item.conclusion || "尚无结论（草稿）").slice(0, 180))}</p>
      <div class="meta">${esc(item.mode)} · ${esc((item.lenses || []).join(" / "))} · ${badge(item.status)} · ${esc(fmtDate(item.created_at))}</div>
    </div>
  `).join("");
  $$("[data-analysis-open]", el).forEach((node) => node.addEventListener("click", () => openAnalysis(node.dataset.analysisOpen)));
}

async function loadStatus() {
  try {
    state.status = await api("/api/status");
    $("#health").classList.add("on");
    renderStatus();
  } catch (error) {
    $("#health").classList.remove("on");
    toast(`无法连接本地服务：${error.message}`, true);
  }
}
function renderBookTable() {
  const term = ($("#book-search").value || "").trim().toLowerCase();
  const statusFilter = $("#book-status-filter").value;
  const rows = state.books.filter((book) => {
    const haystack = [book.title, book.author, ...(book.disciplines || []), book.status].join(" ").toLowerCase();
    return (!term || haystack.includes(term)) && (!statusFilter || book.status === statusFilter);
  });
  const container = $("#book-table");
  if (!rows.length) {
    container.innerHTML = `<div class="empty" style="padding:22px">没有匹配的书。点右上角“导入本地书”。</div>`;
    return;
  }
  container.innerHTML = `
    <table>
      <thead><tr><th>书名</th><th>状态</th><th>学科</th><th>框架</th><th>片段</th><th>导入时间</th></tr></thead>
      <tbody>${rows.map((book) => `
        <tr data-book-open="${esc(book.book_id)}">
          <td><div class="book-title">${esc(book.title)}</div><div class="book-author">${esc(book.author)}${book.one_line_thesis ? " · " + esc(book.one_line_thesis.slice(0, 80)) : ""}</div></td>
          <td>${badge(book.status)}${book.card_confidence ? `<div class="hint">${esc(book.card_confidence)}</div>` : ""}</td>
          <td>${tags(book.disciplines)}</td>
          <td>${esc(book.framework_count ?? 0)}</td>
          <td>${esc(book.chunk_count ?? 0)}</td>
          <td class="mono">${esc(fmtDate(book.ingested_at))}</td>
        </tr>
      `).join("")}</tbody>
    </table>`;
  $$("[data-book-open]", container).forEach((row) => row.addEventListener("click", () => openBook(row.dataset.bookOpen)));
}

function populateSelects() {
  const bookSelect = $("#book-ids");
  const frameworkSelect = $("#framework-ids");
  bookSelect.innerHTML = state.books.map((book) => `<option value="${esc(book.book_id)}">${esc(book.title)} · ${esc(book.status)}</option>`).join("");
  frameworkSelect.innerHTML = state.frameworks.map((framework) => `<option value="${esc(framework.framework_id)}">${esc(framework.name)} · ${esc(framework.book_title || "")}</option>`).join("");
}

async function loadBooks() {
  const data = await api("/api/books");
  state.books = data.books || [];
  populateSelects();
  renderBookTable();
}

async function loadFrameworks() {
  const data = await api("/api/frameworks");
  state.frameworks = data.frameworks || [];
  populateSelects();
}

async function loadAnalyses() {
  const data = await api("/api/analyses");
  state.analyses = data.analyses || [];
  renderRecentAnalyses();
}

function openDrawer(title) {
  $("#drawer-title").textContent = title;
  $("#drawer").setAttribute("aria-hidden", "false");
}
function closeDrawer() {
  $("#drawer").setAttribute("aria-hidden", "true");
}

function citationHtml(citation, titles = state.currentBookTitles) {
  if (!citation) return "";
  const source = [titles[citation.book_id] || citation.book_id || "", citation.chapter || "", citation.page ? `p.${citation.page}` : ""].filter(Boolean).join(" · ");
  return `<div class="quote">${esc(citation.quote || citation.text || "")}<span class="source">${esc(source)}${citation.chunk_id ? " · " + esc(citation.chunk_id) : ""}</span></div>`;
}

async function openBook(bookId) {
  try {
    const data = await api(`/api/books/${encodeURIComponent(bookId)}`);
    const book = data.book;
    const card = data.book_card;
    const frameworks = data.frameworks || [];
    openDrawer(book.title);
    const cardHtml = card ? `
      <section class="card">
        <div class="card-head"><h3>书卡</h3><div>${badge(card.status)} <span class="hint">${esc(card.confidence || "")}</span></div></div>
        <p class="prose">${esc(card.one_line_thesis || "")}</p>
        <div class="card" id="judge-card">
        <div class="card-head"><h3>独立盲评</h3><span class="hint">auto_proxy 只做分诊，不冒充评分</span></div>
        <p class="hint">用真实模型评分；失败不会回退成代理分。只有 status=complete 的分析才能正式评分。</p>
        <div class="form-grid">
          <label>Provider<select id="judge-provider"><option value="ollama">ollama</option><option value="openai-compatible">openai-compatible</option></select></label>
          <label>模型<input id="judge-model" value="qwen2.5:7b-instruct-q4_K_M"></label>
        </div>
        <div class="actions">
          <button class="primary" id="judge-run">运行盲评</button>
          <button class="ghost" id="judge-dry">预览 Prompt</button>
          <span class="form-status" id="judge-status"></span>
        </div>
        <div id="judge-result" class="list empty">还没有评分。</div>
      </div>
      <div class="prose">
          <h4>核心问题</h4><ul>${(card.core_questions || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul>
          <h4>关键概念</h4><p>${tags(card.key_concepts)}</p>
          <h4>假设</h4><ul>${(card.assumptions || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul>
          <h4>局限</h4><ul>${(card.limitations || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul>
          <h4>章节覆盖</h4>
          ${(card.chapter_coverage || []).map((entry) => `<div class="claim"><div class="lens">${esc(entry.chapter || "")}</div><p>${esc(entry.summary || "")}</p>${citationHtml(entry.citation)}</div>`).join("") || "<p class='hint'>—</p>"}
        </div>
      </section>` : `<div class="warning-box">这本书尚未编译。它已经入库并可检索，但没有可审计的书卡/框架。用 agent 生成 patch 后执行 <code>bookcompiler compile</code>，或调用 <code>POST /api/compile</code> 做启发式编译（低置信度，仅用于跑通流程）。</div>`;

    const frameworkHtml = frameworks.length ? frameworks.map((fw) => `
      <section class="card">
        <div class="card-head"><h3>${esc(fw.name)}</h3><div>${badge(fw.status)} <span class="hint">${esc(fw.confidence || "")}</span></div></div>
        <p class="prose">${esc(fw.one_liner || "")}</p>
        <p>${tags(fw.lenses)}</p>
        <div class="prose">
          <h4>适用条件</h4><ul>${(fw.applicable_when || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul>
          <h4>步骤</h4><ol>${(fw.steps || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ol>
          <h4>失败边界</h4><ul>${(fw.failure_modes || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul>
          <h4>原文证据</h4>${(fw.citations || []).map((citation) => citationHtml(citation)).join("") || "<p class='hint'>—</p>"}
        </div>
      </section>`).join("") : `<p class="empty">没有框架。运行编译后再看。</p>`;

    $("#drawer-body").innerHTML = `
      <div class="analysis-meta" style="margin-bottom:14px">${badge(book.status)} · ${esc(book.author)} · ${esc(book.format)} · ${esc(book.chapters)} 章 · ${esc(data.chapters.reduce((sum, item) => sum + item.chunk_count, 0))} 片段<br>${esc(book.path)}<br>导入于 ${esc(fmtDate(book.ingested_at))}</div>
      ${cardHtml}
      <h3 style="font-family:var(--serif);font-weight:400;margin:24px 0 12px">判断框架（${frameworks.length}）</h3>
      ${frameworkHtml}
    `;
  } catch (error) {
    toast(error.message, true);
  }
}

function collectAnalyzeBody() {
  const form = $("#analyze-form");
  const lenses = $$('input[name="lens"]:checked', form).map((input) => input.value);
  return {
    mode: $("#mode-select").value,
    query: form.query.value,
    lenses: lenses.length ? lenses : ["economics", "politics", "law"],
    direction: form.direction.value,
    book_ids: Array.from($("#book-ids").selectedOptions).map((option) => option.value),
    framework_ids: Array.from($("#framework-ids").selectedOptions).map((option) => option.value),
  };
}
function sourceRecommendationHtml(items, title = "信息源缺口提示") {
  if (!items?.length) return "";
  return `
    <div class="selection-group source-gap">
      <h4>${esc(title)}（${items.length}）</h4>
      <p class="hint">这些是问题需要、但书库还没有的权威原文。请下载官方现行有效版本并入库；入库前不要假装 agent 已经读过。</p>
      ${items.map((item) => `
        <div class="select-row">
          <div>
            <strong>[${esc((item.priority || "medium").toUpperCase())}] 《${esc(item.title || "")}》</strong>
            <div class="reason">${esc(item.why || item.reason || "")}</div>
            ${(item.matched_terms || []).length ? `<div class="reason">命中：${esc(item.matched_terms.join("、"))}</div>` : ""}
            ${(item.suggested_disciplines || []).length ? `<div class="reason">建议学科：${esc(item.suggested_disciplines.join("、"))}</div>` : ""}
            ${item.official_source ? `<div class="reason">官方来源：${esc(item.official_source)}</div>` : ""}
            ${item.ingest_hint ? `<code>${esc(item.ingest_hint)}</code>` : ""}
          </div>
          <div class="tag">${esc(item.source_type || "")}</div>
        </div>`).join("")}
    </div>`;
}
function renderSelection(proposal) {
  state.currentProposal = proposal;
  const groups = [
    ["指定的书", proposal.specified_books],
    ["推荐补充的书", proposal.recommended_books],
    ["指定的框架", proposal.specified_frameworks],
    ["推荐补充的框架", proposal.recommended_frameworks],
  ];
  const body = $("#selection-body");
  body.classList.remove("empty");
  body.innerHTML = `
    <div class="analysis-meta">mode=${esc(proposal.mode)} · lenses=${esc((proposal.lenses || []).join(" / "))} · confirmation=${proposal.requires_confirmation ? "required" : "not required"}</div>
    <p class="prose" style="margin-top:10px">${esc(proposal.rationale || "")}</p>
    ${proposal.coverage_gaps?.length ? `<div class="warning-box">覆盖缺口：${esc(proposal.coverage_gaps.join("、"))}</div>` : ""}
    ${sourceRecommendationHtml(proposal.source_recommendations)}
    ${groups.map(([label, items]) => `
      <div class="selection-group">
        <h4>${label}（${(items || []).length}）</h4>
        ${(items || []).length ? items.map((item) => `
          <div class="select-row">
            <div><strong>${esc(item.title || item.name || item.framework_id || item.book_id)}</strong><div class="reason">${esc(item.reason || "")}</div></div>
            <div>${item.status ? badge(item.status) : ""}</div>
          </div>`).join("") : `<p class="hint">—</p>`}
      </div>
    `).join("")}
  `;
  renderConsent(proposal);
}

function renderConsent(proposal) {
  const bar = $("#consent-bar");
  if (!proposal?.requires_confirmation) {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  bar.classList.remove("hidden");
  bar.innerHTML = `
    <h3>这次要用哪些能力？</h3>
    <p>你指定了书或方向。agent 已给出推荐补充。选一个，才会真正生成分析。</p>
    <div class="actions">
      <button class="ghost" data-consent="specified">只用我指定的</button>
      <button class="primary" data-consent="specified+recommended">指定的 + 推荐补充</button>
      <button class="ghost" data-consent="recommended">只用 agent 推荐的</button>
    </div>
  `;
  $$("[data-consent]", bar).forEach((button) => button.addEventListener("click", () => {
    state.consentChoice = button.dataset.consent;
    runAnalysis(button.dataset.consent);
  }));
}

async function planSelection() {
  const status = $("#analyze-status");
  status.textContent = "正在生成选择卡…";
  try {
    const data = await api("/api/plan", { method: "POST", body: JSON.stringify(collectAnalyzeBody()) });
    renderSelection(data.proposal);
    status.textContent = data.proposal.requires_confirmation ? "请先确认选择。" : "选择卡已生成，可以直接生成草稿。";
    return data.proposal;
  } catch (error) {
    status.textContent = "";
    toast(error.message, true);
    return null;
  }
}

async function runAnalysis(choice = "") {
  const status = $("#analyze-status");
  status.textContent = "正在创建分析草稿…";
  const body = { ...collectAnalyzeBody(), choice };
  try {
    const data = await api("/api/analyze", { method: "POST", body: JSON.stringify(body) });
    state.currentBookTitles = data.book_titles || state.currentBookTitles;
    renderSelection(data.proposal);
    renderAnalysis({ ...data.analysis, _book_titles: state.currentBookTitles });
    status.textContent = "草稿已创建。下一步：让 agent 写 conclusion / counterevidence / citations 补丁，再应用。";
    $("#consent-bar").classList.add("hidden");
    state.consentChoice = "";
    await loadAnalyses();
    await loadStatus();
  } catch (error) {
    if (error.status === 409 && error.payload?.proposal) {
      renderSelection(error.payload.proposal);
      status.textContent = "请先确认使用范围。";
      toast("这个模式需要先确认：只用指定、指定+推荐、或只用推荐。", true);
    } else {
      status.textContent = "";
      toast(error.message, true);
    }
  }
}
function renderAnalysis(packet) {
  state.currentAnalysis = packet;
  state.currentBookTitles = packet._book_titles || state.currentBookTitles;
  const result = $("#analysis-result");
  result.classList.remove("hidden");
  const hypotheses = packet.hypotheses || [];
  const counterevidence = packet.counterevidence || [];
  const conflicts = packet.cross_lens_conflicts || [];
  const citations = packet.citations || [];
  const memory = packet.memory_context || [];
  const selection = packet.selection || {};
  const books = selection.books || [];
  const fws = selection.frameworks || [];

  result.innerHTML = `
    <div class="analysis-head">
      <div>
        <p class="eyebrow">ANALYSIS ${esc(packet.analysis_id || "")}</p>
        <h3>${esc(packet.question || "")}</h3>
      </div>
      <div style="text-align:right">${badge(packet.status)}<div class="analysis-meta">${esc(packet.mode)} · ${esc((packet.lenses || []).join(" / "))}<br>${esc(fmtDate(packet.created_at))}</div></div>
    </div>
    <div class="warning-box">这是 ${esc(packet.status)} 包。草稿里的 hypotheses 只是待验证假设，不是结论。完成包必须给出 counterevidence、uncertainty 和原文引用。</div>
    <div class="prose">
      <h4>选中的能力</h4>
      <p>${books.map((book) => `<span class="tag">${esc(book.title || book.book_id)}</span>`).join("") || "—"}</p>
      <p>${fws.map((fw) => `<span class="tag">${esc(fw.name || fw.framework_id)}</span>`).join("") || "—"}</p>
      ${sourceRecommendationHtml(selection.source_recommendations || [])}
      <h4>假设与传导路径</h4>
      ${hypotheses.length ? hypotheses.map((item) => `
        <div class="claim">
          <div class="lens">${esc(item.lens || "")} · ${esc(item.framework || "")}</div>
          <p>${esc(item.claim || "")}</p>
          ${(item.supporting_evidence || []).map((citation) => citationHtml(citation, state.currentBookTitles)).join("")}
        </div>`).join("") : `<p class="hint">—</p>`}
      <h4>反证 / 反向证据</h4>
      ${counterevidence.length ? counterevidence.map((item) => `<div class="claim"><p>${esc(item.claim || item.description || "")}</p>${citationHtml(item.citation, state.currentBookTitles)}</div>`).join("") : `<p class="hint">还没有。完成包必须补上最强反证。</p>`}
      <h4>跨视角冲突</h4>
      ${conflicts.length ? conflicts.map((item) => `<div class="claim"><div class="lens">${esc((item.lenses || []).join(" vs "))}</div><p>${esc(item.description || "")}</p></div>`).join("") : `<p class="hint">—</p>`}
      <h4>结论</h4>
      <p>${esc(packet.conclusion || "（草稿，尚无结论）")}</p>
      <h4>不确定性 / 什么会改变结论</h4>
      <p>${esc(packet.uncertainty || "—")}</p>
      <h4>下一步检查</h4>
      <ul>${(packet.next_checks || []).map((item) => `<li>${esc(item)}</li>`).join("") || "<li>—</li>"}</ul>
      <h4>原文引用（${citations.length}）</h4>
      ${citations.map((citation) => citationHtml(citation, state.currentBookTitles)).join("") || "<p class='hint'>—</p>"}
      <h4>记忆上下文</h4>
      ${memory.length ? memory.map((item) => `<div class="claim"><div class="lens">${esc(item.source || "")}</div><p>${esc(item.note || item.key || item.prior_question || "")}</p></div>`).join("") : `<p class="hint">没有召回到相关记忆。</p>`}
    </div>
    <hr style="border:0;border-top:1px solid var(--line-soft);margin:24px 0">
    <h4 style="font-family:var(--serif);font-weight:400;margin:0 0 10px">给这份分析打分（驱动自进化）</h4>
    <form id="feedback-form" class="card" style="margin-top:0">
      <div class="form-grid">
        <label>评分 1–5<select name="rating"><option>5</option><option>4</option><option selected>3</option><option>2</option><option>1</option></select></label>
        <label>结果 / 用途<input name="outcome" placeholder="例如：用于内部讨论 / 需要重写"></label>
      </div>
      <label>备注<textarea name="note" rows="2" placeholder="哪里好、哪里错、漏了哪本书"></textarea></label>
      <div class="form-grid">
        <label>错误标签<select name="error_labels" multiple size="5">
          ${["retrieval_miss","compilation_error","framework_misapplication","citation_error","lens_omission","conflict_suppression","overconfidence","taste_mismatch"].map((x) => `<option value="${x}">${x}</option>`).join("")}
        </select></label>
        <label>希望下次优先用的书<select name="preferred_book_ids" multiple size="5">${state.books.map((book) => `<option value="${esc(book.book_id)}">${esc(book.title)}</option>`).join("")}</select></label>
      </div>
      <label>缺失证据<textarea name="missing_evidence" rows="2" placeholder="例如：需要一本讲地方财政与银行关系的书"></textarea></label>
      <div class="actions"><button class="primary" type="submit">提交反馈</button></div>
    </form>
    <h4 style="font-family:var(--serif);font-weight:400;margin:24px 0 10px">应用 agent 分析补丁</h4>
    <p class="hint">GUI 只负责写入和验证。补丁由 agent 生成；没有原文引用的补丁会被拒绝。模板只包含可写字段。</p>
    <textarea id="analysis-patch" rows="12" placeholder='{"status":"complete","conclusion":"...","uncertainty":"...","citations":[]}'></textarea>
    <div class="actions">
      <button class="ghost" id="patch-template">填入模板</button>
      <button class="primary" id="apply-patch">应用补丁</button>
      <span class="form-status" id="patch-status"></span>
    </div>
  `;
  $("#judge-run")?.addEventListener("click", () => runJudge(false));
  $("#judge-dry")?.addEventListener("click", () => runJudge(true));
  $("#feedback-form").addEventListener("submit", submitFeedback);
  $("#patch-template").addEventListener("click", () => {
    const template = {
      status: "complete",
      conclusion: packet.conclusion || "",
      uncertainty: packet.uncertainty || "",
      hypotheses: packet.hypotheses || [],
      counterevidence: packet.counterevidence || [],
      cross_lens_conflicts: packet.cross_lens_conflicts || [],
      citations: packet.citations || [],
      jurisdiction: packet.jurisdiction || "",
      not_legal_advice: packet.not_legal_advice ?? (packet.lenses || []).includes("law"),
      next_checks: packet.next_checks || [],
    };
    $("#analysis-patch").value = JSON.stringify(template, null, 2);
  });
  $("#apply-patch").addEventListener("click", applyPatch);
}
function judgeResultHtml(result) {
  if (result.dry_run) {
    return `<div class="claim"><div class="lens">dry run · ${esc(result.rubric_version || "")}</div><p>Prompt ${Number(result.prompt_chars || 0)} 字符，sha256=${esc((result.prompt_sha256 || "").slice(0, 16))}…</p><pre class="code">${esc((result.prompt || "").slice(0, 4000))}</pre></div>`;
  }
  const labels = { source_fidelity: "原文忠实", retrieval_coverage: "检索覆盖", framework_fit: "框架适配", cross_book_synthesis: "跨书综合", cross_lens_integration: "跨学科整合", conflict_handling: "冲突处理", calibration: "置信校准", actionability: "可行动性", failure_mode_awareness: "失败模式" };
  const scores = result.scores || {};
  const cal = result.proxy_calibration || {};
  return `<div class="claim">
    <div class="lens">${esc(result.evaluator || "")} · 总分 ${esc(String(result.total ?? ""))}</div>
    <div class="bars">${Object.entries(scores).map(([key, value]) => `<div class="bar-row"><span>${esc(labels[key] || key)}</span><div class="bar"><i style="width:${Math.max(0, Math.min(100, Number(value) * 10))}%"></i></div><b>${esc(String(value))}</b></div>`).join("")}</div>
    <p>${esc(result.note || "")}</p>
    <p class="hint">与 auto_proxy 偏差：${esc(Object.entries(cal).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(" · "))}</p>
  </div>`;
}
async function runJudge(dryRun) {
  const id = state.currentAnalysis?.analysis_id;
  if (!id) return toast("先打开一个分析", true);
  const status = $("#judge-status");
  status.textContent = dryRun ? "生成 prompt…" : "盲评模型运行中…";
  try {
    const data = await api("/api/judge", { method: "POST", body: JSON.stringify({ analysis_id: id, provider: $("#judge-provider").value, model: $("#judge-model").value, dry_run: dryRun }) });
    $("#judge-result").innerHTML = judgeResultHtml(data);
    status.textContent = dryRun ? "prompt 已生成" : "独立评分已保存";
    if (!dryRun) toast("独立盲评完成");
  } catch (error) {
    status.textContent = "";
    $("#judge-result").innerHTML = `<div class="claim"><p>${esc(error.message)}</p><p class="hint">失败时不会写入评分，也不会用 auto_proxy 冒充。</p></div>`;
    toast(error.message, true);
  }
}
async function graphRagStatus() {
  const box = $("#graphrag-results");
  try {
    const data = await api("/api/graphrag/status");
    box.innerHTML = `<div class="claim"><div class="lens">sidecar ${data.available ? "可用" : "未构建"}${data.stale ? " · 已过期" : ""}</div><p>${esc(data.path || "")}</p><p class="hint">nodes ${esc(String(data.nodes ?? 0))} · edges ${esc(String(data.edges ?? 0))} · communities ${esc(String(data.communities ?? 0))}</p></div>`;
    box.classList.remove("empty");
  } catch (error) { toast(error.message, true); }
}
async function buildGraphRag() {
  const box = $("#graphrag-results");
  box.innerHTML = "重建中…";
  try {
    const data = await api("/api/graphrag/build", { method: "POST", body: "{}" });
    await graphRagStatus();
    toast(`图已重建：${data.nodes} nodes / ${data.communities} communities`);
  } catch (error) { toast(error.message, true); }
}
async function queryGraphRag() {
  const query = $("#graphrag-query").value.trim();
  if (!query) return toast("输入查询", true);
  const box = $("#graphrag-results");
  box.innerHTML = "检索中…";
  try {
    const data = await api(`/api/graphrag/query?query=${encodeURIComponent(query)}&limit=8`);
    const channels = data.channels || {};
    const items = data.items || [];
    box.innerHTML = `<div class="claim"><div class="lens">hybrid ${channels.hybrid?.length || 0} · graph ${channels.graph?.length || 0} · fused ${channels.fused?.length || 0}</div>${items.map((item) => `<p><b>${esc(item.chunk_id || "")}</b> <span class="tag">${esc(item.source || "")}</span> ${esc(item.chapter_title || "")}</p>`).join("") || "<p class='hint'>没有融合结果</p>"}</div>${(data.communities || []).map((c) => `<div class="claim"><div class="lens">community ${esc(String(c.community_id || ""))} · overlap ${esc(String(c.overlap || 0))}</div><p>${esc(c.label || "")}</p></div>`).join("")}`;
    box.classList.remove("empty");
  } catch (error) { toast(error.message, true); }
}
async function syncObsidian() {
  const box = $("#obsidian-results");
  box.textContent = "同步读书成果中…";
  try {
    const data = await api("/api/obsidian/sync", { method: "POST", body: JSON.stringify(obsidianPayload()) });
    const imported = data.import || {};
    const exported = data.export || {};
    box.innerHTML = `<div class="claim"><div class="lens">读书成果已同步</div><p>export：写入 ${esc(String((exported.written || []).length))} · 保留手改 ${esc(String((exported.preserved_user_edits || []).length))} · 冲突 ${esc(String((exported.conflicts || []).length))}</p><p>import：新建 ${esc(String(imported.created || 0))} · 更新 ${esc(String(imported.updated || 0))} · 未变 ${esc(String(imported.unchanged || 0))} · 孤立 ${esc(String(imported.orphaned || 0))} · 缺失 ${esc(String(imported.missing || 0))}</p><p class="hint">${esc(data.vault || "")} · 只从 Inbox 导入新笔记</p></div>`;
    box.classList.remove("empty");
    toast("读书成果同步完成");
  } catch (error) { toast(error.message, true); }
}

function obsidianPayload() {
  const payload = { direction: "both" };
  const vault = $("#obsidian-vault")?.value.trim();
  const inbox = $("#obsidian-inbox")?.value.trim();
  if (vault) payload.vault = vault;
  if (inbox) payload.inbox = inbox;
  return payload;
}

async function syncAllObsidian() {
  const box = $("#obsidian-results");
  box.textContent = "同步读书成果和 Hindsight 记忆…";
  try {
    const data = await api("/api/obsidian/sync-all", { method: "POST", body: JSON.stringify(obsidianPayload()) });
    const book = data.bookcompiler || {};
    const hs = data.hindsight || {};
    const hsExport = hs.export || {};
    const hsImport = hs.import || {};
    const hsCounts = hsExport.counts || {};
    box.innerHTML = `<div class="claim"><div class="lens">全部同步</div><p>BookCompiler：写入 ${esc(String((book.export?.written || []).length))} · 保留手改 ${esc(String((book.export?.preserved_user_edits || []).length))}</p><p>Hindsight：远端 ${esc(String(hsCounts.remote || 0))} · 回写 ${esc(String(hsImport.updated || 0))} · observation 跳过 ${esc(String(hsImport.read_only_skipped || 0))}</p><p class="hint">${esc(hs.error || hsExport.error || hsImport.error || "完成")}</p></div>`;
    box.classList.remove("empty");
    toast(data.ok ? "全部同步完成" : "读书成果已同步，Hindsight 有错误，请查看详情", !data.ok);
  } catch (error) { toast(error.message, true); }
}

async function syncHindsightObsidian() {
  const box = $("#obsidian-results");
  box.textContent = "同步 Hindsight 记忆中…";
  try {
    const data = await api("/api/obsidian/hindsight/sync", { method: "POST", body: JSON.stringify(obsidianPayload()) });
    const exported = data.export || {};
    const imported = data.import || {};
    box.innerHTML = `<div class="claim"><div class="lens">Hindsight 记忆同步</div><p>export：写入 ${esc(String(exported.counts?.written || 0))} · 保留手改 ${esc(String(exported.counts?.preserved_user_edits || 0))} · 冲突 ${esc(String(exported.counts?.conflicts || 0))}</p><p>import：回写 ${esc(String(imported.updated || 0))} · 未变 ${esc(String(imported.unchanged || 0))} · observation 跳过 ${esc(String(imported.read_only_skipped || 0))}</p><p class="hint">${esc(data.error || exported.error || imported.error || "")}</p></div>`;
    box.classList.remove("empty");
    toast(data.ok ? "Hindsight 记忆同步完成" : "Hindsight 同步未完成，请查看错误", !data.ok);
  } catch (error) { toast(error.message, true); }
}

async function hindsightObsidianStatus() {
  try {
    const vault = $("#obsidian-vault")?.value.trim() || "";
    const data = await api(`/api/obsidian/hindsight/status?vault=${encodeURIComponent(vault)}`);
    $("#obsidian-results").innerHTML = `<div class="claim"><div class="lens">Hindsight 同步状态</div><p>已跟踪 ${esc(String(data.tracked_memories || 0))} 条记忆 · ${esc(String(data.memory_files || 0))} 个 Markdown 文件</p><p class="hint">${esc(data.root || "")}<br>${esc(data.write_policy || "")}</p></div>`;
    $("#obsidian-results").classList.remove("empty");
  } catch (error) { toast(error.message, true); }
}
async function obsidianStatus() {
  const vault = $("#obsidian-vault").value.trim();
  try {
    const data = await api(`/api/obsidian/status?vault=${encodeURIComponent(vault)}`);
    const notes = data.notes || {};
    $("#obsidian-results").innerHTML = `<div class="claim"><div class="lens">notes</div><p>active ${esc(String(notes.active || 0))} · orphaned ${esc(String(notes.orphaned || 0))} · missing ${esc(String(notes.missing || 0))} · due ${esc(String(data.due_reviews || 0))}</p><p class="hint">${esc(data.write_policy || "")}</p></div>`;
    $("#obsidian-results").classList.remove("empty");
  } catch (error) { toast(error.message, true); }
}
async function obsidianReviews() {
  try {
    const data = await api("/api/obsidian/reviews?limit=30");
    const due = data.due || [];
    $("#obsidian-results").innerHTML = `<div class="claim"><div class="lens">到期复习 ${due.length}</div>${due.map((item) => `<p><b>${esc(item.note_title || item.note_id || "")}</b> · due ${esc(item.due_at || "")} · mastery ${esc(String(item.mastery ?? ""))}</p>`).join("") || "<p class='hint'>没有到期项目</p>"}</div>`;
    $("#obsidian-results").classList.remove("empty");
  } catch (error) { toast(error.message, true); }
}
async function submitFeedback(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const selected = (name) => Array.from(form.querySelectorAll(`[name="${name}"] option:checked`)).map((option) => option.value);
  const payload = {
    analysis_id: state.currentAnalysis?.analysis_id,
    rating: Number(form.rating.value),
    note: form.note.value,
    outcome: form.outcome.value,
    error_labels: selected("error_labels"),
    preferred_book_ids: selected("preferred_book_ids"),
    preferred_framework_ids: [],
    missing_evidence: form.missing_evidence.value,
  };
  try {
    await api("/api/feedback", { method: "POST", body: JSON.stringify(payload) });
    toast("反馈已记录。去“自进化”页生成提案。");
    await loadStatus();
  } catch (error) {
    toast(error.message, true);
  }
}

async function applyPatch() {
  const status = $("#patch-status");
  let patch;
  try {
    patch = JSON.parse($("#analysis-patch").value);
  } catch (error) {
    status.textContent = "JSON 解析失败。";
    toast("补丁不是合法 JSON。", true);
    return;
  }
  try {
    const data = await api("/api/analysis-patch", {
      method: "POST",
      body: JSON.stringify({ analysis_id: state.currentAnalysis.analysis_id, patch }),
    });
    state.currentAnalysis = data.analysis;
    const packet = { ...data.analysis, _book_titles: state.currentBookTitles };
    renderAnalysis(packet);
    status.textContent = "";
    toast("补丁已通过验证并写入。");
    await loadAnalyses();
  } catch (error) {
    const details = (error.payload?.issues || []).map((issue) => `${issue.severity}: ${issue.code} ${issue.message}`).join("\n");
    status.textContent = details || error.message;
    toast("补丁被拒绝。看下方验证问题。", true);
  }
}

async function openAnalysis(analysisId) {
  try {
    const data = await api(`/api/analysis/${encodeURIComponent(analysisId)}`);
    state.currentBookTitles = data.book_titles || {};
    switchTab("analyze");
    renderAnalysis({ ...data.analysis, _book_titles: state.currentBookTitles });
    window.scrollTo({ top: $("#analysis-result").offsetTop - 80, behavior: "smooth" });
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadMemory() {
  const query = $("#memory-query").value.trim();
  const lenses = $$('input[name="memory-lens"]:checked').map((input) => input.value);
  const params = new URLSearchParams({ query, lenses: (lenses.length ? lenses : ["economics", "politics", "law"]).join(",") });
  try {
    const data = await api(`/api/memory?${params}`);
    const el = $("#memory-results");
    el.classList.remove("empty");
    if (!data.lessons?.length) {
      el.innerHTML = `<p class="empty">没有召回到相关记忆。先给分析打分/写反馈，或添加 memory。</p>`;
      return;
    }
    el.innerHTML = data.lessons.map((lesson) => `
      <div class="list-item">
        <h4>${esc(lesson.source === "feedback" ? `反馈 · ${lesson.prior_question || ""}` : `记忆 · ${lesson.kind || ""}`)}</h4>
        <p>${esc(lesson.note || lesson.key || JSON.stringify(lesson.value || ""))}</p>
        <div class="meta">relevance=${esc(lesson.relevance)} · rating=${esc(lesson.rating ?? "—")} · errors=${esc((lesson.error_labels || []).join(", ") || "—")}</div>
      </div>
    `).join("");
  } catch (error) {
    toast(error.message, true);
  }
}
async function loadEvolution() {
  try {
    const data = await api("/api/evolution");
    const proposals = data.proposals || [];
    const el = $("#proposal-list");
    if (!proposals.length) {
      el.innerHTML = `<p class="empty">还没有提案。先给分析写反馈，再点“从反馈生成提案”。</p>`;
      return;
    }
    el.innerHTML = proposals.map((proposal) => {
      const status = proposal.status || "proposed";
      const actions = [];
      if (status === "proposed") actions.push(["accepted", "接受"], ["rejected", "拒绝"]);
      if (status === "accepted") actions.push(["shadow", "进入影子"], ["rejected", "拒绝"]);
      if (status === "shadow") actions.push(["promoted", "晋升（需回放）"], ["rolled_back", "回滚"], ["rejected", "拒绝"]);
      if (status === "promoted") actions.push(["rolled_back", "回滚"]);
      return `
        <div class="list-item">
          <div class="card-head"><h4>${esc(proposal.target || "unknown target")}</h4><div>${badge(status)}</div></div>
          <p>${esc(proposal.rationale || "")}</p>
          <div class="meta">proposal=${esc(proposal.proposal_id)} · support=${esc(proposal.support ?? 0)} · created=${esc(fmtDate(proposal.created_at))}</div>
          <p class="hint">change: ${esc(JSON.stringify(proposal.change || {}))}</p>
          <p class="hint">风险: ${esc(proposal.risk || "—")} · 回滚: ${esc(proposal.rollback || "—")}</p>
          ${proposal.promotion_evidence ? `<div class="warning-box">promotion_evidence: ${esc(JSON.stringify(proposal.promotion_evidence))}</div>` : ""}
          <div class="actions">${actions.map(([action, label]) => `<button class="ghost" data-evolution-action="${action}" data-proposal="${esc(proposal.proposal_id)}">${label}</button>`).join("")}</div>
        </div>`;
    }).join("");
    $$("[data-evolution-action]", el).forEach((button) => button.addEventListener("click", () => decideEvolution(button.dataset.proposal, button.dataset.evolutionAction)));
  } catch (error) {
    toast(error.message, true);
  }
}

async function decideEvolution(proposalId, status) {
  if (status === "promoted" && !state.lastReplayReport) {
    toast("晋升前必须先运行结构回放。", true);
    return;
  }
  try {
    const payload = { proposal_id: proposalId, status, note: "", replay_report: status === "promoted" ? state.lastReplayReport : null };
    const data = await api("/api/evolution/decide", { method: "POST", body: JSON.stringify(payload) });
    toast(`提案状态：${data.proposal.status}`);
    await loadEvolution();
    await loadStatus();
  } catch (error) {
    toast(error.message, true);
  }
}

async function runReplay() {
  const raw = $("#replay-input").value.trim();
  const status = $("#replay-status");
  let payload = {};
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      payload = Array.isArray(parsed) ? { cases: parsed } : parsed;
    } catch (_) {
      payload = { analysis_ids: raw.split(",").map((item) => item.trim()).filter(Boolean) };
    }
  } else {
    const ids = state.analyses.slice(0, 3).map((item) => item.analysis_id);
    if (!ids.length) {
      toast("没有可用的分析 ID。先在分析页生成草稿。", true);
      return;
    }
    payload = { analysis_ids: ids };
  }
  status.textContent = "回放中…";
  try {
    const data = await api("/api/replay", { method: "POST", body: JSON.stringify(payload) });
    state.lastReplayReport = data.report;
    status.textContent = `完成：${data.report.structural_pass_count}/${data.report.case_count} 通过`;
    const reportEl = $("#replay-report");
    reportEl.classList.remove("hidden");
    reportEl.textContent = JSON.stringify(data.report, null, 2);
    toast("结构回放完成。现在可以在 shadow 提案上点晋升。");
  } catch (error) {
    status.textContent = "";
    toast(error.message, true);
  }
}

async function loadEntities() {
  const term = ($("#entity-query")?.value || "").trim();
  const crossBook = $("#entity-cross-book")?.checked ?? true;
  try {
    const data = await api(`/api/entities?${new URLSearchParams({ query: term, cross_book: String(crossBook), limit: "150" })}`);
    state.entities = data.entities || [];
    const stats = data.stats || {};
    $("#entity-stats").textContent = `${stats.entities || 0} 个实体 · ${stats.cross_book_entities || 0} 个跨书 · ${stats.mentions || 0} 次提及 · ${stats.relations || 0} 条关系`;
    const el = $("#entity-list");
    if (!state.entities.length) {
      el.className = "list empty";
      el.innerHTML = `<p class="empty">没有匹配实体。先编译书并点“重新对齐”。</p>`;
      return;
    }
    el.className = "list";
    el.innerHTML = state.entities.map((entity) => `
      <div class="list-item" data-entity-open="${esc(entity.entity_id)}" style="cursor:pointer">
        <div class="card-head"><h4>${esc(entity.canonical_name)}</h4><span class="badge">${esc(entity.entity_type)}</span></div>
        <p class="hint">${esc(entity.summary || "")}</p>
        <div class="meta">books=${esc(entity.book_count)} · mentions=${esc(entity.mentions)} · aliases=${esc((entity.aliases || []).join(" / "))}</div>
      </div>
    `).join("");
    $$("[data-entity-open]", el).forEach((node) => node.addEventListener("click", () => openEntity(node.dataset.entityOpen)));
  } catch (error) {
    toast(error.message, true);
  }
}

async function openEntity(entityId) {
  try {
    const data = await api(`/api/entities/${encodeURIComponent(entityId)}`);
    const entity = data.entity;
    const mentions = (entity.mentions || []).slice(0, 40).map((mention) => `
      <div class="list-item">
        <div class="meta">${esc(mention.book_title)} · ${esc(mention.chapter_title)} · page ${esc(mention.page_start ?? "—")} · ${esc(mention.surface)}</div>
        <p>${esc((mention.text || "").slice(0, 420))}</p>
      </div>
    `).join("");
    const relations = (entity.relations || []).slice(0, 30).map((relation) => `
      <div class="meta">${esc(relation.relation)} ↔ ${esc(relation.other_name)} (weight ${esc(relation.weight)})</div>
    `).join("");
    const body = `
      <p class="hint">${esc(entity.summary || "")}</p>
      <p>${tags(entity.aliases || [])}</p>
      <h3>跨书关系统计</h3><div class="list">${relations || "<p class='empty'>暂无</p>"}</div>
      <h3>原文提及</h3><div class="list">${mentions || "<p class='empty'>暂无</p>"}</div>
    `;
    const drawerBody = $("#drawer-body");
    drawerBody.innerHTML = body;
    $("#drawer-title").textContent = entity.canonical_name;
    $("#drawer").classList.add("open");
    $("#drawer").setAttribute("aria-hidden", "false");
  } catch (error) {
    toast(error.message, true);
  }
}

async function auditEntities() {
  const button = $("#entity-audit");
  button.disabled = true;
  button.textContent = "审计中…";
  try {
    const data = await api("/api/entities/audit?limit=50");
    const candidates = data.candidates || [];
    const el = $("#entity-audit-report");
    el.classList.remove("hidden");
    if (!candidates.length) {
      el.className = "list empty";
      el.innerHTML = `<p class="empty">没有发现近似重复实体。审计只做提示，不会自动合并。</p>`;
      return;
    }
    el.className = "list";
    el.innerHTML = `<p class="hint">review_only · 共 ${esc(data.candidate_count)} 个候选。近似合并会破坏出处，必须由人或 agent 显式确认，系统不会自动合并。</p>` +
      candidates.map((candidate) => `
        <div class="list-item">
          <div class="card-head"><h4>${esc(candidate.left.canonical_name)} ↔ ${esc(candidate.right.canonical_name)}</h4><span class="badge">${esc(candidate.relation)}</span></div>
          <div class="meta">similarity=${esc(candidate.similarity)} · shared_books=${esc((candidate.shared_books || []).join(" / ") || "—")}</div>
          <div class="meta">${esc((candidate.left.aliases || []).join(" / ") || "—")} ⇄ ${esc((candidate.right.aliases || []).join(" / ") || "—")}</div>
        </div>
      `).join("");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "近似重复审计";
  }
}


async function loadClaims() {
  const query = $("#claim-query")?.value || "";
  const status = $("#claim-status")?.value || "";
  const params = new URLSearchParams({ query, status, limit: "100" });
  try {
    const data = await api(`/api/claims?${params}`);
    const stats = data.stats || {};
    $("#claim-stats").textContent = `${stats.claims || 0} 条命题 · ${stats.contradicts_relations || 0} 组冲突 · ${stats.pending_entity_merges || 0} 个待确认实体合并`;
    const claims = data.claims || [];
    const el = $("#claim-list");
    if (!claims.length) {
      el.className = "list empty";
      el.innerHTML = `<p class="empty">还没有命题。先点“从已学书籍抽取命题”。</p>`;
    } else {
      el.className = "list";
      el.innerHTML = claims.map((claim) => `
        <div class="list-item">
          <div class="card-head">
            <h4>${esc(claim.subject)} · ${esc(claim.predicate)}</h4>
            <span class="badge ${esc(claim.status)}">${esc(claim.status)}</span>
          </div>
          <div class="meta">${esc(claim.book_title || claim.book_id)} · 第 ${esc(claim.page ?? "?")} 页 · 极性 ${esc(claim.polarity)} · 置信度 ${esc(claim.confidence)}</div>
          <p>${esc(claim.object)}</p>
          <blockquote class="quote">${esc(claim.quote)}</blockquote>
          <div class="actions">
            <button class="ghost" onclick="supersedeClaim('${esc(claim.claim_id)}')">标记为被取代</button>
            ${claim.status === "conflicted" ? `<button class="ghost" onclick="dismissClaim('${esc(claim.claim_id)}')">确认为不同观点</button>` : ""}
          </div>
        </div>`).join("");
    }
    renderClaimRelations(claims);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderClaimRelations(claims) {
  const el = $("#claim-relations");
  if (!el) return;
  const conflicted = (claims || []).filter((claim) => claim.status === "conflicted");
  if (!conflicted.length) {
    el.className = "list empty";
    el.innerHTML = `<p class="empty">当前没有 conflicted 命题。冲突检测只做提示，不会自动改判。</p>`;
    return;
  }
  el.className = "list";
  el.innerHTML = conflicted.map((claim) => `
    <div class="list-item">
      <h4>${esc(claim.subject)} · ${esc(claim.predicate)}</h4>
      <p>${esc(claim.object)}</p>
      <div class="meta">${esc(claim.book_title || claim.book_id)} · 第 ${esc(claim.page ?? "?")} 页</div>
      <blockquote class="quote">${esc(claim.quote)}</blockquote>
    </div>`).join("");
}

async function buildClaims() {
  const button = $("#claims-build");
  button.disabled = true;
  button.textContent = "正在抽取命题…";
  try {
    const data = await api("/api/claims/build", { method: "POST", body: JSON.stringify({ limit_per_book: 120, replace: true }) });
    toast(`新增 ${data.claims} 条命题，发现 ${data.conflicts?.conflicts || 0} 组冲突。`);
    await Promise.all([loadClaims(), loadStatus()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "从已学书籍抽取命题";
  }
}

async function supersedeClaim(claimId) {
  const newClaimId = prompt("输入新命题的 claim_id（新命题必须已经存在）：");
  if (!newClaimId) return;
  const note = prompt("写一句可审计的说明：", "用户确认：旧命题已被新证据取代");
  if (note === null) return;
  if (!confirm("确认执行 supersession？旧命题会变为 superseded，可回滚。")) return;
  try {
    await api("/api/claims/supersede", {
      method: "POST",
      body: JSON.stringify({ claim_id: claimId, new_claim_id: newClaimId.trim(), note, confirm: true }),
    });
    toast("已记录 supersession。");
    await loadClaims();
  } catch (error) {
    toast(error.message, true);
  }
}

async function dismissClaim(claimId) {
  try {
    const detail = await api(`/api/claims/${encodeURIComponent(claimId)}`);
    const conflicts = (detail.claim?.relations || []).filter((item) => item.relation === "contradicts");
    if (!conflicts.length) {
      toast("没有找到可处理的冲突关系。");
      return;
    }
    const other = conflicts[0].src_claim_id === claimId ? conflicts[0].dst_claim_id : conflicts[0].src_claim_id;
    if (!confirm(`确认两条命题是不同观点、不是错误吗？\n${claimId} 与 ${other}`)) return;
    await api("/api/claims/dismiss", {
      method: "POST",
      body: JSON.stringify({ claim_id: claimId, new_claim_id: other, note: "reviewed: keep as different views" }),
    });
    toast("已保留为不同观点，两条命题恢复 active。");
    await loadClaims();
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadEntityCandidates() {
  const el = $("#entity-candidate-list");
  if (!el) return;
  try {
    const data = await api("/api/entities/candidates?limit=100");
    const candidates = data.candidates || [];
    if (!candidates.length) {
      el.className = "list empty";
      el.innerHTML = `<p class="empty">没有待确认的实体合并候选。</p>`;
      return;
    }
    el.className = "list";
    el.innerHTML = candidates.map((candidate) => {
      const reason = String(candidate.reason || "");
      const readable = reason.includes("contains")
        ? "名称包含关系：需确认是同一个概念，还是上下位概念。"
        : reason;
      return `
        <div class="list-item">
          <div class="card-head">
            <h4>${esc(candidate.left_name)} ↔ ${esc(candidate.right_name)}</h4>
            <span class="badge ${esc(candidate.status)}">${esc(candidate.status)}</span>
          </div>
          <div class="meta">相似度 ${esc(candidate.similarity)} · ${esc(readable)}</div>
          <div class="meta">共同出现于：${esc((candidate.shared_books || []).join(" / ") || "—")}</div>
          <div class="actions">
            ${candidate.status === "pending" ? `
              <button class="ghost" onclick="mergeCandidate('${esc(candidate.candidate_id)}')">确认合并</button>
              <button class="ghost" onclick="rejectCandidate('${esc(candidate.candidate_id)}')">拒绝</button>` : ""}
            ${candidate.status === "accepted" ? `<button class="ghost" onclick="undoMerge('${esc(candidate.candidate_id)}')">撤销合并</button>` : ""}
          </div>
        </div>`;
    }).join("");
  } catch (error) {
    toast(error.message, true);
  }
}

async function syncEntityAudit() {
  try {
    const data = await api("/api/entities/sync-audit", { method: "POST", body: JSON.stringify({ limit: 50 }) });
    toast(`已扫描并保存 ${data.persisted} 个合并候选。`);
    await loadEntityCandidates();
  } catch (error) {
    toast(error.message, true);
  }
}

async function mergeCandidate(candidateId) {
  if (!confirm("确认合并这两个实体？会移动 mention/relation/claim，且可撤销。")) return;
  try {
    const data = await api("/api/entities/merge", {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId, note: "confirmed in GUI", confirm: true }),
    });
    toast(`合并完成：保留 ${data.kept}，移除 ${data.dropped}，改动已记录。`);
    await Promise.all([loadEntities(), loadEntityCandidates(), loadStatus()]);
  } catch (error) {
    toast(error.message, true);
  }
}

async function rejectCandidate(candidateId) {
  try {
    await api("/api/entities/reject", {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId, note: "reviewed: keep separate" }),
    });
    toast("已拒绝该合并候选。");
    await loadEntityCandidates();
  } catch (error) {
    toast(error.message, true);
  }
}

async function undoMerge(candidateId) {
  if (!confirm("确认撤销这次实体合并？")) return;
  try {
    await api("/api/entities/undo-merge", { method: "POST", body: JSON.stringify({ candidate_id: candidateId }) });
    toast("已撤销实体合并。");
    await Promise.all([loadEntities(), loadEntityCandidates(), loadStatus()]);
  } catch (error) {
    toast(error.message, true);
  }
}

async function alignEntities() {
  const button = $("#align-entities");
  button.disabled = true;
  button.textContent = "对齐中…";
  try {
    const data = await api("/api/entities/align", { method: "POST", body: "{}" });
    toast(`对齐完成：${data.entities} 个实体，其中 ${data.cross_book_entities} 个跨书。`);
    await Promise.all([loadEntities(), loadStatus()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "重新对齐";
  }
}

async function backfillEmbeddings() {
  const button = $("#backfill-embeddings");
  button.disabled = true;
  button.textContent = "补齐中…";
  try {
    const data = await api("/api/embeddings/backfill", { method: "POST", body: JSON.stringify({ local: false }) });
    toast(`嵌入补齐：新增 ${data.embedded}，跳过 ${data.skipped}。`);
    await loadStatus();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "补齐嵌入";
  }
}

async function runRetrievalProbe() {
  const query = ($("#retrieval-query")?.value || "").trim();
  if (!query) { toast("先输入一个问题。", true); return; }
  try {
    const data = await api(`/api/retrieval?${new URLSearchParams({ query, limit: "8" })}`);
    const report = $("#retrieval-report");
    report.classList.remove("hidden");
    report.textContent = JSON.stringify({
      embedding: data.embedding,
      detected_entities: (data.entities?.detected || []).map((item) => item.canonical_name),
      lexical: data.lexical,
      hybrid: data.hybrid,
    }, null, 2);
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadGraph() {
  const node = $("#graph-node").value.trim();
  try {
    const data = await api(`/api/graph?${new URLSearchParams({ node })}`);
    const el = $("#graph-results");
    el.classList.remove("empty");
    if (!data.edges?.length) {
      el.innerHTML = `<p class="empty">没有边。先编译书，或换一个节点。</p>`;
      return;
    }
    el.innerHTML = data.edges.slice(0, 300).map((edge) => `
      <div class="list-item">
        <div class="meta">${esc(edge.src_type)} · ${esc(edge.src_id)} <span style="color:var(--copper)">— ${esc(edge.relation)} →</span> ${esc(edge.dst_type)} · ${esc(edge.dst_id)}</div>
        ${(edge.evidence || []).map((citation) => citationHtml(citation)).join("")}
      </div>
    `).join("");
  } catch (error) {
    toast(error.message, true);
  }
}


async function copyText(text) {
  if (!text) return toast("先填写模型和 provider", true);
  try {
    await navigator.clipboard.writeText(text);
    toast("命令已复制");
  } catch (_) {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); toast("命令已复制"); }
    catch (__) { toast("复制失败，请手动选择命令", true); }
    area.remove();
  }
}

function formatBytes(value) {
  const n = Number(value || 0);
  if (!n) return "";
  const units = ["B", "KB", "MB", "GB"];
  let index = 0;
  let size = n;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size.toFixed(size >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function currentHermesCommand(persist) {
  const model = $("#hermes-model-input").value.trim();
  const provider = $("#hermes-provider-input").value.trim();
  if (!model) { toast("先填写 Hermes 模型名", true); return ""; }
  let command = `/model ${model}`;
  if (provider) command += ` --provider ${provider}`;
  if (persist) command += " --global";
  return command;
}

async function loadModels() {
  try {
    const data = await api("/api/models");
    state.models = data;

    const hermes = data.hermes || {};
    const hModel = $("#hermes-model-input");
    const hProvider = $("#hermes-provider-input");
    const hBase = $("#hermes-base-url-input");
    if (hModel) hModel.value = hermes.model || "";
    if (hProvider) hProvider.value = hermes.provider || "";
    if (hBase) hBase.value = hermes.base_url || "";
    const hStatus = $("#hermes-model-status");
    if (hStatus) {
      hStatus.innerHTML = `
        <div class="claim">
          <div class="lens">当前：${esc(hermes.model || "未配置")}${hermes.provider ? ` · ${esc(hermes.provider)}` : ""}</div>
          <p class="hint">${esc(hermes.base_url || "未设置 base_url")}</p>
          <p class="hint">配置：${esc(hermes.config_path || "")}${hermes.config_exists ? "" : "（未找到）"}</p>
        </div>`;
      hStatus.classList.remove("empty");
    }

    const judge = data.judge || {};
    const jProvider = $("#model-judge-provider");
    const jModel = $("#model-judge-model");
    const jBase = $("#model-judge-base-url");
    if (jProvider) jProvider.value = judge.provider || "ollama";
    if (jModel) jModel.value = judge.model || "";
    if (jBase) jBase.value = judge.base_url || "";
    const jStatus = $("#judge-model-status");
    if (jStatus) {
      jStatus.innerHTML = `
        <div class="claim">
          <div class="lens">当前：${esc(judge.model || "")} · ${esc(judge.provider || "")}</div>
          <p class="hint">${esc(judge.base_url || "")}</p>
          <p class="hint">来源：${judge.source === "env_file" ? ".env" : "内置默认值"} · ${esc(judge.env_file || "")}</p>
          <p class="hint">读书模型：${esc((data.reader || {}).model || "未配置")} · ${esc((data.reader || {}).provider || "")} · 费用闸：${(data.reader || {}).deepseek_guard_enabled ? "开启" : "关闭"}</p>
        </div>`;
      jStatus.classList.remove("empty");
    }

    const ollama = data.ollama || {};
    const list = $("#ollama-model-list");
    if (list) list.innerHTML = (ollama.models || []).map((item) => `<option value="${esc(item.name)}">${esc([item.parameter_size, item.quantization_level].filter(Boolean).join(" · "))}</option>`).join("");
    const ollamaStatus = $("#model-ollama-status");
    if (ollamaStatus) ollamaStatus.textContent = ollama.available ? `在线，发现 ${(ollama.models || []).length} 个模型` : `未连接：${ollama.error || "未知错误"}`;

    const hindsight = data.hindsight || {};
    const hsProvider = $("#model-hindsight-provider");
    const hsModel = $("#model-hindsight-model");
    const hsBase = $("#model-hindsight-base-url");
    if (hsProvider) hsProvider.value = hindsight.provider || "ollama";
    if (hsModel) hsModel.value = hindsight.model || "";
    if (hsBase) hsBase.value = hindsight.base_url || "";
    const hsStatus = $("#hindsight-model-status");
    if (hsStatus) {
      hsStatus.innerHTML = `
        <div class="claim">
          <div class="lens">当前：${esc(hindsight.model || "未配置")} · ${esc(hindsight.provider || "")}</div>
          <p class="hint">${esc(hindsight.base_url || "")}</p>
          <p class="hint">来源：${esc(hindsight.env_file || "")} · 修改后重启 Hindsight</p>
        </div>`;
      hsStatus.classList.remove("empty");
    }

    const embedding = data.embedding || {};
    const embStatus = $("#embedding-model-status");
    if (embStatus) {
      embStatus.innerHTML = `
        <div class="claim">
          <div class="lens">${esc(embedding.model || "")}</div>
          <p class="hint">backend ${esc(embedding.backend || "")} · device ${esc(embedding.device || "")}</p>
          <p class="hint">reranker ${embedding.rerank_enabled ? "开启" : "关闭"}${embedding.rerank_model ? ` · ${esc(embedding.rerank_model)}` : ""}</p>
          <p class="hint">${esc(embedding.warning || "")}</p>
        </div>`;
      embStatus.classList.remove("empty");
    }
  } catch (error) {
    toast(error.message, true);
  }
}

async function saveJudgeModel() {
  const status = $("#model-judge-status");
  if (status) status.textContent = "保存中…";
  try {
    const data = await api("/api/models/judge", {
      method: "POST",
      body: JSON.stringify({
        provider: $("#model-judge-provider").value,
        model: $("#model-judge-model").value,
        base_url: $("#model-judge-base-url").value,
      }),
    });
    if (status) status.textContent = `已保存到 ${data.env_file}`;
    if ($("#judge-provider")) $("#judge-provider").value = data.provider;
    if ($("#judge-model")) $("#judge-model").value = data.model;
    toast("盲评默认模型已更新");
    await loadModels();
  } catch (error) {
    if (status) status.textContent = "";
    toast(error.message, true);
  }
}

async function saveHindsightModel() {
  const status = $("#model-hindsight-save-status");
  if (status) status.textContent = "保存中…";
  try {
    const data = await api("/api/models/hindsight", {
      method: "POST",
      body: JSON.stringify({
        provider: $("#model-hindsight-provider").value,
        model: $("#model-hindsight-model").value,
        base_url: $("#model-hindsight-base-url").value,
      }),
    });
    if (status) status.textContent = `已保存到 ${data.env_file}；重启 Hindsight 后生效`;
    toast("Hindsight 模型已保存，记得重启服务");
    await loadModels();
  } catch (error) {
    if (status) status.textContent = "";
    toast(error.message, true);
  }
}

async function saveHermesConfig() {
  const model = $("#hermes-model-input").value.trim();
  if (!model) return toast("先填写 Hermes 模型名", true);
  if (!confirm("将改写 D:\\hermes agent\\config.yaml，并备份原文件。已运行的 Hermes 仍需重启或用 /model 切换。继续吗？")) return;
  try {
    const data = await api("/api/models/hermes", {
      method: "POST",
      body: JSON.stringify({
        model,
        provider: $("#hermes-provider-input").value.trim() || "custom",
        base_url: ($("#hermes-base-url-input")?.value || state.models?.hermes?.base_url || "").trim(),
      }),
    });
    toast(`Hermes 配置已写入 ${data.config_path}`);
    await loadModels();
  } catch (error) { toast(error.message, true); }
}

async function applyModelPreset(name) {
  const status = $("#model-preset-status");
  if (status) status.textContent = "应用中…";
  try {
    const data = await api("/api/models/preset", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    const failed = (data.results || []).filter((item) => item.error);
    if (status) status.textContent = failed.length ? `完成，但有 ${failed.length} 项失败` : "已应用";
    if (failed.length) {
      toast(`预设已应用，但 ${failed.length} 项失败：${failed.map((item) => `${item.target}: ${item.error}`).join("；")}`, true);
    } else {
      toast(name === "local" ? "已全部切到本地 Ollama" : (name === "mimo" ? "已切换：MiMo 云端阅读/盲评 + 本地记忆" : "已切换：DeepSeek 云端阅读/盲评 + 本地记忆"));
    }
    await loadModels();
  } catch (error) {
    if (status) status.textContent = "";
    toast(error.message, true);
  }
}

function bindEvents() {
  $$(".tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));
  $$("[data-close-drawer]").forEach((node) => node.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });

  $("#refresh-overview").addEventListener("click", async () => {
    await Promise.all([loadStatus(), loadBooks(), loadFrameworks(), loadAnalyses()]);
    toast("已刷新。");
  });
  $("#refresh-books").addEventListener("click", loadBooks);
  $("#book-search").addEventListener("input", renderBookTable);
  $("#book-status-filter").addEventListener("change", renderBookTable);

  $("#open-ingest").addEventListener("click", () => $("#ingest-card").classList.toggle("hidden"));
  $("#close-ingest").addEventListener("click", () => $("#ingest-card").classList.add("hidden"));
  $("#ingest-card").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const status = $("#ingest-status");
    status.textContent = "导入中…";
    try {
      const data = await api("/api/ingest", {
        method: "POST",
        body: JSON.stringify({
          path: form.path.value,
          title: form.title.value,
          author: form.author.value || "Unknown",
          disciplines: form.disciplines.value.split(",").map((item) => item.trim()).filter(Boolean),
        }),
      });
      status.textContent = `已入库：${data.title}（${data.chapters} 章 / ${data.chunks} 片段）`;
      form.reset();
      await Promise.all([loadBooks(), loadStatus()]);
      toast("导入完成。下一步需要 agent 编译成书卡/框架。");
    } catch (error) {
      status.textContent = "";
      toast(error.message, true);
    }
  });

  function resetConsent() {
    state.consentChoice = "";
    const bar = $("#consent-bar");
    bar.classList.add("hidden");
    bar.innerHTML = "";
  }

  $("#mode-select").addEventListener("change", () => {
    const mode = $("#mode-select").value;
    $("#book-ids").closest("label").style.opacity = mode === "books" ? "1" : ".72";
    $("#framework-ids").closest("label").style.opacity = mode === "books" ? "1" : ".72";
    resetConsent();
  });
  $("#analyze-form").querySelectorAll('textarea[name="query"], input[name="direction"], input[name="lens"], #book-ids, #framework-ids').forEach((node) => {
    node.addEventListener("input", resetConsent);
    node.addEventListener("change", resetConsent);
  });
  $("#plan-btn").addEventListener("click", planSelection);
  $("#analyze-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = collectAnalyzeBody();
    if (body.mode !== "auto" && !state.consentChoice) {
      const proposal = await planSelection();
      if (proposal?.requires_confirmation) {
        toast("请先在选择卡下方确认使用范围。", true);
        return;
      }
    }
    await runAnalysis(state.consentChoice || "");
  });

  $("#memory-btn").addEventListener("click", loadMemory);
  $("#propose-btn").addEventListener("click", async () => {
    try {
      const data = await api("/api/evolution/propose", { method: "POST", body: JSON.stringify({ min_support: 1 }) });
      toast(`已生成 ${data.proposals.length} 个提案。`);
      await loadEvolution();
      await loadStatus();
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("#replay-btn").addEventListener("click", runReplay);
  $("#graph-btn").addEventListener("click", loadGraph);
  $("#entity-btn").addEventListener("click", loadEntities);
  $("#entity-query").addEventListener("keydown", (event) => { if (event.key === "Enter") loadEntities(); });
  $("#align-entities").addEventListener("click", alignEntities);
  $("#entity-audit").addEventListener("click", auditEntities);
  $("#entity-sync-audit")?.addEventListener("click", syncEntityAudit);
  $("#entity-candidates")?.addEventListener("click", loadEntityCandidates);
  $("#claims-build")?.addEventListener("click", buildClaims);
  $("#claim-search")?.addEventListener("click", loadClaims);
  $("#claim-query")?.addEventListener("keydown", (event) => { if (event.key === "Enter") loadClaims(); });
  $("#backfill-embeddings").addEventListener("click", backfillEmbeddings);
  $("#retrieval-btn").addEventListener("click", runRetrievalProbe);
  $("#graphrag-status-btn")?.addEventListener("click", graphRagStatus);
  $("#graphrag-build-btn")?.addEventListener("click", buildGraphRag);
  $("#graphrag-query-btn")?.addEventListener("click", queryGraphRag);
  $("#obsidian-sync-btn")?.addEventListener("click", syncObsidian);
  $("#obsidian-sync-all-btn")?.addEventListener("click", syncAllObsidian);
  $("#obsidian-hindsight-sync-btn")?.addEventListener("click", syncHindsightObsidian);
  $("#obsidian-hindsight-status-btn")?.addEventListener("click", hindsightObsidianStatus);
  $("#obsidian-status-btn")?.addEventListener("click", obsidianStatus);
  $("#obsidian-review-btn")?.addEventListener("click", obsidianReviews);
  $("#models-refresh")?.addEventListener("click", loadModels);
  $("#model-ollama-refresh")?.addEventListener("click", loadModels);
  $("#model-judge-save")?.addEventListener("click", saveJudgeModel);
  $("#model-hindsight-save")?.addEventListener("click", saveHindsightModel);
  $("#hermes-save-config")?.addEventListener("click", saveHermesConfig);
  $("#models-mimo-preset")?.addEventListener("click", () => applyModelPreset("mimo"));
  $("#models-cloud-preset")?.addEventListener("click", () => applyModelPreset("cloud"));
  $("#models-local-preset")?.addEventListener("click", () => applyModelPreset("local"));
  $("#hermes-copy-session")?.addEventListener("click", () => {
    const command = currentHermesCommand(false);
    if (!command) return;
    $("#hermes-model-command").textContent = command;
    $("#hermes-model-command").classList.remove("hidden");
    copyText(command);
  });
  $("#hermes-copy-global")?.addEventListener("click", () => {
    const command = currentHermesCommand(true);
    if (!command) return;
    $("#hermes-model-command").textContent = command;
    $("#hermes-model-command").classList.remove("hidden");
    copyText(command);
  });
  $("#hermes-open-picker")?.addEventListener("click", () => {
    $("#hermes-model-command").textContent = "cd /d \"D:\\hermes agent\" && bin\\hermes.cmd model";
    $("#hermes-model-command").classList.remove("hidden");
    toast("在 Hermes 目录运行该命令，可交互式选择 provider 和模型");
  });
}

async function init() {
  bindEvents();
  window.addEventListener("hashchange", () => {
    const name = location.hash.replace("#", "");
    if (["overview", "library", "analyze", "models", "memory", "evolution", "entities", "claims", "inspect"].includes(name)) switchTab(name);
  });
  await Promise.all([loadStatus(), loadBooks(), loadFrameworks(), loadAnalyses()]);
  const mode = $("#mode-select").value;
  $("#book-ids").closest("label").style.opacity = mode === "books" ? "1" : ".72";
  $("#framework-ids").closest("label").style.opacity = mode === "books" ? "1" : ".72";
  const initial = location.hash.replace("#", "");
  if (["library", "analyze", "models", "memory", "evolution", "entities", "claims", "inspect"].includes(initial)) switchTab(initial);
}

document.addEventListener("DOMContentLoaded", init);
