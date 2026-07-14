import json
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from agents import (
    DEEPSEEK_BASE_URL,
    _get_chroma_collection,
    build_knowledge_dashboard,
    build_organization_plan,
    rebuild_favorite_index,
)
from database import (
    append_agent_message,
    create_agent_run,
    create_agent_session,
    finish_agent_run,
    get_agent_session,
    get_cleanup_scan,
    get_favorites,
    get_feedback_for_items,
    get_latest_cleanup_scan,
    get_latest_topic_analysis,
    list_user_memories,
)
from embedding import get_embeddings
from folder_structure_agent import build_folder_structure_plan
from memory_service import present_memory


RECENT_MESSAGES = 8
MEMORY_LIMIT = 8
CANDIDATE_LIMIT = 12
CITATION_LIMIT = 5


@dataclass(frozen=True)
class AgentSkill:
    name: str
    description: str
    risk: str
    executor: Callable[..., Awaitable[dict[str, Any]]] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, AgentSkill] = {}

    def register(self, skill: AgentSkill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> AgentSkill:
        if name not in self._skills:
            raise ValueError(f"unknown agent skill: {name}")
        return self._skills[name]


class Guardrail:
    @staticmethod
    def ensure_allowed(skill: AgentSkill, confirmed: bool = False) -> None:
        if skill.risk == "mutate" and not confirmed:
            raise PermissionError("修改类工具必须经过用户二次确认")


class RunLog:
    async def start(self, uid: str, session_id: str, intent: str) -> dict[str, Any]:
        return await create_agent_run(uid, session_id, intent)

    async def finish(self, run_id: str, status: str, tools: list[dict[str, Any]], citations: list[dict[str, Any]], memories: list[str], error: str = "") -> None:
        await finish_agent_run(run_id, status, tools, citations, memories, error)


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[\u4e00-\u9fa5]+|[A-Za-z0-9]{2,}", value or ""):
        lowered = token.lower()
        tokens.add(lowered)
        if re.fullmatch(r"[\u4e00-\u9fa5]+", token) and len(token) > 2:
            tokens.update(token[index:index + 2] for index in range(len(token) - 1))
    return tokens


def deterministic_intent(message: str) -> str:
    rules = (
        ("draft_structure", r"结构|整理|分类|文件夹"),
        ("inspect_cleanup", r"失效|删除|清理|过期视频"),
        ("analyze_topics", r"主题|兴趣分布|画像变化"),
        ("inspect_health", r"积压|吃灰|健康|多久没看"),
        ("learning", r"学习计划|学习项目|课程|路线"),
    )
    for intent, pattern in rules:
        if re.search(pattern, message, re.I):
            return intent
    return "retrieve"


class Planner:
    async def plan(self, message: str, api_key: str, model: str) -> str:
        fallback = deterministic_intent(message)
        if not api_key:
            return fallback
        prompt = (
            "将用户意图分类，只返回一个标签：retrieve, draft_structure, inspect_cleanup, "
            "analyze_topics, inspect_health, learning。删除或移动请求只能归为 inspect_cleanup。\n"
            f"用户：{message}"
        )
        try:
            client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
            response = await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], max_tokens=20, temperature=0,
            )
            intent = (response.choices[0].message.content or "").strip()
            return intent if intent in {"retrieve", "draft_structure", "inspect_cleanup", "analyze_topics", "inspect_health", "learning"} else fallback
        except Exception:
            return fallback


class ContextBuilder:
    async def build(self, uid: str, session_id: str, message: str) -> dict[str, Any]:
        session = await get_agent_session(uid, session_id, message_limit=RECENT_MESSAGES)
        memories = [present_memory(memory) for memory in await list_user_memories(uid, include_outdated=False)]
        return {
            "recent_messages": (session or {}).get("messages", [])[-RECENT_MESSAGES:],
            "summary": (session or {}).get("summary", ""),
            "memories": select_relevant_memories(message, memories),
            "project_id": (session or {}).get("project_id"),
        }


