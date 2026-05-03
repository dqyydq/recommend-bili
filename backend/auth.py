import secrets
import time
import urllib.parse

import httpx
from fastapi import Request, HTTPException

BILI_PASSPORT = "https://passport.bilibili.com"
BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# 内存 session 存储
sessions: dict[str, dict] = {}
# 二维码轮询池
qrcode_pool: dict[str, dict] = {}

SID_LEN = 32


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

        # 生成二维码图片URL（使用外部API）
        image_url = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=" + urllib.parse.quote(qrcode_url)

    qrcode_pool[qrcode_key] = {
        "status": "pending",
        "session_id": None,
    }
    return {"qrcode_key": qrcode_key, "image_url": image_url}


async def poll_qrcode(key: str) -> dict:
    """轮询二维码状态，确认后创建 session"""
    if key not in qrcode_pool:
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

            sessions[session_id] = {
                "bili_cookies": bili_cookies,
                "deepseek_key": "",
                "uid": uid,
                "nickname": user_info.get("nickname", ""),
                "avatar": user_info.get("avatar", ""),
                "folders": [],
                "created_at": time.time(),
            }

            qrcode_pool[key]["status"] = "confirmed"
            qrcode_pool[key]["session_id"] = session_id

            return {"status": "confirmed", "session_id": session_id}
        else:
            return {"status": "unknown", "code": code}


def get_session(request: Request) -> dict:
    """FastAPI 依赖：从 Cookie 取 session_id，返回 session 数据"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in sessions:
        raise HTTPException(401, detail="未登录")
    return sessions[session_id]
