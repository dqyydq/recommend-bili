import unittest

from learning_project_agent import _allowed_tasks, adjust_proposed_tasks, build_review_summary


class LearningProjectAgentTests(unittest.TestCase):
    def test_tasks_only_keep_retrieved_favorites(self) -> None:
        results = [{"bvid": "BV-allowed", "title": "Allowed", "link": "https://example.test/allowed", "upper": "up", "folder_name": "folder"}]
        tasks = _allowed_tasks([
            {"title": "safe", "rationale": "r", "bvids": ["BV-allowed", "BV-invented"], "estimated_minutes": 30},
            {"title": "unsafe", "bvids": ["BV-invented"], "estimated_minutes": 30},
        ], results, 120)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["favorite_refs"][0]["bvid"], "BV-allowed")

    def test_invalid_model_output_falls_back_to_retrieved_favorites(self) -> None:
        results = [{"bvid": "BV-allowed", "title": "Allowed", "link": "https://example.test/allowed", "upper": "up", "folder_name": "folder"}]
        tasks = _allowed_tasks([], results, 120)
        self.assertEqual(tasks[0]["favorite_refs"][0]["bvid"], "BV-allowed")

    def test_review_includes_skips_and_blocker_notes(self) -> None:
        rate, summary, blocked = build_review_summary(2, [
            {"state": "completed", "title": "A", "user_note": ""},
            {"state": "skipped", "title": "B", "user_note": ""},
            {"state": "blocked", "title": "C", "user_note": "依赖注入没理解"},
        ])
        self.assertEqual(rate, 0.33)
        self.assertEqual(blocked, 1)
        self.assertIn("跳过 1 项", summary)
        self.assertIn("依赖注入没理解", summary)

    def test_blocked_week_reduces_next_week_scope(self) -> None:
        tasks = [{"title": str(index), "estimated_minutes": 40, "rationale": "old"} for index in range(4)]
        adjusted = adjust_proposed_tasks(tasks, 1)
        self.assertEqual(len(adjusted), 3)
        self.assertEqual(adjusted[0]["estimated_minutes"], 30)
        self.assertIn("缩小任务范围", adjusted[0]["rationale"])


if __name__ == "__main__":
    unittest.main()
