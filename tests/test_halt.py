import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import gateway, state, work


class Halt(unittest.TestCase):
    def setUp(self):
        self.previous = copy.deepcopy(state.L)
        self.stopping = state.STOPPING.is_set()
        state.STOPPING.clear()
        state.L.clear()
        state.L.update(state.fresh({}))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Path(self.directory.name) / "ledger.json"
        self.enterContext(patch.object(state.configuration, "LEDGER", self.ledger))
        self.enterContext(patch.object(work, "keep_key"))
        self.enterContext(patch.object(work.lanes, "cancel_agent"))
        self.enterContext(patch.object(work.threading, "Thread"))

    def tearDown(self):
        state.L.clear()
        state.L.update(self.previous)
        state.STOPPING.set() if self.stopping else state.STOPPING.clear()

    def interrupted_task(self):
        task = {"id": "test", "status": "running", "agent": "worker-test", "runs": 5,
                "session": "existing-session", "worktree": "/existing/worktree", "title": "test",
                "project": "sandbox"}
        state.L["tasks"]["test"] = task
        state.L["agents"]["worker-test"] = {
            "task": "test", "thoughts": 3, "started_at": 0}
        state.L["snapshots"]["checkpoint"] = {"owner": "test"}
        return task

    def test_halt_durably_requeues_without_consuming_last_attempt(self):
        task = self.interrupted_task()
        self.assertEqual(gateway.api("halt", {}), {"ok": True})
        saved = json.loads(self.ledger.read_text())
        self.assertTrue(state.STOPPING.is_set())
        self.assertEqual(saved["agents"], {})
        self.assertEqual(saved["tasks"]["test"]["status"], "waiting")
        self.assertEqual(saved["tasks"]["test"]["runs"], 4)
        self.assertIsNone(task["agent"])
        self.assertEqual(task["session"], "existing-session")
        self.assertEqual(task["worktree"], "/existing/worktree")
        self.assertIn("checkpoint", saved["snapshots"])
        self.assertFalse(saved["paused"])
        # A repeated request cannot refund the same run twice.
        gateway.api("halt", {})
        self.assertEqual(task["runs"], 4)

    def test_halt_preserves_an_existing_pause(self):
        state.L["paused"] = True
        gateway.api("halt", {})
        self.assertTrue(json.loads(self.ledger.read_text())["paused"])

    def test_halt_prevents_a_tick_from_admitting_more_work(self):
        gateway.api("halt", {})
        with patch.object(work, "next_task") as next_task:
            work.spawn()
        next_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
