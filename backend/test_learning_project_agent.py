import unittest

from learning_project_agent import _allowed_tasks


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


if __name__ == "__main__":
    unittest.main()
