import asyncio
import time

import httpx

from bili import _client

BATCH = 12
INVALID_CODES = {-404}


async def _check_bvid(bvid: str, client: httpx.AsyncClient) -> str:
    """Return valid, invalid, or unknown. Unknown results must never be deleted."""
    try:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            timeout=15,
        )
        if resp.status_code != 200:
            return "unknown"
        data = resp.json()
        code = data.get("code")
        if code == 0:
            return "valid"
        if code in INVALID_CODES:
            return "invalid"
        return "unknown"
    except (httpx.HTTPError, ValueError):
        return "unknown"


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
