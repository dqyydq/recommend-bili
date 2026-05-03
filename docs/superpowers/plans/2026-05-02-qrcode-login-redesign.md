# 扫码登录 + 功能模块 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构项目为扫码登录架构，新增收藏夹整理和寻找视频两个功能模块。

**Architecture:** 后端纯内存 session（qrcode_pool + sessions 两个 dict），FastAPI session 中间件从 Cookie 取 session_id；前端三视图路由（登录/绑定Key/主控制台），侧边栏 + 主内容区布局。B站 API 调用统一带 session Cookie。

**Tech Stack:** Python 3.11+, FastAPI, httpx, scikit-learn, openai, qrcode; Node.js 18, Vite, 原生 JS

---

## 文件结构

```
backend/
├── auth.py          # [NEW] Session管理、二维码登录、中间件
├── bili.py          # [NEW] B站 API 封装（带Cookie）
├── main.py          # [REWRITE] FastAPI路由，session保护
├── classifier.py    # [KEEP] 分类器，不改
└── requirements.txt # [MODIFY] 加 qrcode

frontend/
├── index.html       # [MODIFY] 加 CSS 引用
└── src/
    ├── main.js      # [REWRITE] App路由入口
    ├── api.js       # [REWRITE] 所有API函数
    ├── styles.css   # [NEW] 全局样式
    ├── login-page.js   # [NEW] 登录页
    ├── bind-page.js    # [NEW] 绑定Key页
    ├── console-page.js # [NEW] 主控制台布局
    ├── classify-module.js # [NEW] 整理收藏夹模块
    └── search-module.js   # [NEW] 寻找视频模块
```

---

### Task 1: 创建 backend/bili.py（B站 API 封装）

**Files:**
- Create: `backend/bili.py`

- [ ] **Step 1: 创建完整的 bili.py**

```python
import asyncio
import httpx

BILI_API = "https://api.bilibili.com"
BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://space.bilibili.com/",
    "Cookie": "buvid3=3787611E-2E66-0B20-D062-B6ACF0A5987B22749infoc",
}


def _headers(cookies: dict[str, str] | None = None) -> dict[str, str]:
    h = dict(BILI_HEADERS)
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        h["Cookie"] = h["Cookie"] + ";" + cookie_str
    return h


async def fetch_fav_folders(uid: str, cookies: dict[str, str] | None = None) -> list[dict]:
    async with httpx.AsyncClient(headers=_headers(cookies)) as client:
        url = f"{BILI_API}/x/v3/fav/folder/created/list-all"
        params = {"up_mid": uid}
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            folders = (data.get("data") or {}).get("list", [])
            if folders:
                return folders

        url2 = f"{BILI_API}/x/v3/fav/folder/list"
        params2 = {"up_mid": uid, "pn": 1, "ps": 20}
        resp2 = await client.get(url2, params=params2, timeout=30)
        resp2.raise_for_status()
        data2 = resp2.json()
        if data2.get("code") == 0:
            return (data2.get("data") or {}).get("list", [])
        return []


async def fetch_fav_items(folder_id: int, cookies: dict[str, str] | None = None) -> list[dict]:
    items: list[dict] = []
    page = 1
    async with httpx.AsyncClient(headers=_headers(cookies)) as client:
        while len(items) < 5:
            url = f"{BILI_API}/x/v3/fav/resource/list"
            params = {
                "fid": folder_id,
                "pn": page,
                "ps": 20,
                "platform": "web",
            }
            resp = await client.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                break
            medias = (data.get("data") or {}).get("medias", []) or []
            if not medias:
                break
            for media in medias:
                if len(items) >= 5:
                    break
                items.append({
                    "bvid": media.get("bvid", ""),
                    "title": media.get("title", ""),
                    "intro": media.get("intro", ""),
                    "upper": (media.get("upper") or {}).get("name", ""),
                    "cover": media.get("cover", ""),
                    "link": f"https://www.bilibili.com/video/{media.get('bvid', '')}",
                    "source_folder": str(folder_id),
                })
            if len(medias) < 20:
                break
            page += 1
            await asyncio.sleep(0.3)
    return items[:40]


async def search_all(keyword: str, page: int = 1) -> list[dict]:
    """B站全站搜索"""
    async with httpx.AsyncClient(headers=BILI_HEADERS) as client:
        url = f"{BILI_API}/x/web-interface/wbi/search/type"
        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "page_size": 20,
        }
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return []
        results = (data.get("data") or {}).get("result", []) or []
        return [
            {
                "bvid": r.get("bvid", ""),
                "title": r.get("title", "").replace('<em class="keyword">', "").replace("</em>", ""),
                "intro": r.get("description", ""),
                "upper": r.get("author", ""),
                "cover": r.get("pic", ""),
                "link": f"https://www.bilibili.com/video/{r.get('bvid', '')}",
            }
            for r in results
        ]


async def add_favorite(bvid: str, folder_id: int | None, cookies: dict[str, str]) -> dict:
    """加入收藏夹"""
    async with httpx.AsyncClient(headers=_headers(cookies)) as client:
        url = f"{BILI_API}/x/v3/fav/resource/deal"
        payload = {
            "rid": bvid,
            "type": "2",
            "add_media_ids": str(folder_id) if folder_id else "",
            "del_media_ids": "",
            "csrf": cookies.get("bili_jct", ""),
        }
        resp = await client.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "message": data.get("message", "加入失败")}
        return {"success": True, "message": "已加入收藏"}


async def get_user_info(uid: str) -> dict:
    """获取用户昵称和头像"""
    async with httpx.AsyncClient(headers=BILI_HEADERS) as client:
        url = f"{BILI_API}/x/space/acc/info"
        params = {"mid": uid}
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return {"nickname": "", "avatar": ""}
        info = (data.get("data") or {})
        return {
            "nickname": info.get("name", ""),
            "avatar": info.get("face", ""),
        }
```

