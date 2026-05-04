import asyncio
import json
import os
import time

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth import generate_qrcode, poll_qrcode, get_session, sessions, qrcode_pool, on_session_updated
from bili import fetch_fav_folders, fetch_fav_items, fetch_all_items, search_all, add_favorite, _client
from classifier import classify_favorites
from clean import scan_invalid
from storage import save as storage_save, list_history as storage_list, load as storage_load

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

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
        "model": s.get("model", "deepseek-v4-flash"),
    }


class KeyRequest(BaseModel):
    api_key: str


class ModelRequest(BaseModel):
    model: str


@app.get("/api/settings")
async def api_settings(session: dict = Depends(get_session)):
    key = session.get("deepseek_key", "")
    masked = key if len(key) <= 8 else key[:4] + "*" * (len(key) - 8) + key[-4:]
    return {
        "api_key": masked,
        "model": session.get("model", "deepseek-v4-flash"),
    }


@app.post("/api/settings/key")
async def settings_key(req: KeyRequest, session: dict = Depends(get_session)):
    session["deepseek_key"] = req.api_key
    on_session_updated(session)
    return {"success": True}


@app.post("/api/settings/model")
async def settings_model(req: ModelRequest, session: dict = Depends(get_session)):
    session["model"] = req.model
    on_session_updated(session)
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


@app.get("/api/analyze")
async def api_analyze(request: Request, folder_id: int | None = None, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    if not api_key:
        return JSONResponse({"error": "请先绑定 DeepSeek API Key"}, status_code=400)

    cookies = session.get("bili_cookies", {})
    uid = session.get("uid", "")

    async def event_stream():
        try:
            if folder_id:
                items = await fetch_fav_items(folder_id, cookies)
                all_items = items
                yield f"event: progress\ndata: {json.dumps({'folder_name': '当前收藏夹', 'folder_count': len(items), 'total_collected': len(all_items)})}\n\n"
            else:
                folders = session.get("folders") or await fetch_fav_folders(uid, cookies)
                session["folders"] = folders
                if not folders:
                    yield f"event: error\ndata: {json.dumps({'error': '未找到收藏夹'})}\n\n"
                    return

                queue: asyncio.Queue = asyncio.Queue()

                async def on_progress(title: str, count: int, total: int):
                    await queue.put(
                        f"event: progress\ndata: {json.dumps({'folder_name': title, 'folder_count': count, 'total_collected': total})}\n\n"
                    )

                fetch_task = asyncio.create_task(
                    fetch_all_items(uid, cookies, folders=folders, on_progress=on_progress)
                )

                while not fetch_task.done():
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=0.15)
                        yield msg
                    except asyncio.TimeoutError:
                        pass

                # 排空残留的进度事件
                try:
                    while True:
                        yield queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

                all_items = fetch_task.result()

            if not all_items:
                yield f"event: error\ndata: {json.dumps({'error': '收藏夹为空'})}\n\n"
                return

            yield f"event: classifying\ndata: {json.dumps({'total': len(all_items)})}\n\n"

            model = session.get("model", "deepseek-v4-flash")
            result = await classify_favorites(all_items, api_key, model=model)
            yield f"event: result\ndata: {json.dumps(result)}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


# ---------- 吃灰检测 ----------

@app.get("/api/dust")
async def api_dust(request: Request, session: dict = Depends(get_session)):
    cookies = session.get("bili_cookies", {})
    uid = session.get("uid", "")

    async def event_stream():
        try:
            yield f"event: progress\ndata: {json.dumps({'phase': 'favorites', 'count': 0})}\n\n"
            folders = session.get("folders") or await fetch_fav_folders(uid, cookies)
            session["folders"] = folders
            if not folders:
                yield f"event: error\ndata: {json.dumps({'error': '未找到收藏夹'})}\n\n"
                return

            # 收藏夹抓取阶段：通过队列桥接 on_progress → SSE
            fav_queue: asyncio.Queue = asyncio.Queue()

            async def on_fav_progress(title, count, total):
                await fav_queue.put(total)

            fetch_task = asyncio.create_task(
                fetch_all_items(uid, cookies, folders=folders, on_progress=on_fav_progress)
            )

            last_fav = 0
            while not fetch_task.done():
                try:
                    last_fav = await asyncio.wait_for(fav_queue.get(), timeout=0.3)
                    yield f"event: progress\ndata: {json.dumps({'phase': 'favorites', 'count': last_fav})}\n\n"
                except asyncio.TimeoutError:
                    pass

            all_items = fetch_task.result()
            yield f"event: progress\ndata: {json.dumps({'phase': 'favorites', 'count': len(all_items)})}\n\n"

            now = time.time()
            DUST = 60 * 86400
            LIGHT = 30 * 86400

            dust_list: list[dict] = []
            light_list: list[dict] = []
            fresh_list: list[dict] = []
            for item in all_items:
                fav_time = item.get("fav_time", 0)
                age = now - fav_time
                rec = {
                    "bvid": item.get("bvid", ""),
                    "title": item.get("title", ""),
                    "cover": item.get("cover", ""),
                    "upper": item.get("upper", ""),
                    "link": item.get("link", ""),
                    "fav_time": fav_time,
                    "folder_name": item.get("folder_name", ""),
                }
                if age > DUST:
                    rec["dust_level"] = "dust"
                    dust_list.append(rec)
                elif age > LIGHT:
                    rec["dust_level"] = "light_dust"
                    light_list.append(rec)
                else:
                    rec["dust_level"] = "fresh"
                    fresh_list.append(rec)

            result = {
                "total": len(all_items),
                "dust": dust_list,
                "light_dust": light_list,
                "fresh": fresh_list,
            }
            yield f"event: result\ndata: {json.dumps(result)}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)

