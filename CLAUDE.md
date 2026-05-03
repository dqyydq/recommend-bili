- - # 收藏夹管家 Agent — CLAUDE.md

    ## 项目概述

    自动整理 B站收藏夹的 AI Agent 项目。用户输入 B站 UID，系统抓取收藏内容，通过 Embedding + KMeans 聚类，再由 LLM 命名分类，最终在网页展示结果。

    后续将升级为 RAG + 多Agent + Tool Calling 完整架构。

    ## 技术栈

    - **后端**：Python 3.11+，FastAPI，Uvicorn
    - **数据库**：PostgreSQL（存储用户收藏元数据和分类结果）
    - **AI**：DeepSeek API（deepseek-chat，兼容 OpenAI SDK 调用方式）
    - **向量**：Ollama 本地 Embedding（`nomic-embed-text` 模型），通过 HTTP 调用，无需 torch
    - **前端**：Node.js 18 + Vite，组件化开发
    - **HTTP 客户端**：httpx（异步）

    ## 项目结构

    ```
    bookmark-agent/
    ├── CLAUDE.md
    ├── README.md
    ├── backend/
    │   ├── requirements.txt
    │   ├── main.py          # FastAPI 入口，路由定义，B站 API 抓取
    │   └── classifier.py    # 分类器：本地 Embedding → KMeans → LLM 命名
    └── frontend/
        ├── package.json     # Node.js 18，Vite
        ├── index.html
        └── src/
            ├── main.js
            ├── api.js       # 后端接口调用封装
            └── components/  # UI 组件
    ```

    ## 常用命令

    ```bash
    # 后端：安装依赖
    pip install -r backend/requirements.txt
    
    # 后端：首次运行时下载本地向量模型（自动，约 120MB）
    # 模型缓存在 ~/.cache/huggingface/，后续启动无需重新下载
    
    # 后端：启动开发服务器
    cd backend && uvicorn main:app --reload --port 8000
    
    # 前端：安装依赖（需要 Node.js 18）
    cd frontend && npm install
    
    # 前端：启动开发服务器
    cd frontend && npm run dev
    
    # 查看后端 API 文档
    open http://localhost:8000/docs
    ```

    ## 数据库

    使用 PostgreSQL，通过 Docker 端口映射到本地，连接字符串通过环境变量注入：

    ```bash
    export DATABASE_URL=postgresql://user:password@localhost:5432/bookmark_agent
    ```

    Docker 启动方式（如容器未运行）：

    ```bash
    docker run -d \
      --name bookmark-postgres \
      -e POSTGRES_USER=user \
      -e POSTGRES_PASSWORD=password \
      -e POSTGRES_DB=bookmark_agent \
      -p 5432:5432 \
      postgres:15
    ```

    **注意**：后端直接跑在宿主机，连接地址固定用 `localhost:5432`。如果后端也容器化，需改用 Docker 网络互通，MVP 阶段不做这个。

    主要数据表（MVP 阶段）：

    - `favorites`：收藏条目（bvid, title, intro, upper, cover, link, source_folder）
    - `categories`：分类结果（name, item_count, created_at）
    - `category_items`：收藏与分类的关联关系

    ## 环境变量

    ```bash
    DEEPSEEK_API_KEY=sk-...          # DeepSeek API Key
    DATABASE_URL=postgresql://...    # PostgreSQL 连接字符串
    PORT=8000                        # 服务端口，默认 8000
    ```

    DeepSeek 使用 OpenAI 兼容接口，base_url 固定为 `https://api.deepseek.com/anthropic`，模型名为 `deepseek-v4-flash[1m]`。

    ## 核心模块说明

    ### main.py

    - `fetch_fav_folders(uid)` — 调用 B站 API 获取收藏夹列表
    - `fetch_fav_items(folder_id)` — 获取收藏夹内视频列表，最多 40 条
    - `POST /api/analyze` — 主接口：抓取 + 分类 + 返回结果
    - `GET /api/demo` — 返回演示数据，不需要真实 UID

    ### classifier.py

    - `get_embeddings(texts)` — 调用本地 Ollama HTTP 接口（`http://localhost:11434/api/embeddings`），模型 `nomic-embed-text`，无需 torch / sentence-transformers
    - `cluster_items(embeddings, n_clusters)` — KMeans 聚类
    - `name_cluster(titles)` — 调用 DeepSeek 给每簇起人话说的名字
    - `classify_favorites(items, n_clusters)` — 完整分类流程

    ## 开发规范

    **代码风格**

    - 所有异步函数用 `async/await`，不用 `threading`
    - 类型注解必须写，使用 Python 3.10+ 的 `list[dict]` 写法，不用 `List[Dict]`
    - 错误处理统一返回 `{"error": "描述"}` 格式，不抛裸异常给前端

    **API 设计**

    - 路由统一前缀 `/api/`
    - 请求体用 Pydantic BaseModel 定义，不用裸 dict
    - API Key 从请求体传入（MVP 阶段），不存服务器

    **数据库**

    - 使用 asyncpg 做异步 PostgreSQL 连接
    - SQL 语句写在函数里，不用 ORM（保持简单）
    - 每个数据库操作单独封装成函数

    **前端**

    - Node.js 版本固定为 18，不要用 20+ 的语法特性
    - 使用 Vite 作为构建工具，不用 Webpack / CRA
    - 组件放在 `src/components/`，接口调用统一封装在 `src/api.js`
    - 不引入重型 UI 框架（如 Element Plus、Ant Design），保持轻量

    ## 升级路线（后续迭代参考）

    ```
    MVP（当前）
      ↓
    阶段二：接入 PostgreSQL，持久化收藏数据
      ↓
    阶段三：ChromaDB 替换 TF-IDF，支持语义搜索
      ↓
    阶段四：Tool Calling — search_favorites / find_duplicates / add_favorite
      ↓
    阶段五：多 Agent — 对话Agent / 检索Agent / 分类Agent / 推送Agent
    ```

    ## 注意事项

    - B站 API 无需登录即可访问公开收藏夹，但有频率限制，抓取时加 `await asyncio.sleep(0.3)` 间隔
    - 抖音无公开 API，MVP 阶段不做，后续用浏览器插件方案
    - DeepSeek API Key 不能打印到日志，不能存数据库，通过环境变量注入
    - Ollama 需要提前在本地启动，默认监听 `http://localhost:11434`，首次使用需拉取模型：`ollama pull nomic-embed-text`
    - Embedding 通过 `httpx` 直接调用 Ollama HTTP 接口，不依赖任何额外 Python 包
    - KMeans 的 `n_clusters` 不能超过 item 数量，`classifier.py` 里已有保护
    - DeepSeek 调用方式与 OpenAI SDK 完全兼容，直接用 `openai` 包，切换 `base_url` 即可
