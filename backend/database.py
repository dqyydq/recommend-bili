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

CREATE TABLE IF NOT EXISTS learning_projects (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    goal TEXT NOT NULL,
    duration_weeks INTEGER NOT NULL CHECK (duration_weeks BETWEEN 1 AND 52),
    weekly_minutes INTEGER NOT NULL CHECK (weekly_minutes BETWEEN 15 AND 10080),
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')) DEFAULT 'active',
    current_week INTEGER NOT NULL DEFAULT 1,
    summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS learning_projects_uid_updated_idx ON learning_projects(uid, updated_at DESC);

CREATE TABLE IF NOT EXISTS learning_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    week_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    favorite_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    estimated_minutes INTEGER NOT NULL DEFAULT 30,
    state TEXT NOT NULL CHECK (state IN ('draft', 'pending', 'completed', 'skipped', 'blocked')) DEFAULT 'draft',
    user_note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS learning_tasks_project_week_idx ON learning_tasks(project_id, week_number, state);

CREATE TABLE IF NOT EXISTS learning_progress_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS learning_conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS learning_conversations_project_created_idx ON learning_conversations(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS learning_weekly_reviews (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
    week_number INTEGER NOT NULL,
    completion_rate NUMERIC NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    proposed_tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('draft', 'confirmed')) DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ,
    UNIQUE (project_id, week_number)
);

CREATE TABLE IF NOT EXISTS folder_structure_plans (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    goal TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'reviewed', 'cancelled')) DEFAULT 'draft',
    action_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS folder_structure_plans_uid_created_idx ON folder_structure_plans(uid, created_at DESC);