# ---------- 收藏夹整理 ----------

class SaveRequest(BaseModel):
    folder_name: str = "全部收藏夹"
    categories: list[dict]


@app.get("/api/clean/scan")
async def api_clean_scan(request: Request, session: dict = Depends(get_session)):
    cookies = session.get("bili_cookies", {})
    uid = session.get("uid", "")

    async def event_stream():
        try:
            queue: asyncio.Queue = asyncio.Queue()

            async def on_progress(total: int, checked: int, invalid_count: int):
                await queue.put({"checked": checked, "total": total, "invalid": invalid_count})

            async def do_scan():
                result = await scan_invalid(cookies, uid, on_progress=on_progress)
                await queue.put({"done": True, "result": result})

            asyncio.create_task(do_scan())

            while True:
                msg = await queue.get()
                if msg.get("done"):
                    result = msg["result"]
                    yield f"event: result\ndata: {json.dumps({'invalid': result, 'total': len(result)})}\n\n"
                    break
                yield f"event: progress\ndata: {json.dumps(msg)}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


class RemoveItem(BaseModel):
    bvid: str
    folder_id: int
    media_id: int = 0


class RemoveRequest(BaseModel):
    items: list[RemoveItem]


@app.post("/api/clean/remove")
async def api_clean_remove(req: RemoveRequest, session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        csrf = cookies.get("bili_jct", "")
        if not csrf:
            return {"error": "缺少 bili_jct (csrf) cookie"}

        # 按收藏夹分组
        items_by_folder: dict[int, list[RemoveItem]] = {}
        for item in req.items:
            if item.media_id:
                items_by_folder.setdefault(item.folder_id, []).append(item)

        removed_total = 0
        async with _client(cookies) as client:
            for folder_id, items in items_by_folder.items():
                resources = ",".join(f"{item.media_id}:2" for item in items)
                resp = await client.post(
                    "https://api.bilibili.com/x/v3/fav/resource/batch-del",
                    data={
                        "media_id": folder_id,
                        "resources": resources,
                        "csrf": csrf,
                    },
                    timeout=30,
                )
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                print(f"[clean/remove] folder={folder_id} resources={resources[:100]} => code={data.get('code')} msg={data.get('message')}")
                if data.get("code") == 0:
                    removed_total += len(items)

        return {"removed": removed_total, "total": len(req.items)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/classify/save")
async def api_classify_save(req: SaveRequest, session: dict = Depends(get_session)):
    try:
        payload = {
            "folder_name": req.folder_name,
            "total": sum(len(c.get("items", [])) for c in req.categories),
            "categories": req.categories,
        }
        filename = storage_save(payload)
        return {"success": True, "filename": filename}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/classify/history")
async def api_classify_history(session: dict = Depends(get_session)):
    try:
        return {"history": storage_list()}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/classify/load")
async def api_classify_load(file: str, session: dict = Depends(get_session)):
    try:
        data = storage_load(file)
        if data is None:
            return {"error": "文件不存在"}
        return data
    except Exception as e:
        return {"error": str(e)}


# ---------- 搜索 ----------

@app.get("/api/search/favorites")
async def api_search_favorites(q: str = "", session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        all_items = await fetch_all_items(uid, cookies)
        results = [item for item in all_items
                   if q.lower() in item["title"].lower() or q.lower() in item.get("intro", "").lower()]
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
