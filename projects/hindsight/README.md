# Hindsight 本地记忆服务

这是 Hindsight 在 `D:\hindsight` 的本地部署中，与 BookCompiler / Hermes 对接的自定义脚本快照。

## 文件

| 文件 | 作用 |
|---|---|
| `run_server.py` | 启动 Hindsight API，自动加载同目录 `.env`，并强制 UTF-8 控制台输出 |
| `smoke_test.py` | 最小连通性测试 |
| `list_docs.py` / `get_doc.py` | 查看和读取 bank 中的文档 |
| `retain_hermes.py` | 把 Hermes 的经验写入 Hindsight |
| `delete_doc.py` / `list_hermes.py` | 维护脚本 |

## 启动

```powershell
cd D:\hindsight
.\.venv\Scripts\python.exe run_server.py
```

服务默认监听 `http://127.0.0.1:8888`，健康检查：

```text
http://127.0.0.1:8888/health
```

## 环境变量

把 `.env.example` 复制为 `.env`，按本机情况填写。最关键的是：

```text
HINDSIGHT_API_DATABASE_URL=postgresql://user:password@127.0.0.1:5432/hindsight
```

默认使用 Ollama 做记忆抽取：

```text
HINDSIGHT_API_LLM_PROVIDER=ollama
HINDSIGHT_API_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M
HINDSIGHT_API_LLM_BASE_URL=http://127.0.0.1:11434/v1
```

## 说明

Hindsight 本体通过 pip / uv 安装，不在这个目录里重复提交；这里只保存部署脚本、集成脚本和配置样例。数据库是 PostgreSQL / pg0，默认端口 `5432`。