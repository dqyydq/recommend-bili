import time
import unittest

from topic_analysis import enrich_topic_clusters, snapshot_version


class TopicAnalysisTests(unittest.TestCase):
    def test_snapshot_version_is_stable_and_changes_with_snapshot(self) -> None:
        items = [
            {"folder_id": 2, "id": 8, "fav_time": 20, "title": "B"},
            {"folder_id": 1, "id": 7, "fav_time": 10, "title": "A"},
        ]
        self.assertEqual(snapshot_version(items), snapshot_version(list(reversed(items))))
        changed = [*items, {"folder_id": 1, "id": 9, "fav_time": 30, "title": "C"}]
        self.assertNotEqual(snapshot_version(items), snapshot_version(changed))

    def test_inferred_interest_never_becomes_dormant(self) -> None:
        now = time.time()
        categories = [{
            "name": "篮球",
            "items": [
                {"folder_id": 1, "id": 1, "title": "旧篮球视频", "upper": "UP", "fav_time": int(now - 500 * 86400)},
            ],
        }]
        cluster = enrich_topic_clusters(categories, now=now)[0]
        self.assertEqual(cluster["interest_state"], "historical")
        self.assertNotEqual(cluster["interest_state"], "dormant")

    def test_recent_items_are_active_and_representatives_are_bounded(self) -> None:
        now = time.time()
        items = [
            {"folder_id": 1, "id": index, "title": f"视频 {index}", "upper": "UP", "fav_time": int(now - index * 86400)}
            for index in range(1, 9)
        ]
        cluster = enrich_topic_clusters([{"name": "开发", "items": items}], now=now)[0]
        self.assertEqual(cluster["interest_state"], "active")
        self.assertEqual(len(cluster["representative_items"]), 5)
        self.assertEqual(cluster["upper_creators"][0], {"name": "UP", "count": 8})


if __name__ == "__main__":
    unittest.main()
