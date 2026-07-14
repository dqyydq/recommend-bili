import time
import unittest

from harness import (
    AgentSkill,
    Guardrail,
    deterministic_intent,
    rerank_candidates,
    select_relevant_memories,
)


class HarnessTests(unittest.TestCase):
    def test_deterministic_router_has_safe_cleanup_route(self) -> None:
        self.assertEqual(deterministic_intent("帮我删除失效视频"), "inspect_cleanup")
        self.assertEqual(deterministic_intent("给我规划 FastAPI 学习路线"), "learning")
        self.assertEqual(deterministic_intent("找几个 FastAPI 视频"), "retrieve")

    def test_mutating_tool_requires_confirmation(self) -> None:
        skill = AgentSkill("remove_favorites", "remove", "mutate")
        with self.assertRaises(PermissionError):
            Guardrail.ensure_allowed(skill)
        Guardrail.ensure_allowed(skill, confirmed=True)

    def test_context_budget_and_dormant_query_override(self) -> None:
        memories = [
            {"id": str(index), "content": f"偏好 Python 教程 {index}", "interest_state": "active", "effective_confidence": 0.8}
            for index in range(12)
        ]
        memories.append({"id": "basketball", "content": "篮球训练", "interest_state": "dormant", "effective_confidence": 1})
        default = select_relevant_memories("找 Python 教程", memories)
        self.assertLessEqual(len(default), 8)
        self.assertNotIn("basketball", {item["id"] for item in default})
        explicit = select_relevant_memories("找篮球训练", memories)
        self.assertIn("basketball", {item["id"] for item in explicit})

    def test_query_relevance_outweighs_profile_match(self) -> None:
        now = time.time()
        candidates = [
            {"folder_id": 1, "id": 1, "title": "FastAPI 项目", "semantic_score": 1, "keyword_score": 1, "fav_time": now},
            {"folder_id": 1, "id": 2, "title": "篮球训练", "semantic_score": 0.45, "keyword_score": 0, "fav_time": now},
        ]
        memories = [{"content": "我喜欢篮球训练"}]
        ranked = rerank_candidates("FastAPI 项目", candidates, memories, {}, now=now)
        self.assertEqual(ranked[0]["id"], 1)
        self.assertEqual(set(ranked[0]["score_breakdown"]), {"semantic", "goal", "profile", "feedback_freshness"})

    def test_ignored_feedback_lowers_score(self) -> None:
        now = time.time()
        candidates = [
            {"folder_id": 1, "id": 1, "title": "Python A", "semantic_score": 0.8, "keyword_score": 0.5, "fav_time": now},
            {"folder_id": 1, "id": 2, "title": "Python B", "semantic_score": 0.8, "keyword_score": 0.5, "fav_time": now},
        ]
        ranked = rerank_candidates("Python", candidates, [], {(1, 1): {"ignored": 3}}, now=now)
        self.assertEqual(ranked[0]["id"], 2)


if __name__ == "__main__":
    unittest.main()
