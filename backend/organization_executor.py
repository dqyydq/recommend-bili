import asyncio
from collections import defaultdict
from typing import Any

import httpx

from bili import _client
from clean import _check_bvid
from database import (
    claim_organization_plan_execution,
    finish_organization_plan_execution,
    get_executable_plan_actions,
    get_organization_plan,
    set_plan_action_execution_result,
)

CHECK_CONCURRENCY = 6
DELETE_URL = "https://api.bilibili.com/x/v3/fav/resource/batch-del"


async def _execute_claimed_organization_plan(uid: str, plan_id: str, cookies: dict[str, str]) -> dict[str, int]:
    actions = await get_executable_plan_actions(uid, plan_id)
    counts = {"deleted": 0, "skipped_valid": 0, "skipped_unreachable": 0, "failed": 0}
    if not actions:
        await finish_organization_plan_execution(uid, plan_id, "completed")
        return counts

    invalid_by_folder: dict[int, list[dict[str, Any]]] = defaultdict(list)
    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)

    async with _client(cookies) as client:
        async def check(action: dict[str, Any]) -> tuple[dict[str, Any], str]:
            async with semaphore:
                return action, await _check_bvid(str(action.get("bvid") or ""), client)

        checks = await asyncio.gather(*(check(action) for action in actions))
        for action, status in checks:
            if status == "invalid":
                invalid_by_folder[int(action["folder_id"])].append(action)
            elif status == "valid":
                await set_plan_action_execution_result(uid, plan_id, action["id"], "skipped_valid", "The resource is still available.")
                counts["skipped_valid"] += 1
            else:
                await set_plan_action_execution_result(uid, plan_id, action["id"], "skipped_unreachable", "Could not verify the resource. Nothing was deleted.")
                counts["skipped_unreachable"] += 1

        for folder_id, group in invalid_by_folder.items():
            resources = ",".join(f"{int(action['media_id'])}:2" for action in group)
            try:
                response = await client.post(
                    DELETE_URL,
                    data={"media_id": folder_id, "resources": resources, "csrf": cookies["bili_jct"]},
                    timeout=30,
                )
                data = response.json()
                if response.status_code == 200 and data.get("code") == 0:
                    for action in group:
                        await set_plan_action_execution_result(uid, plan_id, action["id"], "deleted", "Deleted after a fresh invalid-resource check.")
                        counts["deleted"] += 1
                else:
                    for action in group:
                        await set_plan_action_execution_result(uid, plan_id, action["id"], "failed", "Bilibili did not accept this deletion. Nothing was assumed deleted.")
                        counts["failed"] += 1
            except (httpx.HTTPError, ValueError):
                for action in group:
                    await set_plan_action_execution_result(uid, plan_id, action["id"], "failed", "The deletion request failed. You can retry this action later.")
                    counts["failed"] += 1

    if counts["failed"] and not counts["deleted"] and not counts["skipped_valid"]:
        execution_status = "failed"
    elif counts["failed"] or counts["skipped_unreachable"]:
        execution_status = "partial_failed"
    else:
        execution_status = "completed"
    await finish_organization_plan_execution(uid, plan_id, execution_status)
    return counts


async def execute_organization_plan(uid: str, plan_id: str, cookies: dict[str, str]) -> dict[str, Any]:
    """Execute only server-stored, approved actions after fresh invalid checks."""
    if not await claim_organization_plan_execution(uid, plan_id):
        return {"claimed": False, "plan": await get_organization_plan(uid, plan_id), "counts": {}}

    try:
        counts = await _execute_claimed_organization_plan(uid, plan_id, cookies)
    except Exception as exc:
        print(f"[organization_executor] plan={plan_id} failed: {exc}")
        await finish_organization_plan_execution(uid, plan_id, "failed")
        counts = {"deleted": 0, "skipped_valid": 0, "skipped_unreachable": 0, "failed": 1}
    return {"claimed": True, "plan": await get_organization_plan(uid, plan_id), "counts": counts}
