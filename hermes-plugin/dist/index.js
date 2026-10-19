/* Knowledge Hub — unified Hermes dashboard control plane. */
(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  const React = SDK.React;
  const h = React.createElement;
  const H = SDK.hooks || {};
  const useState = H.useState || React.useState;
  const useEffect = H.useEffect || React.useEffect;
  const useCallback = H.useCallback || React.useCallback;
  const useMemo = H.useMemo || React.useMemo;
  const API_BASE = "/api/plugins/knowledge-hub";
  const BOOKCOMPILER_URL = "http://127.0.0.1:8765";
  const MANUAL_URL = "/dashboard-plugins/knowledge-hub/manual.html";

  // Default the whole Hermes dashboard shell to Simplified Chinese once.
  // The native language switcher at the bottom-left can still change it later.
  try {
    var KH_LOCALE_KEY = "hermes-locale";
    var KH_LOCALE_DEFAULTED = "kh-locale-defaulted-v1";
    if (!localStorage.getItem(KH_LOCALE_DEFAULTED)) {
      localStorage.setItem(KH_LOCALE_DEFAULTED, "1");
      if (!localStorage.getItem(KH_LOCALE_KEY) || localStorage.getItem(KH_LOCALE_KEY) === "en") {
        localStorage.setItem(KH_LOCALE_KEY, "zh");
        window.location.reload();
        return;
      }
    }
  } catch (e) {}

  // Fill in the shell labels that Hermes' bundled zh translation still leaves in English.
  function installChineseShellLabels() {
    var labels = {
      "/files": "文件",
      "/channels": "频道",
      "/webhooks": "Webhook",
      "/pairing": "配对",
      "/system": "系统",
      "/kanban": "看板",
      "/knowledge-hub": "知识中枢",
      "/achievements": "成就"
    };
    function apply() {
      Object.keys(labels).forEach(function (href) {
        var nodes = document.querySelectorAll('a[href="' + href + '"] span');
        for (var i = 0; i < nodes.length; i++) {
          var el = nodes[i];
          if (el.childElementCount === 0 && el.textContent !== labels[href]) {
            el.textContent = labels[href];
          }
        }
      });
    }
    apply();
    if (window.MutationObserver) {
      var scheduled = false;
      var observer = new MutationObserver(function () {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(function () { scheduled = false; apply(); });
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installChineseShellLabels);
  } else {
    installChineseShellLabels();
  }

  function api(path, options) { return SDK.fetchJSON(API_BASE + path, options); }
  function postJSON(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify(body || {})
    });
  }
  function errText(err) {
    if (!err) return "";
    return typeof err === "string" ? err : String(err.message || err.detail || err.error || err);
  }
  function count(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value == null ? "0" : value);
    if (Math.abs(n) >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
    if (Math.abs(n) >= 10000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    return n.toLocaleString("zh-CN");
  }
  function pct(value) {
    const n = Number(value);
    return Number.isFinite(n) ? (n <= 1 ? n * 100 : n).toFixed(1).replace(/\.0$/, "") + "%" : "—";
  }
  function shortDate(value) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  function ago(value) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (sec < 60) return Math.floor(sec) + " 秒前";
    if (sec < 3600) return Math.floor(sec / 60) + " 分钟前";
    if (sec < 86400) return Math.floor(sec / 3600) + " 小时前";
    return Math.floor(sec / 86400) + " 天前";
  }
  function asArray(value) { return Array.isArray(value) ? value : []; }
  function arrayText(value) { return Array.isArray(value) ? value.filter(Boolean).join(" · ") : (value ? String(value) : ""); }
  function serviceMap(rows) {
    const map = {};
    asArray(rows).forEach(function (row) { if (row && row.id) map[row.id] = row; });
    return map;
  }

  function Pill(props) {
    return h("span", { className: "kh-pill " + (props.tone ? "kh-pill-" + props.tone : "") }, props.children);
  }
  function StatusDot(props) {
    return h("span", { className: "kh-dot " + (props.ok ? "kh-dot-ok" : "kh-dot-bad"), title: props.ok ? "在线" : "离线" });
  }
  function StatCard(props) {
    return h("div", { className: "kh-stat" + (props.accent ? " kh-stat-accent" : "") },
      h("div", { className: "kh-stat-label" }, props.label),
      h("div", { className: "kh-stat-value" }, props.value),
      props.hint ? h("div", { className: "kh-stat-hint" }, props.hint) : null);
  }
  function Loading(props) {
    return h("div", { className: "kh-loading" }, h("span", { className: "kh-spinner" }), h("span", null, props.label || "正在读取本地服务…"));
  }
  function ErrorBox(props) {
    if (!props.error) return null;
    return h("div", { className: "kh-error" },
      h("strong", null, "读取失败"),
      h("span", null, errText(props.error)),
      props.onRetry ? h("button", { className: "kh-btn kh-btn-ghost", onClick: props.onRetry }, "重试") : null);
  }
  function Empty(props) { return h("div", { className: "kh-empty" }, props.children || "暂无数据"); }
  function SectionHead(props) {
    return h("div", { className: "kh-section-head" },
      h("div", null, h("h2", null, props.title), props.subtitle ? h("p", null, props.subtitle) : null),
      props.right || null);
  }
  function ResultView(props) {
    const value = props.value;
    if (value == null) return null;
    if (typeof value === "string") return h("pre", { className: "kh-pre" }, value);
    const answer = value.answer || value.text || value.response || value.output || value.content;
    const memories = value.memories || value.items || value.results;
    return h("div", { className: "kh-result" },
      answer ? h("div", { className: "kh-answer" }, String(answer)) : null,
      Array.isArray(memories) && memories.length ? h("div", { className: "kh-result-list" },
        memories.map(function (m, i) {
          const text = typeof m === "string" ? m : (m.text || m.content || m.memory || JSON.stringify(m));
          return h("div", { className: "kh-result-item", key: m.id || i },
            h("span", { className: "kh-result-index" }, String(i + 1).padStart(2, "0")),
            h("div", null, h("div", null, text),
              m.context || m.score != null ? h("div", { className: "kh-muted kh-small" }, arrayText(m.context), m.score != null ? " · score " + Number(m.score).toFixed(3) : "") : null));
        })) : null,
      !answer && (!Array.isArray(memories) || !memories.length) ? h("pre", { className: "kh-pre" }, JSON.stringify(value, null, 2)) : null);
  }
  function BookRow(props) {
    const b = props.book || {};
    return h("div", { className: "kh-book" },
      h("div", { className: "kh-book-main" },
        h("div", { className: "kh-book-title-row" },
          h("strong", null, b.title || "未命名"),
          h(Pill, { tone: b.status === "compiled" ? "ok" : "warn" }, b.status || "unknown"),
          b.card_status ? h(Pill, null, b.card_status) : null),
        h("div", { className: "kh-book-meta" },
          h("span", null, b.author || "未知作者"),
          h("span", null, arrayText(b.disciplines) || "未分类"),
          h("span", null, "框架 " + count(b.framework_count)),
          h("span", null, "chunks " + count(b.chunk_count)),
          h("span", null, "章节 " + count(b.chapters))),
        b.one_line_thesis ? h("p", { className: "kh-book-thesis" }, b.one_line_thesis) : null),
      h("div", { className: "kh-book-side" }, h("div", { className: "kh-mini-label" }, "入库"), h("div", null, shortDate(b.ingested_at))));
  }
  function MemoryRow(props) {
    const m = props.memory || {};
    return h("div", { className: "kh-memory" },
      h("div", { className: "kh-memory-head" },
        h(Pill, { tone: m.fact_type === "world" ? "info" : "ok" }, m.fact_type || "memory"),
        asArray(m.tags).map(function (tag) { return h(Pill, { key: tag }, tag); }),
        h("span", { className: "kh-muted kh-small kh-grow" }, shortDate(m.occurred_start || m.date || m.mentioned_at))),
      h("div", { className: "kh-memory-text" }, m.text || m.content || "（空记忆）"),
      m.context ? h("div", { className: "kh-memory-context" }, m.context) : null);
  }
  function ModelChip(props) {
    return h("div", { className: "kh-model-chip" + (props.tone ? " kh-model-chip-" + props.tone : "") },
      h("span", { className: "kh-muted kh-small" }, props.label), h("strong", null, props.value || "—"));
  }
  function PathRow(props) {
    return h("div", { className: "kh-path-row" }, h("span", { className: "kh-muted kh-small" }, props.label), h("code", null, props.value || "—"));
  }
  function StartButton(props) {
    const state = useState(false); const busy = state[0]; const setBusy = state[1];
    const msgState = useState(""); const msg = msgState[0]; const setMsg = msgState[1];
    function start() {
      setBusy(true); setMsg("");
      postJSON("/actions/start", { service: props.service })
        .then(function (r) { setMsg(r && r.ok ? "已启动" : "未启动"); if (props.onDone) props.onDone(); })
        .catch(function (e) { setMsg(errText(e)); })
        .finally(function () { setBusy(false); });
    }
    return h("span", { className: "kh-start-wrap" },
      h("button", { className: "kh-btn kh-btn-small" + (props.compact ? " kh-btn-compact" : ""), onClick: start, disabled: busy }, busy ? "启动中…" : (props.label || "启动")),
      msg ? h("span", { className: "kh-muted kh-small" }, msg) : null);
  }
  function OverviewPage(props) {
    const data = props.data || {};
    const bc = data.bookcompiler || {};
    const coverage = bc.coverage || {};
    const embedding = bc.embedding || {};
    const entities = bc.entities || {};
    const hsStats = (data.hindsight && data.hindsight.stats_bookcompiler) || {};
    const obs = (data.obsidian && data.obsidian.snapshot) || {};
    const models = data.models || {};
    const services = asArray(data.services);
    const online = services.filter(function (s) { return s.running; }).length;
    const readerModel = (models.reader && models.reader.model) || "未配置";
    const judgeModel = (models.judge && models.judge.model) || "未配置";
    const hermesModel = (models.hermes && models.hermes.model) || "未配置";
    const hindsightModel = (models.hindsight && models.hindsight.model) || "未配置";

    return h("div", { className: "kh-page" },
      h(ErrorBox, { error: props.error, onRetry: props.reload }),
      props.loading && !data.services ? h(Loading) : null,
      h("section", { className: "kh-metrics-grid" },
        h(StatCard, { label: "书籍", value: count(coverage.books), hint: "已入库", accent: true }),
        h(StatCard, { label: "知识框架", value: count(coverage.frameworks), hint: "可调用能力" }),
        h(StatCard, { label: "分析记录", value: count(coverage.analyses), hint: "问题 / 结论 / 引用" }),
        h(StatCard, { label: "文本片段", value: count(embedding.total_chunks), hint: "embedding 覆盖 " + pct(embedding.coverage) }),
        h(StatCard, { label: "跨书实体", value: count(entities.cross_book_entities), hint: "共 " + count(entities.entities) + " 个实体" }),
        h(StatCard, { label: "Hindsight 记忆", value: count(hsStats.total_nodes), hint: "bookcompiler bank" })),
      h("section", { className: "kh-split" },
        h("div", { className: "kh-panel" },
          h(SectionHead, {
            title: "服务状态",
            subtitle: online + " / " + services.length + " 在线 · " + (data.generated_at ? "刷新于 " + shortDate(data.generated_at) : "尚未刷新"),
            right: h("button", { className: "kh-btn kh-btn-ghost", onClick: props.reload }, "刷新")
          }),
          h("div", { className: "kh-service-grid" },
            services.map(function (s) {
              return h("div", { className: "kh-service" + (s.running ? " kh-service-on" : ""), key: s.id },
                h("div", { className: "kh-service-head" }, h(StatusDot, { ok: s.running }), h("strong", null, s.label), h("span", { className: "kh-muted kh-small" }, ":" + s.port)),
                h("div", { className: "kh-service-detail" }, s.detail || ""),
                h("div", { className: "kh-service-actions" },
                  s.url ? h("a", { className: "kh-link", href: s.url, target: "_blank", rel: "noreferrer" }, "打开") : null,
                  !s.running ? h(StartButton, { service: s.id, compact: true }) : null));
            }))),
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "知识调用流水线", subtitle: "书不是一堆上下文，而是可路由、可解释、可复用的能力层。" }),
          h("div", { className: "kh-pipeline" },
            [
              ["01", "入书", "PDF / TXT / EPUB → 章节与 chunks"],
              ["02", "编译", "框架 / claims / 实体 / 引用"],
              ["03", "混合检索", "BM25 + embedding + 实体扩展"],
              ["04", "深度分析", "选中框架，生成可追溯结论"],
              ["05", "沉淀记忆", "偏好 / 纠错 / 经验 → Hindsight"],
              ["06", "Agent 调用", "Hermes 自动路由到已读知识"]
            ].map(function (row) {
              return h("div", { className: "kh-pipeline-step", key: row[0] },
                h("span", { className: "kh-step-no" }, row[0]),
                h("div", null, h("strong", null, row[1]), h("p", null, row[2])));
            })))),
      h("section", { className: "kh-panel" },
        h(SectionHead, { title: "当前模型分工", subtitle: "重任务走 API，本地记忆抽取走 Ollama；四套模型可分别切换。", right: h("button", { className: "kh-btn", onClick: function () { props.onTab("models"); } }, "管理模型") }),
        h("div", { className: "kh-model-strip" },
          h(ModelChip, { label: "Reader / 读书", value: readerModel, tone: "accent" }),
          h(ModelChip, { label: "Judge / 评审", value: judgeModel }),
          h(ModelChip, { label: "Hermes / 对话", value: hermesModel }),
          h(ModelChip, { label: "Hindsight / 记忆", value: hindsightModel }))),
      h("section", { className: "kh-split kh-split-even" },
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "Obsidian 可编辑层", subtitle: "生成的笔记可读可改；Inbox 修改会回流。" }),
          h("div", { className: "kh-inline-stats" },
            h("div", null, h("strong", null, count(obs.bookcompiler_notes)), h("span", null, "BookCompiler 笔记")),
            h("div", null, h("strong", null, count(obs.hindsight_notes)), h("span", null, "Hindsight 笔记"))),
          h("div", { className: "kh-path" }, obs.vault || "Vault 未配置"),
          h("div", { className: "kh-actions" },
            h("button", { className: "kh-btn", onClick: function () { props.onTab("obsidian"); } }, "查看与同步"),
            h("a", { className: "kh-btn kh-btn-ghost", href: "obsidian://open", target: "_blank", rel: "noreferrer" }, "在 Obsidian 打开"))),
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "快速开始", subtitle: "日常最常用的四个动作。" }),
          h("div", { className: "kh-quick-grid" },
            h(QuickAction, { title: "向 Agent 提问", desc: "让 Hermes 自动路由到书库能力", href: "/chat", icon: "◎" }),
            h(QuickAction, { title: "浏览书库", desc: "查看书籍与知识框架", onClick: function () { props.onTab("books"); }, icon: "▤" }),
            h(QuickAction, { title: "召回记忆", desc: "测试 Hindsight 长期记忆", onClick: function () { props.onTab("memory"); }, icon: "◈" }),
            h(QuickAction, { title: "完整教程", desc: "项目 / Hermes / Hindsight", href: MANUAL_URL, icon: "?" })))),
      h("section", { className: "kh-panel" },
        h(SectionHead, { title: "本机数据位置", subtitle: "所有内容都在本地；未上传云端。" }),
        h("div", { className: "kh-path-grid" },
          h(PathRow, { label: "BookCompiler SQLite", value: data.paths && data.paths.bookcompiler_db }),
          h(PathRow, { label: "GraphRAG", value: data.paths && data.paths.bookcompiler_graph_db }),
          h(PathRow, { label: "Hindsight", value: data.paths && data.paths.hindsight_home }),
          h(PathRow, { label: "Obsidian Vault", value: data.paths && data.paths.obsidian_vault }),
          h(PathRow, { label: "Hermes", value: data.paths && data.paths.hermes_home })))
    );
  }
  function QuickAction(props) {
    const content = h(React.Fragment, null,
      h("span", { className: "kh-quick-icon" }, props.icon || "→"),
      h("div", null, h("strong", null, props.title), h("p", null, props.desc)));
    if (props.href) return h("a", { className: "kh-quick", href: props.href, target: props.href.charAt(0) === "/" ? undefined : "_blank", rel: "noreferrer" }, content);
    return h("button", { className: "kh-quick", onClick: props.onClick }, content);
  }
  function BooksPage(props) {
    const dataState = useState(null); const data = dataState[0]; const setData = dataState[1];
    const loadingState = useState(true); const loading = loadingState[0]; const setLoading = loadingState[1];
    const errorState = useState(""); const error = errorState[0]; const setError = errorState[1];
    const qState = useState(""); const q = qState[0]; const setQ = qState[1];
    const showState = useState(true); const showFrameworks = showState[0]; const setShowFrameworks = showState[1];
    const load = useCallback(function () {
      setLoading(true); setError("");
      api("/books").then(setData).catch(function (e) { setError(errText(e)); }).finally(function () { setLoading(false); });
    }, []);
    useEffect(function () { load(); }, [load]);
    const books = asArray(data && data.books);
    const frameworks = asArray(data && data.frameworks);
    const analyses = asArray(data && data.analyses);
    const needle = q.trim().toLowerCase();
    const filteredBooks = useMemo(function () {
      if (!needle) return books;
      return books.filter(function (b) { return [b.title, b.author, arrayText(b.disciplines), b.one_line_thesis].join(" ").toLowerCase().indexOf(needle) >= 0; });
    }, [books, needle]);
    const filteredFrameworks = useMemo(function () {
      if (!needle) return frameworks;
      return frameworks.filter(function (f) { return [f.name, f.one_liner, f.book_title, arrayText(f.lenses), arrayText(f.applicable_when)].join(" ").toLowerCase().indexOf(needle) >= 0; });
    }, [frameworks, needle]);
    return h("div", { className: "kh-page" },
      h("section", { className: "kh-hero kh-hero-compact" },
        h("div", null, h("span", { className: "kh-kicker" }, "KNOWLEDGE LIBRARY"), h("h1", null, "书库与知识框架"), h("p", null, "每本书被编译成若干可调用框架；检索时同时使用 BM25、embedding 与实体扩展。")),
        h("div", { className: "kh-actions" },
          h("a", { className: "kh-btn", href: BOOKCOMPILER_URL + "/#library", target: "_blank", rel: "noreferrer" }, "在 BookCompiler 打开"),
          h("button", { className: "kh-btn kh-btn-primary", onClick: load }, "刷新书库"))),
      h(ErrorBox, { error: error, onRetry: load }),
      loading && !data ? h(Loading) : null,
      h("div", { className: "kh-toolbar" },
        h("input", { className: "kh-input kh-search", value: q, onChange: function (e) { setQ(e.target.value); }, placeholder: "搜索书名、作者、学科、框架、适用场景…" }),
        h("span", { className: "kh-muted" }, filteredBooks.length + " 本书 · " + filteredFrameworks.length + " 个框架"),
        h("button", { className: "kh-btn kh-btn-ghost", onClick: function () { setShowFrameworks(!showFrameworks); } }, showFrameworks ? "收起框架" : "展开框架")),
      h("section", { className: "kh-panel" },
        h(SectionHead, { title: "书籍", subtitle: "编译状态、学科标签与框架数量。" }),
        filteredBooks.length ? filteredBooks.map(function (b) { return h(BookRow, { key: b.book_id, book: b }); }) : h(Empty, null, needle ? "没有匹配的书。" : "书库为空。")),
      showFrameworks ? h("section", { className: "kh-panel" },
        h(SectionHead, { title: "知识框架", subtitle: "Agent 真正调用的是这些方法，而不是整本书的原文。" }),
        h("div", { className: "kh-framework-grid" },
          filteredFrameworks.slice(0, 120).map(function (f) {
            return h("div", { className: "kh-framework", key: f.framework_id || (f.book_id + f.name) },
              h("div", { className: "kh-framework-head" }, h("strong", null, f.name || "未命名框架"), f.status ? h(Pill, { tone: f.status === "verified" ? "ok" : "warn" }, f.status) : null),
              h("div", { className: "kh-muted kh-small" }, f.book_title || ""),
              h("p", null, f.one_liner || ""),
              h("div", { className: "kh-tags" }, asArray(f.lenses).map(function (lens) { return h(Pill, { key: lens, tone: "info" }, lens); })),
              asArray(f.applicable_when).length ? h("div", { className: "kh-applicable" }, "适用：", arrayText(f.applicable_when)) : null);
          })),
        filteredFrameworks.length > 120 ? h("div", { className: "kh-muted kh-small kh-center" }, "仅显示前 120 个，请用搜索缩小范围。") : null) : null,
      h("section", { className: "kh-panel" },
        h(SectionHead, { title: "最近分析", subtitle: "问题、视角、引用数量与状态。" }),
        analyses.length ? h("div", { className: "kh-analysis-list" },
          analyses.slice(0, 20).map(function (a) {
            return h("div", { className: "kh-analysis", key: a.analysis_id },
              h("div", { className: "kh-analysis-q" }, a.question || "（无题目）"),
              h("div", { className: "kh-analysis-meta" },
                h(Pill, { tone: a.status === "completed" ? "ok" : "warn" }, a.status || "draft"),
                h(Pill, null, arrayText(a.lenses) || "general"),
                h("span", { className: "kh-muted kh-small" }, count(a.book_count) + " 本书 · " + count(a.citation_count) + " 条引用 · " + shortDate(a.created_at))));
          })) : h(Empty)));
  }
  function MemoryPage(props) {
    const bankState = useState("bookcompiler"); const bank = bankState[0]; const setBank = bankState[1];
    const banksState = useState([]); const banks = banksState[0]; const setBanks = banksState[1];
    const statsState = useState(null); const stats = statsState[0]; const setStats = statsState[1];
    const itemsState = useState([]); const items = itemsState[0]; const setItems = itemsState[1];
    const qState = useState(""); const q = qState[0]; const setQ = qState[1];
    const loadingState = useState(true); const loading = loadingState[0]; const setLoading = loadingState[1];
    const errorState = useState(""); const error = errorState[0]; const setError = errorState[1];
    const recallQState = useState(""); const recallQ = recallQState[0]; const setRecallQ = recallQState[1];
    const recallResultState = useState(null); const recallResult = recallResultState[0]; const setRecallResult = recallResultState[1];
    const recallBusyState = useState(false); const recallBusy = recallBusyState[0]; const setRecallBusy = recallBusyState[1];
    const reflectResultState = useState(null); const reflectResult = reflectResultState[0]; const setReflectResult = reflectResultState[1];
    const reflectBusyState = useState(false); const reflectBusy = reflectBusyState[0]; const setReflectBusy = reflectBusyState[1];
    const retainTextState = useState(""); const retainText = retainTextState[0]; const setRetainText = retainTextState[1];
    const retainContextState = useState(""); const retainContext = retainContextState[0]; const setRetainContext = retainContextState[1];
    const retainTagsState = useState("preference"); const retainTags = retainTagsState[0]; const setRetainTags = retainTagsState[1];
    const retainBusyState = useState(false); const retainBusy = retainBusyState[0]; const setRetainBusy = retainBusyState[1];
    const messageState = useState(""); const message = messageState[0]; const setMessage = messageState[1];

    useEffect(function () {
      api("/hindsight/banks").then(function (r) { setBanks(asArray(r && r.banks)); }).catch(function () {});
    }, []);
    const loadBank = useCallback(function () {
      setLoading(true); setError("");
      Promise.all([
        api("/hindsight/stats?bank=" + encodeURIComponent(bank)),
        api("/hindsight/memories?bank=" + encodeURIComponent(bank) + "&limit=80" + (q.trim() ? "&q=" + encodeURIComponent(q.trim()) : ""))
      ]).then(function (rows) {
        setStats(rows[0]); setItems(asArray(rows[1] && rows[1].items));
      }).catch(function (e) { setError(errText(e)); }).finally(function () { setLoading(false); });
    }, [bank, q]);
    useEffect(function () { loadBank(); }, [loadBank]);

    function recall() {
      if (!recallQ.trim()) return;
      setRecallBusy(true); setRecallResult(null); setMessage("");
      postJSON("/hindsight/recall", { bank: bank, query: recallQ.trim(), budget: "mid", max_tokens: 4096 })
        .then(setRecallResult).catch(function (e) { setMessage(errText(e)); }).finally(function () { setRecallBusy(false); });
    }
    function reflect() {
      if (!recallQ.trim()) return;
      setReflectBusy(true); setReflectResult(null); setMessage("");
      postJSON("/hindsight/reflect", { bank: bank, query: recallQ.trim(), budget: "low", max_tokens: 4096 })
        .then(setReflectResult).catch(function (e) { setMessage(errText(e)); }).finally(function () { setReflectBusy(false); });
    }
    function retain() {
      if (!retainText.trim()) return;
      setRetainBusy(true); setMessage("");
      postJSON("/hindsight/retain", {
        bank: bank, text: retainText.trim(), context: retainContext.trim(),
        tags: retainTags.split(",").map(function (x) { return x.trim(); }).filter(Boolean)
      }).then(function () {
        setMessage("已写入 " + bank + " bank。"); setRetainText(""); setRetainContext(""); loadBank();
      }).catch(function (e) { setMessage(errText(e)); }).finally(function () { setRetainBusy(false); });
    }
    return h("div", { className: "kh-page" },
      h("section", { className: "kh-hero kh-hero-compact" },
        h("div", null, h("span", { className: "kh-kicker" }, "HINDSIGHT MEMORY"), h("h1", null, "长期记忆"), h("p", null, "这里存的不是整本书，而是跨会话可复用的偏好、纠错、经验与教训。书正文仍在 BookCompiler。")),
        h("div", { className: "kh-bank-switch" },
          asArray(banks).length ? banks.map(function (b) {
            return h("button", { key: b.bank_id, className: "kh-tab-chip" + (b.bank_id === bank ? " active" : ""), onClick: function () { setBank(b.bank_id); setRecallResult(null); setReflectResult(null); } }, b.name || b.bank_id);
          }) : h("span", { className: "kh-muted" }, "bookcompiler / hermes"))),
      h(ErrorBox, { error: error, onRetry: loadBank }),
      message ? h("div", { className: "kh-toast" }, message) : null,
      h("div", { className: "kh-metrics-grid kh-metrics-compact" },
        h(StatCard, { label: "记忆节点", value: count(stats && stats.total_nodes), hint: "bank " + bank }),
        h(StatCard, { label: "关系", value: count(stats && stats.total_links), hint: "semantic links" }),
        h(StatCard, { label: "文档", value: count(stats && stats.total_documents), hint: "source documents" }),
        h(StatCard, { label: "待整合", value: count(stats && stats.pending_operations), hint: "pending operations" })),
      h("section", { className: "kh-split" },
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "回忆 / 反思", subtitle: "先 recall 找相关记忆，再 reflect 让 Hindsight 归纳。" }),
          h("textarea", { className: "kh-textarea", value: recallQ, onChange: function (e) { setRecallQ(e.target.value); }, placeholder: "例如：分析今天央行降准对银行信贷与地方债的影响，应该调用哪些已读知识？" }),
          h("div", { className: "kh-actions" },
            h("button", { className: "kh-btn kh-btn-primary", disabled: recallBusy || !recallQ.trim(), onClick: recall }, recallBusy ? "召回中…" : "Recall 召回"),
            h("button", { className: "kh-btn", disabled: reflectBusy || !recallQ.trim(), onClick: reflect }, reflectBusy ? "反思中…" : "Reflect 反思")),
          recallResult ? h("div", { className: "kh-subpanel" }, h("div", { className: "kh-mini-label" }, "Recall 结果"), h(ResultView, { value: recallResult })) : null,
          reflectResult ? h("div", { className: "kh-subpanel" }, h("div", { className: "kh-mini-label" }, "Reflect 结果"), h(ResultView, { value: reflectResult })) : null),
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "写入一条记忆", subtitle: "适合存用户偏好、纠正、工作流选择与结果。" }),
          h("textarea", { className: "kh-textarea", value: retainText, onChange: function (e) { setRetainText(e.target.value); }, placeholder: "要长期记住的事实 / 偏好 / 教训…" }),
          h("input", { className: "kh-input", value: retainContext, onChange: function (e) { setRetainContext(e.target.value); }, placeholder: "上下文（可选）" }),
          h("input", { className: "kh-input", value: retainTags, onChange: function (e) { setRetainTags(e.target.value); }, placeholder: "tags，用逗号分隔" }),
          h("div", { className: "kh-actions" }, h("button", { className: "kh-btn kh-btn-primary", disabled: retainBusy || !retainText.trim(), onClick: retain }, retainBusy ? "写入中…" : "写入 " + bank)))),
      h("section", { className: "kh-panel" },
        h(SectionHead, {
          title: "记忆列表", subtitle: "共 " + count(stats && stats.total_nodes) + " 条 · 可直接在 Obsidian 的 Hindsight 目录里编辑。",
          right: h("div", { className: "kh-inline" },
            h("input", { className: "kh-input kh-input-small", value: q, onChange: function (e) { setQ(e.target.value); }, placeholder: "过滤记忆…" }),
            h("button", { className: "kh-btn kh-btn-ghost", onClick: loadBank }, "刷新"))
        }),
        loading ? h(Loading, { label: "正在读取记忆…" }) : null,
        items.length ? items.map(function (m) { return h(MemoryRow, { key: m.id, memory: m }); }) : (!loading ? h(Empty, null, "该 bank 暂无记忆。") : null)));
  }
  function ObsidianPage(props) {
    const dataState = useState(null); const data = dataState[0]; const setData = dataState[1];
    const loadingState = useState(true); const loading = loadingState[0]; const setLoading = loadingState[1];
    const errorState = useState(""); const error = errorState[0]; const setError = errorState[1];
    const busyState = useState(false); const busy = busyState[0]; const setBusy = busyState[1];
    const messageState = useState(""); const message = messageState[0]; const setMessage = messageState[1];
    const load = useCallback(function () {
      setLoading(true); setError("");
      api("/obsidian/status").then(setData).catch(function (e) { setError(errText(e)); }).finally(function () { setLoading(false); });
    }, []);
    useEffect(function () { load(); }, [load]);
    const snap = (data && data.snapshot) || {};
    const bookStatus = (data && data.bookcompiler) || {};
    const hsStatus = (data && data.hindsight) || {};

    function syncAll() {
      setBusy(true); setMessage("");
      postJSON("/obsidian/sync-all", { vault: snap.vault || "" })
        .then(function (r) { setMessage(r && r.ok ? "双向同步完成。" : "同步返回：" + JSON.stringify(r)); load(); })
        .catch(function (e) { setMessage(errText(e)); }).finally(function () { setBusy(false); });
    }
    function openPath(target) {
      postJSON("/actions/open-path", { target: target })
        .then(function (r) { setMessage(r && r.ok ? "已打开：" + r.path : "打开失败"); })
        .catch(function (e) { setMessage(errText(e)); });
    }
    function NoteList(props) {
      const rows = asArray(props.rows);
      if (!rows.length) return h(Empty, null, "暂无笔记");
      return h("div", { className: "kh-note-list" }, rows.map(function (note) {
        return h("div", { className: "kh-note", key: note.path },
          h("div", { className: "kh-note-name" }, note.name || note.relative_path),
          h("div", { className: "kh-note-meta" }, note.relative_path || note.path, " · ", ago(note.modified_at)));
      }));
    }
    return h("div", { className: "kh-page" },
      h("section", { className: "kh-hero kh-hero-compact" },
        h("div", null, h("span", { className: "kh-kicker" }, "OBSIDIAN BRIDGE"), h("h1", null, "可读、可改、可回流的知识层"), h("p", null, "BookCompiler 与 Hindsight 都会导出 Markdown。生成的笔记受保护；你在 Inbox / Hindsight 里的修改可以回写到本地数据库。")),
        h("div", { className: "kh-actions" },
          h("button", { className: "kh-btn kh-btn-primary", disabled: busy, onClick: syncAll }, busy ? "同步中…" : "立即双向同步"),
          h("button", { className: "kh-btn", onClick: function () { openPath("vault"); } }, "打开 Vault 文件夹"),
          h("a", { className: "kh-btn kh-btn-ghost", href: "obsidian://open", target: "_blank", rel: "noreferrer" }, "在 Obsidian 打开"))),
      h(ErrorBox, { error: error, onRetry: load }),
      message ? h("div", { className: "kh-toast" }, message) : null,
      loading && !data ? h(Loading, { label: "正在检查 Obsidian…" }) : null,
      h("div", { className: "kh-metrics-grid kh-metrics-compact" },
        h(StatCard, { label: "BookCompiler 笔记", value: count(snap.bookcompiler_notes), hint: "受保护导出 + Inbox", accent: true }),
        h(StatCard, { label: "Hindsight 笔记", value: count(snap.hindsight_notes), hint: "可编辑记忆" }),
        h(StatCard, { label: "Hindsight 文件", value: count(hsStatus.memory_files), hint: "受跟踪 " + count(hsStatus.tracked_memories) }),
        h(StatCard, { label: "Vault", value: snap.vault_exists ? "正常" : "缺失", hint: snap.vault || "未配置" })),
      h("section", { className: "kh-split kh-split-even" },
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "BookCompiler", subtitle: "书籍卡片、框架、分析与 Inbox。" }),
          h("div", { className: "kh-path" }, snap.bookcompiler_root || "—"),
          h("div", { className: "kh-inline-stats" },
            h("div", null, h("strong", null, count(snap.bookcompiler_notes)), h("span", null, "总笔记")),
            h("div", null, h("strong", null, count(snap.hindsight_notes)), h("span", null, "Hindsight")),
            h("div", null, h("strong", null, count(bookStatus.due_reviews)), h("span", null, "待复习"))),
          h("div", { className: "kh-mini-label" }, "最近更新"), h(NoteList, { rows: snap.recent_bookcompiler })),
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "Hindsight", subtitle: "世界记忆可编辑；观察记忆只读。" }),
          h("div", { className: "kh-path" }, snap.hindsight_root || "—"),
          h("div", { className: "kh-callout" }, "可编辑的世界/经验记忆；观察记忆只读；冲突保留，不会被静默覆盖。"),
          h("div", { className: "kh-mini-label" }, "最近更新"), h(NoteList, { rows: snap.recent_hindsight }))),
      h("section", { className: "kh-panel" },
        h(SectionHead, { title: "双向同步规则", subtitle: "为什么不会互相覆盖。" }),
        h("div", { className: "kh-rule-grid" },
          h("div", null, h("strong", null, "生成区 = 受保护"), h("p", null, "BookCompiler 生成的卡片与框架页带有保护标记；重新编译不会覆盖你后来改的内容。")),
          h("div", null, h("strong", null, "Inbox = 输入区"), h("p", null, "你在 BookCompiler Inbox 中新建或修改的笔记会被导入 SQLite，作为阅读者笔记。")),
          h("div", null, h("strong", null, "Hindsight = 经验层"), h("p", null, "世界/经验记忆可编辑并回流；observation 保持只读，冲突会保留而不是静默覆盖。")))));
  }
  function modelFor(data, target) {
    if (!data) return {};
    if (target === "bookcompiler") return data.reader || {};
    return data[target] || {};
  }
  function ModelsPage(props) {
    const dataState = useState(null); const data = dataState[0]; const setData = dataState[1];
    const loadingState = useState(true); const loading = loadingState[0]; const setLoading = loadingState[1];
    const errorState = useState(""); const error = errorState[0]; const setError = errorState[1];
    const busyState = useState(false); const busy = busyState[0]; const setBusy = busyState[1];
    const messageState = useState(""); const message = messageState[0]; const setMessage = messageState[1];
    const targetState = useState("reader"); const target = targetState[0]; const setTarget = targetState[1];
    const providerState = useState("openai-compatible"); const provider = providerState[0]; const setProvider = providerState[1];
    const modelState = useState("mimo-v2.6-flash"); const model = modelState[0]; const setModel = modelState[1];
    const baseState = useState("https://token-plan-cn.xiaomimimo.com/v1"); const baseUrl = baseState[0]; const setBaseUrl = baseState[1];
    const load = useCallback(function () {
      setLoading(true); setError("");
      api("/models").then(function (d) {
        setData(d);
        const m = modelFor(d, target);
        if (m.provider) setProvider(m.provider);
        if (m.model) setModel(m.model);
        if (m.base_url) setBaseUrl(m.base_url);
      }).catch(function (e) { setError(errText(e)); }).finally(function () { setLoading(false); });
    }, [target]);
    useEffect(function () { load(); }, [load]);
    function chooseTarget(next) {
      setTarget(next); setMessage("");
      const m = modelFor(data, next);
      setProvider(m.provider || "openai-compatible"); setModel(m.model || ""); setBaseUrl(m.base_url || "");
    }
    function preset(name) {
      setBusy(true); setMessage("");
      postJSON("/models/preset", { name: name })
        .then(function (r) { setMessage(r && r.ok ? "已应用预设：" + name + "。Hindsight / Hermes 可能需要重启。" : "预设返回：" + JSON.stringify(r)); load(); })
        .catch(function (e) { setMessage(errText(e)); }).finally(function () { setBusy(false); });
    }
    function switchModel() {
      if (!provider.trim() || !model.trim()) { setMessage("provider 和 model 不能为空。"); return; }
      setBusy(true); setMessage("");
      postJSON("/models/switch", { target: target, provider: provider.trim(), model: model.trim(), base_url: baseUrl.trim() })
        .then(function (r) { setMessage((r && r.ok ? "已切换 " + target + "。" : "切换失败。") + (r && r.restart_required ? " 该目标需要重启后生效。" : "") + (r && r.output ? "\n" + r.output : "")); load(); })
        .catch(function (e) { setMessage(errText(e)); }).finally(function () { setBusy(false); });
    }
    const cards = [
      ["reader", "Reader", "读书 / 编译", data && data.reader],
      ["judge", "Judge", "九维评分 / 评审", data && data.judge],
      ["hermes", "Hermes", "主对话 Agent", data && data.hermes],
      ["hindsight", "Hindsight", "记忆抽取 / 反思", data && data.hindsight]
    ];
    return h("div", { className: "kh-page" },
      h("section", { className: "kh-hero kh-hero-compact" },
        h("div", null, h("span", { className: "kh-kicker" }, "MODEL ROUTING"), h("h1", null, "四套模型，一键分工"), h("p", null, "建议：读书与评审用云端大模型，Hindsight 记忆抽取用 Ollama。每个目标都有独立配置，互不绑死。")),
        h("div", { className: "kh-preset-row" },
          h("button", { className: "kh-btn kh-btn-primary", disabled: busy, onClick: function () { preset("mimo"); } }, "小米 MiMo 预设"),
          h("button", { className: "kh-btn", disabled: busy, onClick: function () { preset("local"); } }, "全本地 Ollama"),
          h("button", { className: "kh-btn", disabled: busy, onClick: function () { preset("cloud"); } }, "云端 DeepSeek"))),
      h(ErrorBox, { error: error, onRetry: load }),
      message ? h("div", { className: "kh-toast kh-toast-pre" }, message) : null,
      loading && !data ? h(Loading, { label: "正在读取模型配置…" }) : null,
      h("div", { className: "kh-model-grid" },
        cards.map(function (row) {
          const m = row[3] || {};
          return h("div", { className: "kh-model-card", key: row[0] },
            h("div", { className: "kh-model-card-head" },
              h("div", null, h("span", { className: "kh-muted kh-small" }, row[2]), h("h3", null, row[1])),
              h(Pill, { tone: m.model ? "ok" : "warn" }, m.model ? "已配置" : "未配置")),
            h("div", { className: "kh-model-name" }, m.model || "—"),
            h("div", { className: "kh-model-meta" }, h("span", null, "provider: ", h("code", null, m.provider || "—")), h("span", null, "base: ", h("code", null, m.base_url || "—"))),
            m.api_key_configured != null ? h("div", { className: "kh-muted kh-small" }, "API key: " + (m.api_key_configured ? "已配置" : "缺失")) : null,
            row[0] === "hindsight" ? h("div", { className: "kh-warning-text" }, "修改后需重启 Hindsight 服务") : null);
        })),
      h("section", { className: "kh-split" },
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "单独切换", subtitle: "写入目标自己的配置文件；不会影响其他三个。" }),
          h("label", { className: "kh-field" }, h("span", null, "目标"), h("select", { className: "kh-input", value: target, onChange: function (e) { chooseTarget(e.target.value); } },
            h("option", { value: "reader" }, "Reader / BookCompiler 读书"),
            h("option", { value: "judge" }, "Judge / 评审"),
            h("option", { value: "hermes" }, "Hermes / 主对话"),
            h("option", { value: "hindsight" }, "Hindsight / 记忆"))),
          h("label", { className: "kh-field" }, h("span", null, "Provider"), h("input", { className: "kh-input", value: provider, onChange: function (e) { setProvider(e.target.value); }, placeholder: "openai-compatible / ollama / xiaomi" })),
          h("label", { className: "kh-field" }, h("span", null, "Model"), h("input", { className: "kh-input", value: model, onChange: function (e) { setModel(e.target.value); }, placeholder: "mimo-v2.6-flash" })),
          h("label", { className: "kh-field" }, h("span", null, "Base URL"), h("input", { className: "kh-input", value: baseUrl, onChange: function (e) { setBaseUrl(e.target.value); }, placeholder: "https://…/v1" })),
          h("div", { className: "kh-actions" }, h("button", { className: "kh-btn kh-btn-primary", disabled: busy, onClick: switchModel }, busy ? "写入中…" : "应用到此目标")),
          h("div", { className: "kh-callout" }, "Reader / Judge 的下一次任务生效；Hermes 已打开会话可能需要 /model 或重启；Hindsight 必须重启 run_server.py。")),
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "Ollama 本地模型", subtitle: "Hindsight 记忆抽取默认使用本地模型。" }),
          data && data.ollama && data.ollama.available ? h("div", { className: "kh-ollama-list" },
            asArray(data.ollama.models).map(function (m) {
              return h("div", { className: "kh-ollama", key: m.name }, h("strong", null, m.name), h("span", { className: "kh-muted kh-small" }, (m.parameter_size || "") + " · " + (m.quantization_level || "") + " · " + (Number(m.size || 0) / 1073741824).toFixed(1) + " GB"));
            })) : h(Empty, null, "Ollama 未连接或没有模型。"),
          h("div", { className: "kh-callout" }, "Embedding: " + ((data && data.embedding && data.embedding.model) || "—") + " · backend " + ((data && data.embedding && data.embedding.backend) || "—")))));
  }
  function ServicesPage(props) {
    const dataState = useState(null); const data = dataState[0]; const setData = dataState[1];
    const loadingState = useState(true); const loading = loadingState[0]; const setLoading = loadingState[1];
    const errorState = useState(""); const error = errorState[0]; const setError = errorState[1];
    const logNameState = useState("hindsight"); const logName = logNameState[0]; const setLogName = logNameState[1];
    const logTextState = useState(""); const logText = logTextState[0]; const setLogText = logTextState[1];
    const logBusyState = useState(false); const logBusy = logBusyState[0]; const setLogBusy = logBusyState[1];
    const messageState = useState(""); const message = messageState[0]; const setMessage = messageState[1];
    const load = useCallback(function () {
      setLoading(true); setError("");
      api("/overview").then(setData).catch(function (e) { setError(errText(e)); }).finally(function () { setLoading(false); });
    }, []);
    useEffect(function () { load(); }, [load]);
    function readLog(name) {
      setLogBusy(true); setMessage("");
      api("/logs?name=" + encodeURIComponent(name) + "&lines=300")
        .then(function (r) { setLogText((r && r.text) || "（日志为空）"); })
        .catch(function (e) { setMessage(errText(e)); }).finally(function () { setLogBusy(false); });
    }
    function openPath(target) {
      postJSON("/actions/open-path", { target: target })
        .then(function (r) { setMessage(r && r.ok ? "已打开：" + r.path : "打开失败"); })
        .catch(function (e) { setMessage(errText(e)); });
    }
    const services = asArray(data && data.services);
    const links = [
      ["/chat", "Chat", "与 Agent 对话"],
      ["/sessions", "Sessions", "历史会话"],
      ["/models", "Models", "Hermes 模型页"],
      ["/skills", "Skills", "技能库"],
      ["/mcp", "MCP", "外部工具"],
      ["/plugins", "Plugins", "插件管理"],
      ["/logs", "Logs", "系统日志"],
      ["/config", "Config", "配置编辑"]
    ];
    return h("div", { className: "kh-page" },
      h("section", { className: "kh-hero kh-hero-compact" },
        h("div", null, h("span", { className: "kh-kicker" }, "SERVICE CONTROL"), h("h1", null, "服务与端口"), h("p", null, "统一查看、启动和排障。所有服务只监听本机回环地址。")),
        h("button", { className: "kh-btn kh-btn-primary", onClick: load }, "刷新状态")),
      h(ErrorBox, { error: error, onRetry: load }),
      message ? h("div", { className: "kh-toast" }, message) : null,
      loading && !data ? h(Loading) : null,
      h("div", { className: "kh-service-grid kh-service-grid-large" },
        services.map(function (s) {
          return h("div", { className: "kh-service kh-service-big" + (s.running ? " kh-service-on" : ""), key: s.id },
            h("div", { className: "kh-service-head" }, h(StatusDot, { ok: s.running }), h("strong", null, s.label), h(Pill, { tone: s.running ? "ok" : "bad" }, s.running ? "运行中" : "已停止")),
            h("div", { className: "kh-service-port" }, "127.0.0.1:" + s.port),
            h("div", { className: "kh-service-detail" }, s.detail || ""),
            h("div", { className: "kh-service-actions" },
              s.url ? h("a", { className: "kh-btn kh-btn-small kh-btn-ghost", href: s.url, target: "_blank", rel: "noreferrer" }, "打开") : null,
              !s.running ? h(StartButton, { service: s.id, onDone: load, label: "启动" }) : null));
        })),
      h("section", { className: "kh-split" },
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "Hermes 原生页面", subtitle: "Knowledge Hub 不重造这些页面，只把它们放到统一入口里。" }),
          h("div", { className: "kh-link-grid" }, links.map(function (row) {
            return h("a", { className: "kh-link-card", href: row[0], key: row[0] }, h("strong", null, row[1]), h("span", null, row[2]));
          })),
          h("div", { className: "kh-mini-label" }, "本机目录"),
          h("div", { className: "kh-actions kh-actions-wrap" },
            h("button", { className: "kh-btn kh-btn-ghost", onClick: function () { openPath("hermes"); } }, "Hermes"),
            h("button", { className: "kh-btn kh-btn-ghost", onClick: function () { openPath("bookcompiler"); } }, "BookCompiler"),
            h("button", { className: "kh-btn kh-btn-ghost", onClick: function () { openPath("hindsight"); } }, "Hindsight"),
            h("button", { className: "kh-btn kh-btn-ghost", onClick: function () { openPath("logs"); } }, "Knowledge Hub 日志"))),
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "服务日志", subtitle: "启动失败时先看这里。" }),
          h("div", { className: "kh-inline" },
            h("select", { className: "kh-input", value: logName, onChange: function (e) { setLogName(e.target.value); } },
              h("option", { value: "hindsight" }, "Hindsight stdout"),
              h("option", { value: "hindsight-error" }, "Hindsight stderr"),
              h("option", { value: "bookcompiler" }, "BookCompiler stdout"),
              h("option", { value: "bookcompiler-error" }, "BookCompiler stderr"),
              h("option", { value: "ollama" }, "Ollama"),
              h("option", { value: "hermes-dashboard" }, "Hermes Dashboard")),
            h("button", { className: "kh-btn", disabled: logBusy, onClick: function () { readLog(logName); } }, logBusy ? "读取中…" : "读取日志")),
          h("pre", { className: "kh-log" }, logText || "点击“读取日志”…"))));
  }
  function ReaderPage() {
    const [expanded, setExpanded] = useState(false);

    return h("div", { className: "kh-page kh-reader-page" },
      h("section", { className: "kh-hero kh-hero-compact" },
        h("div", null,
          h("span", { className: "kh-kicker" }, "BOOKCOMPILER WORKBENCH"),
          h("h1", null, "阅读工作台"),
          h("p", null, "完整的 BookCompiler 界面嵌在这里：导入书籍、编译、检索、跨书分析与 Obsidian 导出都在原界面完成。")
        ),
        h("div", { className: "kh-inline" },
          h("button", {
            className: "kh-btn",
            onClick: function () { setExpanded(!expanded); }
          }, expanded ? "收起嵌入窗口" : "展开嵌入窗口"),
          h("a", {
            className: "kh-btn kh-btn-primary",
            href: BOOKCOMPILER_URL,
            target: "_blank",
            rel: "noreferrer"
          }, "在新窗口打开")
        )
      ),

      expanded
        ? h("div", { className: "kh-iframe-wrap" },
            h("iframe", {
              className: "kh-iframe",
              src: BOOKCOMPILER_URL,
              title: "BookCompiler GUI",
              loading: "lazy"
            })
          )
        : h("div", { className: "kh-panel" },
            h("div", { className: "kh-callout" },
              h("strong", null, "为什么默认不直接铺满？"),
              h("span", null, "BookCompiler 是独立 Web 应用，嵌入 iframe 可能受浏览器安全策略影响。先点“展开嵌入窗口”试一次；如果白屏，用“在新窗口打开”即可，功能和数据完全一致。")
            ),
            h("div", { className: "kh-link-grid" },
              h("a", { className: "kh-link-card", href: BOOKCOMPILER_URL + "/#library", target: "_blank", rel: "noreferrer" },
                h("div", { className: "kh-link-title" }, "导入新书"),
                h("p", null, "把 PDF / EPUB / TXT 加入书库，按推荐流程编译。")),
              h("a", { className: "kh-link-card", href: BOOKCOMPILER_URL + "/#library", target: "_blank", rel: "noreferrer" },
                h("div", { className: "kh-link-title" }, "浏览书库"),
                h("p", null, "查看已读的书、框架、实体与跨书关系。")),
              h("a", { className: "kh-link-card", href: BOOKCOMPILER_URL + "/#analyze", target: "_blank", rel: "noreferrer" },
                h("div", { className: "kh-link-title" }, "书库问答"),
                h("p", null, "直接基于已编译知识提问，先验证书读得对不对。")),
              h("a", { className: "kh-link-card", href: "/chat" },
                h("div", { className: "kh-link-title" }, "去 Hermes 对话"),
                h("p", null, "让 Hermes 自动路由到书库能力，做跨学科分析。"))
            )
          ),

      h("p", { className: "kh-muted kh-small kh-center" },
        "提示：书库数据是同一份，无论在嵌入窗口、独立窗口还是 Hermes 对话里访问，都不会产生副本。")
    );
  }
  const GUIDE_STEPS = [
    ["1", "确认服务", "总览里 5 个服务全绿。没绿就去“服务”页点启动，再不行看日志。"],
    ["2", "导入与编译", "到“阅读工作台”导入 PDF/EPUB；编译时使用 Reader 模型，产出框架、claims、实体和 GraphRAG。"],
    ["3", "验证书读得对不对", "用书库问答抽 2-3 个问题，检查答案是否引用了正确的书与章节。"],
    ["4", "让 Hermes 学会路由", "在 Hermes 对话里问一个需要书库的问题；第一次会提示是否启用书库能力，选“用户指定 + 推荐”。"],
    ["5", "沉淀记忆", "重要结论让 Hermes 写入 Hindsight（bank: hermes）；读书产物默认进 bookcompiler bank。"],
    ["6", "人类编辑", "打开 Obsidian，直接改笔记、加批注；下一轮同步会保留你的手改内容。"],
    ["7", "复盘与进化", "每周看一次“记忆”和“书库”页：哪些书被调用、哪些答案不准、缺哪类知识，再补书或调模型。"]
  ];

  const GUIDE_ARCH = [
    ["Hermes Agent", "宿主 / 对话 / 技能 / MCP / 自动路由", "所有入口最终都回到 Hermes：它决定这次问题要不要调书库、要不要召回记忆。"],
    ["BookCompiler", "知识生产层", "把书编译成可检索、可引用的结构化知识：chunks、框架、claims、实体、跨书关系。"],
    ["Hindsight", "经验与偏好层", "记住跨会话的结论、纠正和偏好；不等于原文检索，负责“越用越懂你”。"],
    ["Obsidian", "人类可读可编辑层", "所有产出落成 Markdown，你能随时改；改完再被系统读回。"]
  ];

  const GUIDE_FAQ = [
    ["这是不是加强版 RAG？", "不完全是。RAG 只解决“找到相关段落”；这里多了编译后的框架/实体/关系、跨书对齐、可调用技能和 Hindsight 的跨会话经验。检索只是其中一层。"],
    ["书读完后存在哪？", "原文与 chunk 在 BookCompiler 的 SQLite；结构化知识在同一个库与 GraphRAG 库；人类可读副本在 Obsidian Vault。"],
    ["为什么有时不调用书库？", "Hermes 会先判断问题是否需要。你可以在对话里明确说“用书库回答”，或在设置里把书库能力设为默认推荐。"],
    ["模型怎么分工？", "读书/评审用大模型 API（质量优先）；Hindsight 抽取和日常记忆用 Ollama 本地模型（省钱、隐私）。模型页可一键切换。"],
    ["改了书库笔记会怎样？", "Obsidian 是双向层：你的手改会被保留并标记；系统不会静默覆盖。冲突时以你的版本为准，并在下次编译时提示。"],
    ["会不会把书上传云端？", "不会。书与数据库都在本机；只有调用云端模型时，发送的是当次需要的文本片段，不发整库。"]
  ];

  function GuidePage() {
    return h("div", { className: "kh-page kh-guide-page" },
      h("section", { className: "kh-hero kh-hero-compact" },
        h("div", null,
          h("span", { className: "kh-kicker" }, "HOW IT FITS TOGETHER"),
          h("h1", null, "四套系统，一个入口"),
          h("p", null, "不是把四个项目揉成一份代码，而是让 Hermes 当宿主，把书库、记忆和笔记接成一条可用的流水线。")
        ),
        h("a", { className: "kh-btn kh-btn-primary", href: MANUAL_URL, target: "_blank", rel: "noreferrer" }, "打开完整说明书")
      ),

      h("section", { className: "kh-arch-grid" },
        GUIDE_ARCH.map(function (row) {
          return h("article", { className: "kh-arch-card", key: row[0] },
            h("div", { className: "kh-arch-kind" }, row[1]),
            h("h3", null, row[0]),
            h("p", null, row[2]));
        })
      ),

      h("section", { className: "kh-panel" },
        h(SectionHead, { title: "每天怎么用", subtitle: "按这个顺序走，基本不会踩坑。" }),
        h("div", { className: "kh-steps" },
          GUIDE_STEPS.map(function (row) {
            return h("div", { className: "kh-step", key: row[0] },
              h("div", { className: "kh-step-no" }, row[0]),
              h("div", null,
                h("strong", null, row[1]),
                h("p", null, row[2])));
          })
        )
      ),

      h("section", { className: "kh-split kh-split-even" },
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "Hermes 怎么接书库", subtitle: "三种调用模式，第二次和第三次会先问你。" }),
          h("div", { className: "kh-note-list" },
            h("div", { className: "kh-note" },
              h("strong", null, "模式 1 · 自动匹配"),
              h("p", null, "你不指定书，Hermes 根据问题自己挑书与框架。")),
            h("div", { className: "kh-note" },
              h("strong", null, "模式 2 · 指定领域/方向"),
              h("p", null, "你说“从经济、政治、法律三个角度”，Hermes 先问：只用你指定的，还是加上它推荐的书？")),
            h("div", { className: "kh-note" },
              h("strong", null, "模式 3 · 指定具体书"),
              h("p", null, "你点名某本书，Hermes 仍会问是否叠加推荐能力，避免视野被单本书锁死。"))
          )
        ),
        h("div", { className: "kh-panel" },
          h(SectionHead, { title: "模型分工", subtitle: "贵的做难事，本地做常态。" }),
          h("div", { className: "kh-kv" },
            h("div", null, h("span", null, "读书 / 评审"), h("strong", null, "云端大模型（MiMo / DeepSeek 等）")),
            h("div", null, h("span", null, "Hermes 对话"), h("strong", null, "可切换云端或本地")),
            h("div", null, h("span", null, "Hindsight 抽取"), h("strong", null, "Ollama 本地模型")),
            h("div", null, h("span", null, "Embedding"), h("strong", null, "本地向量 + 关键词混合检索"))
          ),
          h("p", { className: "kh-muted kh-small" }, "模型页支持单目标热切换；改完下一轮任务生效，不需要重启整个系统。")
        )
      ),

      h("section", { className: "kh-panel" },
        h(SectionHead, { title: "数据存在哪", subtitle: "全部本地，可备份、可迁移。" }),
        h("div", { className: "kh-data-table" },
          h("div", { className: "kh-data-row" }, h("span", null, "书库数据库"), h("code", null, "bookcompiler/.bookcompiler/library.db")),
          h("div", { className: "kh-data-row" }, h("span", null, "GraphRAG 图库"), h("code", null, "bookcompiler/.bookcompiler/library.graph.db")),
          h("div", { className: "kh-data-row" }, h("span", null, "Hindsight 记忆"), h("code", null, "PostgreSQL @ 127.0.0.1:5432")),
          h("div", { className: "kh-data-row" }, h("span", null, "人类可读笔记"), h("code", null, "Documents/Obsidian Vault")),
          h("div", { className: "kh-data-row" }, h("span", null, "知识源书"), h("code", null, "D:/fanshu")),
          h("div", { className: "kh-data-row" }, h("span", null, "日志"), h("code", null, "knowledge-hub/logs")),
        )
      ),

      h("section", { className: "kh-panel" },
        h(SectionHead, { title: "常见问题", subtitle: "先看这里，再去翻日志。" }),
        h("div", { className: "kh-faq" },
          GUIDE_FAQ.map(function (row) {
            return h("details", { key: row[0] },
              h("summary", null, row[0]),
              h("p", null, row[1]));
          })
        )
      )
    );
  }
  const KH_TABS = [
    ["overview", "总览", "◫"],
    ["books", "书库", "▤"],
    ["memory", "记忆", "◈"],
    ["obsidian", "Obsidian", "◇"],
    ["models", "模型", "⌘"],
    ["services", "服务", "⚙"],
    ["reader", "阅读工作台", "▣"],
    ["guide", "指南", "?"]
  ];

  function initialTab() {
    let raw = String(window.location.hash || "").replace(/^#/, "");
    if (!raw) {
      try { raw = String(window.sessionStorage.getItem("kh-tab") || ""); } catch (e) { raw = ""; }
    }
    for (let i = 0; i < KH_TABS.length; i += 1) {
      if (KH_TABS[i][0] === raw) return raw;
    }
    return "overview";
  }

  function KnowledgeHub() {
    const tabState = useState(initialTab);
    const tab = tabState[0];
    const setTab = tabState[1];

    const dataState = useState(null);
    const data = dataState[0];
    const setData = dataState[1];

    const loadingState = useState(true);
    const loading = loadingState[0];
    const setLoading = loadingState[1];

    const errorState = useState("");
    const error = errorState[0];
    const setError = errorState[1];

    const reload = useCallback(function () {
      setLoading(true);
      setError("");
      api("/overview")
        .then(function (payload) { setData(payload); })
        .catch(function (e) { setError(errText(e)); })
        .finally(function () { setLoading(false); });
    }, []);

    useEffect(function () {
      reload();
      const timer = setInterval(reload, 30000);
      return function () { clearInterval(timer); };
    }, [reload]);

    function go(next) {
      setTab(next);
      try { window.sessionStorage.setItem("kh-tab", next); } catch (e) { /* ignore */ }
      try { window.history.replaceState(null, "", "#" + next); } catch (e) { /* ignore */ }
    }

    const services = asArray(data && data.services);
    const online = services.filter(function (s) { return s.running; }).length;
    const allOnline = services.length > 0 && online === services.length;

    let body = null;
    if (tab === "overview") {
      body = h(OverviewPage, { data: data, loading: loading, error: error, reload: reload, onTab: go });
    } else if (tab === "books") {
      body = h(BooksPage);
    } else if (tab === "memory") {
      body = h(MemoryPage);
    } else if (tab === "obsidian") {
      body = h(ObsidianPage);
    } else if (tab === "models") {
      body = h(ModelsPage, { onTab: go });
    } else if (tab === "services") {
      body = h(ServicesPage);
    } else if (tab === "reader") {
      body = h(ReaderPage);
    } else {
      body = h(GuidePage);
    }

    return h("div", { className: "kh-root" },
      h("header", { className: "kh-topbar" },
        h("div", { className: "kh-brand" },
          h("div", { className: "kh-logo" }, "K"),
          h("div", null,
            h("div", { className: "kh-brand-row" },
              h("h1", null, "Knowledge Hub"),
              h("span", { className: "kh-version" }, "v1.0")
            ),
            h("p", null, "读书 · 记忆 · 笔记 · 对话，一个入口")
          )
        ),
        h("div", { className: "kh-topbar-right" },
          h("div", { className: "kh-online" },
            h(StatusDot, { ok: allOnline }),
            h("span", null, online + " / " + (services.length || 5) + " 服务在线")
          ),
          h("a", { className: "kh-btn kh-btn-ghost kh-btn-small", href: "/chat" }, "对话"),
          h("a", { className: "kh-btn kh-btn-small", href: BOOKCOMPILER_URL, target: "_blank", rel: "noreferrer" }, "书库独立页"),
          h("a", { className: "kh-btn kh-btn-small", href: MANUAL_URL, target: "_blank", rel: "noreferrer" }, "说明书")
        )
      ),

      h("nav", { className: "kh-tabs", "aria-label": "Knowledge Hub sections" },
        KH_TABS.map(function (row) {
          return h("button", {
            key: row[0],
            className: "kh-tab" + (tab === row[0] ? " active" : ""),
            onClick: function () { go(row[0]); }
          }, h("span", { className: "kh-tab-icon" }, row[2]), h("span", null, row[1]));
        })
      ),

      h("main", { className: "kh-main" }, body),

      h("button", {
        className: "kh-refresh-fab",
        title: "刷新总览数据",
        "aria-label": "刷新",
        onClick: reload
      }, loading ? "…" : "↻")
    );
  }

  window.__HERMES_PLUGINS__.register("knowledge-hub", KnowledgeHub);
})();
