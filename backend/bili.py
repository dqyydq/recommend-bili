import asyncio
import time
import httpx

BILI_API = "https://api.bilibili.com"
FAV_PAGE_SIZE = 20
FOLDER_CONCURRENCY = 3
PAGE_CONCURRENCY = 4
BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://space.bilibili.com/",
    "Origin": "https://space.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

BUVID3 = "3787611E-2E66-0B20-D062-B6ACF0A5987B22749infoc"


def _client(cookies: dict[str, str] | None = None, extra_headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    """创建带 Cookie 的 AsyncClient"""
    jar = httpx.Cookies()
    jar.set("buvid3", BUVID3, domain=".bilibili.com")
    if cookies:
        for k, v in cookies.items():
            jar.set(k, v, domain=".bilibili.com")
    h = dict(BILI_HEADERS)
    if extra_headers:
        h.update(extra_headers)
    limits = httpx.Limits(max_connections=12, max_keepalive_connections=6)
    return httpx.AsyncClient(headers=h, cookies=jar, follow_redirects=True, limits=limits)


async def _get_fav_page(client: httpx.AsyncClient, folder_id: int, page: int, *, retries: int = 3) -> dict:
    url = f"{BILI_API}/x/v3/fav/resource/list"
    params = {
        "media_id": folder_id,
        "pn": page,
        "ps": FAV_PAGE_SIZE,
    }
    for attempt in range(retries):
        resp = await client.get(url, params=params, timeout=30)
        if resp.status_code == 412:
            if attempt < retries - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            return data
        if data.get("code") == -412 and attempt < retries - 1:
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        return data
    return {"code": -1, "data": {}}


def _media_to_item(media: dict, folder_id: int) -> dict:
    return {
        "id": media.get("id", 0),
        "bvid": media.get("bvid", ""),
        "title": media.get("title", ""),
        "intro": media.get("intro", ""),
        "upper": (media.get("upper") or {}).get("name", ""),
        "cover": media.get("cover", ""),
        "link": f"https://www.bilibili.com/video/{media.get('bvid', '')}",
        "source_folder": str(folder_id),
        "fav_time": media.get("fav_time", 0),
    }


def _page_count(data: dict, first_page_items: int, has_more: bool) -> int:
    info = (data.get("data") or {}).get("info") or {}
    total = info.get("media_count") or info.get("count") or info.get("cnt") or 0
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0
    if total > 0:
        return max(1, (total + FAV_PAGE_SIZE - 1) // FAV_PAGE_SIZE)
    return 2 if has_more and first_page_items else 1


async def fetch_fav_folders(uid: str, cookies: dict[str, str] | None = None) -> list[dict]:
    if not uid:
        return []
    async with _client(cookies) as client:
        url = f"{BILI_API}/x/v3/fav/folder/created/list-all"
        params = {"up_mid": uid}
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            folders = (data.get("data") or {}).get("list", [])
            if folders:
                return folders

        # 兜底：部分用户的默认收藏夹不在 created/list-all 里
        url2 = f"{BILI_API}/x/v3/fav/folder/list"
        params2 = {"up_mid": uid, "pn": 1, "ps": 20}
        resp2 = await client.get(url2, params=params2, timeout=30)
        resp2.raise_for_status()
        data2 = resp2.json()
        if data2.get("code") == 0:
            return (data2.get("data") or {}).get("list", [])
        return []


async def fetch_fav_items(folder_id: int, cookies: dict[str, str] | None = None,
                       client: httpx.AsyncClient | None = None) -> list[dict]:
    async def _do(client: httpx.AsyncClient):
        first = await _get_fav_page(client, folder_id, 1)
        if first.get("code") != 0:
            return []

        first_data = first.get("data") or {}
        first_medias = first_data.get("medias", []) or []
        has_more = bool(first_data.get("has_more", False))
        total_pages = _page_count(first, len(first_medias), has_more)
        pages: dict[int, list[dict]] = {1: first_medias}

        if total_pages == 2 and has_more and not ((first_data.get("info") or {}).get("media_count")):
            page = 2
            while has_more:
                data = await _get_fav_page(client, folder_id, page)
                if data.get("code") != 0:
                    break
                page_data = data.get("data") or {}
                medias = page_data.get("medias", []) or []
                if not medias:
                    break
                pages[page] = medias
                has_more = bool(page_data.get("has_more", False))
                page += 1
        elif total_pages > 1:
            semaphore = asyncio.Semaphore(PAGE_CONCURRENCY)

            async def fetch_page(page: int) -> tuple[int, list[dict]]:
                async with semaphore:
                    data = await _get_fav_page(client, folder_id, page)
                if data.get("code") != 0:
                    return page, []
                medias = (data.get("data") or {}).get("medias", []) or []
                return page, medias

            results = await asyncio.gather(*(fetch_page(page) for page in range(2, total_pages + 1)))
            pages.update(dict(results))

        items: list[dict] = []
        for page in sorted(pages):
            items.extend(_media_to_item(media, folder_id) for media in pages[page])
        return items

    if client is not None:
        return await _do(client)
    else:
        async with _client(cookies) as client:
            return await _do(client)


async def fetch_all_items(uid: str, cookies: dict[str, str] | None = None,
                          folders: list[dict] | None = None,
                          on_progress=None) -> list[dict]:
    """Fetch all favorite folders concurrently and back off only on failures."""
    if folders is None:
        folders = await fetch_fav_folders(uid, cookies)
    valid = [(f.get("media_id") or f.get("id"), f)
             for f in folders if f.get("media_id") or f.get("id")]
    if not valid:
        return []

    completed_total = 0
    results_by_folder: list[list[dict]] = [[] for _ in valid]
    total_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(FOLDER_CONCURRENCY)

    async def fetch_folder(client: httpx.AsyncClient, index: int, fid: int, folder: dict) -> list[dict]:
        nonlocal completed_total
        fname = folder.get("title", "收藏夹")
        items: list[dict] = []
        async with semaphore:
            for attempt in range(3):
                try:
                    items = await fetch_fav_items(fid, cookies, client=client)
                    break
                except Exception as e:
                    if attempt < 2:
                        delay = 1.5 * (attempt + 1)
                        print(f"[fetch_all] '{fname}' fetch failed, retry in {delay:.1f}s: {e}")
                        await asyncio.sleep(delay)
                    else:
                        print(f"[fetch_all] folder '{fname}' (id={fid}) failed: {e}")
                        items = []
        if not items:
            print(f"[fetch_all] folder '{fname}' (id={fid}) returned 0 items")
        for item in items:
            item["folder_name"] = fname
            item["folder_id"] = fid
        async with total_lock:
            results_by_folder[index] = items
            completed_total += len(items)
            total = completed_total
        if on_progress:
            await on_progress(fname, len(items), total)
        return items

    async with _client(cookies) as client:
        tasks = [
            asyncio.create_task(fetch_folder(client, index, fid, folder))
            for index, (fid, folder) in enumerate(valid)
        ]
        await asyncio.gather(*tasks)

    all_items = [item for items in results_by_folder for item in items]
    print(f"[fetch_all] 完成: {len(all_items)} 条, {len(folders)} 个收藏夹")
    return all_items


async def search_all(keyword: str, page: int = 1) -> list[dict]:
    """B站全站搜索"""
    async with _client() as client:
        url = f"{BILI_API}/x/web-interface/wbi/search/type"
        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "page_size": 20,
        }
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return []
        results = (data.get("data") or {}).get("result", []) or []
        return [
            {
                "bvid": r.get("bvid", ""),
                "title": r.get("title", "").replace('<em class="keyword">', "").replace("</em>", ""),
                "intro": r.get("description", ""),
                "upper": r.get("author", ""),
                "cover": r.get("pic", ""),
                "link": f"https://www.bilibili.com/video/{r.get('bvid', '')}",
            }
            for r in results
        ]


async def add_favorite(bvid: str, folder_id: int | None, cookies: dict[str, str]) -> dict:
    """加入收藏夹"""
    async with _client(cookies) as client:
        url = f"{BILI_API}/x/v3/fav/resource/deal"
        payload = {
            "rid": bvid,
            "type": "2",
            "add_media_ids": str(folder_id) if folder_id else "",
            "del_media_ids": "",
            "csrf": cookies.get("bili_jct", ""),
        }
        resp = await client.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "message": data.get("message", "加入失败")}
        return {"success": True, "message": "已加入收藏"}


