# Favorite Agent

Favorite Agent 是一个本地优先、可自行部署的 B站收藏知识助手。它把收藏同步到 PostgreSQL，用 Chroma 做可重建的向量索引，并通过可审计 Harness 完成连续对话、智能检索、主题地图、学习项目、时间感知记忆和安全清理。

它不是自动改动收藏夹的黑盒：读取、分析和草稿可以自动运行；删除、移动等 B站操作必须由用户确认，并在执行前再次验证。

## 核心能力

- PostgreSQL 全量/增量同步，页面不重复抓取全部收藏。
- Chroma + PostgreSQL 混合检索，带引用、重排解释和连续对话。
- 语义、情景、程序三类记忆；推断兴趣按 90 天半衰期降权。
- `active / cooling / dormant / historical` 兴趣状态，休眠必须由用户明确确认。
- 持久化主题地图、失效视频四态扫描和逐项执行记录。
- 学习项目保存检索证据、任务、对话、反馈和周回顾草稿。
- OpenAI-compatible 模型接口；Embedding 支持 `fastembed / openai / hashing`，不依赖 Ollama。
- 无 B站账号和 API Key 的演示模式。

## 本地启动（Windows + uv）

要求：Python 3.11、Node.js 18、uv、Docker Desktop。

```powershell
Copy-Item .env.example .env
# 编辑 .env，至少设置 POSTGRES_PASSWORD 和 APP_ENCRYPTION_KEY

uv venv --python 3.11
.venv\Scripts\activate
uv pip install -r backend\requirements.txt

Set-Location frontend
npm install
Set-Location ..

powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

打开 `http://127.0.0.1:3000`。后端文档位于 `http://127.0.0.1:8000/docs`，健康检查位于 `http://127.0.0.1:8000/api/health`。

停止项目：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1
```

启动脚本只管理本项目记录的进程和 Compose 中的 `bookmark-postgres`，不会终止未知进程。

## Docker 完整启动

```powershell
Copy-Item .env.example .env
docker compose --profile full up --build
```

打开 `http://127.0.0.1:8000`。容器镜像使用 uv 安装 Python 依赖，并在构建阶段生成前端静态文件。

## 模型配置

登录后在“设置”中填写：

- API Key
- 模型名
- OpenAI-compatible Base URL

默认 Base URL 为 `https://api.deepseek.com`。没有模型 Key 时，检索、主题地图、学习任务和 Harness 仍会使用确定性降级结果；模型只负责更自然的规划、命名和总结。

Embedding 默认使用本地 `fastembed`。如果模型下载失败会自动降级到 `hashing`。切换 Provider 或模型后，在应用中重建索引即可；旧 Chroma 索引不是业务真相源。

## 演示模式

在 `.env` 设置：

```dotenv
DEMO_MODE=true
```

登录页会出现“体验演示模式”。演示数据写入独立 UID，不需要 B站账号或模型 Key，且不会执行远程修改。

## 数据与隐私

- PostgreSQL 是业务真相源；Chroma 可随时重建。
- B站 Cookie 与模型 Key 仅在配置 `APP_ENCRYPTION_KEY` 后加密持久化。
- “设置”支持导出用户数据和清空 Agent 长期记忆。
- 清空记忆不会删除收藏；清理收藏会二次确认且只处理确定失效项。

## 测试

```powershell
.venv\Scripts\activate
python -m unittest discover -s backend -p "test_*.py"

Set-Location frontend
npm test
npm run build
```

## 架构与扩展

- [Harness 架构](docs/architecture.md)
- [Agent Skill 示例](docs/agent-skill-example.md)
- [贡献指南](CONTRIBUTING.md)
- [产品与记忆设计](docs/superpowers/specs/2026-07-13-personal-video-harness-design.md)

## 安全边界

社区 Skill 默认只读。项目不加载不受信任的动态 Python 代码，不提供自由运行多 Agent 或无需确认的危险自动化。主动调度只创建本地建议和草稿。
