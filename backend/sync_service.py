import asyncio
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from bili import _client, fetch_fav_folders, fetch_fav_items
from database import (
    create_sync_job,
    finish_sync_state,
    get_folder_counts,
    get_sync_state,
    mark_missing_folders,
    record_operation,
    replace_folder_snapshot,
    upsert_folder_metadata,
    upsert_user,
    update_sync_job,
)

FULL_RECONCILE_SECONDS = int(os.getenv("FULL_RECONCILE_SECONDS", str(24 * 3600)))
SYNC_TIMEOUT_SECONDS = int(os.getenv("SYNC_TIMEOUT_SECONDS", "600"))
SYNC_RETRIES = int(os.getenv("SYNC_RETRIES", "2"))
SYNC_FOLDER_CONCURRENCY = int(os.getenv("SYNC_FOLDER_CONCURRENCY", "3"))

_user_locks: dict[str, asyncio.Lock] = {}
_tasks: dict[str, asyncio.Task] = {}


def _folder_id(folder: dict) -> int | None:
    value = folder.get("media_id") or folder.get("id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _folder_count(folder: dict) -> int:
    for key in ("media_count", "count", "cnt"):
        try:
            return int(folder.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0


def _needs_full_sync(state: dict, force: bool) -> bool:
    if force or state.get("sync_required") or not state.get("last_full_sync_at"):
        return True
    last_full = state["last_full_sync_at"]
    if isinstance(last_full, datetime):
        return (datetime.now(timezone.utc) - last_full).total_seconds() >= FULL_RECONCILE_SECONDS
    return True


async def start_sync(
    uid: str,
    cookies: dict,
    nickname: str = "",
    avatar: str = "",
    force: bool = False,
) -> dict:
    await upsert_user(uid, nickname, avatar)
    state = await get_sync_state(uid)
    mode = "full" if _needs_full_sync(state, force) else "incremental"
    job_id = secrets.token_urlsafe(16)
    existing = await create_sync_job(job_id, uid, mode)
    if existing is not None:
        return {**existing, "already_running": True}

    task = asyncio.create_task(_run_sync(job_id, uid, cookies, mode == "full"))
    _tasks[job_id] = task
    return {"id": job_id, "status": "queued", "mode": mode, "already_running": False}


async def _run_sync(job_id: str, uid: str, cookies: dict, is_full: bool) -> None:
    lock = _user_locks.setdefault(uid, asyncio.Lock())
    try:
        async with lock:
            await update_sync_job(job_id, status="running", started_at=datetime.now(timezone.utc), message="正在读取收藏夹")
            for attempt in range(SYNC_RETRIES + 1):
                try:
                    async with asyncio.timeout(SYNC_TIMEOUT_SECONDS):
                        stats = await _sync_user(uid, cookies, is_full, job_id)
                    await finish_sync_state(uid, is_full)
                    await update_sync_job(
                        job_id,
                        status="completed",
                        finished_at=datetime.now(timezone.utc),
                        message="同步完成",
                        **stats,
                    )
                    await record_operation(uid, "favorites_sync", {"mode": "full" if is_full else "incremental", **stats})
                    return
                except Exception as exc:
                    if attempt >= SYNC_RETRIES:
                        await update_sync_job(
                            job_id,
                            status="failed",
                            finished_at=datetime.now(timezone.utc),
                            retries=attempt,
                            error_message="同步失败，请稍后重试",
                            message="同步失败",
                        )
                        print(f"[sync] uid={uid} failed: {exc}")
                        return
                    await update_sync_job(job_id, retries=attempt + 1, message="同步失败，正在重试")
                    await asyncio.sleep(2 ** attempt)
    finally:
        _tasks.pop(job_id, None)


async def _sync_user(uid: str, cookies: dict, is_full: bool, job_id: str) -> dict:
    remote_folders = await fetch_fav_folders(uid, cookies)
    valid_folders = [folder for folder in remote_folders if _folder_id(folder) is not None]
    current_counts = await get_folder_counts(uid)
    if not valid_folders and current_counts:
        raise RuntimeError("Bilibili returned no folders; keeping the existing snapshot")
    targets = valid_folders if is_full else [
        folder for folder in valid_folders
        if current_counts.get(_folder_id(folder)) != _folder_count(folder)
    ]
    await update_sync_job(job_id, folders_total=len(targets), message="正在抓取变化的收藏夹")

    semaphore = asyncio.Semaphore(SYNC_FOLDER_CONCURRENCY)

    async with _client(cookies) as client:
        async def fetch_folder(folder: dict) -> tuple[dict, list[dict]]:
            folder_id = _folder_id(folder)
            if folder_id is None:
                return folder, []
            async with semaphore:
                items = await fetch_fav_items(folder_id, cookies, client=client)
            if _folder_count(folder) > 0 and not items:
                raise RuntimeError(f"folder {folder_id} returned no items while metadata reports content")
            for item in items:
                item["folder_id"] = folder_id
                item["folder_name"] = str(folder.get("title") or "收藏夹")
            return folder, items

        snapshots = await asyncio.gather(*(fetch_folder(folder) for folder in targets))

    processed = 0
    item_count = 0
    for folder, items in snapshots:
        await replace_folder_snapshot(uid, folder, items)
        processed += 1
        item_count += len(items)
        await update_sync_job(
            job_id,
            folders_processed=processed,
            items_processed=item_count,
            message="正在写入本地收藏快照",
        )

    await upsert_folder_metadata(uid, valid_folders)
    await mark_missing_folders(uid, [folder_id for folder in valid_folders if (folder_id := _folder_id(folder)) is not None])
    return {"folders_total": len(targets), "folders_processed": processed, "items_processed": item_count}