- [ ] **Step 2: 验证 bili.py 语法**

Run: `cd backend && python -c "import ast; ast.parse(open('bili.py').read()); print('OK')"`
Expected: `OK`

---

### Task 2: 创建 backend/auth.py（Session + 二维码登录）

**Files:**
- Create: `backend/auth.py`

- [ ] **Step 1: 创建完整的 auth.py**

```python
import secrets
import time
import urllib.parse

import httpx
from fastapi import Request, HTTPException

BILI_PASSPORT = "https://passport.bilibili.com"
BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# 内存 session 存储
sessions: dict[str, dict] = {}
# 二维码轮询池
qrcode_pool: dict[str, dict] = {}

SID_LEN = 32


async def generate_qrcode() -> dict:
    """调用 B站 API 生成二维码，返回 {qrcode_key, image_url}"""
    async with httpx.AsyncClient(headers=BILI_HEADERS) as client:
        url = f"{BILI_PASSPORT}/x/passport-login/web/qrcode/generate"
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise HTTPException(502, detail="B站二维码生成失败")
        qrcode_key = data["data"]["qrcode_key"]
        qrcode_url = data["data"]["url"]

        # 生成二维码图片URL（使用外部API）
        image_url = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=" + urllib.parse.quote(qrcode_url)

    qrcode_pool[qrcode_key] = {
        "status": "pending",
        "session_id": None,
    }
    return {"qrcode_key": qrcode_key, "image_url": image_url}


async def poll_qrcode(key: str) -> dict:
    """轮询二维码状态，确认后创建 session"""
    if key not in qrcode_pool:
        raise HTTPException(404, detail="二维码已过期")

    async with httpx.AsyncClient(headers=BILI_HEADERS) as client:
        url = f"{BILI_PASSPORT}/x/passport-login/web/qrcode/poll"
        params = {"qrcode_key": key}
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code")

        if code == 86101:
            qrcode_pool[key]["status"] = "pending"
            return {"status": "pending"}
        elif code == 86090:
            qrcode_pool[key]["status"] = "scanned"
            return {"status": "scanned"}
        elif code == 86038:
            qrcode_pool[key]["status"] = "expired"
            qrcode_pool.pop(key, None)
            return {"status": "expired"}
        elif code == 0:
            # 登录成功，提取 Cookie
            raw_cookies = {}
            for cookie in resp.cookies.jar:
                raw_cookies[cookie.name] = cookie.value

            bili_cookies = {
                "SESSDATA": raw_cookies.get("SESSDATA", ""),
                "bili_jct": raw_cookies.get("bili_jct", ""),
                "DedeUserID": raw_cookies.get("DedeUserID", ""),
            }

            session_id = secrets.token_hex(SID_LEN // 2)

            # 从 B站 获取用户信息
            uid = bili_cookies.get("DedeUserID", "")
            from bili import get_user_info
            user_info = await get_user_info(uid)

            sessions[session_id] = {
                "bili_cookies": bili_cookies,
                "deepseek_key": "",
                "uid": uid,
                "nickname": user_info.get("nickname", ""),
                "avatar": user_info.get("avatar", ""),
                "folders": [],
                "created_at": time.time(),
            }

            qrcode_pool[key]["status"] = "confirmed"
            qrcode_pool[key]["session_id"] = session_id

            return {"status": "confirmed", "session_id": session_id}
        else:
            return {"status": "unknown", "code": code}


def get_session(request: Request) -> dict:
    """FastAPI 依赖：从 Cookie 取 session_id，返回 session 数据"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(401, detail="未登录")
    return sessions[session_id]
```

