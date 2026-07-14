import asyncio
import json
import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from agents import (
    analyze_favorite_profile,
    build_knowledge_dashboard,
    build_learning_path,
    build_organization_plan,
    rebuild_favorite_index,
)
from auth import COOKIE_SECURE, delete_session, generate_qrcode, poll_qrcode, get_session, sessions, qrcode_pool, on_session_updated
from bili import search_all, add_favorite, _client, normalize_cover_url
from classifier import classify_favorites
from clean import _check_bvid, scan_invalid
from cleanup_service import run_cleanup_scan
from database import (
    approve_organization_plan, close_db, get_favorite_cover, get_favorites, get_folders, get_organization_plan,
    init_db, list_classifications, list_organization_plans, load_classification,
    mark_sync_required, record_operation, save_classification, search_favorites, set_plan_action_state,
    confirm_learning_week, confirm_weekly_review, create_learning_project, delete_learning_project,
    get_learning_project, list_learning_projects, update_learning_task,
    finalize_folder_structure_plan, get_folder_structure_plan, list_folder_structure_plans,
    set_folder_structure_action_state,
    claim_cleanup_scan_execution, create_cleanup_scan, create_topic_analysis, get_cleanup_scan,
    get_latest_cleanup_scan, get_latest_topic_analysis, get_topic_analysis, set_cleanup_item_execution,
    update_cleanup_scan,
    create_user_memory, delete_user_memory, get_agent_session, get_user_memory, list_agent_sessions,
    list_user_memories, save_favorite_feedback, update_user_memory,
    archive_learning_project,
    clear_user_memories, export_user_data, list_proactive_suggestions, pool, update_proactive_suggestion,
)
from folder_structure_agent import build_folder_structure_plan
from learning_project_agent import build_project_review, build_project_week, chat_with_project
from organization_executor import execute_organization_plan
from sync_service import start_sync
from topic_analysis import run_topic_analysis, snapshot_version
from memory_service import present_memory, validate_memory_state, validate_memory_update
from harness import favorite_harness
from model_provider import DEFAULT_MODEL_BASE_URL, create_model_provider
from embedding import EMBEDDING_MODEL, EMBEDDING_PROVIDER, configured_embedding_collection_suffix
from scheduler import scheduler_loop
from demo import DEMO_UID, seed_demo_data

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]

app = FastAPI()


@app.on_event("startup")
async def startup_database() -> None:
    await init_db()
    app.state.scheduler_stop = asyncio.Event()
    app.state.scheduler_task = asyncio.create_task(scheduler_loop(app.state.scheduler_stop))


@app.on_event("shutdown")
async def shutdown_database() -> None:
    if hasattr(app.state, "scheduler_stop"):
        app.state.scheduler_stop.set()
    if hasattr(app.state, "scheduler_task"):
        await app.state.scheduler_task
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


@app.get("/api/health")
async def api_health():
    database_status = "ok"
    try:
        await pool().fetchval("SELECT 1")
    except Exception:
        database_status = "unavailable"
    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "database": database_status,
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_index_suffix": configured_embedding_collection_suffix(),
        "demo_mode": os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"},
    }

# ---------- 登录 ----------

@app.post("/api/auth/qrcode")
async def auth_qrcode():
    result = await generate_qrcode()
    return result


@app.post("/api/demo/session", dependencies=[Depends(require_trusted_origin)])
async def demo_session():
    if os.getenv("DEMO_MODE", "false").lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=404, detail="演示模式未启用")
    await seed_demo_data()
    session_id = os.urandom(16).hex()
    sessions[session_id] = {
        "bili_cookies": {}, "deepseek_key": "", "model": "deepseek-v4-flash",
        "model_base_url": DEFAULT_MODEL_BASE_URL, "uid": DEMO_UID, "nickname": "演示用户", "avatar": "",
        "folders": [], "created_at": time.time(), "expires_at": time.time() + 86400,
    }
    response = JSONResponse({"success": True})
    response.set_cookie("session_id", session_id, httponly=True, max_age=86400, samesite="lax", secure=COOKIE_SECURE, path="/")
    return response


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
        "model_base_url": s.get("model_base_url", DEFAULT_MODEL_BASE_URL),
    }


class KeyRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=256)


class ModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=8, max_length=500)


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


class LearningProjectRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    duration_weeks: int = Field(default=4, ge=1, le=52)
    weekly_minutes: int = Field(default=180, ge=15, le=10080)
    favorite_refs: list[dict] = Field(default_factory=list, max_length=20)
    source_session_id: str | None = Field(default=None, max_length=100)


class LearningTaskUpdateRequest(BaseModel):
    state: str = Field(pattern="^(pending|completed|skipped|blocked)$")
    note: str = Field(default="", max_length=1000)


class LearningChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class FolderStructurePlanRequest(BaseModel):
    goal: str = Field(default="按用途与主题重建收藏夹结构", min_length=1, max_length=500)


class FolderStructureActionRequest(BaseModel):
    state: str = Field(pattern="^(approved|skipped)$")


class TopicAnalysisRequest(BaseModel):
    folder_id: int | None = Field(default=None, gt=0)
    force: bool = False


class CleanupScanRequest(BaseModel):
    force: bool = False


class CleanupExecuteItem(BaseModel):
    folder_id: int = Field(gt=0)
    media_id: int = Field(gt=0)


class CleanupExecuteRequest(BaseModel):
    items: list[CleanupExecuteItem] = Field(min_length=1, max_length=100)


class MemoryCreateRequest(BaseModel):
    memory_type: str = Field(pattern="^(semantic|episodic|procedural)$")
    content: str = Field(min_length=1, max_length=1000)
    source_kind: str = Field(default="explicit", pattern="^(explicit|behavior|project|system)$")
    confidence: float = Field(default=1.0, ge=0, le=1)
    interest_state: str = Field(default="active", pattern="^(active|cooling|dormant|historical)$")
    project_id: str | None = Field(default=None, max_length=100)


class MemoryUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    interest_state: str | None = Field(default=None, pattern="^(active|cooling|dormant|historical)$")
    confirm_as_explicit: bool = False


class FavoriteFeedbackRequest(BaseModel):
    folder_id: int = Field(gt=0)
    media_id: int = Field(gt=0)
    feedback: str = Field(pattern="^(useful|ignored|watched|later)$")
    session_id: str | None = Field(default=None, max_length=100)
    project_id: str | None = Field(default=None, max_length=100)


class HarnessChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=100)
    project_id: str | None = Field(default=None, max_length=100)


class SuggestionUpdateRequest(BaseModel):
    status: str = Field(pattern="^(accepted|dismissed)$")


class ClearMemoriesRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=40)


@app.get("/api/settings")
async def api_settings(session: dict = Depends(get_session)):
    key = session.get("deepseek_key", "")
    masked = "*" * 8 if key and len(key) <= 8 else (key[:4] + "*" * 8 + key[-4:] if key else "")
    return {
        "api_key": masked,
        "model": session.get("model", "deepseek-v4-flash"),
        "base_url": session.get("model_base_url", DEFAULT_MODEL_BASE_URL),
    }


@app.post("/api/settings/key", dependencies=[Depends(require_trusted_origin)])
async def settings_key(req: KeyRequest, session: dict = Depends(get_session)):
    session["deepseek_key"] = req.api_key
    on_session_updated(session)
    return {"success": True}


@app.post("/api/settings/model", dependencies=[Depends(require_trusted_origin)])
async def settings_model(req: ModelRequest, session: dict = Depends(get_session)):
    base_url = req.base_url or session.get("model_base_url", DEFAULT_MODEL_BASE_URL)
    try:
        create_model_provider(session.get("deepseek_key", "placeholder-key"), req.model, base_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session["model"] = req.model
    session["model_base_url"] = base_url.rstrip("/")
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
            result = await classify_favorites(all_items, api_key, model=model, base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL))
            yield f"event: result\ndata: {json.dumps(result)}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/topics/analyses", dependencies=[Depends(require_trusted_origin)])
