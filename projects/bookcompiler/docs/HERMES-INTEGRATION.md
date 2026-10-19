# 对接 Hermes Agent

## 1. 为什么选 Hermes

Hermes Agent（Nous Research，MIT）本身就有：

- 跨会话记忆与技能（skills）系统；
- 自进化/技能改进循环；
- MCP 客户端；
- CLI、TUI、网关和多平台入口。

BookCompiler 不应该复制这些能力。正确的接缝是 **MCP 工具 + 一个薄技能**：

```text
Hermes Agent
  ├─ 自进化 / 会话记忆 / 技能管理   （Hermes 负责）
  ├─ book-library 技能              （路由与引用纪律）
  └─ MCP: bookcompiler              （书本证据、实体、编译、受控进化）
        └─ SQLite library.db
```

这样书库仍然是一个通用能力：Claude Desktop、Codex、其他 MCP 宿主也能接，
不绑死在 Hermes 上。

## 2. 安装位置

本机按用户要求部署在：

```text
D:\hermes agent\              # HERMES_HOME
D:\hermes agent\hermes-agent\ # 源码 checkout (v0.22.2, commit d923a5eb48)
D:\hermes agent\bin\hermes.exe # launcher
D:\hermes agent\config.yaml   # Hermes 配置
D:\hermes agent\skills\       # 技能目录
```

用户级环境变量已设置为 `HERMES_HOME=D:\hermes agent`。如果 launcher 找不到
安装目录，先运行 `hermes pm repair`，再运行 `hermes doctor` 检查。

安装命令（非交互、跳过浏览器/computer-use 重依赖）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File 'D:\hermes agent\install.ps1' `
  -HermesHome 'D:\hermes agent' `
  -InstallDir 'D:\hermes agent\hermes-agent' `
  -NonInteractive -SkipBrowser -SkipComputerUse
```

## 3. MCP 配置

在 `D:\hermes agent\config.yaml` 中加入：

```yaml
mcp_servers:
  bookcompiler:
    command: "D:\\anaconda\\python.exe"
    args:
      - "-m"
      - "bookcompiler.cli"
      - "--db"
      - "C:\\Users\\mybea\\projects\\bookcompiler\\.bookcompiler\\library.db"
      - "mcp"
    env:
      PYTHONIOENCODING: "utf-8"
      PYTHONPATH: "C:\\Users\\mybea\\projects\\bookcompiler\\src"
```

`bookcompiler mcp` 是 stdio MCP server，不占端口。实测：

```text
hermes mcp test bookcompiler
  ✓ Connected (1318ms)
  ✓ Tools discovered: 13
```

不要给 `book-library` 技能加 `requires_toolsets: [bookcompiler]`：
`bookcompiler` 是 MCP server 名，不是 Hermes 的 toolset 名；这样写会让技能
找不到工具。MCP 工具会由 Hermes 自动暴露给会话。

它实现了：

```text
initialize / ping / tools/list / tools/call
resources/list / prompts/list
```

工具清单：

| 工具 | 作用 |
|---|---|
| `book_library` | 列出已入库/已深度编译的书，嵌入与实体统计 |
| `book_plan` | 三种选书模式 + 推荐理由 + 覆盖缺口 |
| `book_recall` | 混合检索，返回逐字引用、章节、页码、分数拆解 |
| `book_analyze` | 生成多镜头 AnalysisPacket 与 memo 脚手架 |
| `book_ingest` | 只接收本地文件，不自动下载 |
| `book_export_text` | 导出章节供 agent 精读 |
| `book_compile` | 应用 agent 写的编译补丁并校验引用 |
| `book_validate` | 校验书卡/框架/分析 |
| `book_feedback` | 结构化反馈，进入受控进化 |
| `book_memory` | Hindsight 式教训召回（不存原文） |
| `book_entities` | 跨书实体、别名、提及、共现 |
| `book_evolution` | 提案/回放/晋升/回滚 |
| `book_status` | 覆盖、嵌入、实体、检索诊断 |

## 4. 技能安装

把仓库里的 `skills/book-library/` 复制到：

```text
D:\hermes agent\skills\book-library\SKILL.md
```

这个技能不是“一本书一个技能”，而是整个书库的**路由器**：

