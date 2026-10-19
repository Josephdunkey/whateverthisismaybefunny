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