async def api_create_topic_analysis(req: TopicAnalysisRequest, session: dict = Depends(get_session)):
    uid = session.get("uid", "")
    items = await get_favorites(uid, req.folder_id)
    if not items:
        raise HTTPException(status_code=409, detail="本地收藏快照为空，请先执行同步")
    api_key = session.get("deepseek_key", "")
    version = snapshot_version(items)
    if req.force:
        version = f"{version}-{int(time.time())}"
    analysis, cached = await create_topic_analysis(uid, req.folder_id, version, len(items))
    if analysis["status"] == "queued":
        asyncio.create_task(run_topic_analysis(
            analysis["id"], items, api_key, session.get("model", "deepseek-v4-flash"),
            session.get("model_base_url", DEFAULT_MODEL_BASE_URL),
        ))
    return {"analysis": analysis, "cached": cached}


@app.get("/api/topics/analyses/latest")
async def api_latest_topic_analysis(folder_id: int | None = None, session: dict = Depends(get_session)):
    analysis = await get_latest_topic_analysis(session.get("uid", ""), folder_id)
    return {"analysis": analysis}


@app.get("/api/topics/analyses/{analysis_id}")
async def api_topic_analysis(analysis_id: str, session: dict = Depends(get_session)):
    analysis = await get_topic_analysis(session.get("uid", ""), analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="主题分析不存在")
    return {"analysis": analysis}


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


@app.post("/api/clean/scans", dependencies=[Depends(require_trusted_origin)])
async def api_create_cleanup_scan(req: CleanupScanRequest, session: dict = Depends(get_session)):
    uid = session.get("uid", "")
    items = await get_favorites(uid)
    if not items:
        raise HTTPException(status_code=409, detail="本地收藏快照为空，请先执行同步")
    scan, reused = await create_cleanup_scan(uid, len(items))
    if scan["status"] == "queued":
        asyncio.create_task(run_cleanup_scan(scan["id"], session.get("bili_cookies", {}), items))
    return {"scan": scan, "reused": reused}


@app.get("/api/clean/scans/latest")
async def api_latest_cleanup_scan(session: dict = Depends(get_session)):
    return {"scan": await get_latest_cleanup_scan(session.get("uid", ""))}


@app.get("/api/clean/scans/{scan_id}")
async def api_cleanup_scan(scan_id: str, session: dict = Depends(get_session)):
    scan = await get_cleanup_scan(session.get("uid", ""), scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="清理扫描不存在")
    return {"scan": scan}


@app.post("/api/clean/scans/{scan_id}/execute", dependencies=[Depends(require_trusted_origin)])
async def api_execute_cleanup_scan(scan_id: str, req: CleanupExecuteRequest, session: dict = Depends(get_session)):
    uid = session.get("uid", "")
    cookies = session.get("bili_cookies", {})
    csrf = cookies.get("bili_jct", "")
    if not csrf:
        raise HTTPException(status_code=400, detail="缺少 bili_jct (csrf) cookie")
    requested = [(item.folder_id, item.media_id) for item in req.items]
    candidates = await claim_cleanup_scan_execution(uid, scan_id, requested)
    if candidates is None:
        raise HTTPException(status_code=409, detail="扫描不存在、未完成或正在执行")

    removed = 0
    skipped = 0
    failed = 0
    try:
        async with _client(cookies) as client:
            for item in candidates:
                folder_id = int(item["folder_id"])
                media_id = int(item["media_id"])
                status = await _check_bvid(item["bvid"], client)
                if status != "invalid":
                    skipped += 1
                    await set_cleanup_item_execution(scan_id, folder_id, media_id, "skipped", "执行前复核未确认失效")
                    continue
                resp = await client.post(
                    "https://api.bilibili.com/x/v3/fav/resource/batch-del",
                    data={"media_id": folder_id, "resources": f"{media_id}:2", "csrf": csrf},
                    timeout=30,
                )
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if data.get("code") == 0:
                    removed += 1
                    await set_cleanup_item_execution(scan_id, folder_id, media_id, "removed", "已从收藏夹移除")
                else:
                    failed += 1
                    await set_cleanup_item_execution(scan_id, folder_id, media_id, "failed", str(data.get("message") or "B站删除失败"))
    finally:
        await update_cleanup_scan(scan_id, status="completed", message="执行完成", finished_at=datetime.now(timezone.utc))

    if removed:
        await mark_sync_required(uid)
        await record_operation(uid, "execute_cleanup_scan", {"scan_id": scan_id, "removed": removed, "skipped": skipped, "failed": failed})
    return {"scan": await get_cleanup_scan(uid, scan_id), "removed": removed, "skipped": skipped, "failed": failed}


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