CREATE TABLE IF NOT EXISTS folder_structure_actions (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES folder_structure_plans(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    topic TEXT NOT NULL,
    destination_name TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    confidence REAL NOT NULL,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_state TEXT NOT NULL CHECK (review_state IN ('pending', 'approved', 'skipped')) DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (plan_id, sequence)
);
CREATE INDEX IF NOT EXISTS folder_structure_actions_plan_idx ON folder_structure_actions(plan_id, sequence);

CREATE TABLE IF NOT EXISTS topic_analyses (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    folder_id BIGINT,
    snapshot_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    item_count INTEGER NOT NULL DEFAULT 0,
    cluster_count INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS topic_analyses_uid_created_idx ON topic_analyses(uid, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS topic_analyses_snapshot_completed_idx
    ON topic_analyses(uid, COALESCE(folder_id, 0), snapshot_version) WHERE status = 'completed';

CREATE TABLE IF NOT EXISTS topic_clusters (
    id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES topic_analyses(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    name TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    item_count INTEGER NOT NULL DEFAULT 0,
    representative_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    upper_creators JSONB NOT NULL DEFAULT '[]'::jsonb,
    time_trend JSONB NOT NULL DEFAULT '{}'::jsonb,
    interest_state TEXT NOT NULL CHECK (interest_state IN ('active', 'cooling', 'dormant', 'historical')) DEFAULT 'historical',
    UNIQUE (analysis_id, sequence)
);

CREATE TABLE IF NOT EXISTS topic_cluster_items (
    cluster_id TEXT NOT NULL REFERENCES topic_clusters(id) ON DELETE CASCADE,
    folder_id BIGINT NOT NULL,
    media_id BIGINT NOT NULL,
    bvid TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (cluster_id, folder_id, media_id)
);

CREATE TABLE IF NOT EXISTS cleanup_scans (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'executing')),
    total INTEGER NOT NULL DEFAULT 0,
    checked INTEGER NOT NULL DEFAULT 0,
    confirmed_invalid_count INTEGER NOT NULL DEFAULT 0,
    review_required_count INTEGER NOT NULL DEFAULT 0,
    unknown_count INTEGER NOT NULL DEFAULT 0,
    available_count INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS cleanup_scans_uid_created_idx ON cleanup_scans(uid, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_cleanup_scan_per_user
    ON cleanup_scans(uid) WHERE status IN ('queued', 'running', 'executing');

CREATE TABLE IF NOT EXISTS cleanup_scan_items (
    scan_id TEXT NOT NULL REFERENCES cleanup_scans(id) ON DELETE CASCADE,
    folder_id BIGINT NOT NULL,
    media_id BIGINT NOT NULL,
    bvid TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL CHECK (verdict IN ('confirmed_invalid', 'review_required', 'unknown', 'available')),
    reason TEXT NOT NULL DEFAULT '',
    selected_by_default BOOLEAN NOT NULL DEFAULT FALSE,
    execution_state TEXT NOT NULL CHECK (execution_state IN ('pending', 'removed', 'skipped', 'failed')) DEFAULT 'pending',
    execution_message TEXT NOT NULL DEFAULT '',
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at TIMESTAMPTZ,
    PRIMARY KEY (scan_id, folder_id, media_id)
);
CREATE INDEX IF NOT EXISTS cleanup_scan_items_scan_verdict_idx ON cleanup_scan_items(scan_id, verdict);
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
        await conn.execute(
            "UPDATE topic_analyses SET status = 'failed', finished_at = NOW(), error_message = 'server restarted during analysis' "
            "WHERE status IN ('queued', 'running')"
        )
        await conn.execute(
            "UPDATE cleanup_scans SET status = 'failed', finished_at = NOW(), error_message = 'server restarted during scan' "
            "WHERE status IN ('queued', 'running', 'executing')"
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


async def get_favorite_cover(uid: str, folder_id: int, media_id: int) -> str:
    async with pool().acquire() as conn:
        value = await conn.fetchval(
            "SELECT cover FROM favorites WHERE uid = $1 AND folder_id = $2 AND media_id = $3 AND is_active = TRUE",
            uid, folder_id, media_id,
        )
    return str(value or "")


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


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def create_learning_project(uid: str, goal: str, duration_weeks: int, weekly_minutes: int) -> dict[str, Any]:
    project_id = secrets.token_urlsafe(12)
    async with pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO learning_projects (id, uid, goal, duration_weeks, weekly_minutes) VALUES ($1,$2,$3,$4,$5)",
            project_id, uid, goal, duration_weeks, weekly_minutes,
        )
    return await get_learning_project(uid, project_id) or {}


async def list_learning_projects(uid: str) -> list[dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, goal, duration_weeks, weekly_minutes, status, current_week, summary, created_at, updated_at "
            "FROM learning_projects WHERE uid = $1 ORDER BY updated_at DESC", uid,
        )
    return [dict(row) for row in rows]


async def get_learning_project(uid: str, project_id: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM learning_projects WHERE uid = $1 AND id = $2", uid, project_id)
        if project is None:
            return None
        tasks = await conn.fetch("SELECT * FROM learning_tasks WHERE project_id = $1 ORDER BY week_number, created_at", project_id)
        reviews = await conn.fetch(
            "SELECT id, week_number, completion_rate, summary, proposed_tasks, status, created_at, confirmed_at "
            "FROM learning_weekly_reviews WHERE project_id = $1 ORDER BY week_number DESC", project_id,
        )
        messages = await conn.fetch(
            "SELECT id, role, content, created_at FROM learning_conversations WHERE project_id = $1 "
            "ORDER BY created_at DESC LIMIT 16", project_id,
        )
    data = dict(project)
    data["tasks"] = [{**dict(row), "favorite_refs": _json_value(row["favorite_refs"])} for row in tasks]
    data["reviews"] = [{**dict(row), "proposed_tasks": _json_value(row["proposed_tasks"])} for row in reviews]
    data["messages"] = [dict(row) for row in reversed(messages)]
    return data


async def delete_learning_project(uid: str, project_id: str) -> bool:
    async with pool().acquire() as conn:
        result = await conn.execute("DELETE FROM learning_projects WHERE uid = $1 AND id = $2", uid, project_id)
    return result.endswith("1")


async def save_learning_draft_tasks(uid: str, project_id: str, week_number: int, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            exists = await conn.fetchval("SELECT 1 FROM learning_projects WHERE uid = $1 AND id = $2 AND status = 'active'", uid, project_id)
            if not exists:
                return None
            await conn.execute("DELETE FROM learning_tasks WHERE project_id = $1 AND week_number = $2 AND state = 'draft'", project_id, week_number)
            await conn.executemany(
                "INSERT INTO learning_tasks (id, project_id, week_number, title, rationale, favorite_refs, estimated_minutes) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)",
                [(secrets.token_urlsafe(12), project_id, week_number, task["title"], task.get("rationale", ""),
                  json.dumps(task.get("favorite_refs", []), ensure_ascii=False), int(task.get("estimated_minutes", 30))) for task in tasks],
            ) if tasks else None
            await conn.execute("UPDATE learning_projects SET updated_at = NOW() WHERE id = $1", project_id)
    return await get_learning_project(uid, project_id)


async def confirm_learning_week(uid: str, project_id: str, week_number: int) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            updated = await conn.execute(
                "UPDATE learning_tasks task SET state = 'pending', updated_at = NOW() FROM learning_projects project "
                "WHERE task.project_id = project.id AND project.uid = $1 AND task.project_id = $2 AND task.week_number = $3 AND task.state = 'draft'",
                uid, project_id, week_number,
            )
            if updated.endswith("0"):
                return None
            await conn.execute("UPDATE learning_projects SET current_week = GREATEST(current_week, $3), updated_at = NOW() WHERE uid = $1 AND id = $2", uid, project_id, week_number)
    return await get_learning_project(uid, project_id)


async def update_learning_task(uid: str, project_id: str, task_id: str, state: str, note: str) -> dict[str, Any] | None:
    if state not in {'completed', 'skipped', 'blocked', 'pending'}:
        raise ValueError("invalid task state")
    async with pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "UPDATE learning_tasks task SET state = $4, user_note = $5, updated_at = NOW() FROM learning_projects project "
                "WHERE task.project_id = project.id AND project.uid = $1 AND task.project_id = $2 AND task.id = $3 AND task.state <> 'draft' RETURNING task.id",
                uid, project_id, task_id, state, note[:1000],
            )
            if row is None:
                return None
            await conn.execute("INSERT INTO learning_progress_events (id, project_id, task_id, state, note) VALUES ($1,$2,$3,$4,$5)",
                               secrets.token_urlsafe(12), project_id, task_id, state, note[:1000])
            await conn.execute("UPDATE learning_projects SET updated_at = NOW() WHERE id = $1", project_id)
    return await get_learning_project(uid, project_id)


async def append_learning_message(uid: str, project_id: str, role: str, content: str) -> bool:
    async with pool().acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM learning_projects WHERE uid = $1 AND id = $2", uid, project_id)
        if not exists:
            return False
        await conn.execute("INSERT INTO learning_conversations (id, project_id, role, content) VALUES ($1,$2,$3,$4)",
                           secrets.token_urlsafe(12), project_id, role, content[:4000])
        await conn.execute("UPDATE learning_projects SET updated_at = NOW() WHERE id = $1", project_id)
    return True


async def save_learning_summary(uid: str, project_id: str, summary: str) -> None:
    async with pool().acquire() as conn:
        await conn.execute("UPDATE learning_projects SET summary = $3, updated_at = NOW() WHERE uid = $1 AND id = $2", uid, project_id, summary[:2000])


async def save_weekly_review(uid: str, project_id: str, week_number: int, completion_rate: float, summary: str, proposed_tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM learning_projects WHERE uid = $1 AND id = $2", uid, project_id)
        if not exists:
            return None
        await conn.execute(
            "INSERT INTO learning_weekly_reviews (id, project_id, week_number, completion_rate, summary, proposed_tasks) VALUES ($1,$2,$3,$4,$5,$6::jsonb) "
            "ON CONFLICT (project_id, week_number) DO UPDATE SET completion_rate = EXCLUDED.completion_rate, summary = EXCLUDED.summary, proposed_tasks = EXCLUDED.proposed_tasks, status = 'draft'",
            secrets.token_urlsafe(12), project_id, week_number, completion_rate, summary[:3000], json.dumps(proposed_tasks, ensure_ascii=False),
        )
    return await get_learning_project(uid, project_id)


async def confirm_weekly_review(uid: str, project_id: str, week_number: int) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            review = await conn.fetchrow(
                "SELECT review.* FROM learning_weekly_reviews review JOIN learning_projects project ON project.id = review.project_id "
                "WHERE project.uid = $1 AND review.project_id = $2 AND review.week_number = $3 AND review.status = 'draft'",
                uid, project_id, week_number,
            )
            if review is None:
                return None
            tasks = _json_value(review["proposed_tasks"]) or []
            await conn.executemany(
                "INSERT INTO learning_tasks (id, project_id, week_number, title, rationale, favorite_refs, estimated_minutes, state) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,'pending')",
                [(secrets.token_urlsafe(12), project_id, week_number + 1, task["title"], task.get("rationale", ""), json.dumps(task.get("favorite_refs", []), ensure_ascii=False), int(task.get("estimated_minutes", 30))) for task in tasks],
            ) if tasks else None
            await conn.execute("UPDATE learning_weekly_reviews SET status = 'confirmed', confirmed_at = NOW() WHERE id = $1", review["id"])
            await conn.execute("UPDATE learning_projects SET current_week = $3, updated_at = NOW() WHERE uid = $1 AND id = $2", uid, project_id, week_number + 1)
    return await get_learning_project(uid, project_id)


async def create_folder_structure_plan(uid: str, goal: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    plan_id = secrets.token_urlsafe(12)
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO folder_structure_plans (id, uid, goal, action_count) VALUES ($1,$2,$3,$4)",
                plan_id, uid, goal, len(actions),
            )
            if actions:
                await conn.executemany(
                    "INSERT INTO folder_structure_actions (id, plan_id, sequence, purpose, topic, destination_name, item_count, confidence, items) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)",
                    [(secrets.token_urlsafe(12), plan_id, index, action["purpose"], action["topic"], action["destination_name"],
                      action["item_count"], action["confidence"], json.dumps(action["items"], ensure_ascii=False))
                     for index, action in enumerate(actions, start=1)],
                )
    return await get_folder_structure_plan(uid, plan_id) or {}


async def get_folder_structure_plan(uid: str, plan_id: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        plan = await conn.fetchrow("SELECT id, goal, status, action_count, created_at, updated_at FROM folder_structure_plans WHERE uid = $1 AND id = $2", uid, plan_id)
        if plan is None:
            return None
        rows = await conn.fetch(
            "SELECT id, sequence, purpose, topic, destination_name, item_count, confidence, items, review_state "
            "FROM folder_structure_actions WHERE plan_id = $1 ORDER BY sequence", plan_id,
        )
    data = dict(plan)
    data["actions"] = [{**dict(row), "items": _json_value(row["items"])} for row in rows]
    return data


async def list_folder_structure_plans(uid: str, limit: int = 20) -> list[dict[str, Any]]:
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, goal, status, action_count, created_at, updated_at FROM folder_structure_plans "
            "WHERE uid = $1 ORDER BY created_at DESC LIMIT $2", uid, limit,
        )
    return [dict(row) for row in rows]


async def set_folder_structure_action_state(uid: str, plan_id: str, action_id: str, state: str) -> dict[str, Any] | None:
    if state not in {'approved', 'skipped'}:
        raise ValueError("invalid structure action state")
    async with pool().acquire() as conn:
        result = await conn.execute(
            "UPDATE folder_structure_actions action SET review_state = $4 FROM folder_structure_plans plan "
            "WHERE action.plan_id = plan.id AND plan.uid = $1 AND action.plan_id = $2 AND action.id = $3 AND plan.status = 'draft'",
            uid, plan_id, action_id, state,
        )
        if result.endswith("1"):
            await conn.execute("UPDATE folder_structure_plans SET updated_at = NOW() WHERE id = $1", plan_id)
    return await get_folder_structure_plan(uid, plan_id) if result.endswith("1") else None


async def finalize_folder_structure_plan(uid: str, plan_id: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        result = await conn.execute(
            "UPDATE folder_structure_plans SET status = 'reviewed', updated_at = NOW() WHERE uid = $1 AND id = $2 AND status = 'draft'",
            uid, plan_id,
        )
    return await get_folder_structure_plan(uid, plan_id) if result.endswith("1") else None


async def create_topic_analysis(uid: str, folder_id: int | None, snapshot_version: str, item_count: int) -> tuple[dict[str, Any], bool]:
    """Create a durable analysis job, or reuse a completed result for the same snapshot."""
    async with pool().acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM topic_analyses WHERE uid = $1 AND COALESCE(folder_id, 0) = COALESCE($2, 0) "
            "AND snapshot_version = $3 AND status = 'completed' ORDER BY created_at DESC LIMIT 1",
            uid, folder_id, snapshot_version,
        )
        if existing:
            return dict(existing), True
        active = await conn.fetchrow(
            "SELECT * FROM topic_analyses WHERE uid = $1 AND COALESCE(folder_id, 0) = COALESCE($2, 0) "
            "AND snapshot_version = $3 AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
            uid, folder_id, snapshot_version,
        )
        if active:
            return dict(active), False
        analysis_id = secrets.token_urlsafe(12)
        row = await conn.fetchrow(
            "INSERT INTO topic_analyses (id, uid, folder_id, snapshot_version, status, item_count, message) "
            "VALUES ($1,$2,$3,$4,'queued',$5,'等待分析') RETURNING *",
            analysis_id, uid, folder_id, snapshot_version, item_count,
        )
    return dict(row), False


async def set_topic_analysis_status(analysis_id: str, status: str, message: str = "", error_message: str = "") -> None:
    if status not in {"running", "completed", "failed"}:
        raise ValueError("invalid topic analysis status")
    async with pool().acquire() as conn:
        await conn.execute(
            "UPDATE topic_analyses SET status = $2, message = $3, error_message = $4, "
            "started_at = CASE WHEN $2 = 'running' THEN COALESCE(started_at, NOW()) ELSE started_at END, "
            "finished_at = CASE WHEN $2 IN ('completed', 'failed') THEN NOW() ELSE finished_at END WHERE id = $1",
            analysis_id, status, message[:500], error_message[:2000],
        )


async def save_topic_analysis_result(analysis_id: str, clusters: list[dict[str, Any]]) -> None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM topic_clusters WHERE analysis_id = $1", analysis_id)
            for sequence, cluster in enumerate(clusters, start=1):
                cluster_id = secrets.token_urlsafe(12)
                await conn.execute(
                    "INSERT INTO topic_clusters (id, analysis_id, sequence, name, summary, item_count, representative_items, upper_creators, time_trend, interest_state) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10)",
                    cluster_id, analysis_id, sequence, cluster["name"], cluster.get("summary", ""),
                    len(cluster.get("items", [])), json.dumps(cluster.get("representative_items", []), ensure_ascii=False),
                    json.dumps(cluster.get("upper_creators", []), ensure_ascii=False),
                    json.dumps(cluster.get("time_trend", {}), ensure_ascii=False), cluster.get("interest_state", "historical"),
                )
                items = cluster.get("items", [])
                if items:
                    await conn.executemany(
                        "INSERT INTO topic_cluster_items (cluster_id, folder_id, media_id, bvid, score) VALUES ($1,$2,$3,$4,$5)",
                        [(cluster_id, int(item.get("folder_id") or 0), int(item.get("id") or item.get("media_id") or 0),
                          str(item.get("bvid") or ""), float(item.get("topic_score") or 0)) for item in items],
                    )
            await conn.execute(
                "UPDATE topic_analyses SET status = 'completed', cluster_count = $2, message = '分析完成', finished_at = NOW() WHERE id = $1",
                analysis_id, len(clusters),
            )


async def get_topic_analysis(uid: str, analysis_id: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        analysis = await conn.fetchrow("SELECT * FROM topic_analyses WHERE uid = $1 AND id = $2", uid, analysis_id)
        if analysis is None:
            return None
        clusters = await conn.fetch(
            "SELECT id, sequence, name, summary, item_count, representative_items, upper_creators, time_trend, interest_state "
            "FROM topic_clusters WHERE analysis_id = $1 ORDER BY sequence", analysis_id,
        )
    result = dict(analysis)
    result["clusters"] = [
        {**dict(row), "representative_items": _json_value(row["representative_items"]),
         "upper_creators": _json_value(row["upper_creators"]), "time_trend": _json_value(row["time_trend"])}
        for row in clusters
    ]
    return result


async def get_latest_topic_analysis(uid: str, folder_id: int | None = None) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM topic_analyses WHERE uid = $1 AND ($2::bigint IS NULL OR folder_id = $2) "
            "ORDER BY created_at DESC LIMIT 1", uid, folder_id,
        )
    return await get_topic_analysis(uid, row["id"]) if row else None


async def create_cleanup_scan(uid: str, total: int) -> tuple[dict[str, Any], bool]:
    async with pool().acquire() as conn:
        active = await conn.fetchrow(
            "SELECT * FROM cleanup_scans WHERE uid = $1 AND status IN ('queued', 'running', 'executing') ORDER BY created_at DESC LIMIT 1", uid,
        )
        if active:
            return dict(active), True
        scan_id = secrets.token_urlsafe(12)
        row = await conn.fetchrow(
            "INSERT INTO cleanup_scans (id, uid, status, total, message) VALUES ($1,$2,'queued',$3,'等待扫描') RETURNING *",
            scan_id, uid, total,
        )
    return dict(row), False


async def update_cleanup_scan(scan_id: str, **fields: Any) -> None:
    allowed = {
        "status", "total", "checked", "confirmed_invalid_count", "review_required_count",
        "unknown_count", "available_count", "message", "error_message", "started_at", "finished_at",
    }
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return
    columns = list(values)
    assignments = ", ".join(f"{column} = ${index}" for index, column in enumerate(columns, start=2))
    async with pool().acquire() as conn:
        await conn.execute(f"UPDATE cleanup_scans SET {assignments} WHERE id = $1", scan_id, *(values[column] for column in columns))


async def save_cleanup_scan_items(scan_id: str, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    async with pool().acquire() as conn:
        await conn.executemany(
            "INSERT INTO cleanup_scan_items (scan_id, folder_id, media_id, bvid, title, verdict, reason, selected_by_default) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (scan_id, folder_id, media_id) DO UPDATE SET "
            "verdict = EXCLUDED.verdict, reason = EXCLUDED.reason, selected_by_default = EXCLUDED.selected_by_default, checked_at = NOW()",
            [(scan_id, int(item.get("folder_id") or 0), int(item.get("id") or item.get("media_id") or 0),
              str(item.get("bvid") or ""), str(item.get("title") or ""), item["verdict"], item.get("reason", ""),
              item["verdict"] == "confirmed_invalid") for item in items],
        )


async def get_cleanup_scan(uid: str, scan_id: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        scan = await conn.fetchrow("SELECT * FROM cleanup_scans WHERE uid = $1 AND id = $2", uid, scan_id)
        if scan is None:
            return None
        rows = await conn.fetch(
            "SELECT folder_id, media_id, bvid, title, verdict, reason, selected_by_default, execution_state, execution_message, checked_at, executed_at "
            "FROM cleanup_scan_items WHERE scan_id = $1 ORDER BY selected_by_default DESC, title", scan_id,
        )
    result = dict(scan)
    result["items"] = [dict(row) for row in rows]
    return result


async def get_latest_cleanup_scan(uid: str) -> dict[str, Any] | None:
    async with pool().acquire() as conn:
        scan_id = await conn.fetchval("SELECT id FROM cleanup_scans WHERE uid = $1 ORDER BY created_at DESC LIMIT 1", uid)
    return await get_cleanup_scan(uid, scan_id) if scan_id else None


async def claim_cleanup_scan_execution(uid: str, scan_id: str, requested: list[tuple[int, int]]) -> list[dict[str, Any]] | None:
    async with pool().acquire() as conn:
        async with conn.transaction():
            result = await conn.execute(
                "UPDATE cleanup_scans SET status = 'executing', message = '正在复核并执行' WHERE uid = $1 AND id = $2 AND status = 'completed'",
                uid, scan_id,
            )
            if not result.endswith("1"):
                return None
            rows = await conn.fetch(
                "SELECT folder_id, media_id, bvid, title FROM cleanup_scan_items WHERE scan_id = $1 "
                "AND verdict = 'confirmed_invalid' AND execution_state = 'pending'",
                scan_id,
            )
    requested_set = set(requested)
    return [dict(row) for row in rows if (int(row["folder_id"]), int(row["media_id"])) in requested_set]


async def set_cleanup_item_execution(scan_id: str, folder_id: int, media_id: int, state: str, message: str) -> None:
    if state not in {"removed", "skipped", "failed"}:
        raise ValueError("invalid cleanup execution state")
    async with pool().acquire() as conn:
        await conn.execute(
            "UPDATE cleanup_scan_items SET execution_state = $4, execution_message = $5, executed_at = NOW() "
            "WHERE scan_id = $1 AND folder_id = $2 AND media_id = $3",
            scan_id, folder_id, media_id, state, message[:500],
        )
