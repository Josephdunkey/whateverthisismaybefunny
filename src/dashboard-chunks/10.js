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