_COVER_HOST_SUFFIXES = (".hdslb.com", ".bilibili.com")
_MAX_COVER_BYTES = 5 * 1024 * 1024


@app.get("/api/favorites/{folder_id}/{media_id}/cover")
async def api_favorite_cover(folder_id: int, media_id: int, session: dict = Depends(get_session)):
    """Proxy a stored Bilibili cover without accepting arbitrary remote URLs."""
    from urllib.parse import urlparse

    cover = normalize_cover_url(await get_favorite_cover(session.get("uid", ""), folder_id, media_id))
    parsed = urlparse(cover)
    if not cover or parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(_COVER_HOST_SUFFIXES):
        raise HTTPException(status_code=404, detail="封面不可用")
    try:
        async with _client(session.get("bili_cookies", {}), {"Referer": "https://www.bilibili.com/"}) as client:
            remote = await client.get(cover, timeout=12)
            remote.raise_for_status()
            content_type = remote.headers.get("content-type", "")
            if not content_type.startswith("image/") or len(remote.content) > _MAX_COVER_BYTES:
                raise HTTPException(status_code=404, detail="封面不可用")
            return Response(remote.content, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="封面不可用")


# ---------- Agent 能力 ----------

@app.post("/api/agents/chat", dependencies=[Depends(require_trusted_origin)])
async def api_agent_chat(req: HarnessChatRequest, session: dict = Depends(get_session)):
    try:
        return await favorite_harness.chat(
            uid=session.get("uid", ""), cookies=session.get("bili_cookies", {}), message=req.message,
            api_key=session.get("deepseek_key", ""), model=session.get("model", "deepseek-v4-flash"),
            session_id=req.session_id, project_id=req.project_id, base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/agents/sessions")
async def api_agent_sessions(session: dict = Depends(get_session)):
    return {"sessions": await list_agent_sessions(session.get("uid", ""))}


@app.get("/api/agents/sessions/{session_id}")
async def api_agent_session(session_id: str, session: dict = Depends(get_session)):
    data = await get_agent_session(session.get("uid", ""), session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"session": data}


@app.get("/api/agents/memories")
async def api_agent_memories(include_outdated: bool = True, session: dict = Depends(get_session)):
    memories = await list_user_memories(session.get("uid", ""), include_outdated=include_outdated)
    return {"memories": [present_memory(memory) for memory in memories]}


@app.post("/api/agents/memories/clear", dependencies=[Depends(require_trusted_origin)])
async def api_clear_agent_memories(req: ClearMemoriesRequest, session: dict = Depends(get_session)):
    if req.confirmation != "CLEAR MEMORIES":
        raise HTTPException(status_code=422, detail="请输入 CLEAR MEMORIES 确认清空")
    count = await clear_user_memories(session.get("uid", ""))
    return {"cleared": count}


@app.get("/api/agents/suggestions")
async def api_agent_suggestions(session: dict = Depends(get_session)):
    return {"suggestions": await list_proactive_suggestions(session.get("uid", ""))}


@app.post("/api/agents/suggestions/{suggestion_id}", dependencies=[Depends(require_trusted_origin)])
async def api_update_agent_suggestion(suggestion_id: str, req: SuggestionUpdateRequest, session: dict = Depends(get_session)):
    suggestion = await update_proactive_suggestion(session.get("uid", ""), suggestion_id, req.status)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="建议不存在或已经处理")
    return {"suggestion": suggestion}


@app.get("/api/data/export")
async def api_export_data(session: dict = Depends(get_session)):
    return {
        "exported_at": datetime.now(timezone.utc),
        "schema_version": "0.2.0-harness",
        "data": await export_user_data(session.get("uid", "")),
    }


