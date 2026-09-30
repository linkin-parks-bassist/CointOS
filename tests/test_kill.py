"""Directed kills withhold task admission across every scheduling source."""
import json
import unittest
from unittest.mock import patch

from cointos import api, lifecycle, spawner, state, tasks
from tests import support


class Kill(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))

    def test_killed_work_survives_restart_held_until_explicit_release(self):
        for kind in ("item", "garden", "steward", "operator"):
            with self.subTest(kind=kind):
                task = (support.queued(self.project, "child") if kind == "item" else
                        tasks.create(kind, tasks.SYSTEM, kind, "Work", [6]))
                support.running(task, "run", worktree=False)
                result = api.kill_agent({"agent": "run"})
                self.assertTrue(result["held"])
                self.assertEqual((task["status"], task["runs"], task["receipt"]), ("waiting", 0, None))
                restored = state.fresh(json.loads(json.dumps(state.L)))
                state.L.clear()
                state.L.update(restored)
                task = state.L["tasks"][task["id"]]
                api.resume({})
                self.assertFalse(spawner.runnable(task, {"p": {"child": "ready"}}))
                with patch.object(spawner, "refresh", return_value=({}, {}, False)), \
                     patch.object(spawner, "reorder"), patch.object(spawner, "queued_work", return_value=[]), \
                     patch.object(spawner, "integrations", return_value=[]), \
                     patch.object(spawner, "tree_work", return_value=[]), \
                     patch.object(spawner, "periodic", return_value=[]):
                    self.assertIsNone(spawner.next_task())
                api.resume_task({"task": task["id"]})
                self.assertTrue(spawner.runnable(task, {"p": {"child": "ready"}}))
                task["status"] = "done"

    def test_kill_after_receipt_preserves_the_terminal_outcome(self):
        task = support.running(tasks.create("steward", tasks.SYSTEM, "scout", "Work", [6]), "run", False)
        lifecycle.submit(task["id"], "run", "complete", "Done")
        self.assertFalse(api.kill_agent({"agent": "run"})["held"])
        self.assertEqual(task["status"], "done")
