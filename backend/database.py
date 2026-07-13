import json
import os
import secrets
from typing import Any

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,
    nickname TEXT NOT NULL DEFAULT '',
    avatar TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS favorite_folders (
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    folder_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    media_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at TIMESTAMPTZ,
    PRIMARY KEY (uid, folder_id)
);

CREATE TABLE IF NOT EXISTS favorites (
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    folder_id BIGINT NOT NULL,
    media_id BIGINT NOT NULL,
    bvid TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    intro TEXT NOT NULL DEFAULT '',
    upper_name TEXT NOT NULL DEFAULT '',
    cover TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    fav_time BIGINT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (uid, folder_id, media_id),
    FOREIGN KEY (uid, folder_id) REFERENCES favorite_folders(uid, folder_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS favorites_uid_active_idx ON favorites(uid, is_active, fav_time DESC);
CREATE INDEX IF NOT EXISTS favorites_uid_bvid_idx ON favorites(uid, bvid);

CREATE TABLE IF NOT EXISTS user_sync_state (
    uid TEXT PRIMARY KEY REFERENCES users(uid) ON DELETE CASCADE,
    last_sync_at TIMESTAMPTZ,
    last_full_sync_at TIMESTAMPTZ,
    sync_required BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_jobs (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    mode TEXT NOT NULL CHECK (mode IN ('incremental', 'full')),
    folders_total INTEGER NOT NULL DEFAULT 0,
    folders_processed INTEGER NOT NULL DEFAULT 0,
    items_processed INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_sync_per_user ON sync_jobs(uid) WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS sync_jobs_uid_created_idx ON sync_jobs(uid, created_at DESC);

CREATE TABLE IF NOT EXISTS operation_logs (
    id BIGSERIAL PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    operation_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS classification_history (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    folder_name TEXT NOT NULL,
    total INTEGER NOT NULL,
    categories JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS classification_history_uid_created_idx ON classification_history(uid, created_at DESC);

CREATE TABLE IF NOT EXISTS organization_plans (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    goal TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'cancelled')) DEFAULT 'draft',
    action_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS organization_plans_uid_created_idx ON organization_plans(uid, created_at DESC);

CREATE TABLE IF NOT EXISTS organization_plan_actions (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES organization_plans(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('review_duplicate', 'review_stale')),
    risk TEXT NOT NULL CHECK (risk IN ('low', 'medium', 'high')),
    state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'skipped')) DEFAULT 'pending',
    folder_id BIGINT NOT NULL,
    media_id BIGINT NOT NULL,
    bvid TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    folder_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (plan_id, sequence)
);
CREATE INDEX IF NOT EXISTS organization_plan_actions_plan_idx ON organization_plan_actions(plan_id, sequence);

ALTER TABLE organization_plans ADD COLUMN IF NOT EXISTS execution_status TEXT NOT NULL DEFAULT 'idle';
ALTER TABLE organization_plans ADD COLUMN IF NOT EXISTS execution_started_at TIMESTAMPTZ;
ALTER TABLE organization_plans ADD COLUMN IF NOT EXISTS execution_finished_at TIMESTAMPTZ;
ALTER TABLE organization_plan_actions ADD COLUMN IF NOT EXISTS execution_state TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE organization_plan_actions ADD COLUMN IF NOT EXISTS execution_message TEXT NOT NULL DEFAULT '';
ALTER TABLE organization_plan_actions ADD COLUMN IF NOT EXISTS executed_at TIMESTAMPTZ;
"""


def _record_to_dict(record: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(record) if record is not None else None


async def init_db() -> None:
    global _pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required. Configure PostgreSQL before starting the backend.")
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=int(os.getenv("DB_POOL_SIZE", "10")), command_timeout=30)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)
        await conn.execute(
            "UPDATE sync_jobs SET status = 'failed', finished_at = NOW(), error_message = 'server restarted during sync' "
            "WHERE status IN ('queued', 'running')"
        )


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database is not initialized")
    return _pool


async def upsert_user(uid: str, nickname: str = "", avatar: str = "") -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (uid, nickname, avatar) VALUES ($1, $2, $3)
            ON CONFLICT (uid) DO UPDATE SET nickname = EXCLUDED.nickname, avatar = EXCLUDED.avatar, updated_at = NOW()
            """,
            uid, nickname, avatar,
        )
        await conn.execute("INSERT INTO user_sync_state (uid) VALUES ($1) ON CONFLICT (uid) DO NOTHING", uid)


async def get_sync_state(uid: str) -> dict[str, Any]:
    async with pool().acquire() as conn:
        record = await conn.fetchrow("SELECT * FROM user_sync_state WHERE uid = $1", uid)
    return _record_to_dict(record) or {"sync_required": True, "last_sync_at": None, "last_full_sync_at": None}


async def mark_sync_required(uid: str) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            "UPDATE user_sync_state SET sync_required = TRUE, updated_at = NOW() WHERE uid = $1",
            uid,
        )


async def get_folders(uid: str) -> list[dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT folder_id AS media_id, folder_id AS id, title, media_count, last_synced_at "
            "FROM favorite_folders WHERE uid = $1 AND is_active = TRUE ORDER BY title",
            uid,
        )
    return [dict(row) for row in rows]


async def get_folder_counts(uid: str) -> dict[int, int]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT folder_id, media_count FROM favorite_folders WHERE uid = $1 AND is_active = TRUE",
            uid,
        )
    return {int(row["folder_id"]): int(row["media_count"]) for row in rows}


