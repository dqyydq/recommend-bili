import asyncio
import json
import os
import time

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from agents import (
    analyze_favorite_profile,
    build_knowledge_dashboard,
    build_learning_path,
    build_organization_plan,
    rebuild_favorite_index,
    semantic_search_favorites,
)
from auth import COOKIE_SECURE, delete_session, generate_qrcode, poll_qrcode, get_session, sessions, qrcode_pool, on_session_updated
from bili import search_all, add_favorite, _client
from classifier import classify_favorites
from clean import _check_bvid, scan_invalid
from database import (
    approve_organization_plan, close_db, get_favorites, get_folders, get_organization_plan,
    init_db, list_classifications, list_organization_plans, load_classification,
    mark_sync_required, record_operation, save_classification, search_favorites, set_plan_action_state,
)
from organization_executor import execute_organization_plan
from sync_service import start_sync

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]

app = FastAPI()


@app.on_event("startup")
async def startup_database() -> None:
    await init_db()


@app.on_event("shutdown")
async def shutdown_database() -> None:
    await close_db()


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="不受信任的请求来源")

# ---------- 登录 ----------

@app.post("/api/auth/qrcode")
async def auth_qrcode():
    result = await generate_qrcode()
    return result


@app.get("/api/auth/qrcode/{key}/poll")
async def auth_poll(key: str):
    result = await poll_qrcode(key)
    if result.get("session_id"):
        session = sessions[result["session_id"]]
        sync = await start_sync(
            session["uid"],
            session.get("bili_cookies", {}),
            session.get("nickname", ""),
            session.get("avatar", ""),
            force=True,
        )
        result["sync_job"] = sync
        resp = JSONResponse(result)
        resp.set_cookie(
            key="session_id",
            value=result["session_id"],
            httponly=True,
            max_age=86400 * 7,
            samesite="lax",
            secure=COOKIE_SECURE,
            path="/",
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
    api_key: str = Field(min_length=8, max_length=256)


class ModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=100)


class SemanticSearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=20)
    refresh: bool = False


class LearningPathRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    refresh: bool = False


class OrganizationPlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    max_actions: int = Field(default=12, ge=1, le=30)


class PlanActionStateRequest(BaseModel):
    state: str = Field(pattern="^(approved|skipped)$")


@app.get("/api/settings")
async def api_settings(session: dict = Depends(get_session)):
    key = session.get("deepseek_key", "")
    masked = "*" * 8 if key and len(key) <= 8 else (key[:4] + "*" * 8 + key[-4:] if key else "")
    return {
        "api_key": masked,
        "model": session.get("model", "deepseek-v4-flash"),
    }


@app.post("/api/settings/key", dependencies=[Depends(require_trusted_origin)])
async def settings_key(req: KeyRequest, session: dict = Depends(get_session)):
    session["deepseek_key"] = req.api_key
    on_session_updated(session)
    return {"success": True}


@app.post("/api/settings/model", dependencies=[Depends(require_trusted_origin)])
async def settings_model(req: ModelRequest, session: dict = Depends(get_session)):
    session["model"] = req.model
    on_session_updated(session)
    return {"success": True}


# ---------- B站数据 ----------

class SyncRequest(BaseModel):
    force: bool = False


@app.post("/api/sync", dependencies=[Depends(require_trusted_origin)])
async def api_sync(req: SyncRequest, session: dict = Depends(get_session)):
    return await start_sync(
        session.get("uid", ""),
        session.get("bili_cookies", {}),
        session.get("nickname", ""),
        session.get("avatar", ""),
        force=req.force,
    )


@app.get("/api/sync/status")
async def api_sync_status(session: dict = Depends(get_session)):
    from database import get_sync_job, get_sync_state

    uid = session.get("uid", "")
    return {"state": await get_sync_state(uid), "job": await get_sync_job(uid)}

@app.get("/api/folders")
async def api_folders(session: dict = Depends(get_session)):
    try:
        uid = session.get("uid", "")
        folders = await get_folders(uid)
        session["folders"] = folders
        return {"folders": folders}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/favorites")