async def get_user_info(uid: str) -> dict:
    """获取用户昵称和头像"""
    async with _client() as client:
        url = f"{BILI_API}/x/space/acc/info"
        params = {"mid": uid}
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return {"nickname": "", "avatar": ""}
        info = (data.get("data") or {})
        return {
            "nickname": info.get("name", ""),
            "avatar": info.get("face", ""),
        }


async def fetch_history(cookies: dict[str, str], days: int = 90,
                      on_progress=None) -> list[dict]:
    """拉取最近 N 天 B站观看历史，支持进度回调"""
    cutoff = time.time() - days * 86400
    history: list[dict] = []
    max_id = 0
    print(f"[history] 开始拉取观看历史, days={days}, cutoff_ts={int(cutoff)}")
    async with _client(cookies) as client:
        while True:
            url = f"{BILI_API}/x/web-interface/history/cursor"
            params: dict = {
                "max": str(max_id),
                "view_at": str(max_id),  # B站游标分页：max 和 view_at 用同一个值
                "ps": 20,
                "type": "archive",
            }
            try:
                resp = await client.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"[history] 请求失败 (max_id={max_id}): {e}")
                break
            code = data.get("code")
            items = (data.get("data") or {}).get("list", []) or []
            has_more = (data.get("data") or {}).get("has_more", False)
            print(f"[history] page max={max_id} code={code} items={len(items)} has_more={has_more}")
            if code != 0:
                print(f"[history] API code={code} msg={data.get('message')} — 停止拉取")
                break
            if not items:
                break
            for item in items:
                view_at = item.get("view_at", 0)
                # 超过 N 天前的记录，停止拉取
                if view_at < cutoff:
                    print(f"[history] 已到达 {days} 天前的记录 (view_at={view_at} < cutoff={int(cutoff)}) — 停止拉取")
                    if on_progress:
                        await on_progress(len(history))
                    return history
                history.append({
                    "bvid": item.get("bvid", ""),
                    "title": item.get("title", ""),
                    "view_at": view_at,
                })
            if on_progress:
                await on_progress(len(history))
            max_id = items[-1].get("view_at", 0)
            if not has_more:
                break
            await asyncio.sleep(0.3)
    print(f"[history] 结束: 共 {len(history)} 条记录")
    return history