@app.post("/api/agents/memories", dependencies=[Depends(require_trusted_origin)])
async def api_create_agent_memory(req: MemoryCreateRequest, session: dict = Depends(get_session)):
    try:
        validate_memory_state(req.source_kind, req.interest_state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    memory = await create_user_memory(
        session.get("uid", ""), req.memory_type, req.content, req.source_kind, req.confidence,
        interest_state=req.interest_state, project_id=req.project_id,
        evidence=[{"evidence_type": "user_statement", "excerpt": req.content}] if req.source_kind == "explicit" else None,
    )
    return {"memory": present_memory(memory)}


@app.patch("/api/agents/memories/{memory_id}", dependencies=[Depends(require_trusted_origin)])
async def api_update_agent_memory(memory_id: str, req: MemoryUpdateRequest, session: dict = Depends(get_session)):
    uid = session.get("uid", "")
    memory = await get_user_memory(uid, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    changes = req.model_dump(exclude_unset=True, exclude={"confirm_as_explicit"})
    if req.confirm_as_explicit:
        changes["source_kind"] = "explicit"
        changes["last_confirmed_at"] = datetime.now(timezone.utc)
    candidate = {**memory, **changes}
    try:
        validate_memory_update(candidate, changes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated = await update_user_memory(uid, memory_id, **changes)
    return {"memory": present_memory(updated or memory)}


@app.post("/api/agents/memories/{memory_id}/outdate", dependencies=[Depends(require_trusted_origin)])
async def api_outdate_agent_memory(memory_id: str, session: dict = Depends(get_session)):
    memory = await update_user_memory(session.get("uid", ""), memory_id, status="outdated")
    if memory is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"memory": present_memory(memory)}


@app.post("/api/agents/memories/{memory_id}/restore", dependencies=[Depends(require_trusted_origin)])
async def api_restore_agent_memory(memory_id: str, session: dict = Depends(get_session)):
    memory = await update_user_memory(session.get("uid", ""), memory_id, status="active")
    if memory is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"memory": present_memory(memory)}


@app.delete("/api/agents/memories/{memory_id}", dependencies=[Depends(require_trusted_origin)])
async def api_delete_agent_memory(memory_id: str, session: dict = Depends(get_session)):
    if not await delete_user_memory(session.get("uid", ""), memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"deleted": True}


@app.post("/api/agents/feedback", dependencies=[Depends(require_trusted_origin)])
async def api_agent_feedback(req: FavoriteFeedbackRequest, session: dict = Depends(get_session)):
    uid = session.get("uid", "")
    favorites = await get_favorites(uid, req.folder_id)
    if not any(int(item.get("id") or 0) == req.media_id for item in favorites):
        raise HTTPException(status_code=404, detail="收藏条目不存在")
    if req.session_id and await get_agent_session(uid, req.session_id) is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    if req.project_id and await get_learning_project(uid, req.project_id) is None:
        raise HTTPException(status_code=404, detail="学习项目不存在")
    feedback = await save_favorite_feedback(
        uid, req.folder_id, req.media_id, req.feedback, req.session_id, req.project_id,
    )
    return {"feedback": feedback}

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
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        folders = await get_folders(uid)
        session["folders"] = folders
        model = session.get("model", "deepseek-v4-flash")
        return await analyze_favorite_profile(
            uid, cookies, api_key, model, folders=folders,
            base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL),
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/agents/learning-path")
async def api_agent_learning_path(req: LearningPathRequest, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
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
            base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL),
        )
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/agents/learning-projects")
async def api_learning_projects(session: dict = Depends(get_session)):
    return {"projects": await list_learning_projects(session.get("uid", ""))}