- [ ] **Step 2: 验证 auth.py 语法**

Run: `cd backend && python -c "import ast; ast.parse(open('auth.py').read()); print('OK')"`
Expected: `OK`

---

### Task 3: 更新 backend/requirements.txt

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 加 qrcode 依赖**

```python
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
httpx>=0.27.0
pydantic>=2.0.0
scikit-learn>=1.4.0
openai>=1.12.0
python-dotenv>=1.0.0
qrcode[pil]>=7.4.0
```

但我们在 auth.py 中使用的是外部 QR 服务，实际不需要 qrcode 库。不过为以后后端直接生成二维码预留。当前 Task 只需确保不破坏现有依赖。

- [ ] **Step 2: 验证**

Run: `cd backend && pip install -r requirements.txt`
Expected: All packages install successfully.

---

### Task 4: 重写 backend/main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 用完整新代码替换 main.py**

```python
import os

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import generate_qrcode, poll_qrcode, get_session, sessions, qrcode_pool
from bili import fetch_fav_folders, fetch_fav_items, search_all, add_favorite
from classifier import classify_favorites

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 登录 ----------

@app.post("/api/auth/qrcode")
async def auth_qrcode():
    result = await generate_qrcode()
    return result


@app.get("/api/auth/qrcode/{key}/poll")
async def auth_poll(key: str):
    result = await poll_qrcode(key)
    if result.get("session_id"):
        resp = JSONResponse(result)
        resp.set_cookie(
            key="session_id",
            value=result["session_id"],
            httponly=True,
            max_age=86400 * 7,
            samesite="lax",
        )
        return resp
    return result


@app.get("/api/me")
async def me(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        return {"logged_in": False}
    s = sessions[session_id]
    return {
        "logged_in": True,
        "has_key": bool(s.get("deepseek_key")),
        "nickname": s.get("nickname", ""),
        "avatar": s.get("avatar", ""),
    }


class KeyRequest(BaseModel):
    api_key: str


@app.post("/api/settings/key")
async def settings_key(req: KeyRequest, session: dict = Depends(get_session)):
    session["deepseek_key"] = req.api_key
    return {"success": True}


# ---------- B站数据 ----------

@app.get("/api/folders")
async def api_folders(session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        folders = await fetch_fav_folders(uid, cookies)
        session["folders"] = folders
        return {"folders": folders}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/favorites")
async def api_favorites(folder_id: int, session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        items = await fetch_fav_items(folder_id, cookies)
        return {"items": items}
    except Exception as e:
        return {"error": str(e)}


class AnalyzeRequest(BaseModel):
    folder_id: int | None = None
    n_clusters: int | None = None


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest, session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        api_key = session.get("deepseek_key", "")
        if not api_key:
            return JSONResponse({"error": "请先绑定 DeepSeek API Key"}, status_code=400)

        if req.folder_id:
            all_items = await fetch_fav_items(req.folder_id, cookies)
        else:
            folders = await fetch_fav_folders(uid, cookies)
            all_items = []
            for folder in folders:
                fid = folder.get("media_id") or folder.get("id")
                if not fid:
                    continue
                items = await fetch_fav_items(fid, cookies)
                all_items.extend(items)

        if not all_items:
            return {"error": "收藏夹为空"}

        n_clusters = req.n_clusters or min(3, len(all_items))
        result = await classify_favorites(all_items, n_clusters, api_key)
        return result
    except Exception as e:
        return {"error": str(e)}


# ---------- 搜索 ----------

@app.get("/api/search/favorites")
async def api_search_favorites(q: str = "", session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        folders = await fetch_fav_folders(uid, cookies)
        results = []
        for folder in folders:
            fid = folder.get("media_id") or folder.get("id")
            if not fid:
                continue
            items = await fetch_fav_items(fid, cookies)
            for item in items:
                if q.lower() in item["title"].lower() or q.lower() in item.get("intro", "").lower():
                    item["folder_name"] = folder.get("title", "默认收藏夹")
                    results.append(item)
        return {"results": results, "total": len(results)}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/search/all")
async def api_search_all(q: str = "", page: int = 1):
    try:
        results = await search_all(q, page)
        return {"results": results}
    except Exception as e:
        return {"error": str(e)}


class AddFavoriteRequest(BaseModel):
    bvid: str
    folder_id: int | None = None


@app.post("/api/favorites/add")
async def api_favorites_add(req: AddFavoriteRequest, session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        result = await add_favorite(req.bvid, req.folder_id, cookies)
        return result
    except Exception as e:
        return {"error": str(e)}


# ---------- 退出 ----------

@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        sessions.pop(session_id, None)
    resp = JSONResponse({"success": True})
    resp.delete_cookie("session_id")
    return resp


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
```

