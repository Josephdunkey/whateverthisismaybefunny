# Knowledge Hub · Project Map

这个项目不是一个把所有代码复制到一起的 monorepo，而是一个**统一控制面**：
四个独立系统各保留自己的进程、数据库和升级路径，由 Knowledge Hub 在一个 GUI 里编排。

| 层 | 路径 | 角色 |
|---|---|---|
| 控制面 | `D:\knowledge-hub` | 启动器、配置、日志、教程、前端源码分块 |
| 宿主 | `D:\hermes agent` | Chat、Skills、MCP、自动路由、Dashboard 插件宿主 |
| 知识层 | `C:\Users\mybea\projects\bookcompiler` | 书 → chunks → 框架 / claims / 实体 / GraphRAG |
| 记忆层 | `D:\hindsight` | 偏好、纠错、跨会话经验；PostgreSQL + pgvector |
| 人类层 | `C:\Users\mybea\Documents\Obsidian Vault` | 可读、可改、可回流的 Markdown |
| 书源 | `D:\fanshu` | 原始 PDF / EPUB / TXT |

## 数据流

```text
D:\fanshu
   │ 导入 + 编译
   ▼
BookCompiler（SQLite / GraphRAG）
   │ 结构化知识 + 引用
   ├──────────────► Hermes Agent（对话 / 路由 / 分析）
   │                        │
   │                        │ 经验、偏好、纠错
   │                        ▼
   │                   Hindsight（PostgreSQL）
   │                        │
   └──────────────► Obsidian Vault ◄──────────────┘
                           │
                           ▼
                    Knowledge Hub GUI
```

## 入口

- 统一控制台：`http://127.0.0.1:9119/knowledge-hub`
- 一键启动：`D:\knowledge-hub\start-knowledge-hub.bat`
- 开始菜单快捷方式：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Knowledge Hub.lnk`
- GitHub 仓库：https://github.com/Josephdunkey/whateverthisismaybefunny

## 前端源码

- 分块源码：`D:\knowledge-hub\src\dashboard-chunks\01.js` … `10.js`
- 合并命令：`powershell -File D:\knowledge-hub\tools\build-dashboard.ps1`
- 产物：`D:\hermes agent\plugins\knowledge-hub\dashboard\dist\index.js`
- 样式：`D:\hermes agent\plugins\knowledge-hub\dashboard\dist\style.css`

## 后端插件

- 入口：`D:\hermes agent\plugins\knowledge-hub\dashboard\plugin_api.py`
- 清单：`D:\hermes agent\plugins\knowledge-hub\dashboard\manifest.json`
- 启用配置：`D:\hermes agent\config.yaml` 的 `plugins.enabled`

## 设计边界

- 不复制 Hermes / BookCompiler / Hindsight 的源码。
- 不改 Hermes React 源码；只使用官方 dashboard plugin 机制。
- 不把书全文塞进 prompt；检索与引用仍由 BookCompiler 负责。
- 不静默覆盖 Obsidian 手改内容；同步有保护规则。