def select_relevant_memories(message: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_tokens = _tokens(message)
    relevant = []
    for memory in memories:
        memory_tokens = _tokens(memory.get("content", ""))
        direct_match = bool(query_tokens & memory_tokens)
        if memory.get("interest_state") in {"dormant", "historical"} and not direct_match:
            continue
        score = float(memory.get("effective_confidence") or 0) + (0.5 if direct_match else 0)
        if score > 0.15:
            relevant.append((score, memory))
    relevant.sort(key=lambda value: value[0], reverse=True)
    return [memory for _, memory in relevant[:MEMORY_LIMIT]]


async def hybrid_retrieve(uid: str, cookies: dict[str, str], query: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_items = await get_favorites(uid)
    by_key = {(int(item.get("folder_id") or 0), int(item.get("id") or 0)): {**item, "semantic_score": 0.0, "keyword_score": 0.0} for item in all_items}
    query_tokens = _tokens(query)
    for item in by_key.values():
        item_tokens = _tokens(f"{item.get('title', '')} {item.get('intro', '')} {item.get('upper', '')} {item.get('folder_name', '')}")
        item["keyword_score"] = min(1.0, len(query_tokens & item_tokens) / max(1, len(query_tokens)))
    try:
        collection = _get_chroma_collection(uid)
        if collection.count() == 0 and all_items:
            await rebuild_favorite_index(uid, cookies)
            collection = _get_chroma_collection(uid)
        if collection.count():
            embedding = (await get_embeddings([query]))[0]
            raw = collection.query(
                query_embeddings=[embedding], n_results=min(CANDIDATE_LIMIT, collection.count()),
                include=["metadatas", "distances"],
            )
            for meta, distance in zip(raw.get("metadatas", [[]])[0], raw.get("distances", [[]])[0]):
                key = (int(meta.get("folder_id") or 0), int(meta.get("media_id") or 0))
                if key in by_key:
                    by_key[key]["semantic_score"] = max(0.0, min(1.0, 1 - float(distance)))
    except Exception as exc:
        print(f"[harness] vector retrieval unavailable, using PostgreSQL snapshot: {exc}")

    candidates = sorted(by_key.values(), key=lambda item: max(item["semantic_score"], item["keyword_score"]), reverse=True)[:CANDIDATE_LIMIT]
    feedback = await get_feedback_for_items(uid, [(int(item["folder_id"]), int(item["id"])) for item in candidates])
    return rerank_candidates(query, candidates, memories, feedback)


def rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    memories: list[dict[str, Any]],
    feedback: dict[tuple[int, int], dict[str, int]],
    now: float | None = None,
) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    memory_tokens = set().union(*(_tokens(memory.get("content", "")) for memory in memories)) if memories else set()
    current = now or time.time()
    for item in candidates:
        text_tokens = _tokens(f"{item.get('title', '')} {item.get('intro', '')} {item.get('folder_name', '')}")
        semantic = max(float(item["semantic_score"]), float(item["keyword_score"]))
        goal = min(1.0, len(query_tokens & text_tokens) / max(1, len(query_tokens)))
        profile = min(1.0, len(memory_tokens & text_tokens) / max(1, len(memory_tokens))) if memory_tokens else 0.0
        item_feedback = feedback.get((int(item["folder_id"]), int(item["id"])), {})
        feedback_score = 0.5 + min(0.5, 0.15 * item_feedback.get("useful", 0) + 0.1 * item_feedback.get("later", 0))
        feedback_score -= min(0.5, 0.2 * item_feedback.get("ignored", 0) + 0.1 * item_feedback.get("watched", 0))
        age_days = max(0.0, (current - float(item.get("fav_time") or current)) / 86400)
        freshness = max(0.0, 1 - age_days / 730)
        item["rerank_score"] = round(0.55 * semantic + 0.20 * goal + 0.15 * profile + 0.10 * ((feedback_score + freshness) / 2), 4)
        item["score_breakdown"] = {"semantic": round(semantic, 4), "goal": round(goal, 4), "profile": round(profile, 4), "feedback_freshness": round((feedback_score + freshness) / 2, 4)}
    return sorted(candidates, key=lambda item: item["rerank_score"], reverse=True)


class Reranker:
    @staticmethod
    def rank(query: str, candidates: list[dict[str, Any]], memories: list[dict[str, Any]], feedback: dict[tuple[int, int], dict[str, int]]) -> list[dict[str, Any]]:
        return rerank_candidates(query, candidates, memories, feedback)


def _citation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "folder_id": int(item.get("folder_id") or 0), "media_id": int(item.get("id") or 0),
        "bvid": item.get("bvid", ""), "title": item.get("title", ""), "upper": item.get("upper", ""),
        "folder_name": item.get("folder_name", ""), "link": item.get("link", ""),
        "score": item.get("rerank_score", 0), "score_breakdown": item.get("score_breakdown", {}),
    }


