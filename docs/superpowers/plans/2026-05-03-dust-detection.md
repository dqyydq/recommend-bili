# 吃灰检测 实现计划

> **Goal:** 新增「吃灰检测」模块，拉取收藏夹 + 90天观看历史，交叉对比判定吃灰等级

**Architecture:** bili.py 新增 fetch_history → main.py 新增 GET /api/dust SSE → 前端 dust-module.js EventSource 监听

**Tech Stack:** Python 3.11+, httpx, FastAPI StreamingResponse

---

### Task 1: bili.py — 新增 fetch_history()

**Files:** Modify `backend/bili.py`

在文件末尾添加:

```python
async def fetch_history(cookies: dict[str, str], days: int = 90) -> list[dict]:
    """拉取最近 N 天 B站观看历史"""
    cutoff = time.time() - days * 86400
    history: list[dict] = []
    max_id = 0
    async with _client(cookies) as client:
        while True:
            url = f"{BILI_API}/x/web-interface/history/cursor"
            params = {
                "max": str(max_id) if max_id else "0",
                "view_at": str(int(cutoff)),
                "ps": 20,
                "type": "archive",
            }
            resp = await client.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                break
            items = (data.get("data") or {}).get("list", []) or []
            if not items:
                break
            for item in items:
                history.append({
                    "bvid": item.get("bvid", ""),
                    "title": item.get("title", ""),
                    "view_at": item.get("view_at", 0),
                })
            max_id = items[-1].get("view_at", 0)
            if len(items) < 20:
                break
            await asyncio.sleep(0.5)
    return history
```

加 `import time` 到文件顶部 import。

---

### Task 2: main.py — 新增 GET /api/dust

**Files:** Modify `backend/main.py`

在 `# ---------- 搜索 ----------` 之前插入新路由:

```python
from bili import fetch_history  # 加到文件顶部 import

# ---------- 吃灰检测 ----------

@app.get("/api/dust")
async def api_dust(request: Request, session: dict = Depends(get_session)):
    cookies = session.get("bili_cookies", {})
    uid = session.get("uid", "")

    async def event_stream():
        try:
            # Phase 1: 抓取收藏夹
            yield f"event: progress\ndata: {json.dumps({'phase': 'favorites', 'count': 0})}\n\n"
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
                for item in items:
                    item["folder_name"] = folder.get("title", "收藏夹")
                all_items.extend(items)
                yield f"event: progress\ndata: {json.dumps({'phase': 'favorites', 'count': len(all_items)})}\n\n"
                await asyncio.sleep(0.3)

            # Phase 2: 抓取观看历史
            yield f"event: progress\ndata: {json.dumps({'phase': 'history', 'count': 0})}\n\n"
            history = await fetch_history(cookies, days=90)
            watched_bvids = {h["bvid"] for h in history}
            bvid_to_view_at = {h["bvid"]: h["view_at"] for h in history}
            yield f"event: progress\ndata: {json.dumps({'phase': 'history', 'count': len(history)})}\n\n"

            # Phase 3: 判定
            now = time.time()
            DUST = 60 * 86400
            LIGHT = 30 * 86400

            dust = []; light = []; watched = []; fresh = []
            for item in all_items:
                fav_time = item.get("fav_time", 0)
                age = now - fav_time
                record = {
                    "bvid": item.get("bvid", ""),
                    "title": item.get("title", ""),
                    "cover": item.get("cover", ""),
                    "upper": item.get("upper", ""),
                    "link": item.get("link", ""),
                    "fav_time": fav_time,
                    "folder_name": item.get("folder_name", ""),
                }
                if item.get("bvid") in watched_bvids:
                    record["view_at"] = bvid_to_view_at[item["bvid"]]
                    record["dust_level"] = "watched"
                    watched.append(record)
                elif age > DUST:
                    record["dust_level"] = "dust"
                    dust.append(record)
                elif age > LIGHT:
                    record["dust_level"] = "light_dust"
                    light.append(record)
                else:
                    record["dust_level"] = "fresh"
                    fresh.append(record)

            result = {
                "total": len(all_items),
                "dust": dust,
                "light_dust": light,
                "watched": watched,
                "fresh": fresh,
            }
            yield f"event: result\ndata: {json.dumps(result)}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
```

顶部 import 加 `import time` 和 `from bili import ..., fetch_history`。

---

### Task 3: console-page.js — 侧边栏加菜单项

**Files:** Modify `frontend/src/console-page.js`

加 import:
```javascript
import { renderDustModule } from "./dust-module.js";
```

侧边栏加菜单项 (在"寻找视频"后面):
```html
<div class="menu-item" data-page="dust">吃灰检测</div>
```

pageMap 加条目:
```javascript
dust: { title: "吃灰检测", render: renderDustModule },
```

---

### Task 4: dust-module.js — 新文件

**Files:** Create `frontend/src/dust-module.js`

EventSource 监听 `/api/dust`，进度条 + 结果展示（统计卡片 + 按吃灰程度排序的视频列表，带颜色标签）。
