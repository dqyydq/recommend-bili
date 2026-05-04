def is_invalid(media: dict) -> bool:
    """检测视频是否失效 (B站 attr 位掩码)"""
    attr = media.get("attr", 0)
    return attr < 0 or (attr & 0x20) != 0


async def scan_invalid(cookies: dict, fetch_fav_folders, fetch_fav_items, uid: str) -> list[dict]:
    """扫描全量收藏夹，返回失效视频列表"""
    folders = await fetch_fav_folders(uid, cookies)
    invalid: list[dict] = []
    for folder in folders:
        fid = folder.get("media_id") or folder.get("id")
        if not fid:
            continue
        items = await fetch_fav_items(fid, cookies)
        for item in items:
            if is_invalid(item):
                item["folder_name"] = folder.get("title", "收藏夹")
                invalid.append(item)
    return invalid