async def upsert_folder_metadata(uid: str, folders: list[dict[str, Any]]) -> None:
    values = []
    for folder in folders:
        folder_id = folder.get("media_id") or folder.get("id")
        if not folder_id:
            continue
        values.append((
            uid,
            int(folder_id),
            str(folder.get("title") or "收藏夹"),
            int(folder.get("media_count") or folder.get("count") or 0),
        ))
    if not values:
        return
    async with pool().acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO favorite_folders (uid, folder_id, title, media_count, is_active)
            VALUES ($1, $2, $3, $4, TRUE)
            ON CONFLICT (uid, folder_id) DO UPDATE SET
                title = EXCLUDED.title, media_count = EXCLUDED.media_count, is_active = TRUE
            """,
            values,
        )


async def get_favorites(uid: str, folder_id: int | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT v.media_id AS id, v.bvid, v.title, v.intro, v.upper_name AS upper, v.cover, v.link,
               v.folder_id, v.fav_time, f.title AS folder_name
        FROM favorites v
        JOIN favorite_folders f USING (uid, folder_id)
        WHERE v.uid = $1 AND v.is_active = TRUE AND f.is_active = TRUE
    """
    args: list[Any] = [uid]
    if folder_id is not None:
        query += " AND v.folder_id = $2"
        args.append(folder_id)
    query += " ORDER BY fav_time DESC, media_id DESC"
    async with pool().acquire() as conn:
        rows = await conn.fetch(query, *args)
    return [dict(row) for row in rows]


async def search_favorites(uid: str, query: str, limit: int = 100) -> list[dict[str, Any]]:
    pattern = f"%{query.strip()}%"
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT v.media_id AS id, v.bvid, v.title, v.intro, v.upper_name AS upper, v.cover, v.link,
                   v.folder_id, v.fav_time, f.title AS folder_name
            FROM favorites v
            JOIN favorite_folders f USING (uid, folder_id)
            WHERE v.uid = $1 AND v.is_active = TRUE AND f.is_active = TRUE
              AND (v.title ILIKE $2 OR v.intro ILIKE $2 OR v.upper_name ILIKE $2)
            ORDER BY fav_time DESC
            LIMIT $3
            """,
            uid, pattern, limit,
        )
    return [dict(row) for row in rows]


async def replace_folder_snapshot(uid: str, folder: dict[str, Any], items: list[dict[str, Any]]) -> None:
    folder_id = int(folder.get("media_id") or folder.get("id"))
    title = str(folder.get("title") or "收藏夹")
    media_count = int(folder.get("media_count") or folder.get("count") or len(items))
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO favorite_folders (uid, folder_id, title, media_count, is_active, last_synced_at)
                VALUES ($1, $2, $3, $4, TRUE, NOW())
                ON CONFLICT (uid, folder_id) DO UPDATE SET
                    title = EXCLUDED.title, media_count = EXCLUDED.media_count, is_active = TRUE, last_synced_at = NOW()
                """,
                uid, folder_id, title, media_count,
            )
            await conn.execute(
                "UPDATE favorites SET is_active = FALSE WHERE uid = $1 AND folder_id = $2",
                uid, folder_id,
            )
            if items:
                await conn.executemany(
                    """
                    INSERT INTO favorites (
                        uid, folder_id, media_id, bvid, title, intro, upper_name, cover, link, fav_time, is_active, synced_at
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,TRUE,NOW())
                    ON CONFLICT (uid, folder_id, media_id) DO UPDATE SET
                        bvid = EXCLUDED.bvid, title = EXCLUDED.title, intro = EXCLUDED.intro,
                        upper_name = EXCLUDED.upper_name, cover = EXCLUDED.cover, link = EXCLUDED.link,
                        fav_time = EXCLUDED.fav_time, is_active = TRUE, synced_at = NOW()
                    """,
                    [
                        (
                            uid, folder_id, int(item.get("id") or 0), str(item.get("bvid") or ""),
                            str(item.get("title") or ""), str(item.get("intro") or ""), str(item.get("upper") or ""),
                            str(item.get("cover") or ""), str(item.get("link") or ""), int(item.get("fav_time") or 0),
                        )
                        for item in items if int(item.get("id") or 0) > 0
                    ],
                )