async def api_favorites(folder_id: int, session: dict = Depends(get_session)):
    try:
        items = await get_favorites(session.get("uid", ""), folder_id)
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
                all_items = await get_favorites(uid, folder_id)
                yield f"event: progress\ndata: {json.dumps({'folder_name': '当前收藏夹', 'folder_count': len(all_items), 'total_collected': len(all_items)})}\n\n"
            else:
                all_items = await get_favorites(uid)
                yield f"event: progress\ndata: {json.dumps({'folder_name': '本地收藏快照', 'folder_count': len(all_items), 'total_collected': len(all_items)})}\n\n"

            if not all_items:
                yield f"event: error\ndata: {json.dumps({'error': '本地收藏快照为空，请先执行同步'})}\n\n"
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
            all_items = await get_favorites(uid)
            if not all_items:
                yield f"event: error\ndata: {json.dumps({'error': '本地收藏快照为空，请先执行同步'})}\n\n"
                return
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

            async def on_progress(total: int, checked: int, invalid_count: int, unknown_count: int):
                await queue.put({"checked": checked, "total": total, "invalid": invalid_count, "unknown": unknown_count})

            async def do_scan():
                try:
                    items = await get_favorites(uid)
                    result = await scan_invalid(cookies, items, on_progress=on_progress)
                    await queue.put({"done": True, "result": result})
                except Exception as exc:
                    await queue.put({"done": True, "error": "扫描失败，请稍后重试"})
                    print(f"[clean] scan failed: {exc}")

            asyncio.create_task(do_scan())

            while True:
                msg = await queue.get()
                if msg.get("done"):
                    if msg.get("error"):
                        yield f"event: error\ndata: {json.dumps({'error': msg['error']})}\n\n"
                        break
                    result = msg["result"]
                    yield f"event: result\ndata: {json.dumps(result)}\n\n"
                    break
                yield f"event: progress\ndata: {json.dumps(msg)}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


class RemoveItem(BaseModel):
    bvid: str = Field(min_length=1, max_length=32)
    folder_id: int = Field(gt=0)
    media_id: int = Field(gt=0)


class RemoveRequest(BaseModel):
    items: list[RemoveItem] = Field(min_length=1, max_length=100)