- [ ] **Step 2: 验证 main.py 语法**

Run: `cd backend && python -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

---

### Task 5: 重写 frontend/src/api.js

**Files:**
- Modify: `frontend/src/api.js`

- [ ] **Step 1: 替换 api.js 全部内容**

```javascript
const BASE = "http://localhost:8000/api";

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return resp.json();
}

export function getQrcode() {
  return request("/auth/qrcode", { method: "POST" });
}

export function pollQrcode(key) {
  return request(`/auth/qrcode/${key}/poll`, { method: "GET" });
}

export function getMe() {
  return request("/me");
}

export function setApiKey(apiKey) {
  return request("/settings/key", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function getFolders() {
  return request("/folders");
}

export function getFavorites(folderId) {
  return request(`/favorites?folder_id=${folderId}`);
}

export function analyze(folderId, nClusters) {
  const body = {};
  if (folderId) body.folder_id = folderId;
  if (nClusters) body.n_clusters = nClusters;
  return request("/analyze", { method: "POST", body: JSON.stringify(body) });
}

export function searchFavorites(q) {
  return request(`/search/favorites?q=${encodeURIComponent(q)}`);
}

export function searchAll(q, page = 1) {
  return request(`/search/all?q=${encodeURIComponent(q)}&page=${page}`);
}

export function addToFavorite(bvid, folderId) {
  return request("/favorites/add", {
    method: "POST",
    body: JSON.stringify({ bvid, folder_id: folderId }),
  });
}

export function logout() {
  return request("/auth/logout", { method: "POST" });
}
```

- [ ] **Step 2: 验证语法**

Run: `cd frontend && node -c src/api.js`
Expected: No output (syntax OK).

---

### Task 6: 创建 frontend/src/styles.css

**Files:**
- Create: `frontend/src/styles.css`

- [ ] **Step 1: 创建样式文件**

```css
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  background: #f5f5f5;
  color: #333;
}

/* 居中卡片页（登录、绑定Key） */
.centered-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
}

.card {
  background: #fff;
  border-radius: 16px;
  padding: 40px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  text-align: center;
}

.card h1 {
  font-size: 24px;
  margin-bottom: 8px;
  color: #222;
}

.card .subtitle {
  font-size: 14px;
  color: #999;
  margin-bottom: 24px;
}

.card .hint {
  font-size: 12px;
  color: #aaa;
  margin-top: 16px;
}

/* 主控制台布局 */
.console {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 220px;
  background: #fff;
  border-right: 1px solid #eee;
  padding-top: 20px;
  flex-shrink: 0;
}

.sidebar .logo {
  padding: 0 20px 20px;
  font-size: 18px;
  font-weight: 700;
  color: #FB7299;
}

.sidebar .menu-item {
  padding: 14px 20px;
  cursor: pointer;
  font-size: 15px;
  color: #666;
  border-left: 3px solid transparent;
  transition: all 0.15s;
}

.sidebar .menu-item:hover {
  background: #fdf2f5;
  color: #FB7299;
}

.sidebar .menu-item.active {
  background: #fdf2f5;
  color: #FB7299;
  border-left-color: #FB7299;
}

