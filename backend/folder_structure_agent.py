from collections import defaultdict
from typing import Any

from database import create_folder_structure_plan, get_favorites

TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("RAG 与知识库", ("rag", "知识库", "向量数据库", "chroma", "检索增强")),
    ("Agent 开发", ("agent", "智能体", "tool calling", "function calling", "mcp")),
    ("FastAPI 与后端", ("fastapi", "后端", "api", "数据库", "postgres", "docker")),
    ("Python", ("python", "django", "flask", "pandas", "爬虫")),
    ("前端开发", ("javascript", "typescript", "vue", "react", "css", "前端")),
    ("算法与基础", ("算法", "数据结构", "leetcode", "计算机", "操作系统")),
    ("设计与产品", ("设计", "产品", "ui", "ux", "figma")),
    ("效率工具", ("效率", "工具", "obsidian", "notion", "自动化")),
    ("影视与纪录片", ("纪录片", "电影", "影视", "剧集", "访谈")),
    ("生活与兴趣", ("旅行", "美食", "摄影", "音乐", "健身", "游戏")),
]


def _text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ("title", "intro", "upper", "folder_name")).lower()


def _topic(item: dict[str, Any]) -> tuple[str, float]:
    text = _text(item)
    for topic, keywords in TOPICS:
        if any(keyword in text for keyword in keywords):
            return topic, 0.82
    return "待复查", 0.35


def _purpose(item: dict[str, Any], topic: str) -> str:
    text = _text(item)
    if topic == "待复查":
        return "已完成/待复查"
    if topic in {"影视与纪录片", "生活与兴趣"}:
        return "待消遣"
    if any(keyword in text for keyword in ("文档", "手册", "参考", "合集", "资源", "工具")):
        return "常用资料"
    return "待学习"


def build_structure_actions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[tuple[dict[str, Any], float]]] = defaultdict(list)
    for item in items:
        topic, confidence = _topic(item)
        groups[(_purpose(item, topic), topic)].append((item, confidence))

    actions = []
    for (purpose, topic), grouped in groups.items():
        average = round(sum(confidence for _, confidence in grouped) / len(grouped), 2)
        destination = f"{purpose} / {topic}"
        actions.append({
            "purpose": purpose,
            "topic": topic,
            "destination_name": destination,
            "item_count": len(grouped),
            "confidence": average,
            "items": [{
                "media_id": item.get("id"), "folder_id": item.get("folder_id"), "bvid": item.get("bvid", ""),
                "title": item.get("title", ""), "link": item.get("link", ""), "source_folder": item.get("folder_name", ""),
            } for item, _ in grouped],
        })
    return sorted(actions, key=lambda action: (action["purpose"], -action["item_count"], action["topic"]))


async def build_folder_structure_plan(uid: str, goal: str) -> dict[str, Any]:
    items = await get_favorites(uid)
    if not items:
        return {"error": "本地收藏快照为空，请先完成同步"}
    actions = build_structure_actions(items)
    return await create_folder_structure_plan(uid, goal.strip() or "按用途与主题重建收藏夹结构", actions)
