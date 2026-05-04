def is_invalid(media: dict) -> bool:
    """检测视频是否失效 — 多条件判定"""
    title = media.get("title", "")
    bvid = media.get("bvid", "")
    attr = media.get("attr", 0)

    # 标题为"已失效视频" → B站 标记失效
    if title == "已失效视频":
        return True

    # bvid 为空 → 无法访问
    if not bvid:
        return True

    # attr 位掩码: 常见失效标记位 = 0x01(删除) | 0x04(审核) | 0x20(私密/失效)
    if attr < 0 or (attr & 0x25) != 0:
        return True

    return False


async def scan_invalid(cookies: dict, fetch_fav_folders, fetch_fav_items, uid: str) -> list[dict]:
    """扫描全量收藏夹，返回失效视频列表"""
    folders = await fetch_fav_folders(uid, cookies)
    invalid: list[dict] = []
    total = 0
    skipped = 0
    seen_attrs: set[int] = set()
    for folder in folders:
        fid = folder.get("media_id") or folder.get("id")
        if not fid:
            continue
        try:
            items = await fetch_fav_items(fid, cookies)
        except Exception as e:
            skipped += 1
            print(f"[clean] skip folder {fid}: {e}")
            continue
        for item in items:
            total += 1
            seen_attrs.add(item.get("attr", 0))
            if is_invalid(item):
                item["folder_name"] = folder.get("title", "收藏夹")
                invalid.append(item)
        await asyncio.sleep(0.5)
    print(f"[clean] scanned {total} items from {len(folders)} folders (skipped {skipped}), attrs: {sorted(seen_attrs)}")
    return invalid