@app.post("/api/clean/remove", dependencies=[Depends(require_trusted_origin)])
async def api_clean_remove(req: RemoveRequest, session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        csrf = cookies.get("bili_jct", "")
        if not csrf:
            return {"error": "缺少 bili_jct (csrf) cookie"}

        # Re-check every candidate: client input must never be enough to delete a favorite.
        items_by_folder: dict[int, list[RemoveItem]] = {}
        removed_total = 0
        skipped_total = 0
        async with _client(cookies) as client:
            statuses = await asyncio.gather(*(_check_bvid(item.bvid, client) for item in req.items))
            for item, status in zip(req.items, statuses):
                if status == "invalid":
                    items_by_folder.setdefault(item.folder_id, []).append(item)
                else:
                    skipped_total += 1

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

        if removed_total:
            await mark_sync_required(session.get("uid", ""))
            await record_operation(session.get("uid", ""), "remove_invalid_favorites", {"removed": removed_total})
        return {"removed": removed_total, "skipped": skipped_total, "total": len(req.items)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/classify/save", dependencies=[Depends(require_trusted_origin)])
async def api_classify_save(req: SaveRequest, session: dict = Depends(get_session)):
    try:
        filename = await save_classification(session.get("uid", ""), req.folder_name, req.categories)
        return {"success": True, "filename": filename}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/classify/history")
async def api_classify_history(session: dict = Depends(get_session)):
    try:
        return {"history": await list_classifications(session.get("uid", ""))}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/classify/load")
async def api_classify_load(file: str, session: dict = Depends(get_session)):
    try:
        data = await load_classification(session.get("uid", ""), file)
        if data is None:
            return {"error": "文件不存在"}
        return data
    except Exception as e:
        return {"error": str(e)}


# ---------- 搜索 ----------

@app.get("/api/search/favorites")
async def api_search_favorites(q: str = "", session: dict = Depends(get_session)):
    try:
        uid = session.get("uid", "")
        results = await search_favorites(uid, q)
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


@app.post("/api/favorites/add", dependencies=[Depends(require_trusted_origin)])
async def api_favorites_add(req: AddFavoriteRequest, session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        result = await add_favorite(req.bvid, req.folder_id, cookies)
        if result.get("success"):
            await mark_sync_required(session.get("uid", ""))
            await record_operation(session.get("uid", ""), "add_favorite", {"bvid": req.bvid, "folder_id": req.folder_id})
        return result
    except Exception as e:
        return {"error": str(e)}


# ---------- Agent 能力 ----------

@app.get("/api/agents/dashboard")
async def api_agent_dashboard(session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        folders = await get_folders(uid)
        session["folders"] = folders
        return await build_knowledge_dashboard(uid, cookies, folders=folders)
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/agents/profile")
async def api_agent_profile(session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    if not api_key:
        return JSONResponse({"error": "请先绑定 DeepSeek API Key"}, status_code=400)
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        folders = await get_folders(uid)
        session["folders"] = folders
        model = session.get("model", "deepseek-v4-flash")
        return await analyze_favorite_profile(uid, cookies, api_key, model, folders=folders)
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/agents/learning-path")
async def api_agent_learning_path(req: LearningPathRequest, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    if not api_key:
        return JSONResponse({"error": "请先绑定 DeepSeek API Key"}, status_code=400)
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        folders = await get_folders(uid)
        session["folders"] = folders
        model = session.get("model", "deepseek-v4-flash")
        return await build_learning_path(
            uid,
            cookies,
            req.goal,
            api_key,
            model,
            folders=folders,
            refresh=req.refresh,
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/agents/organization-plans", dependencies=[Depends(require_trusted_origin)])
async def api_organization_plan(req: OrganizationPlanRequest, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    if not api_key:
        return JSONResponse({"error": "请先绑定 DeepSeek API Key"}, status_code=400)
    try:
        return await build_organization_plan(
            session.get("uid", ""),
            req.goal,
            api_key,
            session.get("model", "deepseek-v4-flash"),
            req.max_actions,
        )
    except Exception as exc:
        print(f"[organization_plan] failed: {exc}")
        return {"error": "整理计划生成失败，请稍后重试"}


@app.get("/api/agents/organization-plans")
async def api_organization_plans(session: dict = Depends(get_session)):
    return {"plans": await list_organization_plans(session.get("uid", ""))}


@app.get("/api/agents/organization-plans/{plan_id}")
async def api_organization_plan_detail(plan_id: str, session: dict = Depends(get_session)):
    plan = await get_organization_plan(session.get("uid", ""), plan_id)
    if plan is None:
        return JSONResponse({"error": "整理计划不存在"}, status_code=404)
    return plan


@app.post("/api/agents/organization-plans/{plan_id}/actions/{action_id}", dependencies=[Depends(require_trusted_origin)])
async def api_organization_plan_action(
    plan_id: str,
    action_id: str,
    req: PlanActionStateRequest,
    session: dict = Depends(get_session),
):
    plan = await set_plan_action_state(session.get("uid", ""), plan_id, action_id, req.state)
    if plan is None:
        return JSONResponse({"error": "动作不存在或计划已确认"}, status_code=409)
    return plan


@app.post("/api/agents/organization-plans/{plan_id}/approve", dependencies=[Depends(require_trusted_origin)])
async def api_organization_plan_approve(plan_id: str, session: dict = Depends(get_session)):
    plan = await approve_organization_plan(session.get("uid", ""), plan_id)
    if plan is None:
        return JSONResponse({"error": "计划不存在或已确认"}, status_code=409)
    await record_operation(session.get("uid", ""), "approve_organization_plan", {"plan_id": plan_id})
    return plan


@app.post("/api/agents/organization-plans/{plan_id}/execute", dependencies=[Depends(require_trusted_origin)])
async def api_organization_plan_execute(plan_id: str, session: dict = Depends(get_session)):
    cookies = session.get("bili_cookies", {})
    if not cookies.get("bili_jct"):
        return JSONResponse({"error": "Missing Bilibili CSRF cookie. Please log in again."}, status_code=400)

    result = await execute_organization_plan(session.get("uid", ""), plan_id, cookies)
    plan = result.get("plan")
    if plan is None:
        return JSONResponse({"error": "Organization plan not found."}, status_code=404)

    counts = result.get("counts", {})
    if result.get("claimed") and counts.get("deleted", 0):
        uid = session.get("uid", "")
        await mark_sync_required(uid)
        await record_operation(uid, "execute_organization_plan", {"plan_id": plan_id, **counts})
        await start_sync(uid, cookies, session.get("nickname", ""), session.get("avatar", ""))
    return {**plan, "execution_counts": counts, "execution_started": bool(result.get("claimed"))}


@app.post("/api/agents/search/index", dependencies=[Depends(require_trusted_origin)])
async def api_agent_search_index(session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        folders = await get_folders(uid)
        session["folders"] = folders
        return await rebuild_favorite_index(uid, cookies, folders=folders)
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/agents/search")
async def api_agent_search(req: SemanticSearchRequest, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    if not api_key:
        return JSONResponse({"error": "请先绑定 DeepSeek API Key"}, status_code=400)
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        folders = await get_folders(uid)
        session["folders"] = folders
        model = session.get("model", "deepseek-v4-flash")
        return await semantic_search_favorites(
            uid,
            cookies,
            req.q,
            api_key,
            model,
            folders=folders,
            top_k=req.top_k,
            refresh=req.refresh,
        )
    except Exception as e:
        return {"error": str(e)}


# ---------- 退出 ----------

@app.post("/api/auth/logout", dependencies=[Depends(require_trusted_origin)])
async def auth_logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        delete_session(session_id)
    resp = JSONResponse({"success": True})
    resp.delete_cookie("session_id", path="/")
    return resp


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
