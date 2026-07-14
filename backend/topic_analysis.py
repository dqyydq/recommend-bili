import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from classifier import classify_favorites
from database import save_topic_analysis_result, set_topic_analysis_status


def snapshot_version(items: list[dict[str, Any]]) -> str:
    identity = [
        (int(item.get("folder_id") or 0), int(item.get("id") or 0), int(item.get("fav_time") or 0), str(item.get("title") or ""))
        for item in items
    ]
    encoded = json.dumps(sorted(identity), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(item.get("id") or 0),
        "folder_id": int(item.get("folder_id") or 0),
        "bvid": str(item.get("bvid") or ""),
        "title": str(item.get("title") or ""),
        "upper": str(item.get("upper") or ""),
        "link": str(item.get("link") or ""),
        "fav_time": int(item.get("fav_time") or 0),
    }


def enrich_topic_clusters(categories: list[dict[str, Any]], now: float | None = None) -> list[dict[str, Any]]:
    current = now or time.time()
    clusters: list[dict[str, Any]] = []
    for category in categories:
        source_items = sorted(category.get("items", []), key=lambda item: int(item.get("fav_time") or 0), reverse=True)
        items = [_public_item(item) for item in source_items]
        creators = Counter(item["upper"] for item in items if item["upper"])
        months = Counter()
        for item in items:
            if item["fav_time"]:
                month = datetime.fromtimestamp(item["fav_time"], tz=timezone.utc).strftime("%Y-%m")
                months[month] += 1
        newest = max((item["fav_time"] for item in items), default=0)
        age_days = (current - newest) / 86400 if newest else float("inf")
        # Dormant is reserved for an explicit user statement or confirmation.
        interest_state = "active" if age_days <= 90 else "cooling" if age_days <= 365 else "historical"
        clusters.append({
            "name": str(category.get("name") or "未命名主题")[:80],
            "summary": f"包含 {len(items)} 条收藏，最近一次收藏在 {int(age_days) if age_days != float('inf') else '未知'} 天前。",
            "items": items,
            "representative_items": items[:5],
            "upper_creators": [{"name": name, "count": count} for name, count in creators.most_common(5)],
            "time_trend": {"monthly": dict(sorted(months.items())), "newest_fav_time": newest},
            "interest_state": interest_state,
        })
    return sorted(clusters, key=lambda cluster: len(cluster["items"]), reverse=True)


async def run_topic_analysis(
    analysis_id: str,
    items: list[dict[str, Any]],
    api_key: str,
    model: str,
) -> None:
    try:
        await set_topic_analysis_status(analysis_id, "running", "正在生成向量并聚合主题")
        result = await classify_favorites(items, api_key, model=model)
        clusters = enrich_topic_clusters(result.get("categories", []))
        await save_topic_analysis_result(analysis_id, clusters)
    except Exception as exc:
        await set_topic_analysis_status(analysis_id, "failed", "主题分析失败", str(exc))
        print(f"[topics] analysis={analysis_id} failed: {exc}")
