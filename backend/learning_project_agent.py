from typing import Any

from openai import AsyncOpenAI

from agents import DEEPSEEK_BASE_URL, _json_from_text, semantic_search_favorites
from database import append_learning_message, get_learning_project, save_learning_draft_tasks, save_learning_summary, save_weekly_review


def _fallback_tasks(results: list[dict[str, Any]], weekly_minutes: int) -> list[dict[str, Any]]:
    count = max(1, min(5, len(results)))
    minutes = max(15, weekly_minutes // count)
    return [{
        "title": item.get("title", "学习收藏"),
        "rationale": "从与你目标最相关的收藏开始，完成后记录一个可复用结论。",
        "favorite_refs": [{key: item.get(key, "") for key in ("folder_id", "media_id", "id", "bvid", "title", "link", "upper", "folder_name")}],
        "estimated_minutes": minutes,
    } for item in results[:count]]


def _allowed_tasks(raw_tasks: Any, results: list[dict[str, Any]], weekly_minutes: int) -> list[dict[str, Any]]:
    allowed = {str(item.get("bvid") or ""): item for item in results if item.get("bvid")}
    tasks: list[dict[str, Any]] = []
    for raw in raw_tasks if isinstance(raw_tasks, list) else []:
        refs = []
        for bvid in raw.get("bvids", []) if isinstance(raw, dict) else []:
            item = allowed.get(str(bvid))
            if item:
                refs.append({key: item.get(key, "") for key in ("folder_id", "media_id", "id", "bvid", "title", "link", "upper", "folder_name")})
        if refs and isinstance(raw, dict) and str(raw.get("title") or "").strip():
            tasks.append({
                "title": str(raw["title"]).strip()[:160],
                "rationale": str(raw.get("rationale") or "从相关收藏中完成一个可观察的学习产出。")[:400],
                "favorite_refs": refs,
                "estimated_minutes": max(15, min(weekly_minutes, int(raw.get("estimated_minutes") or 30))),
            })
        if len(tasks) >= 5:
            break
    return tasks or _fallback_tasks(results, weekly_minutes)


def build_review_summary(week: int, tasks: list[dict[str, Any]]) -> tuple[float, str, int]:
    completed = sum(task.get("state") == "completed" for task in tasks)
    skipped = sum(task.get("state") == "skipped" for task in tasks)
    blocked_tasks = [task for task in tasks if task.get("state") == "blocked"]
    rate = round(completed / len(tasks), 2) if tasks else 0.0
    summary = f"第 {week} 周完成 {completed}/{len(tasks)} 项，跳过 {skipped} 项，阻塞 {len(blocked_tasks)} 项。"
    blockers = "；".join(task.get("user_note") or task.get("title", "") for task in blocked_tasks[:3])
    if blockers:
        summary += f" 主要阻塞：{blockers}。"
    return rate, summary, len(blocked_tasks)


def adjust_proposed_tasks(tasks: list[dict[str, Any]], blocked_count: int) -> list[dict[str, Any]]:
    if not blocked_count:
        return tasks
    adjusted = [dict(task) for task in tasks[:max(1, len(tasks) - 1)]]
    for task in adjusted:
        task["estimated_minutes"] = max(15, int(task["estimated_minutes"] * 0.75))
        task["rationale"] = "上周存在阻塞，本周缩小任务范围并优先完成可验证的小产出。"
    return adjusted


async def build_project_week(uid: str, project_id: str, cookies: dict, api_key: str, model: str, week_number: int | None = None) -> dict[str, Any] | None:
    project = await get_learning_project(uid, project_id)
    if project is None:
        return None
    week = week_number or int(project["current_week"])
    saved_refs = list((project.get("context") or {}).get("favorite_refs") or [])
    search = await semantic_search_favorites(uid, cookies, project["goal"], api_key, model, top_k=10)
    seen = {str(item.get("bvid") or "") for item in saved_refs}
    results = saved_refs + [item for item in search.get("results", []) if str(item.get("bvid") or "") not in seen]
    tasks = _fallback_tasks(results, int(project["weekly_minutes"]))
    if results:
        prompt = (
            "Generate 3-5 weekly learning tasks as JSON only. Use only provided bvids. "
            "Schema: {\"tasks\":[{\"title\":str,\"rationale\":str,\"bvids\":[str],\"estimated_minutes\":int}]}.\n"
            f"Goal: {project['goal']}\nWeekly minutes: {project['weekly_minutes']}\nCandidates: "
            + "\n".join(f"{item['bvid']} | {item['title']}" for item in results)
        )
        try:
            client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
            response = await client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=900, temperature=0.35)
            parsed = _json_from_text(response.choices[0].message.content or "") or {}
            tasks = _allowed_tasks(parsed.get("tasks"), results, int(project["weekly_minutes"]))
        except Exception as exc:
            print(f"[learning_project] plan fallback: {exc}")
    return await save_learning_draft_tasks(uid, project_id, week, tasks)


async def chat_with_project(uid: str, project_id: str, cookies: dict, message: str, api_key: str, model: str) -> dict[str, Any] | None:
    project = await get_learning_project(uid, project_id)
    if project is None or not await append_learning_message(uid, project_id, "user", message):
        return None
    search = await semantic_search_favorites(uid, cookies, message, api_key, model, top_k=6)
    recent = project.get("messages", [])[-10:]
    tasks = [task for task in project.get("tasks", []) if task.get("week_number") == project.get("current_week")]
    prompt = (
        "You are a concise Chinese learning companion. Answer only for this project. Do not invent saved videos or execute actions. "
        f"Goal: {project['goal']}\nSummary: {project.get('summary', '')}\n"
        f"Tasks: {[{'title': t['title'], 'state': t['state'], 'note': t['user_note']} for t in tasks]}\n"
        f"Recent conversation: {[(m['role'], m['content']) for m in recent]}\n"
        f"Retrieved favorites: {[(r['title'], r['link']) for r in search.get('results', [])]}\nUser: {message}"
    )
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        response = await client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=600, temperature=0.55)
        answer = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[learning_project] chat fallback: {exc}")
        answer = "我已记下你的问题。先从本周最小的一项任务开始，完成后告诉我哪里卡住了。"
    await append_learning_message(uid, project_id, "assistant", answer)
    await save_learning_summary(uid, project_id, f"最近关注：{message[:160]}")
    return await get_learning_project(uid, project_id)


async def build_project_review(uid: str, project_id: str, cookies: dict, api_key: str, model: str) -> dict[str, Any] | None:
    project = await get_learning_project(uid, project_id)
    if project is None:
        return None
    week = int(project["current_week"])
    tasks = [task for task in project.get("tasks", []) if task.get("week_number") == week and task.get("state") != "draft"]
    rate, summary, blocked_count = build_review_summary(week, tasks)
    next_search = await semantic_search_favorites(uid, cookies, project["goal"], api_key, model, top_k=8)
    proposed = _fallback_tasks(next_search.get("results", []), int(project["weekly_minutes"]))
    proposed = adjust_proposed_tasks(proposed, blocked_count)
    return await save_weekly_review(uid, project_id, week, rate, summary, proposed)
