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