- 用户给新闻/事件时自动调用 `book_library` / `book_plan`；
- 模式 `direction` / `books` 必须先问用户选 `specified`、
  `specified+recommended` 还是 `recommended`；
- 所有事实必须带逐字引用；
- 只有 `learned=true` 的书才算“读过”。

## 5. 模型配置（本机已验证）

本机用 DeepSeek 的 OpenAI 兼容端点跑通。`D:\hermes agent\config.yaml` 的关键项：

```yaml
model:
  provider: "custom"
  default: "deepseek-v4-pro"
  base_url: "https://api.deepseek.com/v1"
  key_env: "DEEPSEEK_API_KEY"

agent:
  reasoning_effort: "medium"
  reasoning_overrides:
    deepseek-v4-pro: "low"
```

`DEEPSEEK_API_KEY` 写在 `D:\hermes agent\.env`，不要把 key 提交到仓库或贴到回答里。

为什么是 `low`：本机实测 `medium` 时，DeepSeek 的推理 token 可能把输出预算吃掉，
Hermes 会报“model's reply was cut off before it finished”。把该模型覆盖为 `low`
后，`hermes chat` 不需要额外参数也能稳定给出最终回答。

## 6. 自进化的边界

Hermes 自己的技能自进化与 BookCompiler 的书库进化是两层，不要混为一谈：

- Hermes 可以改进“怎么调用书库工具”的技能文本；
- BookCompiler 只允许把反馈变成**有界配置补丁**：
  检索权重、书/框架偏好加成；
- 晋升必须有结构回放报告；应用前写快照，失败自动恢复；
- 不允许自动改写 BookCard、FrameworkCard、引用或代码。

## 7. 验证

MCP 握手（不启动 Hermes 也能测）：

```powershell
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' | D:\anaconda\python.exe -m bookcompiler.cli --db C:\Users\mybea\projects\bookcompiler\.bookcompiler\library.db mcp
```

Hermes 侧：

```powershell
cd 'D:\hermes agent\hermes-agent'
hermes mcp
hermes chat
```

然后问：

```text
今天央行降准，同时地方政府要求银行支持债务化解。结合你读过的书分析风险是否从财政转移到银行体系。
```

预期：Hermes 自动调用 `book_library` -> `book_plan` -> `book_analyze`，并在回答中
列出实际引用的书、章节、页码和逐字引用。

本机已经实测通过。一个更短的可复现探针：

```powershell
$env:HERMES_HOME='D:\hermes agent'
[IO.File]::WriteAllText('D:\hermes agent\_probe.txt',
  '用你读过的书回答：降准是否必然导致银行信贷扩张？请给出一句原文引用和页码。只引用你真正学过的书。',
  [Text.UTF8Encoding]::new($false))
& 'D:\hermes agent\bin\hermes.exe' chat --query-file 'D:\hermes agent\_probe.txt' --oneshot -Q
```

实测回答引用了《中央银行与货币供给》第 277 页和第 298 页的逐字原文，并明确说
“降准不是必然导致信贷扩张”。PowerShell 可能把 Hermes 的 stderr 包装成
`NativeCommandError`，导致命令 exit code 为 1；只要标准输出里有完整回答，就说明
功能正常，不是书库调用失败。

## 8. 日常使用

```powershell
$env:HERMES_HOME='D:\hermes agent'
& 'D:\hermes agent\bin\hermes.exe' chat
```

如果 `D:\hermes agent\bin` 已在 PATH 中，直接 `hermes chat` 即可。技能描述包含
中文触发场景（“用读过的书分析新闻/政策/市场事件”等），正常情况下不需要显式
`-s book-library`。

## 9. 已知限制

- 这是 MCP 集成，不是 Hermes 的 native plugin；Hermes 升级不会破坏 MCP 协议，
  但工具 schema 变更需要同步技能。
- Hermes 的模型质量、工具调用能力和会话记忆仍由 Hermes 自己负责。
- 当前只有 4 本书深度编译；其余 8 本是 `ingested`，不能宣称“已学会”。
- 端到端验证是 one-shot CLI 探针，不是长期生产压测；并发、长会话压缩和网关入口尚未压测。
- Hermes 自己的技能自进化和 BookCompiler 的有界进化是两层，不要混为一谈。
- MCP server 以本地进程运行，书库文件权限等同当前 Windows 用户。
