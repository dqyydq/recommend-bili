import asyncio
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
            return (data.get("data") or {}).get("list", [])
        return []


async def fetch_fav_items(folder_id: int, cookies: dict[str, str] | None = None) -> list[dict]:
    items: list[dict] = []
    page = 1
    async with _client(cookies, extra_headers={"Referer": "https://space.bilibili.com/"}) as client:
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
                    "bvid": media.get("bvid", ""),
                    "title": media.get("title", ""),
                    "intro": media.get("intro", ""),
                    "upper": (media.get("upper") or {}).get("name", ""),
                    "cover": media.get("cover", ""),
                    "link": f"https://www.bilibili.com/video/{media.get('bvid', '')}",
                    "source_folder": str(folder_id),
                })
            if not has_more or not medias:
                break
            page += 1
            await asyncio.sleep(0.8)
    return items


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
