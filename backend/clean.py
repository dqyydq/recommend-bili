import asyncio

import httpx
from bili import _client, fetch_all_items

BATCH = 20


async def _check_bvid(bvid: str, client: httpx.AsyncClient) -> bool:
    try:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            timeout=15,
        )
        data = resp.json()
        return data.get("code") != 0
    except Exception:
        return True


async def scan_invalid(
    cookies: dict, uid: str,
    on_progress=None,
) -> list[dict]:
    """扫描所有收藏夹中的失效视频（并行抓取 + 高并发校验）"""

    all_items = await fetch_all_items(uid, cookies)

    total = len(all_items)
    print(f"[clean] collected {total} items, verifying...")

    sem = asyncio.Semaphore(BATCH)
    invalid: list[dict] = []
    checked = 0

    async with _client(cookies) as client:

        async def verify(item: dict):
            nonlocal checked
            async with sem:
                if await _check_bvid(item["bvid"], client):
                    invalid.append(item)
                checked += 1
                if on_progress and (checked % 20 == 0 or checked == total):
                    await on_progress(total, checked, len(invalid))
                elif checked % 50 == 0:
                    print(f"[clean] verified {checked}/{total}, found {len(invalid)} invalid")

        await asyncio.gather(*[verify(item) for item in all_items])

    print(f"[clean] done: {total} checked, {len(invalid)} invalid")
    return invalid
