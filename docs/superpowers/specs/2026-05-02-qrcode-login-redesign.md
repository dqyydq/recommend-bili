# 收藏夹管家 — 扫码登录 + 功能模块重设计

## 概述

将项目从"输入 UID + API Key"的 MVP 模式，改为"用户扫码登录 B站 → 进入功能界面 → 各功能模块"的交互方式。

## 架构方案

**方案 A：纯内存 Session**

- 后端用两个全局 dict 管理会话：`qrcode_pool` 和 `sessions`
- 不依赖数据库，所有数据实时调 B站 API
- 后端重启所有用户掉线，MVP 阶段可接受

## 数据流

```
用户打开页面
  ↓
前端检查 Cookie 里的 session_id
  ↓
无 session → 展示登录页 → 后端生成二维码 → 前端展示二维码图片
  ↓
用户用 B站 App 扫码并确认登录
  ↓
后端轮询状态拿到 B站 Cookie → 创建 session → 返回 Set-Cookie
  ↓
前端带 session_id 请求 /api/me
  ↓
未绑定 Key → 展示绑定页
已绑定   → 进入主控制台（默认展示"整理收藏夹"）
```

## Session 数据结构

```python
sessions: dict[str, dict] = {
    "session_id": {
        "bili_cookies": {"SESSDATA": "...", "bili_jct": "..."},
        "deepseek_key": "sk-...",
        "uid": "108031069",
        "nickname": "用户名",
        "avatar": "https://...",
        "folders": [...],  # 登录时缓存的收藏夹列表
        "created_at": timestamp,
    }
}

qrcode_pool: dict[str, dict] = {
    "qrcode_key": {
        "status": "pending",  # pending / scanned / confirmed / expired
        "session_id": None,
    }
}
```

## 后端接口

### 登录与 Session

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/qrcode` | 生成二维码，返回 `{qrcode_key, url}` |
| GET  | `/api/auth/qrcode/{key}/poll` | 轮询状态，返回 `{status, session_id?}` |
| GET  | `/api/me` | 获取当前用户信息（含 `has_key`、昵称、头像） |
| POST | `/api/settings/key` | 绑定 DeepSeek API Key（body: `{api_key}`） |

### B站数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/folders` | 获取收藏夹列表（带 session Cookie 调 B站） |
| GET  | `/api/favorites?folder_id={id}` | 获取收藏夹内容（每文件夹最多 5 条测试） |
| POST | `/api/analyze` | 整理收藏夹（Body: `{folder_id?, n_clusters?}`） |
| GET  | `/api/search/favorites?q={keyword}` | 在已收藏内容中搜索 |
| GET  | `/api/search/all?q={keyword}` | B站全站搜索 |
| POST | `/api/favorites/add` | 加入收藏（body: `{bvid, folder_id?}`） |

### Session 中间件

- 每个请求读 Cookie 里的 `session_id`
- 查 `sessions` dict，无 session 返回 401
- 有 session 的 B站 API 请求自动从 session 取 Cookie 拼到请求头

## B站二维码登录流程

1. 后端调 `passport.bilibili.com/x/passport-login/web/qrcode/generate` 获取 `url` + `qrcode_key`
2. 前端渲染二维码图片
3. 前端每秒轮询 `GET /api/auth/qrcode/{key}/poll`
4. 后端调 B站 `.../qrcode/poll?qrcode_key={key}`
   - `code: 86101` → `{"status": "pending"}`
   - `code: 86090` → `{"status": "scanned"}`
   - `code: 0`     → 提取 B站 Cookie（SESSDATA, bili_jct 等），创建 session，返回 `{"status": "confirmed", "session_id": "..."}`
   - `code: 86038` → `{"status": "expired"}`
5. 创建 session 后同步获取用户基本信息（昵称、头像），存入 session

## 前端页面结构

视觉风格：干净现代，圆角卡片，B站粉 `#FB7299` 做强调色，背景浅灰 `#f5f5f5`。

### 页面 1：登录页
- 全屏居中，白色圆角卡片，400px 宽
- 二维码 200×200，下方动态状态文字
- 过期自动刷新二维码

### 页面 2：绑定 Key 页
- 居中卡片，输入框 + 确认按钮
- 首次登录后出现，绑定后进入主控制台

### 页面 3：主控制台
- 左侧边栏（220px）："整理收藏夹" / "寻找视频"
- 顶部 Header：标题 + 用户头像/昵称 + 退出按钮
- 右侧主内容区根据菜单切换

## 功能模块

### 整理收藏夹
- 收藏夹下拉框（默认全部）、分类数量输入
- 点击"开始整理"触发 `/api/analyze`
- 结果按分类卡片展示，每条视频可点击跳转 B站

### 寻找视频
- 子 Tab：搜索已收藏 / 搜索全站
- 搜索已收藏：文本匹配标题和简介，结果标注所属收藏夹
- 搜索全站：调 B站搜索 API，每条有"加入收藏"按钮，弹窗选目标收藏夹

## 技术栈

- 后端：Python 3.11+, FastAPI, httpx, scikit-learn, openai
- AI：Ollama (nomic-embed-text) + DeepSeek (deepseek-v4-flash[1m])
- 前端：Node.js 18, Vite, 原生 JS
- 无数据库依赖（纯内存 session）

## 当前状态限制

- `fetch_fav_items` 上限临时设为 5 条（调试中）
- 单条 embedding 文本截断 200 字
- B站公开 API 可能无法覆盖只使用默认收藏夹的用户