async def answer_from_evidence(message: str, context: dict[str, Any], citations: list[dict[str, Any]], api_key: str, model: str) -> str:
    if not citations:
        return "我没有在当前收藏快照里找到足够相关的证据。可以换一个更具体的主题、UP 主或使用场景。"
    evidence = "\n".join(f"[{index + 1}] {item['title']} | {item['upper']} | {item['folder_name']} | {item['link']}" for index, item in enumerate(citations))
    memory_lines = "\n".join(f"- {memory['content']}" for memory in context["memories"])
    if api_key:
        prompt = f"""你是个人视频知识助手。只根据证据回答，不得编造视频。使用 Markdown，引用必须写成 [1] 这样的编号。用户当前问题优先于画像；画像仅用于排序和措辞。结尾给一个明确下一步。\n\n用户问题：{message}\n相关记忆：\n{memory_lines or '无'}\n证据：\n{evidence}"""
        try:
            client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
            response = await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], max_tokens=800, temperature=0.35,
            )
            answer = (response.choices[0].message.content or "").strip()
            if answer:
                return answer
        except Exception as exc:
            print(f"[harness] answer model unavailable: {exc}")
    top = citations[:3]
    return "## 检索结论\n\n" + "\n".join(f"- [{index + 1}] **{item['title']}**，来自 {item['upper'] or '未知 UP 主'}。" for index, item in enumerate(top)) + "\n\n这些结果按当前问题、有效画像、反馈和新鲜度综合排序。"


