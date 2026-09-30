import json
import unittest
from unittest.mock import patch

from cointos import api, snapshots, spawner, state, tasks
from tests import support


class Halt(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self, {"paused": False})
        support.quiet(self)

    def interrupted_task(self):
        task = tasks.create("steward", tasks.SYSTEM, "scout", "Look around", [6])
        support.running(task, "steward-1")
        task.update(runs=5, session="existing-session")
        state.L["snapshots"]["checkpoint"] = {"owner": task["id"]}
        return task

    def saved(self):
        from cointos.config import LEDGER
        return json.loads(LEDGER.read_text())

    def test_halt_durably_requeues_without_consuming_last_attempt(self):
        task = self.interrupted_task()
        self.assertEqual(api.dispatch("halt", {}), {"ok": True})
        saved = self.saved()
        self.assertTrue(state.STOPPING.is_set())
        self.assertEqual(saved["agents"], {})
        self.assertEqual((saved["tasks"][task["id"]]["status"], saved["tasks"][task["id"]]["runs"]), ("waiting", 4))
        self.assertEqual((task["agent"], task["session"]), (None, "existing-session"))
        self.assertIn("checkpoint", saved["snapshots"])
        self.assertFalse(saved["paused"])
        api.dispatch("halt", {})  # a repeated request cannot refund the same run twice
        self.assertEqual(task["runs"], 4)

    def test_halt_preserves_an_existing_pause(self):
        state.L["paused"] = True
        api.dispatch("halt", {})
        self.assertTrue(self.saved()["paused"])

    def test_halt_prevents_a_tick_from_admitting_more_work(self):
        api.dispatch("halt", {})
        with patch.object(spawner, "next_task") as next_task:
            spawner.spawn()
        next_task.assert_not_called()

    def test_forget_requires_quiescence_and_persists_only_requested_removal(self):
        forgotten = tasks.create("steward", tasks.SYSTEM, "old", "", [6])
        kept = tasks.create("steward", tasks.SYSTEM, "keep", "", [6])
        with self.assertRaises(api.ApiError):
            api.dispatch("forget-task", {"task": forgotten["id"]})
        state.L["paused"] = True
        state.L["agents"]["live"] = {}
        with self.assertRaises(api.ApiError):
            api.dispatch("forget-task", {"task": forgotten["id"]})
        state.L["agents"].clear()
        state.L["lanes"][0]["resident"] = forgotten["id"]
        state.L["lanes"][1]["resident"] = kept["id"]
        with patch.object(snapshots, "forget_owner") as forget:
            api.dispatch("forget-task", {"task": forgotten["id"]})
            api.dispatch("forget-task", {"task": forgotten["id"]})
        forget.assert_called_once_with(forgotten["id"])
        saved = self.saved()
        self.assertEqual(set(saved["tasks"]), {kept["id"]})
        self.assertTrue(saved["paused"])
        self.assertEqual((saved["lanes"][0]["resident"], saved["lanes"][1]["resident"]), (None, kept["id"]))

    def test_clear_history_removes_only_unreferenced_terminal_tasks(self):
        where = support.project(self, support.repository(self))
        by_status = {status: tasks.create("steward", tasks.SYSTEM, status, "", [6]) for status in ("done", "failed", "waiting")}
        for status, task in by_status.items():
            task["status"] = status
        worker = support.queued(where, "item")
        worker["status"] = "done"  # its integration is still running, so it stays
        integration = tasks.create("integrate", where, "integrate-item-1", "", [2], item="item", worker=worker["id"])
        support.running(integration, "integrator-1", worktree=False)
        state.L["lanes"][0]["resident"] = by_status["failed"]["id"]
        with patch.object(snapshots, "forget_owner") as forget:
            result = api.dispatch("clear-task-history", {})
        self.assertEqual(result, {"ok": True, "removed": 2, "task_records": 2, "queue_records": 0})
        self.assertEqual(set(state.L["tasks"]), {by_status["waiting"]["id"], worker["id"], integration["id"]})
        self.assertIsNone(state.L["lanes"][0]["resident"])
        self.assertEqual({c.args[0] for c in forget.call_args_list}, {by_status["done"]["id"], by_status["failed"]["id"]})


if __name__ == "__main__":
    unittest.main()
