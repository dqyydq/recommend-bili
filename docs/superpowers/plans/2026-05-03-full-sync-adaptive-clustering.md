# 全量抓取 + 自适应聚类 + SSE 进度反馈 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `/api/analyze` 升级为全量抓取、轮廓系数自适应聚类的 SSE 流式端点，前端实时展示抓取进度。

**Architecture:** `bili.py` 取消限制全量分页 → `main.py` SSE 流式端点边抓边推送进度 → `classifier.py` 新增 `optimal_k()` 自动确定分类数 → 前端 `EventSource` 实时监听进度和结果。

**Tech Stack:** Python 3.11+, FastAPI StreamingResponse, sklearn silhouette_score, EventSource API

---

## 文件结构

```
backend/
├── bili.py          ← [MODIFY] fetch_fav_items 取消上限，全量分页
├── classifier.py    ← [MODIFY] 新增 optimal_k(), classify_favorites 移除 n_clusters 参数
└── main.py          ← [MODIFY] POST /api/analyze → GET SSE 端点
frontend/src/
├── classify-module.js ← [MODIFY] EventSource 监听 + 进度条
└── api.js           ← [MODIFY] 移除 analyze(), 添加 SSE URL 常量
```

---

### Task 1: bili.py — 全量分页抓取

**Files:**
- Modify: `backend/bili.py`

**Change:** `fetch_fav_items` 取消 `while len(items) < 5` 限制和 `return items[:40]`，改用 `has_more` 字段判断是否继续分页。

- [ ] **Step 1: 替换 while 循环条件和返回逻辑**

Replace lines 47-81 (entire function body after `items = []`):

```python
    items: list[dict] = []
    page = 1
    async with _client(cookies, extra_headers={"Referer": "https://www.bilibili.com/"}) as client:
        while True:
            url = f"{BILI_API}/x/v3/fav/resource/list"
            params = {
                "media_id": folder_id,
                "pn": page,
                "ps": 20,
            }
            resp = await client.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                break
            medias = (data.get("data") or {}).get("medias", []) or []
            has_more = (data.get("data") or {}).get("has_more", False)
            for media in medias:
                items.append({
                    "bvid": media.get("bvid", ""),
                    "title": media.get("title", ""),
                    "intro": media.get("intro", ""),
                    "upper": (media.get("upper") or {}).get("name", ""),
                    "cover": media.get("cover", ""),
                    "link": f"https://www.bilibili.com/video/{media.get('bvid', '')}",
                    "source_folder": str(folder_id),
                })
            if not has_more or not medias:
                break
            page += 1
            await asyncio.sleep(0.3)
    return items
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && python -c "import ast; ast.parse(open('bili.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

### Task 2: classifier.py — 自适应聚类 optimal_k()

**Files:**
- Modify: `backend/classifier.py`

**Changes:**
1. Add `numpy` import
2. Add `optimal_k()` function
3. Modify `classify_favorites` signature (remove `n_clusters` param), call `optimal_k()` internally
4. Clean up debug prints

- [ ] **Step 1: Add numpy import**

Replace line 1-2:

```python
import os

import httpx
from openai import AsyncOpenAI
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
```

Add `import numpy as np` after `from sklearn.metrics`:

```python
import os

import httpx
import numpy as np
from openai import AsyncOpenAI
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
```

- [ ] **Step 2: Add optimal_k() function**

Insert between `cluster_items` and `name_cluster`:

```python
def optimal_k(embeddings: list[list[float]]) -> int:
    """轮廓系数自适应确定最佳 k，肘部法则兜底"""
    n = len(embeddings)
    if n < 3:
        return 1
    max_k = min(15, n - 1)
    X = np.array(embeddings)

    best_k = 2
    best_silhouette = -1
    for k in range(2, max_k + 1):
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(X)
        score = silhouette_score(X, labels)
        if score > best_silhouette:
            best_silhouette = score
            best_k = k

    # 轮廓分数太差，数据聚类性弱，退到肘部法则
    if best_silhouette < 0.2:
        sse = []
        for k in range(2, max_k + 1):
            km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
            sse.append(km.inertia_)
        # 肘部拐点：找 SSE 下降速率最大变化处
        deltas = [sse[i - 1] - sse[i] for i in range(1, len(sse))]
        delta_deltas = [deltas[i] - deltas[i + 1] for i in range(len(deltas) - 1)]
        if delta_deltas:
            elbow_idx = int(np.argmax(delta_deltas))
            best_k = elbow_idx + 2  # k starts at 2

    return max(2, min(best_k, max_k))
```

- [ ] **Step 3: Modify classify_favorites signature**

Remove `n_clusters` parameter, call `optimal_k()` internally.

Replace lines 65-96 (entire `classify_favorites` function):

```python
async def classify_favorites(items: list[dict], api_key: str) -> dict:
    if not items:
        return {"categories": [], "total": 0}

    texts = [f"{item['title']} {item.get('intro', '')}"[:200] for item in items]
    embeddings = await get_embeddings(texts)

    n_clusters = optimal_k(embeddings)

    labels = cluster_items(embeddings, n_clusters)

    clusters: dict[int, list[dict]] = {}
    for item, label in zip(items, labels):
        clusters.setdefault(label, []).append(item)

    categories = []
    for cluster_items_list in clusters.values():
        titles = [item["title"] for item in cluster_items_list]
        name = await name_cluster(titles, api_key)
        categories.append({
            "name": name,
            "items": cluster_items_list,
        })

    return {
        "categories": categories,
        "total": len(items),
    }
