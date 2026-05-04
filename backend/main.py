import asyncio
import json
import os
import time

import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth import generate_qrcode, poll_qrcode, get_session, sessions, qrcode_pool
from bili import fetch_fav_folders, fetch_fav_items, search_all, add_favorite, fetch_history
from classifier import classify_favorites
from clean import scan_invalid
from storage import save as storage_save, list_history as storage_list, load as storage_load

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}

app = FastAPI()


async def _scrape_all_folders(uid: str, cookies: dict, folders: list[dict] | None = None) -> list[dict]:
    """遍历所有收藏夹抓取全量视频，返回带 folder_name 的 items 列表"""
    if folders is None:
        folders = await fetch_fav_folders(uid, cookies)
    all_items: list[dict] = []
    for folder in folders:
        fid = folder.get("media_id") or folder.get("id")
        if not fid:
            continue
        items = await fetch_fav_items(fid, cookies)
        for item in items:
            item["folder_name"] = folder.get("title", "收藏夹")
        all_items.extend(items)
    return all_items

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
                folders = [{"id": folder_id, "title": "当前收藏夹"}]
            else:
                folders = session.get("folders") or await fetch_fav_folders(uid, cookies)
                session["folders"] = folders
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

            all_items = await _scrape_all_folders(uid, cookies, folders=folders)
            yield f"event: progress\ndata: {json.dumps({'phase': 'favorites', 'count': len(all_items)})}\n\n"

            yield f"event: progress\ndata: {json.dumps({'phase': 'history', 'count': 0})}\n\n"
            history = await fetch_history(cookies, days=90)
            watched_bvids = {h["bvid"] for h in history}
            bvid_to_view_at = {h["bvid"]: h["view_at"] for h in history}
            yield f"event: progress\ndata: {json.dumps({'phase': 'history', 'count': len(history)})}\n\n"

            now = time.time()
            DUST = 60 * 86400
            LIGHT = 30 * 86400

            dust_list: list[dict] = []
            light_list: list[dict] = []
            watched_list: list[dict] = []
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
                if item.get("bvid") in watched_bvids:
                    rec["view_at"] = bvid_to_view_at[item["bvid"]]
                    rec["dust_level"] = "watched"
                    watched_list.append(rec)
                elif age > DUST:
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
                "watched": watched_list,
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
            yield f"event: progress\ndata: {json.dumps({'phase': 'scanning', 'count': 0})}\n\n"
            invalid = await scan_invalid(cookies, fetch_fav_folders, fetch_fav_items, uid)
            yield f"event: progress\ndata: {json.dumps({'phase': 'done', 'count': len(invalid)})}\n\n"
            yield f"event: result\ndata: {json.dumps({'invalid': invalid, 'total': len(invalid)})}\n\n"
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


class RemoveRequest(BaseModel):
    bvids: list[str]


@app.post("/api/clean/remove")
async def api_clean_remove(req: RemoveRequest, session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        csrf = cookies.get("bili_jct", "")
        jar = httpx.Cookies()
        jar.set("buvid3", "3787611E-2E66-0B20-D062-B6ACF0A5987B22749infoc", domain=".bilibili.com")
        for k, v in cookies.items():
            jar.set(k, v, domain=".bilibili.com")

        removed = 0
        async with httpx.AsyncClient(cookies=jar, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://space.bilibili.com/",
        }) as client:
            for bvid in req.bvids:
                resp = await client.post(
                    "https://api.bilibili.com/x/v3/fav/resource/deal",
                    data={"rid": bvid, "type": "2", "add_media_ids": "", "del_media_ids": "1", "csrf": csrf},
                    timeout=30,
                )
                data = resp.json()
                if data.get("code") == 0:
                    removed += 1
                await asyncio.sleep(0.5)
        return {"removed": removed, "total": len(req.bvids)}
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
        all_items = await _scrape_all_folders(uid, cookies)
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
