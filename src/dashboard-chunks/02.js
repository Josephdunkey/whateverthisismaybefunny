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