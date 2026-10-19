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