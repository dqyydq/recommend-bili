import json
import os
import re
import time
from collections import Counter

from openai import AsyncOpenAI

from bili import fetch_all_items, fetch_fav_folders
from classifier import DEEPSEEK_BASE_URL, get_embeddings

CHROMA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "chroma"))
PROFILE_SAMPLE_SIZE = 80
CHROMA_BATCH_SIZE = 500
RECENT_LIMIT = 6


def _safe_collection_name(uid: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", uid or "anonymous")
    return f"favorites_{cleaned}"[:63]


def _item_text(item: dict) -> str:
    parts = [
        item.get("title", ""),
        item.get("intro", ""),
        item.get("upper", ""),
        item.get("folder_name", ""),
    ]
    return " ".join(part for part in parts if part)[:800]


def _chunks(values: list, size: int):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _json_from_text(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _fallback_profile(items: list[dict]) -> dict:
    folders = Counter(item.get("folder_name", "收藏夹") for item in items)
    uppers = Counter(item.get("upper", "") for item in items if item.get("upper"))
    title_words = Counter()
    for item in items:
        for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", item.get("title", "")):
            title_words[token] += 1

    top_words = [word for word, _ in title_words.most_common(8)]
    persona = "收藏探索家" if len(items) < 30 else "兴趣仓库管理员"
    return {
        "persona": persona,
        "subtitle": "你的收藏里藏着一条很有个人风格的兴趣路线。",
        "tags": top_words[:6] or ["学习", "灵感", "待看"],
        "radar": [
            {"label": "学习密度", "score": 70},
            {"label": "娱乐补给", "score": 55},
            {"label": "技术含量", "score": 65},
            {"label": "吃灰风险", "score": 60},
            {"label": "探索欲", "score": 75},
        ],
        "insights": [
            f"收藏最多的文件夹是「{folders.most_common(1)[0][0]}」。" if folders else "你的收藏夹结构还比较轻。",
            f"常出现的 UP 主包括：{', '.join(name for name, _ in uppers.most_common(3))}。" if uppers else "UP 主分布比较分散。",
            "可以先从收藏时间较久、标题仍然吸引你的内容开始复盘。",
        ],
        "roasts": [
            "这些收藏不是仓储物流，偶尔也需要被打开一下。",
            "先看一个 12 分钟的，给未来的自己一点交代。",
        ],
        "actions": [
            "今天挑 3 个最想看的视频，建一个「本周真看」小清单。",
            "把重复的入门教程合并，只留下最新或最系统的一版。",
            "给最大的一类收藏起一个更具体的名字，减少下次寻找成本。",
        ],
    }


def _keyword_reason(query: str, meta: dict) -> str:
    haystack = f"{meta.get('title', '')} {meta.get('folder_name', '')} {meta.get('upper', '')}".lower()
    tokens = [token.lower() for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", query)]
    hits = [token for token in tokens if token in haystack]
    if hits:
        return f"命中关键词：{', '.join(hits[:3])}"
    if meta.get("folder_name"):
        return f"语义接近，来源收藏夹：{meta.get('folder_name')}"
    return "语义相似度较高"


async def build_knowledge_dashboard(uid: str, cookies: dict, folders: list[dict] | None = None) -> dict:
    items, folders = await fetch_session_items(uid, cookies, folders)
    now = time.time()
    dust_items = [
        item for item in items
        if item.get("fav_time") and now - item.get("fav_time", 0) > 60 * 86400
    ]
    light_dust_items = [
        item for item in items
        if item.get("fav_time") and 30 * 86400 < now - item.get("fav_time", 0) <= 60 * 86400
    ]
    folders_counter = Counter(item.get("folder_name", "收藏夹") for item in items)
    uppers_counter = Counter(item.get("upper", "") for item in items if item.get("upper"))
    recent_items = sorted(items, key=lambda item: item.get("fav_time", 0), reverse=True)[:RECENT_LIMIT]
    old_but_named = sorted(dust_items, key=lambda item: item.get("fav_time", 0))[:RECENT_LIMIT]

    collection_count = 0
    try:
        collection_count = _get_chroma_collection(uid).count()
    except Exception:
        collection_count = 0

    total = len(items)
    health_score = 100
    if total:
        health_score -= min(45, int(len(dust_items) / total * 60))
        health_score -= min(20, max(0, len(folders_counter) - 12))
    health_score = max(30 if total else 0, min(100, health_score))

    return {
        "total": total,
        "folders_count": len(folders or []),
        "indexed": collection_count,
        "dust_count": len(dust_items),
        "light_dust_count": len(light_dust_items),
        "health_score": health_score,
        "top_folders": [
            {"name": name, "count": count}
            for name, count in folders_counter.most_common(6)
        ],
        "top_uppers": [
            {"name": name, "count": count}
            for name, count in uppers_counter.most_common(6)
        ],
        "recent_items": [
            {
                "title": item.get("title", ""),
                "upper": item.get("upper", ""),
                "link": item.get("link", ""),
                "folder_name": item.get("folder_name", ""),
                "fav_time": item.get("fav_time", 0),
            }
            for item in recent_items
        ],
        "today_actions": [
            "用智能检索找一个今天要看的主题。",
            "从高吃灰收藏里打开 1 个仍然有价值的视频。",
            "重建一次索引，确保最近新增收藏可被语义检索。",
        ],
        "cleanup_candidates": [
            {
                "title": item.get("title", ""),
                "upper": item.get("upper", ""),
                "link": item.get("link", ""),
                "folder_name": item.get("folder_name", ""),
                "fav_time": item.get("fav_time", 0),
            }
            for item in old_but_named
        ],
    }


async def fetch_session_items(uid: str, cookies: dict, folders: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    if folders is None:
        folders = await fetch_fav_folders(uid, cookies)
    items = await fetch_all_items(uid, cookies, folders=folders)
    return items, folders


async def analyze_favorite_profile(
    uid: str,
    cookies: dict,
    api_key: str,
    model: str,
    folders: list[dict] | None = None,
) -> dict:
    items, folders = await fetch_session_items(uid, cookies, folders)
    if not items:
        return {"error": "收藏夹为空，暂时无法生成画像"}

    recent_items = sorted(items, key=lambda item: item.get("fav_time", 0), reverse=True)[:PROFILE_SAMPLE_SIZE]
    folders_counter = Counter(item.get("folder_name", "收藏夹") for item in items)
    uppers_counter = Counter(item.get("upper", "") for item in items if item.get("upper"))
    now = time.time()
    old_count = sum(1 for item in items if item.get("fav_time") and now - item.get("fav_time", 0) > 60 * 86400)

    sample_lines = [
        f"- {item.get('title', '')} | UP:{item.get('upper', '')} | 文件夹:{item.get('folder_name', '')}"
        for item in recent_items
    ]
    prompt = f"""
你是一个有趣但克制的 B 站收藏夹人格画像 Agent。请根据用户收藏内容生成 JSON，不要输出 Markdown。

硬性 JSON schema：
{{
  "persona": "不超过12字的人格称号",
  "subtitle": "一句轻松但不油腻的画像说明",
  "tags": ["3-8个兴趣标签"],
  "radar": [{{"label":"学习密度","score":0到100}}, {{"label":"娱乐补给","score":0到100}}, {{"label":"技术含量","score":0到100}}, {{"label":"吃灰风险","score":0到100}}, {{"label":"探索欲","score":0到100}}],
  "insights": ["3-5条具体观察"],
  "roasts": ["2-3条轻松吐槽，不要冒犯"],
  "actions": ["3条今天能做的小行动"]
}}

统计信息：
- 收藏总数：{len(items)}
- 收藏夹数：{len(folders or [])}
- 超过60天未动的收藏数：{old_count}
- 收藏最多的文件夹：{folders_counter.most_common(5)}
- 常见UP主：{uppers_counter.most_common(5)}

最近/代表性收藏：
{chr(10).join(sample_lines)}
""".strip()

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            temperature=0.8,
        )
        profile = _json_from_text(resp.choices[0].message.content or "")
    except Exception as e:
        print(f"[profile_agent] LLM failed, using fallback: {e}")
        profile = {}

    if not profile:
        profile = _fallback_profile(items)

    profile["total"] = len(items)
    profile["folders_count"] = len(folders or [])
    profile["dust_count"] = old_count
    return profile


def _get_chroma_collection(uid: str):
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("缺少 chromadb 依赖，请先安装 backend/requirements.txt") from exc

    os.makedirs(CHROMA_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_or_create_collection(
        name=_safe_collection_name(uid),
        metadata={"hnsw:space": "cosine"},
    )


async def rebuild_favorite_index(uid: str, cookies: dict, folders: list[dict] | None = None) -> dict:
    items, folders = await fetch_session_items(uid, cookies, folders)
    collection = _get_chroma_collection(uid)
    existing = collection.get(include=[])
    if existing.get("ids"):
        collection.delete(ids=existing["ids"])

    if not items:
        return {"indexed": 0, "folders_count": len(folders or [])}

    texts = [_item_text(item) for item in items]
    embeddings = await get_embeddings(texts)
    ids = [
        f"{item.get('bvid') or 'item'}-{item.get('folder_id') or item.get('source_folder') or 'folder'}-{index}"
        for index, item in enumerate(items)
    ]
    metadatas = [
        {
            "bvid": item.get("bvid", ""),
            "title": item.get("title", ""),
            "upper": item.get("upper", ""),
            "link": item.get("link", ""),
            "folder_name": item.get("folder_name", ""),
            "fav_time": item.get("fav_time", 0),
        }
        for item in items
    ]
    for ids_batch, texts_batch, embeddings_batch, metadatas_batch in zip(
        _chunks(ids, CHROMA_BATCH_SIZE),
        _chunks(texts, CHROMA_BATCH_SIZE),
        _chunks(embeddings, CHROMA_BATCH_SIZE),
        _chunks(metadatas, CHROMA_BATCH_SIZE),
    ):
        collection.upsert(
            ids=ids_batch,
            documents=texts_batch,
            embeddings=embeddings_batch,
            metadatas=metadatas_batch,
        )
    return {"indexed": len(items), "folders_count": len(folders or [])}


async def semantic_search_favorites(
    uid: str,
    cookies: dict,
    query: str,
    api_key: str,
    model: str,
    folders: list[dict] | None = None,
    top_k: int = 8,
    refresh: bool = False,
) -> dict:
    if not query.strip():
        return {"error": "请输入检索问题"}

    collection = _get_chroma_collection(uid)
    count = collection.count()
    if refresh or count == 0:
        index_info = await rebuild_favorite_index(uid, cookies, folders)
        count = index_info["indexed"]

    if count == 0:
        return {"answer": "收藏夹为空，暂时没有可检索的内容。", "results": [], "indexed": 0}

    query_embedding = (await get_embeddings([query]))[0]
    raw = collection.query(
        query_embeddings=[query_embedding],
        n_results=max(1, min(top_k, count)),
        include=["metadatas", "documents", "distances"],
    )

    metadatas = raw.get("metadatas", [[]])[0]
    distances = raw.get("distances", [[]])[0]
    results = []
    for meta, distance in zip(metadatas, distances):
        results.append({
            "title": meta.get("title", ""),
            "upper": meta.get("upper", ""),
            "link": meta.get("link", ""),
            "folder_name": meta.get("folder_name", ""),
            "bvid": meta.get("bvid", ""),
            "score": round(1 - float(distance), 4),
            "reason": _keyword_reason(query, meta),
        })

    context = "\n".join(
        f"{index + 1}. {item['title']} | UP:{item['upper']} | 收藏夹:{item['folder_name']} | 链接:{item['link']}"
        for index, item in enumerate(results)
    )
    prompt = f"""
你是一个收藏夹检索 Agent。用户会用自然语言找 B 站收藏内容。
请基于检索结果回答，语气聪明、直接、有一点趣味，但不要编造不存在的视频。
如果结果不够确定，请说明“我更像是找到了一批相关线索”。

用户问题：{query}

检索结果：
{context}

请输出：
1. 一段简短回答
2. 2-3条为什么推荐这些结果
3. 一个下一步行动建议
""".strip()

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=650,
            temperature=0.55,
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[retrieval_agent] LLM failed: {e}")
        answer = "我先帮你找到了这些最相关的收藏，LLM 总结暂时失败，但结果列表可以直接打开查看。"

    return {
        "answer": answer,
        "results": results,
        "indexed": count,
    }


def _fallback_learning_path(goal: str, results: list[dict], indexed: int) -> dict:
    stages = []
    chunk_size = max(1, min(3, len(results)))
    for index in range(0, min(len(results), 9), chunk_size):
        stage_items = results[index:index + chunk_size]
        stages.append({
            "title": f"第 {len(stages) + 1} 阶段",
            "purpose": "按相关度逐步消化收藏内容。",
            "items": stage_items,
            "task": "看完后用一句话记录这个视频解决了什么问题。",
        })
    return {
        "goal": goal,
        "summary": f"基于 {indexed} 条已索引收藏，我先排出一条可执行路线。",
        "stages": stages,
        "warnings": [] if results else ["没有找到足够相关的收藏，建议换一个更具体的目标。"],
    }


async def build_learning_path(
    uid: str,
    cookies: dict,
    goal: str,
    api_key: str,
    model: str,
    folders: list[dict] | None = None,
    refresh: bool = False,
) -> dict:
    search = await semantic_search_favorites(
        uid,
        cookies,
        goal,
        api_key,
        model,
        folders=folders,
        top_k=12,
        refresh=refresh,
    )
    if search.get("error"):
        return search
    results = search.get("results", [])
    if not results:
        return _fallback_learning_path(goal, [], search.get("indexed", 0))

    context = "\n".join(
        f"{index + 1}. {item.get('title', '')} | UP:{item.get('upper', '')} | 收藏夹:{item.get('folder_name', '')} | 链接:{item.get('link', '')}"
        for index, item in enumerate(results)
    )
    prompt = f"""
你是一个学习路线 Agent。用户希望从自己的 B 站收藏夹中完成一个目标。
请只基于给定收藏视频规划路线，不要编造新视频。输出 JSON，不要 Markdown。

JSON schema:
{{
  "goal": "用户目标",
  "summary": "路线总体说明，不超过80字",
  "stages": [
    {{
      "title": "阶段名",
      "purpose": "为什么先做这个阶段",
      "items": [{{"title":"视频标题","upper":"UP主","link":"链接","folder_name":"收藏夹","reason":"为什么放在这里"}}],
      "task": "阶段完成后的具体小任务"
    }}
  ],
  "warnings": ["可选，说明结果不足或需要补充的地方"]
}}

用户目标：{goal}

候选收藏：
{context}
""".strip()

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=0.45,
        )
        path = _json_from_text(resp.choices[0].message.content or "")
    except Exception as e:
        print(f"[learning_agent] LLM failed, using fallback: {e}")
        path = {}

    if not path:
        path = _fallback_learning_path(goal, results, search.get("indexed", 0))
    path["indexed"] = search.get("indexed", 0)
    return path