```

- [ ] **Step 4: Clean debug prints from get_embeddings and name_cluster**

In `get_embeddings` (lines 13-33), replace to remove debug prints:

```python
async def get_embeddings(texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    async with httpx.AsyncClient() as client:
        for text in texts:
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": text,
            }
            resp = await client.post(OLLAMA_URL, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding", [])
            embeddings.append(embedding)
    return embeddings
```

In `name_cluster` (lines 44-62), replace to remove debug prints:

```python
async def name_cluster(titles: list[str], api_key: str) -> str:
    client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    prompt = (
        "请根据以下视频标题，给这个分类起一个简洁的中文名字（不超过10个字）：\n"
        + "\n".join(f"- {t}" for t in titles)
        + "\n\n只需要返回分类名字，不要任何解释。"
    )
    resp = await client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20,
    )
    return resp.choices[0].message.content.strip()
```

- [ ] **Step 5: Verify syntax**

Run: `cd backend && python -c "import ast; ast.parse(open('classifier.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

### Task 3: main.py — SSE 流式端点

**Files:**
- Modify: `backend/main.py`

**Changes:**
1. Remove `AnalyzeRequest` model class (lines 94-96)
2. Replace `POST /api/analyze` (lines 99-132) with `GET /api/analyze` SSE endpoint
3. Add imports: `asyncio, StreamingResponse`
4. Remove debug prints from the old route

- [ ] **Step 1: Add StreamingResponse import**

Replace line 5:

```python
from fastapi.responses import JSONResponse
```
with:
```python
from fastapi.responses import JSONResponse, StreamingResponse
```

- [ ] **Step 2: Replace analyze route definition**

Remove lines 94-132 (AnalyzeRequest class + old POST route), insert new SSE route:

```python
@app.get("/api/analyze")
async def api_analyze(request: Request, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    if not api_key:
        return JSONResponse({"error": "请先绑定 DeepSeek API Key"}, status_code=400)

    cookies = session.get("bili_cookies", {})
    uid = session.get("uid", "")

    async def event_stream():
        try:
            folders = await fetch_fav_folders(uid, cookies)
            if not folders:
                yield f"event: error\ndata: {json.dumps({'error': '未找到收藏夹'})}\n\n"
                return

            all_items: list[dict] = []
            for folder in folders:
                fid = folder.get("media_id") or folder.get("id")
                if not fid:
                    continue
                items = await fetch_fav_items(fid, cookies)
                all_items.extend(items)
                yield f"event: progress\ndata: {json.dumps({'folder_name': folder.get('title', '收藏夹'), 'folder_count': len(items), 'total_collected': len(all_items)})}\n\n"
                await asyncio.sleep(0.3)

            if not all_items:
                yield f"event: error\ndata: {json.dumps({'error': '收藏夹为空'})}\n\n"
                return

            yield f"event: classifying\ndata: {json.dumps({'total': len(all_items)})}\n\n"

            result = await classify_favorites(all_items, api_key)
            yield f"event: result\ndata: {json.dumps(result)}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
```

- [ ] **Step 3: Add json and asyncio imports at top**

Replace the import block (lines 1-10):

```python
import asyncio
import json
import os

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth import generate_qrcode, poll_qrcode, get_session, sessions, qrcode_pool
from bili import fetch_fav_folders, fetch_fav_items, search_all, add_favorite
from classifier import classify_favorites
```

- [ ] **Step 4: Verify syntax + imports**

Run: `cd backend && python -c "import ast; ast.parse(open('main.py', encoding='utf-8').read()); print('OK')"`
Run: `cd backend && python -c "from main import app; print('Routes:', len(app.routes))"`
Expected: `Routes: 15`

---

### Task 4: frontend classify-module.js — EventSource + 进度

**Files:**
- Modify: `frontend/src/classify-module.js`

**Change:** Replace `fetch` + `await analyze()` with `EventSource` SSE listener, remove folder/cluster selectors, add progress bar.

- [ ] **Step 1: Replace entire file**

Read the file first, then overwrite completely:

```javascript
import { getFolders } from "./api.js";

const SSE_URL = "http://localhost:8000/api/analyze";

export async function renderClassifyModule(container) {
  container.innerHTML = `
    <div>
      <div style="display:flex;gap:12px;align-items:center;margin-bottom:20px;">
        <button id="analyzeBtn" class="btn">开始整理</button>
        <button id="cancelBtn" class="btn btn-secondary" style="display:none;">取消</button>
      </div>
      <div id="progressArea" style="display:none;margin-bottom:16px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
          <div id="progressBar" style="flex:1;height:6px;background:#eee;border-radius:3px;overflow:hidden;">
            <div id="progressFill" style="height:100%;width:0%;background:#FB7299;transition:width 0.3s;"></div>
          </div>
          <span id="progressPercent" style="font-size:13px;color:#999;">0%</span>
        </div>
        <span id="progressText" style="font-size:13px;color:#666;"></span>
      </div>
      <div id="analyzeResult"></div>
    </div>
  `;

  let abortCtrl = null;

  const btn = document.getElementById("analyzeBtn");
  const cancelBtn = document.getElementById("cancelBtn");
  const progressArea = document.getElementById("progressArea");
  const progressFill = document.getElementById("progressFill");
  const progressPercent = document.getElementById("progressPercent");
  const progressText = document.getElementById("progressText");
  const resultEl = document.getElementById("analyzeResult");

  // 获取收藏夹总数用于进度估算
  let estimatedTotal = 50; // 默认预估
  try {
    const data = await getFolders();
    if (data.folders) {
      // 粗略估算：每个收藏夹平均20条
      estimatedTotal = data.folders.length * 20;
    }
  } catch (e) {}

  btn.addEventListener("click", () => {
    resultEl.innerHTML = "";
    btn.disabled = true;
    btn.style.display = "none";
    cancelBtn.style.display = "inline-block";
    progressArea.style.display = "block";
    progressFill.style.width = "0%";
    progressPercent.textContent = "0%";
    progressText.textContent = "正在抓取收藏夹…";

    abortCtrl = new AbortController();
    const es = new EventSource(SSE_URL);

    es.addEventListener("progress", (e) => {
      const d = JSON.parse(e.data);
      const pct = Math.min(99, Math.round((d.total_collected / estimatedTotal) * 100));
      progressFill.style.width = pct + "%";
      progressPercent.textContent = pct + "%";
      progressText.textContent = `已抓取 ${d.total_collected} 条（${d.folder_name}：${d.folder_count} 条）`;
    });

    es.addEventListener("classifying", (e) => {
      const d = JSON.parse(e.data);
      progressFill.style.width = "100%";
      progressPercent.textContent = "100%";
      progressText.textContent = `抓取完成，共 ${d.total} 条。正在 AI 分析分类…`;
    });

    es.addEventListener("result", (e) => {
      es.close();
      resetUI();
      const data = JSON.parse(e.data);
      renderResult(data, resultEl);
    });

    es.addEventListener("error", (e) => {
      es.close();
      resetUI();
      let msg = "请求失败";
      try {
        if (e.data) {
          const d = JSON.parse(e.data);
          if (d.error) msg = d.error;
        }
      } catch (_) {}
      resultEl.innerHTML = `<p style="color:#f43f5e;">${msg}</p>`;
    });

    // 服务端连接错误（非SSE事件错误）
    es.onerror = () => {
      es.close();
      resetUI();
      resultEl.innerHTML = `<p style="color:#f43f5e;">连接中断，请重试</p>`;
    };

    abortCtrl.signal.addEventListener("abort", () => {
      es.close();
    });
  });

  cancelBtn.addEventListener("click", () => {
    if (abortCtrl) abortCtrl.abort();
    resetUI();
  });

  function resetUI() {
    btn.disabled = false;
    btn.style.display = "inline-block";
    cancelBtn.style.display = "none";
  }
}

function renderResult(data, resultEl) {
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
}
```

- [ ] **Step 2: Verify JS syntax**

Run: `node -c D:\python_code\Favorite-agent\frontend\src\classify-module.js`
Expected: No output (clean)

---

### Task 5: frontend api.js — 移除 analyze()

**Files:**
- Modify: `frontend/src/api.js`

**Change:** Remove the `analyze()` function (now handled via SSE EventSource).

- [ ] **Step 1: Remove analyze function**

Read the file first. Find and remove this block:

```javascript
export function analyze(folderId, nClusters) {
  const body = {};
  if (folderId) body.folder_id = folderId;
  if (nClusters) body.n_clusters = nClusters;
  return request("/analyze", { method: "POST", body: JSON.stringify(body) });
}
```

- [ ] **Step 2: Verify JS syntax**

Run: `node -c D:\python_code\Favorite-agent\frontend\src\api.js`
Expected: No output (clean)

---

## 自审检查清单

- [x] Spec 覆盖：全量抓取 (Task 1)、自适应聚类 (Task 2)、SSE 进度 (Task 3)、前端 EventSource (Task 4)、旧接口清理 (Task 5)
- [x] 无占位符：每步包含完整可运行代码
- [x] 类型一致性：`classify_favorites` 签名变更在 Task 2 (classifier.py) 和 Task 3 (main.py) 之间一致（移除了 n_clusters）
- [x] SSE 事件名：`progress` / `classifying` / `result` / `error` 前后端一致
- [x] 导入正确：Task 2 添加的 `import numpy as np` 和 `from sklearn.metrics import silhouette_score` 对应 `optimal_k()` 的使用
- [x] Task 5：移除 api.js 的 `analyze()` 但保留其他函数（searchFavorites 等仍使用 request()）
