import asyncio
import time

import httpx

from bili import _client

BATCH = 12
INVALID_CODES = {-404}
REVIEW_REQUIRED_CODES = {-403, -10403, 62002}


async def inspect_bvid(bvid: str, client: httpx.AsyncClient) -> tuple[str, str]:
    """Return a durable cleanup verdict and a user-facing reason."""
    if not bvid:
        return "unknown", "缺少 BV 号，无法验证"
    try:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            timeout=15,
        )
        if resp.status_code == 429:
            return "unknown", "B站限流，本次不处理"
        if resp.status_code != 200:
            return "unknown", f"网络响应异常（HTTP {resp.status_code}）"
        data = resp.json()
        code = data.get("code")
        message = str(data.get("message") or data.get("msg") or "")
        if code == 0:
            return "available", "视频当前可访问"
        if code in INVALID_CODES:
            return "confirmed_invalid", message or "B站确认视频不存在"
        if code in REVIEW_REQUIRED_CODES:
            return "review_required", message or "视频受权限或地区限制，需人工确认"
        return "unknown", message or f"未识别的 B站状态（{code}）"
    except (httpx.HTTPError, ValueError):
        return "unknown", "网络超时或响应无法解析，本次不处理"


async def _check_bvid(bvid: str, client: httpx.AsyncClient) -> str:
    """Return valid, invalid, or unknown. Unknown results must never be deleted."""
    verdict, _ = await inspect_bvid(bvid, client)
    return {"available": "valid", "confirmed_invalid": "invalid"}.get(verdict, "unknown")


async def scan_invalid(
    cookies: dict,
    items: list[dict],
    on_progress=None,
) -> dict:
    """Scan favorites without treating rate limits or network failures as invalid videos."""
    started_at = time.time()
    total = len(items)
    if total == 0:
        return {"invalid": [], "unknown": [], "checked": 0}

    semaphore = asyncio.Semaphore(BATCH)
    invalid: list[dict] = []
    unknown: list[dict] = []
    checked = 0
    lock = asyncio.Lock()

    async with _client(cookies) as client:
        async def verify(item: dict) -> None:
            nonlocal checked
            async with semaphore:
                status = await _check_bvid(item.get("bvid", ""), client)
            async with lock:
                if status == "invalid":
                    invalid.append(item)
                elif status == "unknown":
                    unknown.append(item)
                checked += 1
                if on_progress and (checked % 10 == 0 or checked == total):
                    await on_progress(total, checked, len(invalid), len(unknown))

        await asyncio.gather(*(verify(item) for item in items))

    elapsed = time.time() - started_at
    print(f"[clean] checked={checked} invalid={len(invalid)} unknown={len(unknown)} elapsed={elapsed:.1f}s")
    return {"invalid": invalid, "unknown": unknown, "checked": checked}
