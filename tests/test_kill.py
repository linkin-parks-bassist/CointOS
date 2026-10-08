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
                with patch.object(spawner, "refresh", return_value=({}, {})), \
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

    def test_killed_work_does_not_slow_the_steward(self):
        task = support.running(tasks.create("garden", tasks.SYSTEM, "garden", "Work", [7]), "run", False)
        api.kill_agent({"agent": "run"})
        with patch.dict(spawner.CONFIG["spawner"], steward_every_seconds=100), \
             patch.object(tasks, "enabled_projects", return_value=[self.project]), \
             patch.object(tasks, "last_created", side_effect=lambda kind, place: 0 if kind == "steward" else 1e18), \
             patch.object(spawner, "now", return_value=150):
            self.assertTrue(spawner.periodic())
            task.pop("admission_hold")
            self.assertFalse(spawner.periodic())

    def test_the_user_cancels_a_live_upkeep_task_for_good(self):
        task = support.running(tasks.create("garden", tasks.SYSTEM, "garden", "Work", [7]), "gardener-1", False)
        result = api.dispatch("cancel", {"items": [task["id"]], "reason": "not needed now"})
        self.assertEqual(result["cancelled"], [task["id"]])
        self.assertEqual((task["status"], task["agent"], task["cancelled"]), ("failed", None, "not needed now"))
        self.assertNotIn("gardener-1", state.L["agents"])
        with self.assertRaises(ValueError):
            api.dispatch("cancel", {"items": [task["id"]], "reason": "again"})

    def test_controls_name_tasks_and_reach_their_queue_record_through_it(self):
        worker = support.queued(self.project, "child")
        support.running(worker, "worker-1")
        state.L["tasks"]["p:integrate-child-1"] = {**worker, "id": "p:integrate-child-1", "kind": "integrate",
                                                   "agent": None, "status": "waiting"}
        api.dispatch("hold", {"item": "p:integrate-child-1"})  # reaches p:child through its record link
        self.assertEqual(state.L["queue"]["p:child"]["held_by"], "user")
        garden = tasks.create("garden", tasks.SYSTEM, "garden", "Work", [7])
        with self.assertRaisesRegex(ValueError, "has no queue item"):
            api.dispatch("hold", {"item": garden["id"]})
        with self.assertRaisesRegex(ValueError, "not a live task"):
            api.dispatch("cancel", {"items": ["p:nothing"], "reason": "x"})