.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.header {
  height: 60px;
  background: #fff;
  border-bottom: 1px solid #eee;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.header .page-title {
  font-size: 18px;
  font-weight: 600;
}

.header .user-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header .user-info img {
  width: 32px;
  height: 32px;
  border-radius: 50%;
}

.header .logout-btn {
  padding: 6px 14px;
  border: 1px solid #ddd;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  color: #999;
}

.header .logout-btn:hover {
  color: #FB7299;
  border-color: #FB7299;
}

.content {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
}

/* 表单 */
.input {
  padding: 10px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  width: 280px;
  outline: none;
  transition: border-color 0.15s;
}

.input:focus {
  border-color: #FB7299;
}

.btn {
  padding: 10px 24px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  background: #FB7299;
  color: #fff;
  transition: background 0.15s;
}

.btn:hover {
  background: #e8627d;
}

.btn:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.btn-secondary {
  background: #fff;
  color: #666;
  border: 1px solid #ddd;
}

.btn-secondary:hover {
  border-color: #FB7299;
  color: #FB7299;
}

/* 状态标签 */
.status-pending { color: #999; }
.status-scanned { color: #3b82f6; }
.status-confirmed { color: #22c55e; }
.status-expired { color: #f43f5e; }

/* 结果卡片 */
.result-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}

.result-card h3 {
  font-size: 16px;
  margin-bottom: 12px;
  color: #FB7299;
}

.result-card .item-count {
  font-weight: 400;
  font-size: 13px;
  color: #999;
}

.result-list {
  list-style: none;
}

.result-list li {
  padding: 8px 0;
  border-bottom: 1px solid #f5f5f5;
  font-size: 14px;
}

.result-list li:last-child {
  border-bottom: none;
}

.result-list a {
  color: #333;
  text-decoration: none;
}

.result-list a:hover {
  color: #FB7299;
}

.result-list .meta {
  font-size: 12px;
  color: #999;
}

/* 搜索 */
.search-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.tabs {
  display: flex;
  gap: 0;
  margin-bottom: 20px;
  border-bottom: 2px solid #eee;
}

.tab {
  padding: 10px 24px;
  cursor: pointer;
  font-size: 14px;
  color: #999;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.15s;
}

.tab.active {
  color: #FB7299;
  border-bottom-color: #FB7299;
}

/* 弹窗 */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  background: #fff;
  border-radius: 12px;
  padding: 28px;
  min-width: 360px;
  max-width: 480px;
}

.modal h3 {
  margin-bottom: 16px;
}

.modal select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  margin-bottom: 16px;
}

.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

/* spinner */
.spinner {
  display: inline-block;
  width: 20px; height: 20px;
  border: 2px solid #f3f3f3;
  border-top: 2px solid #FB7299;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 提示消息 */
.toast {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: #333;
  color: #fff;
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 14px;
  z-index: 200;
  animation: fadein 0.3s;
}

@keyframes fadein {
  from { opacity: 0; transform: translateX(-50%) translateY(-10px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
```

---

### Task 7: 创建 frontend/src/login-page.js

**Files:**
- Create: `frontend/src/login-page.js`

- [ ] **Step 1: 创建登录页**

```javascript
import { getQrcode, pollQrcode } from "./api.js";

export function renderLoginPage(app) {
  app.innerHTML = `
    <div class="centered-page">
      <div class="card" style="width:400px;">
        <h1>收藏夹管家</h1>
        <p class="subtitle">用 B站 App 扫码登录，自动整理收藏夹</p>
        <img id="qrImg" src="" alt="二维码" style="width:200px;height:200px;" />
        <p id="statusText" class="status-pending" style="margin-top:12px;">等待扫码…</p>
        <p class="hint">请使用 B站 App 扫描二维码</p>
      </div>
    </div>
  `;

  startQrcode();
}

async function startQrcode() {
  try {
    const data = await getQrcode();
    const img = document.getElementById("qrImg");
    const status = document.getElementById("statusText");
    img.src = data.image_url;
    pollLoop(data.qrcode_key, status);
  } catch (err) {
    document.getElementById("statusText").textContent = "网络异常，请刷新重试";
  }
}

async function pollLoop(key, statusEl) {
  const timer = setInterval(async () => {
    try {
      const data = await pollQrcode(key);
      if (data.status === "scanned") {
        statusEl.textContent = "已扫码，请在手机上确认…";
        statusEl.className = "status-scanned";
      } else if (data.status === "confirmed") {
        statusEl.textContent = "登录成功，跳转中…";
        statusEl.className = "status-confirmed";
        clearInterval(timer);
        setTimeout(() => location.reload(), 500);
      } else if (data.status === "expired") {
        statusEl.textContent = "二维码已过期，正在刷新…";
        statusEl.className = "status-expired";
        clearInterval(timer);
        setTimeout(startQrcode, 1000);
      }
    } catch (err) {
      // 网络波动不中断轮询
    }
  }, 2000);
}
```

---

### Task 8: 创建 frontend/src/bind-page.js

**Files:**
- Create: `frontend/src/bind-page.js`

- [ ] **Step 1: 创建绑定 Key 页**

```javascript
import { setApiKey } from "./api.js";

export function renderBindPage(app) {
  app.innerHTML = `
    <div class="centered-page">
      <div class="card">
        <h1>绑定 API Key</h1>
        <p class="subtitle">输入 DeepSeek API Key，用于分类命名</p>
        <div style="margin-bottom:16px;">
          <input id="keyInput" class="input" type="password" placeholder="sk-..." />
        </div>
        <p id="bindError" style="color:#f43f5e;font-size:13px;margin-bottom:12px;display:none;"></p>
        <button id="bindBtn" class="btn">确认并进入</button>
        <p class="hint">Key 仅保存在当前会话，后端重启后需重新绑定</p>
      </div>
    </div>
  `;

  document.getElementById("bindBtn").addEventListener("click", async () => {
    const key = document.getElementById("keyInput").value.trim();
    const errEl = document.getElementById("bindError");
    if (!key) {
      errEl.textContent = "请输入 API Key";
      errEl.style.display = "block";
      return;
    }
    try {
      await setApiKey(key);
      location.reload();
    } catch (e) {
      errEl.textContent = "绑定失败: " + e.message;
      errEl.style.display = "block";
    }
  });
}
```

---

### Task 9: 创建 frontend/src/classify-module.js

**Files:**
- Create: `frontend/src/classify-module.js`

- [ ] **Step 1: 创建整理收藏夹模块**

```javascript
import { getFolders, analyze } from "./api.js";

export async function renderClassifyModule(container) {
  container.innerHTML = `
    <div>
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:20px;">
        <select id="folderSelect" class="input" style="width:200px;">
          <option value="">全部收藏夹</option>
        </select>
        <input id="clusterCount" class="input" type="number" value="3" min="1" max="10"
               style="width:80px;" placeholder="分类数" />
        <button id="analyzeBtn" class="btn">开始整理</button>
        <span id="analyzeSpinner" style="display:none;" class="spinner"></span>
      </div>
      <div id="analyzeResult"></div>
    </div>
  `;

  const folderSelect = document.getElementById("folderSelect");
  try {
    const data = await getFolders();
    if (data.folders) {
      for (const f of data.folders) {
        const opt = document.createElement("option");
        opt.value = f.id || f.media_id || "";
        opt.textContent = f.title || "收藏夹";
        folderSelect.appendChild(opt);
      }
    }
  } catch (e) {
    // 收藏夹加载失败，保留"全部收藏夹"选项
  }

  document.getElementById("analyzeBtn").addEventListener("click", async () => {
    const resultEl = document.getElementById("analyzeResult");
    const spinner = document.getElementById("analyzeSpinner");
    const btn = document.getElementById("analyzeBtn");
    const folderId = folderSelect.value || null;
    const nClusters = parseInt(document.getElementById("clusterCount").value) || 3;

    spinner.style.display = "inline-block";
    btn.disabled = true;
    resultEl.innerHTML = "";

    try {
      const data = await analyze(folderId, nClusters);
      if (data.error) {
        resultEl.innerHTML = `<p style="color:#f43f5e;">${data.error}</p>`;
        return;
      }
      let html = `<p style="margin-bottom:16px;">共 ${data.total} 条收藏，分为 ${data.categories.length} 类：</p>`;
      for (const cat of data.categories) {
        html += `<div class="result-card">
          <h3>${cat.name} <span class="item-count">（${cat.items.length}）</span></h3>
          <ul class="result-list">`;
        for (const item of cat.items) {
          html += `<li>
            <a href="${item.link}" target="_blank" rel="noopener">${item.title}</a>
            <span class="meta"> — ${item.upper}</span>
          </li>`;
        }
        html += `</ul></div>`;
      }
      resultEl.innerHTML = html;
    } catch (e) {
      resultEl.innerHTML = `<p style="color:#f43f5e;">请求失败: ${e.message}</p>`;
    } finally {
      spinner.style.display = "none";
      btn.disabled = false;
    }
  });
}
```

---

### Task 10: 创建 frontend/src/search-module.js

**Files:**
- Create: `frontend/src/search-module.js`

- [ ] **Step 1: 创建寻找视频模块**

```javascript
import { searchFavorites, searchAll, addToFavorite, getFolders } from "./api.js";

let cachedFolders = [];

export async function renderSearchModule(container) {
  container.innerHTML = `
    <div>
      <div class="tabs">
        <div class="tab active" data-tab="in-fav">搜索已收藏</div>
        <div class="tab" data-tab="all">搜索全站</div>
      </div>
      <div class="search-bar">
        <input id="searchInput" class="input" placeholder="输入关键词搜索…" style="flex:1;" />
        <button id="searchBtn" class="btn">搜索</button>
        <span id="searchSpinner" style="display:none;" class="spinner"></span>
      </div>
      <div id="searchResult"></div>
      <div id="addModal" style="display:none;"></div>
    </div>
  `;

  try {
    const data = await getFolders();
    cachedFolders = data.folders || [];
  } catch (e) {}

  let currentTab = "in-fav";

  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentTab = tab.dataset.tab;
      document.getElementById("searchInput").value = "";
      document.getElementById("searchResult").innerHTML = "";
    });
  });

  document.getElementById("searchBtn").addEventListener("click", async () => {
    const q = document.getElementById("searchInput").value.trim();
    if (!q) return;
    const resultEl = document.getElementById("searchResult");
    const spinner = document.getElementById("searchSpinner");
    spinner.style.display = "inline-block";
    resultEl.innerHTML = "";
    try {
      if (currentTab === "in-fav") {
        const data = await searchFavorites(q);
        if (data.error) { resultEl.innerHTML = `<p style="color:#f43f5e;">${data.error}</p>`; return; }
        if (data.results.length === 0) {
          resultEl.innerHTML = `<p style="color:#999;">未找到匹配的收藏视频</p>`;
          return;
        }
        let html = `<p style="margin-bottom:12px;">找到 ${data.total} 条结果：</p>`;
        for (const item of data.results) {
          html += `<div class="result-card">
            <a href="${item.link}" target="_blank" rel="noopener">${item.title}</a>
            <span class="meta" style="margin-left:8px;">— ${item.upper}</span>
            <span class="meta" style="float:right;">${item.folder_name || ""}</span>
          </div>`;
        }
        resultEl.innerHTML = html;
      } else {
        const data = await searchAll(q);
        if (data.error) { resultEl.innerHTML = `<p style="color:#f43f5e;">${data.error}</p>`; return; }
        if (data.results.length === 0) {
          resultEl.innerHTML = `<p style="color:#999;">未找到相关视频</p>`;
          return;
        }
        let html = "";
        for (const item of data.results) {
          html += `<div class="result-card" style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <a href="${item.link}" target="_blank" rel="noopener">${item.title}</a>
              <div class="meta">${item.upper}</div>
            </div>
            <button class="btn btn-secondary" data-bvid="${item.bvid}" data-title="${item.title}">+ 收藏</button>
          </div>`;
        }
        resultEl.innerHTML = html;

        resultEl.querySelectorAll("[data-bvid]").forEach(btn => {
          btn.addEventListener("click", () => showAddModal(btn.dataset.bvid, btn.dataset.title));
        });
      }
    } catch (e) {
      resultEl.innerHTML = `<p style="color:#f43f5e;">搜索失败: ${e.message}</p>`;
    } finally {
      spinner.style.display = "none";
    }
  });

  document.getElementById("searchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("searchBtn").click();
  });
}

