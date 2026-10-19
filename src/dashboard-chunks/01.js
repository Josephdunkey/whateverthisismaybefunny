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