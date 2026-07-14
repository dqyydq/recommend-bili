import time

from database import replace_folder_snapshot, upsert_user


DEMO_UID = "9000000000"


async def seed_demo_data() -> None:
    now = int(time.time())
    await upsert_user(DEMO_UID, "演示用户", "")
    folders = [
        (1001, "Agent 与 RAG", [
            (2001, "从零构建 RAG 检索系统", "知识库、向量检索与重排实战", "技术拾荒者", 8),
            (2002, "FastAPI Agent 工具调用", "用 FastAPI 编排可审计工具", "后端实验室", 18),
            (2003, "Chroma 混合检索实践", "向量召回和关键词检索", "AI 工程笔记", 65),
        ]),
        (1002, "产品与设计", [
            (2101, "个人知识产品如何持续有用", "从一次性工具到持续反馈闭环", "产品沉思录", 12),
            (2102, "复杂工具的工作台信息架构", "任务、上下文和待确认操作", "设计系统", 95),
        ]),
        (1003, "历史兴趣", [
            (2201, "篮球基础脚步训练", "适合初学者的脚步练习", "球场课堂", 760),
            (2202, "投篮动作拆解", "投篮姿势与发力顺序", "篮球研究所", 680),
        ]),
    ]
    for folder_id, title, videos in folders:
        items = [{
            "id": media_id,
            "bvid": f"BV{media_id}",
            "title": video_title,
            "intro": intro,
            "upper": upper,
            "cover": "",
            "link": f"https://www.bilibili.com/video/BV{media_id}",
            "fav_time": now - age_days * 86400,
        } for media_id, video_title, intro, upper, age_days in videos]
        await replace_folder_snapshot(DEMO_UID, {"media_id": folder_id, "title": title, "media_count": len(items)}, items)