@app.post("/api/agents/learning-projects", dependencies=[Depends(require_trusted_origin)])
async def api_create_learning_project(req: LearningProjectRequest, session: dict = Depends(get_session)):
    uid = session.get("uid", "")
    if req.source_session_id and await get_agent_session(uid, req.source_session_id) is None:
        raise HTTPException(status_code=404, detail="来源对话不存在")
    refs = []
    for item in req.favorite_refs[:20]:
        refs.append({key: item.get(key) for key in ("folder_id", "media_id", "bvid", "title", "upper", "folder_name", "link") if item.get(key) is not None})
    project = await create_learning_project(
        uid, req.goal, req.duration_weeks, req.weekly_minutes,
        context={"favorite_refs": refs}, source_session_id=req.source_session_id,
    )
    await create_user_memory(
        uid, "semantic", f"当前学习目标：{req.goal}", "project", 1.0,
        interest_state="active", project_id=project.get("id"),
        evidence=[{"evidence_type": "learning_project", "reference_id": project.get("id", ""), "excerpt": req.goal}],
    )
    await record_operation(session.get("uid", ""), "create_learning_project", {"project_id": project.get("id", "")})
    return project


@app.post("/api/agents/learning-projects/{project_id}/archive", dependencies=[Depends(require_trusted_origin)])
async def api_archive_learning_project(project_id: str, session: dict = Depends(get_session)):
    project = await archive_learning_project(session.get("uid", ""), project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="学习项目不存在或已经归档")
    await record_operation(session.get("uid", ""), "archive_learning_project", {"project_id": project_id})
    return project


@app.get("/api/agents/learning-projects/{project_id}")
async def api_learning_project(project_id: str, session: dict = Depends(get_session)):
    project = await get_learning_project(session.get("uid", ""), project_id)
    if project is None:
        return JSONResponse({"error": "学习项目不存在"}, status_code=404)
    return project


@app.delete("/api/agents/learning-projects/{project_id}", dependencies=[Depends(require_trusted_origin)])
async def api_delete_learning_project(project_id: str, session: dict = Depends(get_session)):
    if not await delete_learning_project(session.get("uid", ""), project_id):
        return JSONResponse({"error": "学习项目不存在"}, status_code=404)
    await record_operation(session.get("uid", ""), "delete_learning_project", {"project_id": project_id})
    return {"success": True}


@app.post("/api/agents/learning-projects/{project_id}/plan", dependencies=[Depends(require_trusted_origin)])
async def api_learning_project_plan(project_id: str, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    project = await build_project_week(session.get("uid", ""), project_id, session.get("bili_cookies", {}), api_key, session.get("model", "deepseek-chat"), base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL))
    if project is None:
        return JSONResponse({"error": "学习项目不存在"}, status_code=404)
    return project


@app.post("/api/agents/learning-projects/{project_id}/weeks/{week_number}/confirm", dependencies=[Depends(require_trusted_origin)])
async def api_confirm_learning_week(project_id: str, week_number: int, session: dict = Depends(get_session)):
    project = await confirm_learning_week(session.get("uid", ""), project_id, week_number)
    if project is None:
        return JSONResponse({"error": "没有可确认的计划草稿"}, status_code=409)
    return project


@app.post("/api/agents/learning-projects/{project_id}/tasks/{task_id}", dependencies=[Depends(require_trusted_origin)])
async def api_update_learning_task(project_id: str, task_id: str, req: LearningTaskUpdateRequest, session: dict = Depends(get_session)):
    project = await update_learning_task(session.get("uid", ""), project_id, task_id, req.state, req.note)
    if project is None:
        return JSONResponse({"error": "任务不存在或尚未确认"}, status_code=404)
    return project


@app.post("/api/agents/learning-projects/{project_id}/chat", dependencies=[Depends(require_trusted_origin)])
async def api_learning_project_chat(project_id: str, req: LearningChatRequest, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    project = await chat_with_project(session.get("uid", ""), project_id, session.get("bili_cookies", {}), req.message, api_key, session.get("model", "deepseek-chat"), base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL))
    if project is None:
        return JSONResponse({"error": "学习项目不存在"}, status_code=404)
    return project


@app.post("/api/agents/learning-projects/{project_id}/review", dependencies=[Depends(require_trusted_origin)])
async def api_learning_project_review(project_id: str, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    project = await build_project_review(session.get("uid", ""), project_id, session.get("bili_cookies", {}), api_key, session.get("model", "deepseek-chat"), base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL))
    if project is None:
        return JSONResponse({"error": "学习项目不存在"}, status_code=404)
    return project