class FavoriteHarness:
    def __init__(self) -> None:
        self.planner = Planner()
        self.context_builder = ContextBuilder()
        self.guardrail = Guardrail()
        self.run_log = RunLog()
        self.tools = ToolRegistry()
        for name, description, risk in (
            ("retrieve_favorites", "混合检索本地收藏", "read"),
            ("analyze_topics", "读取最近主题分析", "read"),
            ("inspect_collection_health", "检查收藏积压与健康度", "read"),
            ("detect_expired_videos", "读取失效扫描结果", "read"),
            ("manage_learning_project", "生成学习项目建议", "draft"),
            ("draft_folder_structure", "生成收藏夹结构草稿", "draft"),
            ("remove_favorites", "从 B站收藏夹移除条目", "mutate"),
        ):
            self.tools.register(AgentSkill(name, description, risk))

    def tool_call(self, name: str, **metadata: Any) -> dict[str, Any]:
        skill = self.tools.get(name)
        self.guardrail.ensure_allowed(skill)
        return {"name": skill.name, "risk": skill.risk, **metadata}

    async def chat(
        self, uid: str, cookies: dict[str, str], message: str, api_key: str, model: str,
        session_id: str | None = None, project_id: str | None = None,
    ) -> dict[str, Any]:
        session = await get_agent_session(uid, session_id) if session_id else None
        if session_id and session is None:
            raise ValueError("对话不存在")
        if session is None:
            session = await create_agent_session(uid, project_id=project_id, title=message[:80])
        session_id = session["id"]
        await append_agent_message(session_id, "user", message)
        intent = await self.planner.plan(message, api_key, model)
        run = await self.run_log.start(uid, session_id, intent)
        tools: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        suggested_actions: list[dict[str, Any]] = []
        context = await self.context_builder.build(uid, session_id, message)
        try:
            if intent == "draft_structure":
                result = await build_folder_structure_plan(uid, message)
                tools.append(self.tool_call("draft_folder_structure", result_id=result.get("id")))
                answer = f"## 结构蓝图已生成\n\n我生成了 **{result.get('action_count', 0)} 个结构节点**。它只是本地草稿，不会直接修改 B站收藏夹。"
                suggested_actions.append({"type": "navigate", "label": "前往操作记录审核", "destination": "operations"})
            elif intent == "inspect_health":
                result = await build_knowledge_dashboard(uid, cookies)
                tools.append(self.tool_call("inspect_collection_health"))
                answer = f"## 收藏健康概览\n\n当前健康度 **{result.get('health_score', 0)} 分**，有 **{result.get('dust_count', 0)} 条**超过 60 天未处理，另有 **{result.get('light_dust_count', 0)} 条**进入轻度积压。"
                suggested_actions.append({"type": "navigate", "label": "查看收藏库", "destination": "library"})
            elif intent == "inspect_cleanup":
                scan = await get_latest_cleanup_scan(uid)
                tools.append(self.tool_call("detect_expired_videos"))
                if scan:
                    answer = f"## 最近扫描\n\n已检查 **{scan.get('checked', 0)} 条**，其中 **{scan.get('confirmed_invalid_count', 0)} 条**确定失效。未知和需复核项不会默认选择。"
                else:
                    answer = "## 尚未扫描\n\n还没有失效视频扫描记录。扫描只读取状态，真正移除仍需你二次确认。"
                suggested_actions.append({"type": "navigate", "label": "打开安全清理", "destination": "operations"})
            elif intent == "analyze_topics":
                analysis = await get_latest_topic_analysis(uid)
                tools.append(self.tool_call("analyze_topics"))
                if analysis and analysis.get("status") == "completed":
                    names = "、".join(cluster["name"] for cluster in analysis.get("clusters", [])[:5])
                    answer = f"## 最近主题地图\n\n从 {analysis.get('item_count', 0)} 条收藏中识别出 **{analysis.get('cluster_count', 0)} 个主题**：{names or '暂无主题'}。"
                else:
                    answer = "## 主题地图尚未完成\n\n请先在收藏库生成一次主题地图，后续相同快照会直接复用。"
                suggested_actions.append({"type": "navigate", "label": "查看主题地图", "destination": "library"})
            elif intent == "learning":
                tools.append(self.tool_call("manage_learning_project"))
                answer = "## 建议创建持续学习项目\n\n这个目标需要保存任务、对话和周回顾，学习项目比一次性检索更合适。"
                suggested_actions.append({"type": "navigate", "label": "创建学习项目", "destination": "learning"})
            else:
                candidates = await hybrid_retrieve(uid, cookies, message, context["memories"])
                citations = [_citation(item) for item in candidates[:CITATION_LIMIT]]
                tools.append(self.tool_call("retrieve_favorites", candidate_count=len(candidates)))
                answer = await answer_from_evidence(message, context, citations, api_key, model)
            await append_agent_message(session_id, "assistant", answer, {"citations": citations, "suggested_actions": suggested_actions})
            memory_ids = [memory["id"] for memory in context["memories"]]
            await self.run_log.finish(run["id"], "completed", tools, citations, memory_ids)
            return {"session_id": session_id, "run_id": run["id"], "answer_markdown": answer, "citations": citations, "suggested_actions": suggested_actions, "memories_used": context["memories"]}
        except Exception as exc:
            await self.run_log.finish(run["id"], "failed", tools, citations, [], str(exc))
            raise


favorite_harness = FavoriteHarness()