function showAddModal(bvid, title) {
  const existing = document.getElementById("addModal");
  if (existing) existing.remove();

  const options = cachedFolders.map(f =>
    `<option value="${f.id || f.media_id || ""}">${f.title || "收藏夹"}</option>`
  ).join("");

  const modal = document.createElement("div");
  modal.id = "addModal";
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal">
      <h3>加入收藏：${title}</h3>
      <select id="addFolderSelect">${options}</select>
      <div class="modal-actions">
        <button id="cancelAddBtn" class="btn btn-secondary">取消</button>
        <button id="confirmAddBtn" class="btn">确认加入</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  document.getElementById("cancelAddBtn").addEventListener("click", () => modal.remove());
  document.getElementById("confirmAddBtn").addEventListener("click", async () => {
    const folderId = document.getElementById("addFolderSelect").value || null;
    try {
      const result = await addToFavorite(bvid, folderId);
      showToast(result.message || (result.success ? "已加入" : "加入失败"));
      modal.remove();
    } catch (e) {
      showToast("操作失败: " + e.message);
    }
  });
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });
}

function showToast(msg) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2500);
}
```

---

### Task 11: 创建 frontend/src/console-page.js

**Files:**
- Create: `frontend/src/console-page.js`

- [ ] **Step 1: 创建主控制台布局**

```javascript
import { logout } from "./api.js";
import { renderClassifyModule } from "./classify-module.js";
import { renderSearchModule } from "./search-module.js";

