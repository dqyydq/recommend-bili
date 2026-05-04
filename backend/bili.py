import asyncio
import time
import httpx

BILI_API = "https://api.bilibili.com"
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
    return httpx.AsyncClient(headers=h, cookies=jar, follow_redirects=True)


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
    items: list[dict] = []
    page = 1

    async def _do(client: httpx.AsyncClient):
        nonlocal page
        while True:
            url = f"{BILI_API}/x/v3/fav/resource/list"
            params = {
                "media_id": folder_id,
                "pn": page,
                "ps": 20,
            }
            resp = await client.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                break
            medias = (data.get("data") or {}).get("medias", []) or []
            has_more = (data.get("data") or {}).get("has_more", False)
            for media in medias:
                items.append({
                    "id": media.get("id", 0),
                    "bvid": media.get("bvid", ""),
                    "title": media.get("title", ""),
                    "intro": media.get("intro", ""),
                    "upper": (media.get("upper") or {}).get("name", ""),
                    "cover": media.get("cover", ""),
                    "link": f"https://www.bilibili.com/video/{media.get('bvid', '')}",
                    "source_folder": str(folder_id),
                    "fav_time": media.get("fav_time", 0),
                })
            if not has_more or not medias:
                break
            page += 1
            await asyncio.sleep(0.3)

    if client is not None:
        await _do(client)
    else:
        async with _client(cookies) as client:
            await _do(client)
    return items


_FOLDER_SEM = asyncio.Semaphore(2)


async def fetch_all_items(uid: str, cookies: dict[str, str] | None = None,
                          folders: list[dict] | None = None,
                          on_progress=None) -> list[dict]:
    """并行抓取所有收藏夹的视频（共享 client + 错峰启动）"""
    if folders is None:
        folders = await fetch_fav_folders(uid, cookies)
    valid = {f.get("media_id") or f.get("id"): f
             for f in folders if f.get("media_id") or f.get("id")}
    if not valid:
        return []

    fids = list(valid.keys())

    async with _client(cookies) as client:

        async def _fetch_one(fid: int, idx: int):
            # 错峰启动：每个任务间隔 0.15s，避免同时建连触发风控
            await asyncio.sleep(idx * 0.15)
            async with _FOLDER_SEM:
                return await fetch_fav_items(fid, cookies, client=client)

        results = await asyncio.gather(
            *[_fetch_one(fid, i) for i, fid in enumerate(fids)],
            return_exceptions=True,
        )

    all_items: list[dict] = []
    for fid, items in zip(fids, results):
        folder = valid[fid]
        fname = folder.get("title", "收藏夹")
        if isinstance(items, Exception):
            print(f"[fetch_all] 收藏夹 '{fname}' (id={fid}) 抓取异常: {items}")
            continue
        if not items:
            print(f"[fetch_all] 收藏夹 '{fname}' (id={fid}) 返回 0 条，可能被限流或为空")
        for item in items:
            item["folder_name"] = fname
            item["folder_id"] = fid
        all_items.extend(items)
        if on_progress:
            await on_progress(fname, len(items), len(all_items))

    print(f"[fetch_all] 完成: {len(all_items)} 条, {len(fids)} 个收藏夹")
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


async def fetch_history(cookies: dict[str, str], days: int = 90) -> list[dict]:
    """拉取最近 N 天 B站观看历史"""
    cutoff = time.time() - days * 86400
    history: list[dict] = []
    max_id = 0
    async with _client(cookies) as client:
        while True:
            url = f"{BILI_API}/x/web-interface/history/cursor"
            params = {
                "max": str(max_id) if max_id else "0",
                "view_at": str(int(cutoff)),
                "ps": 20,
                "type": "archive",
            }
            resp = await client.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                break
            items = (data.get("data") or {}).get("list", []) or []
            if not items:
                break
            for item in items:
                history.append({
                    "bvid": item.get("bvid", ""),
                    "title": item.get("title", ""),
                    "view_at": item.get("view_at", 0),
                })
            max_id = items[-1].get("view_at", 0)
            if len(items) < 20:
                break
            await asyncio.sleep(0.3)
    return history
