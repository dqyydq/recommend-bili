import asyncio

import httpx

BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

BATCH = 8  # 并发数


async def _check_bvid(bvid: str, client: httpx.AsyncClient) -> bool:
    """调 B站 view API 验证，返回 True=失效"""
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
    """全量抓取 → view API 逐条验证失效，on_progress(total, checked, invalid_count) 回调"""
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

    jar = httpx.Cookies()
    jar.set("buvid3", "3787611E-2E66-0B20-D062-B6ACF0A5987B22749infoc", domain=".bilibili.com")
    if cookies:
        for k, v in cookies.items():
            jar.set(k, v, domain=".bilibili.com")

    sem = asyncio.Semaphore(BATCH)
    invalid: list[dict] = []
    checked = 0

    async def verify(item: dict):
        nonlocal checked
        async with sem:
            async with httpx.AsyncClient(headers=BILI_HEADERS, cookies=jar) as client:
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
