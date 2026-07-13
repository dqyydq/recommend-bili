import unittest

from folder_structure_agent import build_structure_actions


class FolderStructureAgentTests(unittest.TestCase):
    def test_routes_known_topics_to_purpose_and_topic(self) -> None:
        actions = build_structure_actions([{"id": 1, "title": "FastAPI with PostgreSQL", "folder_name": "old"}])
        self.assertEqual(actions[0]["destination_name"], "待学习 / FastAPI 与后端")
        self.assertEqual(actions[0]["confidence"], 0.82)

    def test_routes_uncertain_items_to_review(self) -> None:
        actions = build_structure_actions([{"id": 1, "title": "random title", "folder_name": "old"}])
        self.assertEqual(actions[0]["destination_name"], "已完成/待复查 / 待复查")
        self.assertEqual(actions[0]["confidence"], 0.35)


if __name__ == "__main__":
    unittest.main()
