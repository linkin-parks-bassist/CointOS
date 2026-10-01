"""Holding and revising queued work: an owner can stop an item from starting while deciding, and
change what it asks for at any point before acceptance."""
from pathlib import Path
import unittest

from cointos import api, lifecycle, prompts, queues, spawner, state, tasks
from tests import support


class Revision(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))
        state.L["cadence"]["steward:system"] = state.now()  # keep the periodic steward out of the way
        self.manager = support.running(support.queued(self.project, "decide", "Decide the interface", kind="command"),
                                       "manager-1")

    def as_manager(self, action, **body):
        return api.dispatch(action, {**body, "proposed_by": self.manager["id"], "run": "manager-1"})

    def worker(self, name="impl", brief="Implement it", start=True):
        worker = support.queued(self.project, name, brief)
        if start:
            support.running(worker, "worker-1")
        return worker

    # ------------------------------------------------ holding

    def test_human_holds_keep_their_authority_after_daemon_replacement(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        queues.add(self.project, "queued", "managed", "Manager-owned item")
        state.L["queue"]["p:impl"]["held_by"] = "previous_owner"
        state.L["queue"]["p:managed"]["held_by"] = self.manager["id"]
        replacement = state.fresh(state.L)
        state.L.clear()
        state.L.update(replacement)
        self.assertEqual(state.L["queue"]["p:impl"]["held_by"], "user")
        self.assertEqual(state.L["queue"]["p:managed"]["held_by"], self.manager["id"])
        api.dispatch("hold", {"item": "p:impl"})
        api.dispatch("unhold", {"item": "p:impl"})
        api.dispatch("unhold", {"item": "p:managed"})
        self.assertTrue(all(r["held_by"] is None for r in state.L["queue"].values()))

    def test_a_held_item_does_not_start_until_released(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        self.as_manager("hold", item="p:impl")
        self.assertIsNone(spawner.next_task())
        self.as_manager("unhold", item="p:impl")
        self.assertEqual(spawner.next_task()["id"], "p:impl")

    def test_holding_a_running_item_stops_it_uncharged_and_keeps_it_waiting(self):
        worker = self.worker()
        self.as_manager("hold", item="p:impl")
        self.assertEqual((worker["status"], worker["runs"]), ("waiting", 0))
        self.assertNotIn("worker-1", state.L["agents"])
        self.assertIsNone(spawner.next_task(), "a held waiting task is not resumed")

    def test_a_held_reviewed_item_is_not_integrated(self):
        worker = support.reviewed(self.worker(start=False), "worker-1")
        self.as_manager("hold", item="p:impl")
        self.assertIsNone(spawner.next_task())
        self.assertEqual(worker["status"], "review")

    def test_holds_end_when_their_holder_settles(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        self.as_manager("hold", item="p:impl")
        lifecycle.submit(self.manager["id"], "manager-1", "blocked", "Needs the user's call")
        self.assertIsNone(state.L["queue"]["p:impl"]["held_by"])

    def test_one_holder_at_a_time_and_user_can_release_any(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        api.dispatch("hold", {"item": "p:impl"})
        with self.assertRaisesRegex(ValueError, "already held by user"):
            self.as_manager("hold", item="p:impl")
        self.as_manager("revise", item="p:impl", brief="Implement it differently", reason="interface changed")
        self.assertIsNone(state.L["queue"]["p:impl"]["held_by"], "a revision releases the hold")

    # ------------------------------------------------ revising

    def test_revising_an_undispatched_item_replaces_its_brief_and_dependencies(self):
        queues.add(self.project, "queued", "iface", "Extend the interface")
        queues.add(self.project, "queued", "impl", "Implement it")
        before = state.L["queue"]["p:impl"]["hash"]
        self.as_manager("revise", item="p:impl", brief="Depends on: iface\nImplement the extended interface",
                        reason="the interface is extended first", stage="implementation")
        record = state.L["queue"]["p:impl"]
        self.assertEqual((record["depends"], record["status"]), (["iface"], "queued"))
        self.assertNotEqual(record["hash"], before)
        self.assertEqual(spawner.next_task()["id"], "p:iface", "the revised item now waits for its new dependency")

    def test_revising_a_running_item_restarts_it_fresh_on_the_new_brief(self):
        worker = self.worker()
        worker.update(session="old-session", runs=3)
        (Path(worker["worktree"]) / "partial.c").write_text("int partial;\n")
        self.as_manager("revise", item="p:impl", brief="Implement the extended interface", reason="interface extended")
        self.assertNotIn("worker-1", state.L["agents"])
        self.assertEqual((worker["status"], worker["session"], worker["runs"]), ("waiting", None, 0))
        self.assertEqual((worker["brief"], worker["record_hash"]),
                         ("Implement the extended interface", state.L["queue"]["p:impl"]["hash"]))
        self.assertTrue((Path(worker["worktree"]) / "partial.c").exists(), "the branch keeps earlier work")
        text = prompts.launch_text(worker, self.project)
        self.assertIn(f"Revised by {self.manager['id']}: interface extended", text)
        self.assertIn("Implement the extended interface", text)
        self.assertEqual(spawner.next_task()["id"], "p:impl")

    def test_revising_a_reviewed_item_sends_it_back_to_its_worker(self):
        worker = support.reviewed(self.worker(start=False), "worker-1")
        self.as_manager("revise", item="p:impl", brief="Implement the extended interface", reason="interface extended")
        self.assertEqual((worker["status"], worker["receipt"], worker["review"]), ("waiting", None, None))

    def test_a_reviewed_item_under_integration_must_wait(self):
        worker = support.reviewed(self.worker(start=False), "worker-1")
        integration = tasks.create("integrate", self.project, "integrate-impl", "b", [2], item="impl", worker=worker["id"])
        support.running(integration, "integrator-1", worktree=False)
        with self.assertRaisesRegex(ValueError, "being integrated"):
            self.as_manager("revise", item="p:impl", brief="Something else", reason="changed")
        self.assertEqual(worker["status"], "review")

    def test_a_failed_item_can_be_revised_into_new_work(self):
        worker = self.worker()
        worker["runs"] = state.CONFIG["spawner"]["max_runs_per_task"]
        lifecycle.stop("worker-1", "silent too long", requeue=True)
        self.assertEqual((worker["status"], state.L["queue"]["p:impl"]["status"]), ("failed", "blocked"))
        self.as_manager("revise", item="p:impl", brief="Implement a smaller slice", reason="the old scope was too big")
        self.assertEqual((worker["status"], worker["runs"], state.L["queue"]["p:impl"]["status"]), ("waiting", 0, "queued"))

    def test_accepted_or_superseded_work_cannot_be_revised(self):
        worker = self.worker(start=False)
        worker.update(status="done", acceptance={"commit": "c", "worker_commit": "w", "via": "landing"})
        lifecycle.project(worker)
        with self.assertRaisesRegex(ValueError, "already accepted"):
            self.as_manager("revise", item="p:impl", brief="Again", reason="more")
        queues.add(self.project, "queued", "old", "Old")
        state.L["queue"]["p:old"]["replaced_by"] = ["impl"]
        with self.assertRaisesRegex(ValueError, "superseded"):
            self.as_manager("revise", item="p:old", brief="Again", reason="more")

    def test_a_revision_needs_a_reason_and_a_valid_brief(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        for body, message in (({"brief": "New", "reason": " "}, "why"), ({"brief": "", "reason": "r"}, "brief"),
                              ({"brief": "New", "reason": "r", "stage": "whatever"}, "stage")):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, message):
                self.as_manager("revise", item="p:impl", **body)
        self.assertEqual(state.L["queue"]["p:impl"]["brief"], "Implement it")

    # ------------------------------------------------ rights

    def test_only_the_owning_projects_manager_or_user_decides(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        steward = support.running(tasks.create("steward", tasks.SYSTEM, "loose-ends", "", [6]), "steward-1", worktree=False)
        with self.assertRaisesRegex(ValueError, "owning project's running manager"):
            api.dispatch("hold", {"item": "p:impl", "proposed_by": steward["id"], "run": "steward-1"})
        other = {**self.project, "name": "q"}
        state.CONFIG["projects"].append(other)
        foreign = support.running(support.queued(other, "plan", "Plan", kind="command"), "manager-2", worktree=False)
        with self.assertRaisesRegex(ValueError, "owning project's running manager"):
            api.dispatch("revise", {"item": "p:impl", "brief": "X", "reason": "r",
                                    "proposed_by": foreign["id"], "run": "manager-2"})
        with self.assertRaisesRegex(ValueError, "unknown queue item"):
            api.dispatch("hold", {"item": "impl"})
        api.dispatch("hold", {"item": "p:impl"})  # the user
        self.assertEqual(state.L["queue"]["p:impl"]["held_by"], "user")


if __name__ == "__main__":
    unittest.main()
