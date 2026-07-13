import base64
import io
import json
import os
import secrets
import time

import httpx
import qrcode
from fastapi import Request, HTTPException

from security import load_encrypted_json, persistence_enabled, save_encrypted_json

BILI_PASSPORT = "https://passport.bilibili.com"
BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# 内存 session 存储
sessions: dict[str, dict] = {}
# 二维码轮询池
qrcode_pool: dict[str, dict] = {}

SID_LEN = 32
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(86400 * 7)))
_cookie_secure_value = os.getenv("COOKIE_SECURE") or ("true" if os.getenv("APP_ENV") == "production" else "false")
COOKIE_SECURE = _cookie_secure_value.lower() in {"1", "true", "yes"}
QR_TTL_SECONDS = 300

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.enc")
LEGACY_SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
SETTINGS_DIR = os.path.join(DATA_DIR, "settings")


def _save_sessions():
    if not persistence_enabled():
        return
    try:
        save_encrypted_json(SESSIONS_FILE, sessions)
    except Exception as e:
        print(f"[auth] 保存 sessions 失败: {e}")


def _load_sessions():
    if not persistence_enabled():
        if os.path.isfile(LEGACY_SESSIONS_FILE):
            print("[auth] legacy plaintext sessions.json ignored; configure APP_ENCRYPTION_KEY before migrating")
        return
    try:
        data = load_encrypted_json(SESSIONS_FILE) or {}
        now = time.time()
        for sid, s in data.items():
            if s.get("expires_at", 0) > now:
                sessions[sid] = s
        print(f"[auth] 已恢复 {len(sessions)} 个 session")
    except Exception as e:
        print(f"[auth] 加载 sessions 失败: {e}")


def _settings_path(uid: str) -> str | None:
    if not uid.isdigit():
        return None
    return os.path.join(SETTINGS_DIR, f"{uid}.enc")


def _load_user_settings(uid: str) -> dict:
    """返回 {api_key, model}，文件不存在返回默认值"""
    path = _settings_path(uid)
    if not persistence_enabled() or not path:
        return {"api_key": "", "model": "deepseek-v4-flash"}
    try:
        return load_encrypted_json(path) or {"api_key": "", "model": "deepseek-v4-flash"}
    except Exception:
        return {"api_key": "", "model": "deepseek-v4-flash"}


def _save_user_settings(uid: str, api_key: str, model: str):
    path = _settings_path(uid)
    if not persistence_enabled() or not path:
        return
    try:
        save_encrypted_json(path, {"api_key": api_key, "model": model})
    except Exception as e:
        print(f"[auth] 保存 settings 失败: {e}")


# 启动时恢复 session
_load_sessions()


async def generate_qrcode() -> dict:
    """调用 B站 API 生成二维码，返回 {qrcode_key, image_url}"""
    async with httpx.AsyncClient(headers=BILI_HEADERS) as client:
        url = f"{BILI_PASSPORT}/x/passport-login/web/qrcode/generate"
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise HTTPException(502, detail="B站二维码生成失败")
        qrcode_key = data["data"]["qrcode_key"]
        qrcode_url = data["data"]["url"]

        image = qrcode.make(qrcode_url)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    now = time.time()
    for pool_key, entry in list(qrcode_pool.items()):
        if now - entry.get("created_at", now) > QR_TTL_SECONDS:
            qrcode_pool.pop(pool_key, None)
    qrcode_pool[qrcode_key] = {
        "status": "pending",
        "session_id": None,
        "created_at": now,
    }
    return {"qrcode_key": qrcode_key, "image_url": image_url}


async def poll_qrcode(key: str) -> dict:
    """轮询二维码状态，确认后创建 session"""
    if key not in qrcode_pool or time.time() - qrcode_pool[key].get("created_at", 0) > QR_TTL_SECONDS:
        qrcode_pool.pop(key, None)
        raise HTTPException(404, detail="二维码已过期")

    async with httpx.AsyncClient(headers=BILI_HEADERS) as client:
        url = f"{BILI_PASSPORT}/x/passport-login/web/qrcode/poll"
        params = {"qrcode_key": key}
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code")

        if code == 86101:
            qrcode_pool[key]["status"] = "pending"
            return {"status": "pending"}
        elif code == 86090:
            qrcode_pool[key]["status"] = "scanned"
            return {"status": "scanned"}
        elif code == 86038:
            qrcode_pool[key]["status"] = "expired"
            qrcode_pool.pop(key, None)
            return {"status": "expired"}
        elif code == 0:
            # 登录成功，提取 Cookie（键名不区分大小写）
            raw_cookies = {}
            for cookie in resp.cookies.jar:
                raw_cookies[cookie.name.lower()] = cookie.value

            def _ck(key: str) -> str:
                return raw_cookies.get(key.lower(), "")

            bili_cookies = {
                "SESSDATA": _ck("SESSDATA"),
                "bili_jct": _ck("bili_jct"),
                "DedeUserID": _ck("DedeUserID"),
            }

            session_id = secrets.token_hex(SID_LEN // 2)

            uid = bili_cookies.get("DedeUserID", "")
            # 兜底：从响应 body 里取 mid
            if not uid:
                uid = str(data.get("data", {}).get("mid", ""))
            if not uid:
                raise HTTPException(502, detail="登录成功但未获取到用户UID")

            print(f"[auth] 登录成功, uid={uid}")
            from bili import get_user_info
            user_info = await get_user_info(uid)

            settings = _load_user_settings(uid)

            sessions[session_id] = {
                "bili_cookies": bili_cookies,
                "deepseek_key": settings["api_key"],
                "model": settings.get("model", "deepseek-v4-flash"),
                "uid": uid,
                "nickname": user_info.get("nickname", ""),
                "avatar": user_info.get("avatar", ""),
                "folders": [],
                "created_at": time.time(),
                "expires_at": time.time() + SESSION_TTL_SECONDS,
            }

            _save_sessions()

            qrcode_pool[key]["status"] = "confirmed"
            qrcode_pool[key]["session_id"] = session_id

            return {"status": "confirmed", "session_id": session_id}
        else:
            return {"status": "unknown", "code": code}


def delete_session(session_id: str) -> None:
    if sessions.pop(session_id, None) is not None:
        _save_sessions()


def get_session(request: Request) -> dict:
    """FastAPI 依赖：从 Cookie 取 session_id，返回 session 数据"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(401, detail="未登录")
    session = sessions[session_id]
    if session.get("expires_at", 0) <= time.time():
        delete_session(session_id)
        raise HTTPException(401, detail="登录已过期")
    return session


def on_session_updated(session: dict):
    """session 变更后调用（settings/key, settings/model 路由使用）"""
    _save_sessions()
    uid = session.get("uid", "")
    if uid:
        _save_user_settings(uid, session.get("deepseek_key", ""), session.get("model", "deepseek-v4-flash"))
