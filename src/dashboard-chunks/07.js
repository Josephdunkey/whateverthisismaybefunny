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