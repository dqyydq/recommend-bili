import asyncio
from datetime import datetime, timezone
from typing import Any

from bili import _client
from clean import inspect_bvid
from database import save_cleanup_scan_items, update_cleanup_scan


def cleanup_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"confirmed_invalid": 0, "review_required": 0, "unknown": 0, "available": 0}
    for item in items:
        counts[item["verdict"]] += 1
    return counts


async def run_cleanup_scan(scan_id: str, cookies: dict[str, str], items: list[dict[str, Any]]) -> None:
    total = len(items)
    checked = 0
    results: list[dict[str, Any]] = []
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(12)
    try:
        await update_cleanup_scan(scan_id, status="running", started_at=datetime.now(timezone.utc), message="正在检测视频状态")
        async with _client(cookies) as client:
            async def verify(item: dict[str, Any]) -> None:
                nonlocal checked
                async with semaphore:
                    verdict, reason = await inspect_bvid(str(item.get("bvid") or ""), client)
                record = {**item, "verdict": verdict, "reason": reason}
                async with lock:
                    results.append(record)
                    checked += 1
                    if checked % 10 == 0 or checked == total:
                        counts = cleanup_counts(results)
                        await update_cleanup_scan(
                            scan_id, checked=checked, confirmed_invalid_count=counts["confirmed_invalid"],
                            review_required_count=counts["review_required"], unknown_count=counts["unknown"],
                            available_count=counts["available"], message=f"已检测 {checked}/{total} 条",
                        )

            await asyncio.gather(*(verify(item) for item in items))
        await save_cleanup_scan_items(scan_id, results)
        counts = cleanup_counts(results)
        await update_cleanup_scan(
            scan_id, status="completed", checked=total, confirmed_invalid_count=counts["confirmed_invalid"],
            review_required_count=counts["review_required"], unknown_count=counts["unknown"],
            available_count=counts["available"], message="扫描完成", finished_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        await update_cleanup_scan(
            scan_id, status="failed", error_message=str(exc)[:2000], message="扫描失败",
            finished_at=datetime.now(timezone.utc),
        )
        print(f"[cleanup] scan={scan_id} failed: {exc}")
