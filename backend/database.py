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
