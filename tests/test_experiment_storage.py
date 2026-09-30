import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class ExperimentStorageTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tempdir.name) / "test.sqlite3")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_session_experiment_result_and_review_roundtrip(self):
        session = self.storage.start_session("room-1", "test live")
        experiment = self.storage.create_experiment(
            {
                "category": "visual",
                "name": "冷色人物 + 暗背景",
                "hypothesis": "提高第一眼进房意愿",
                "target_metric": "entry_rate",
                "variables": {
                    "hair": "silver-blue",
                    "background": "dark-bamboo",
                },
            }
        )

        running = self.storage.start_experiment(experiment["id"], session["id"])
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["session_id"], session["id"])

        completed = self.storage.save_experiment_result(
            experiment["id"],
            {
                "metrics": {"entry_rate": 0.219},
                "conclusion": "进房提升，留人待验证",
                "decision": "iterate",
                "next_experiment": "固定画面，只改唱歌开场",
            },
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["decision"], "iterate")
        self.assertAlmostEqual(
            completed["result"]["metrics"]["entry_rate"],
            0.219,
        )

        review = self.storage.save_daily_review(
            session["id"],
            {
                "entry_winners": [{"node": "开灯"}],
                "retention_winners": [],
                "interaction_revenue_winners": [],
                "waste_points": [],
                "clip_candidates": [],
                "findings": ["画面变量值得继续验证"],
                "next_tests": ["固定画面，只改开场"],
                "data_quality": {"timeline_aligned": False},
                "source_metadata": {},
            },
        )
        self.assertEqual(review["session_id"], session["id"])
        self.assertEqual(
            review["review"]["next_tests"],
            ["固定画面，只改开场"],
        )


if __name__ == "__main__":
    unittest.main()
