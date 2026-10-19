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