async def mark_missing_folders(uid: str, active_folder_ids: list[int]) -> None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE favorite_folders SET is_active = FALSE WHERE uid = $1 AND NOT (folder_id = ANY($2::bigint[]))",
                uid, active_folder_ids,
            )
            await conn.execute(
                "UPDATE favorites SET is_active = FALSE WHERE uid = $1 AND folder_id NOT IN "
                "(SELECT folder_id FROM favorite_folders WHERE uid = $1 AND is_active = TRUE)",
                uid,
            )


async def finish_sync_state(uid: str, is_full: bool) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE user_sync_state SET last_sync_at = NOW(),
                last_full_sync_at = CASE WHEN $2 THEN NOW() ELSE last_full_sync_at END,
                sync_required = FALSE, updated_at = NOW()
            WHERE uid = $1
            """,
            uid, is_full,
        )


async def create_sync_job(job_id: str, uid: str, mode: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO sync_jobs (id, uid, status, mode) VALUES ($1, $2, 'queued', $3)",
                job_id, uid, mode,
            )
        except asyncpg.UniqueViolationError:
            row = await conn.fetchrow(
                "SELECT * FROM sync_jobs WHERE uid = $1 AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
                uid,
            )
            return _record_to_dict(row)
    return None


async def update_sync_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    columns = list(fields)
    assignments = ", ".join(f"{column} = ${index}" for index, column in enumerate(columns, start=2))
    values = [job_id, *(fields[column] for column in columns)]
    async with pool().acquire() as conn:
        await conn.execute(f"UPDATE sync_jobs SET {assignments} WHERE id = $1", *values)


async def get_sync_job(uid: str, job_id: str | None = None) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        if job_id:
            row = await conn.fetchrow("SELECT * FROM sync_jobs WHERE uid = $1 AND id = $2", uid, job_id)
        else:
            row = await conn.fetchrow("SELECT * FROM sync_jobs WHERE uid = $1 ORDER BY created_at DESC LIMIT 1", uid)
    return _record_to_dict(row)


async def record_operation(uid: str, operation_type: str, payload: dict[str, Any]) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO operation_logs (uid, operation_type, payload) VALUES ($1, $2, $3::jsonb)",
            uid, operation_type, json.dumps(payload, ensure_ascii=False),
        )


async def save_classification(uid: str, folder_name: str, categories: list[dict[str, Any]]) -> str:
    record_id = secrets.token_urlsafe(12)
    total = sum(len(category.get("items", [])) for category in categories)
    async with pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO classification_history (id, uid, folder_name, total, categories) VALUES ($1, $2, $3, $4, $5::jsonb)",
            record_id, uid, folder_name, total, json.dumps(categories, ensure_ascii=False),
        )
    return record_id


async def list_classifications(uid: str) -> list[dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id AS filename, created_at, total, jsonb_array_length(categories) AS categories_count "
            "FROM classification_history WHERE uid = $1 ORDER BY created_at DESC",
            uid,
        )
    return [dict(row) for row in rows]


async def load_classification(uid: str, record_id: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT folder_name, total, categories, created_at FROM classification_history WHERE uid = $1 AND id = $2",
            uid, record_id,
        )
    if row is None:
        return None
    categories = row["categories"]
    if isinstance(categories, str):
        categories = json.loads(categories)
    return {
        "folder_name": row["folder_name"],
        "total": row["total"],
        "categories": categories,
        "created_at": row["created_at"].isoformat(),
    }


async def create_organization_plan(uid: str, goal: str, summary: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    plan_id = secrets.token_urlsafe(12)
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO organization_plans (id, uid, goal, summary, action_count) VALUES ($1, $2, $3, $4, $5)",
                plan_id, uid, goal, summary, len(actions),
            )
            if actions:
                await conn.executemany(
                    """
                    INSERT INTO organization_plan_actions (
                        id, plan_id, sequence, action_type, risk, folder_id, media_id, bvid, title, folder_name, reason
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    """,
                    [
                        (
                            secrets.token_urlsafe(12), plan_id, index, action["action_type"], action["risk"],
                            action["folder_id"], action["media_id"], action.get("bvid", ""),
                            action["title"], action["folder_name"], action["reason"],
                        )
                        for index, action in enumerate(actions, start=1)
                    ],
                )
    return await get_organization_plan(uid, plan_id) or {}


async def get_organization_plan(uid: str, plan_id: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        plan = await conn.fetchrow(
            "SELECT id, goal, summary, status, action_count, created_at, approved_at, execution_status, "
            "execution_started_at, execution_finished_at FROM organization_plans WHERE uid = $1 AND id = $2",
            uid, plan_id,
        )
        if plan is None:
            return None
        actions = await conn.fetch(
            "SELECT id, sequence, action_type, risk, state, folder_id, media_id, bvid, title, folder_name, reason, "
            "execution_state, execution_message, executed_at "
            "FROM organization_plan_actions WHERE plan_id = $1 ORDER BY sequence",
            plan_id,
        )
    data = dict(plan)
    data["actions"] = [dict(action) for action in actions]
    return data


async def list_organization_plans(uid: str, limit: int = 20) -> list[dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, goal, summary, status, action_count, created_at, approved_at, execution_status, "
            "execution_started_at, execution_finished_at "
            "FROM organization_plans WHERE uid = $1 ORDER BY created_at DESC LIMIT $2",
            uid, limit,
        )
    return [dict(row) for row in rows]


async def set_plan_action_state(uid: str, plan_id: str, action_id: str, state: str) -> dict[str, Any] | None:
    if state not in {"approved", "skipped"}:
        raise ValueError("invalid action state")
    async with pool().acquire() as conn:
        result = await conn.execute(
            """
            UPDATE organization_plan_actions action SET state = $4
            FROM organization_plans plan
            WHERE action.plan_id = plan.id AND plan.uid = $1 AND action.plan_id = $2 AND action.id = $3
              AND plan.status = 'draft'
            """,
            uid, plan_id, action_id, state,
        )
    return await get_organization_plan(uid, plan_id) if result.endswith("1") else None


async def approve_organization_plan(uid: str, plan_id: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            result = await conn.execute(
                "UPDATE organization_plans SET status = 'approved', approved_at = NOW(), updated_at = NOW() "
                "WHERE uid = $1 AND id = $2 AND status = 'draft'",
                uid, plan_id,
            )
            if not result.endswith("1"):
                return None
            await conn.execute(
                "UPDATE organization_plan_actions SET state = 'approved' WHERE plan_id = $1 AND state = 'pending'",
                plan_id,
            )
    return await get_organization_plan(uid, plan_id)


async def claim_organization_plan_execution(uid: str, plan_id: str) -> bool:
    """Claim an approved plan exactly once before any external mutation."""
    async with pool().acquire() as conn:
        result = await conn.execute(
            """
            UPDATE organization_plans
            SET execution_status = 'running', execution_started_at = NOW(), execution_finished_at = NULL, updated_at = NOW()
            WHERE uid = $1 AND id = $2 AND status = 'approved'
              AND execution_status IN ('idle', 'partial_failed', 'failed')
            """,
            uid, plan_id,
        )
    return result.endswith("1")


async def get_executable_plan_actions(uid: str, plan_id: str) -> list[dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT action.id, action.folder_id, action.media_id, action.bvid, action.title
            FROM organization_plan_actions action
            JOIN organization_plans plan ON plan.id = action.plan_id
            WHERE plan.uid = $1 AND action.plan_id = $2 AND plan.execution_status = 'running'
              AND action.state = 'approved'
              AND action.execution_state IN ('pending', 'failed', 'skipped_unreachable')
            ORDER BY action.sequence
            """,
            uid, plan_id,
        )
    return [dict(row) for row in rows]


async def set_plan_action_execution_result(
    uid: str,
    plan_id: str,
    action_id: str,
    execution_state: str,
    message: str,
) -> None:
    allowed_states = {'deleted', 'skipped_valid', 'skipped_unreachable', 'failed'}
    if execution_state not in allowed_states:
        raise ValueError("invalid execution state")
    async with pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE organization_plan_actions action
            SET execution_state = $4, execution_message = $5, executed_at = NOW()
            FROM organization_plans plan
            WHERE action.plan_id = plan.id AND plan.uid = $1 AND action.plan_id = $2 AND action.id = $3
              AND plan.execution_status = 'running'
            """,
            uid, plan_id, action_id, execution_state, message[:240],
        )


async def finish_organization_plan_execution(uid: str, plan_id: str, execution_status: str) -> None:
    if execution_status not in {'completed', 'partial_failed', 'failed'}:
        raise ValueError("invalid plan execution status")
    async with pool().acquire() as conn:
        await conn.execute(
            """
            UPDATE organization_plans
            SET execution_status = $3, execution_finished_at = NOW(), updated_at = NOW()
            WHERE uid = $1 AND id = $2 AND execution_status = 'running'
            """,
            uid, plan_id, execution_status,
        )