export function renderConsole(app, user) {
  app.innerHTML = `
    <div class="console">
      <div class="sidebar">
        <div class="logo">收藏夹管家</div>
        <div class="menu-item active" data-page="classify">整理收藏夹</div>
        <div class="menu-item" data-page="search">寻找视频</div>
      </div>
      <div class="main-area">
        <div class="header">
          <div class="page-title" id="pageTitle">整理收藏夹</div>
          <div class="user-info">
            <img src="${user.avatar || ''}" alt="" onerror="this.style.display='none'" />
            <span>${user.nickname || "用户"}</span>
            <button id="logoutBtn" class="logout-btn">退出</button>
          </div>
        </div>
        <div class="content" id="contentArea"></div>
      </div>
    </div>
  `;

  const pageTitle = document.getElementById("pageTitle");
  const contentArea = document.getElementById("contentArea");

  const pageMap = {
    classify: { title: "整理收藏夹", render: renderClassifyModule },
    search: { title: "寻找视频", render: renderSearchModule },
  };

  document.querySelectorAll(".menu-item").forEach(item => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".menu-item").forEach(i => i.classList.remove("active"));
      item.classList.add("active");
      const page = item.dataset.page;
      pageTitle.textContent = pageMap[page].title;
      pageMap[page].render(contentArea);
    });
  });

  document.getElementById("logoutBtn").addEventListener("click", async () => {
    try { await logout(); } catch (e) {}
    location.reload();
  });

  // 默认加载整理收藏夹
  renderClassifyModule(contentArea);
}
```

---

### Task 12: 重写 frontend/src/main.js（App 路由入口）

**Files:**
- Modify: `frontend/src/main.js`

- [ ] **Step 1: 替换 main.js 全部内容**

```javascript
import { getMe } from "./api.js";
import { renderLoginPage } from "./login-page.js";
import { renderBindPage } from "./bind-page.js";
import { renderConsole } from "./console-page.js";

