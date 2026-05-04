import asyncio
import time

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

    t0 = time.time()
    all_items = await fetch_all_items(uid, cookies)

    total = len(all_items)
    if total == 0:
        print("[clean] 无收藏视频，跳过校验")
        return []

    elapsed_fetch = time.time() - t0
    print(f"[clean] {total} 条待校验 (抓取耗时 {elapsed_fetch:.1f}s)，启动 {BATCH} 并发...")

    sem = asyncio.Semaphore(BATCH)
    invalid: list[dict] = []
    checked = 0
    t_verify = time.time()

    async with _client(cookies) as client:

        async def verify(item: dict):
            nonlocal checked
            async with sem:
                if await _check_bvid(item["bvid"], client):
                    invalid.append(item)
                checked += 1
                if on_progress and (checked % 10 == 0 or checked == total):
                    await on_progress(total, checked, len(invalid))
                elif checked % 20 == 0:
                    pct = checked * 100 // total
                    elapsed = time.time() - t_verify
                    eta = (elapsed / checked) * (total - checked) if checked > 0 else 0
                    print(f"[clean] {checked}/{total} ({pct}%) 失效 {len(invalid)} | 预计剩余 {eta:.0f}s")

        await asyncio.gather(*[verify(item) for item in all_items])

    elapsed = time.time() - t0
    print(f"[clean] 完成: {total} 条校验, {len(invalid)} 失效 | 总耗时 {elapsed:.1f}s (抓取 {elapsed_fetch:.1f}s + 校验 {elapsed - elapsed_fetch:.1f}s)")
    return invalid
