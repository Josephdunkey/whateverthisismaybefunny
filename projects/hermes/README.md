# Hermes Agent 集成

Hermes 的安装目录是 `D:\hermes agent`。这个目录保存的是**自定义集成部分**，不是 Hermes 本体。

## 包含内容

| 路径 | 作用 |
|---|---|
| `config.example.yaml` | 脱敏后的关键配置：插件、模型、MCP |
| `start-hermes.bat` | 启动 Hermes Chat |
| `switch-models.bat` | 调用 BookCompiler 的模型切换脚本 |
| `skills/book-library/SKILL.md` | 把已读过的书当成可调用专家能力 |
| `skills/book-learning-loop/SKILL.md` | 读书 → 验证 → 评分 → 进化的闭环 |

## 安装统一 GUI

仓库根目录的 `hermes-plugin/` 就是 Knowledge Hub Dashboard 插件。部署：

```powershell
powershell -File D:\knowledge-hub\tools\deploy-plugin.ps1
```

然后在 `D:\hermes agent\config.yaml` 中启用：

```yaml
plugins:
  enabled:
    - knowledge-hub
```

重启 Hermes Dashboard，访问：

```text
http://127.0.0.1:9119/knowledge-hub
```

## 安装技能

把 `skills/` 下的两个目录复制到：

```text
D:\hermes agent\skills\
```

Darwin Skill 本体较大，且来自上游项目，未复制进本仓库；本机已安装在：

```text
D:\hermes agent\skills\darwin-skill
```

## 安全边界

不要提交以下内容：

- `D:\hermes agent\.env`
- `D:\hermes agent\auth.json`
- `D:\hermes agent\state.db`
- `sessions/`、`logs/`、`cache/`、`installs/`