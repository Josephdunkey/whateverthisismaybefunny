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