async function boot() {
  const app = document.getElementById("app");

  // 检查登录状态
  let user;
  try {
    user = await getMe();
  } catch (e) {
    user = { logged_in: false };
  }

  if (!user.logged_in) {
    renderLoginPage(app);
  } else if (!user.has_key) {
    renderBindPage(app);
  } else {
    renderConsole(app, user);
  }
}

boot();
```

---

### Task 13: 更新 frontend/index.html

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: 加 CSS 引用**

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>收藏夹管家</title>
    <link rel="stylesheet" href="/src/styles.css" />
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

---

## 自审检查清单

- [x] Spec 覆盖：所有接口（auth/qrcode, poll, me, settings/key, folders, favorites, analyze, search/favorites, search/all, favorites/add, logout）都有对应任务
- [x] 无占位符：每个任务都包含完整可运行的代码
- [x] 类型一致性：前端 api.js 的导出与各 page.js 的 import 完全匹配
- [x] 文件路径：所有 Create/Modify 路径指向正确的项目位置
- [x] Session 中间件：auth.py 的 get_session 使用 FastAPI Depends 模式
- [x] Cookie 处理：poll 成功时 Set-Cookie session_id（httponly），logout 时 delete_cookie
- [x] CORS：FastAPI 的 allow_origins 改为 Vite 开发端口 5173，allow_credentials=True
- [x] 现有代码保留：classifier.py 完全不动
