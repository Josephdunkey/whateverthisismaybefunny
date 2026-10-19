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