import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from worker import Store


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, per_task=10, total=15)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_duplicate_and_conflicting_id(self):
        self.assertTrue(self.store.enqueue("a", 5))
        self.assertFalse(self.store.enqueue("a", 5))
        with self.assertRaises(ValueError):
            self.store.enqueue("a", 6)
        self.assertEqual(self.store.tick(), "simulated")
        self.assertEqual(self.store.tick(), "idle")
        self.assertEqual(self.store.status()["simulated_cost_cents"], 5)

    def test_total_and_per_task_limits(self):
        for key, cost in [("a", 11), ("b", 10), ("c", 6), ("d", 5)]:
            self.store.enqueue(key, cost)
        self.assertEqual(self.store.tick(), "rejected_budget")
        self.assertEqual(self.store.tick(), "simulated")
        self.assertEqual(self.store.tick(), "rejected_budget")
        self.assertEqual(self.store.tick(), "simulated")
        self.assertEqual(self.store.status()["simulated_cost_cents"], 15)

    def test_pause_and_restart(self):
        self.store.enqueue("a", 5)
        pause = Path(self.temp.name) / "PAUSED"
        pause.touch()
        self.assertEqual(self.store.tick(), "paused")
        pause.unlink()
        self.assertEqual(self.store.tick(), "simulated")
        self.store.close()
        self.store = Store(self.temp.name, per_task=10, total=15)
        self.assertEqual(self.store.tick(), "idle")
        self.assertEqual(self.store.status()["simulated_cost_cents"], 5)

    def test_invalid_amounts(self):
        for cost in [0, -1, 1.5, True, "NaN"]:
            with self.assertRaises((TypeError, ValueError)):
                self.store.enqueue("invalid", cost)

    def test_live_mode_cannot_be_enabled(self):
        with patch.dict(os.environ, {"RUN_MODE": "live"}):
            with self.assertRaises(ValueError):
                Store(self.temp.name)


if __name__ == "__main__":
    unittest.main()
