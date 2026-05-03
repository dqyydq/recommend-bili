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
