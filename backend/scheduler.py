import asyncio
import json
import os
import secrets
from datetime import datetime, timezone

from database import pool


SCHEDULER_INTERVAL_SECONDS = max(60, int(os.getenv("PROACTIVE_INTERVAL_SECONDS", "3600")))


async def generate_proactive_suggestions() -> int:
    """Create local drafts only. This function never calls a mutating Bilibili API."""
    created = 0
    async with pool().acquire() as conn:
        locked = await conn.fetchval("SELECT pg_try_advisory_lock(hashtext('favorite-agent-proactive-scheduler'))")
        if not locked:
            return 0
        try:
            users = await conn.fetch("SELECT uid FROM users")
            now = datetime.now(timezone.utc)
            day_key = now.strftime("%Y-%m-%d")
            week_key = now.strftime("%G-W%V")
            for user in users:
                uid = str(user["uid"])
                project = await conn.fetchrow(
                    "SELECT id, goal, current_week FROM learning_projects WHERE uid = $1 AND status = 'active' ORDER BY updated_at DESC LIMIT 1", uid,
                )
                favorite_count = int(await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE uid = $1 AND is_active = TRUE", uid) or 0)
                daily_title = "继续当前学习目标" if project else "从收藏里挑一件今天要做的事"
                daily_body = f"继续「{project['goal']}」第 {project['current_week']} 周。" if project else f"你有 {favorite_count} 条本地收藏，可以从一个具体问题开始检索。"
                created += await _insert(conn, uid, "daily", day_key, daily_title, daily_body, {"project_id": project["id"] if project else None})
                if project:
                    created += await _insert(conn, uid, "weekly_review", week_key, "本周学习回顾草稿", "回顾只会生成下周建议，确认后才生效。", {"project_id": project["id"]})
                scan = await conn.fetchrow(
                    "SELECT id, confirmed_invalid_count FROM cleanup_scans WHERE uid = $1 AND status = 'completed' ORDER BY created_at DESC LIMIT 1", uid,
                )
                if scan and int(scan["confirmed_invalid_count"] or 0) > 0:
                    created += await _insert(conn, uid, "cleanup", day_key, "有确定失效收藏等待确认", f"最近扫描发现 {scan['confirmed_invalid_count']} 条确定失效收藏。", {"scan_id": scan["id"]})
                cooling = await conn.fetchrow(
                    "SELECT id, content FROM user_memories WHERE uid = $1 AND status = 'active' AND interest_state = 'cooling' ORDER BY updated_at LIMIT 1", uid,
                )
                if cooling:
                    created += await _insert(conn, uid, "interest_change", week_key, "确认一项兴趣变化", f"这项兴趣似乎在降温：{cooling['content']}。只有你确认后才会休眠。", {"memory_id": cooling["id"]})
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtext('favorite-agent-proactive-scheduler'))")
    return created


async def _insert(conn, uid: str, kind: str, period_key: str, title: str, body: str, payload: dict) -> int:
    result = await conn.execute(
        "INSERT INTO proactive_suggestions (id, uid, kind, period_key, title, body, payload) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb) "
        "ON CONFLICT (uid, kind, period_key) DO NOTHING",
        secrets.token_urlsafe(12), uid, kind, period_key, title[:200], body[:1000], json.dumps(payload, ensure_ascii=False),
    )
    return 1 if result.endswith("1") else 0


async def scheduler_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await generate_proactive_suggestions()
        except Exception as exc:
            print(f"[scheduler] proactive generation failed: {exc}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=SCHEDULER_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