@app.post("/api/agents/learning-projects/{project_id}/reviews/{week_number}/confirm", dependencies=[Depends(require_trusted_origin)])
async def api_confirm_learning_review(project_id: str, week_number: int, session: dict = Depends(get_session)):
    project = await confirm_weekly_review(session.get("uid", ""), project_id, week_number)
    if project is None:
        return JSONResponse({"error": "没有可确认的周回顾草稿"}, status_code=409)
    return project


@app.post("/api/agents/organization-plans", dependencies=[Depends(require_trusted_origin)])
async def api_organization_plan(req: OrganizationPlanRequest, session: dict = Depends(get_session)):
    api_key = session.get("deepseek_key", "")
    try:
        return await build_organization_plan(
            session.get("uid", ""),
            req.goal,
            api_key,
            session.get("model", "deepseek-v4-flash"),
            req.max_actions,
            base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL),
        )
    except Exception as exc:
        print(f"[organization_plan] failed: {exc}")
        return {"error": "整理计划生成失败，请稍后重试"}


@app.post("/api/agents/folder-structure-plans", dependencies=[Depends(require_trusted_origin)])
async def api_folder_structure_plan(req: FolderStructurePlanRequest, session: dict = Depends(get_session)):
    plan = await build_folder_structure_plan(session.get("uid", ""), req.goal)
    if plan.get("error"):
        return JSONResponse(plan, status_code=400)
    await record_operation(session.get("uid", ""), "build_folder_structure_plan", {"plan_id": plan.get("id", ""), "actions": plan.get("action_count", 0)})
    return plan


@app.get("/api/agents/folder-structure-plans")
async def api_folder_structure_plans(session: dict = Depends(get_session)):
    return {"plans": await list_folder_structure_plans(session.get("uid", ""))}


@app.get("/api/agents/folder-structure-plans/{plan_id}")
async def api_folder_structure_plan_detail(plan_id: str, session: dict = Depends(get_session)):
    plan = await get_folder_structure_plan(session.get("uid", ""), plan_id)
    if plan is None:
        return JSONResponse({"error": "结构蓝图不存在"}, status_code=404)
    return plan


@app.post("/api/agents/folder-structure-plans/{plan_id}/actions/{action_id}", dependencies=[Depends(require_trusted_origin)])
async def api_folder_structure_action(plan_id: str, action_id: str, req: FolderStructureActionRequest, session: dict = Depends(get_session)):
    plan = await set_folder_structure_action_state(session.get("uid", ""), plan_id, action_id, req.state)
    if plan is None:
        return JSONResponse({"error": "目标文件夹不存在或蓝图已确认"}, status_code=409)
    return plan


@app.post("/api/agents/folder-structure-plans/{plan_id}/finalize", dependencies=[Depends(require_trusted_origin)])
async def api_finalize_folder_structure_plan(plan_id: str, session: dict = Depends(get_session)):
    plan = await finalize_folder_structure_plan(session.get("uid", ""), plan_id)
    if plan is None:
        return JSONResponse({"error": "蓝图不存在或已确认"}, status_code=409)
    await record_operation(session.get("uid", ""), "review_folder_structure_plan", {"plan_id": plan_id})
    return plan


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


@app.post("/api/agents/search", dependencies=[Depends(require_trusted_origin)])
async def api_agent_search(req: SemanticSearchRequest, session: dict = Depends(get_session)):
    try:
        cookies = session.get("bili_cookies", {})
        uid = session.get("uid", "")
        if req.refresh:
            await rebuild_favorite_index(uid, cookies, folders=await get_folders(uid))
        response = await favorite_harness.chat(
            uid=uid, cookies=cookies, message=req.q, api_key=session.get("deepseek_key", ""),
            model=session.get("model", "deepseek-v4-flash"), base_url=session.get("model_base_url", DEFAULT_MODEL_BASE_URL),
        )
        return {
            "answer": response["answer_markdown"],
            "results": response["citations"][:req.top_k],
            "session_id": response["session_id"],
            "run_id": response["run_id"],
        }
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


_FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.isfile(os.path.join(_FRONTEND_DIST, "index.html")):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
