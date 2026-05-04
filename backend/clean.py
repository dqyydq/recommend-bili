import asyncio

import httpx
from bili import _client

BATCH = 8


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
    cookies: dict, fetch_fav_folders, fetch_fav_items, uid: str,
    on_progress=None,
) -> list[dict]:
    folders = await fetch_fav_folders(uid, cookies)

    all_items: list[dict] = []
    for folder in folders:
        fid = folder.get("media_id") or folder.get("id")
        if not fid:
            continue
        try:
            items = await fetch_fav_items(fid, cookies)
        except Exception:
            continue
        for item in items:
            item["folder_name"] = folder.get("title", "收藏夹")
            item["folder_id"] = fid
        all_items.extend(items)
        await asyncio.sleep(0.3)

    total = len(all_items)
    print(f"[clean] collected {total} items, verifying...")

    sem = asyncio.Semaphore(BATCH)
    invalid: list[dict] = []
    checked = 0

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

    async with _client(cookies) as client:
        await asyncio.gather(*[verify(item) for item in all_items])

    print(f"[clean] done: {total} checked, {len(invalid)} invalid")
    return invalid
