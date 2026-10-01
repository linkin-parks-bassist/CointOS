import copy
import unittest
from unittest import mock

from cointos import lanes, lifecycle, snapshots, state

WORK = state.CONFIG["work_model"]


class Snapshots(unittest.TestCase):
    """Only a conversation that can go on keeps saved contexts, and only ones it can go on from."""

    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        saved = dict(lanes.HELD)
        self.addCleanup(lambda: (lanes.HELD.clear(), lanes.HELD.update(saved)))
        state.L.clear()
        state.L.update(state.fresh({}))
        state.L["lanes"] = [lane for lane in state.L["lanes"] if lane["model"] == WORK][:1]
        state.L["tasks"]["t"] = {"id": "t", "status": "running"}
        self.forgotten = []
        self.enterContext(mock.patch.object(snapshots.BACKEND, "save", self.save))
        self.enterContext(mock.patch.object(snapshots.BACKEND, "forget", lambda config, name: self.forgotten.append(name)))
        self.enterContext(mock.patch.object(snapshots.BACKEND, "restore", lambda config, model, index, name: True))
        self.enterContext(mock.patch.object(snapshots, "make_room", lambda need: True))
        self.while_saving = lambda: None

    def save(self, config, model, index, name):
        self.while_saving()  # a save takes seconds, outside the lock
        return {"bytes": 1}

    def test_a_state_saved_as_its_task_ends_is_not_kept(self):
        self.while_saving = lambda: state.L["tasks"]["t"].update(status="done")
        self.assertFalse(snapshots.keep(0, [1, 2, 3], "t", "suspended"))
        self.assertEqual(state.L["snapshots"], {})
        self.assertEqual(len(self.forgotten), 1)

    def test_a_state_saved_as_its_task_is_forgotten_is_not_kept(self):
        self.while_saving = lambda: state.L["tasks"].pop("t")
        self.assertFalse(snapshots.keep(0, [1, 2, 3], "t", "suspended"))
        self.assertEqual(state.L["snapshots"], {})

    def test_coin_david_and_shared_starts_are_kept_without_tasks(self):
        for tokens, owner in enumerate(("coin", "user", "shared")):
            self.assertTrue(snapshots.keep(0, [tokens], owner, "checkpoint"))
        self.assertEqual(sorted(s["owner"] for s in state.L["snapshots"].values()), ["coin", "shared", "user"])

    def test_conversation_liveness_is_task_reachability_not_task_outcome(self):
        self.assertTrue(snapshots.live("t"))
        state.L["tasks"]["t"]["status"] = "review"
        self.assertTrue(snapshots.live("t"), "reviewed work can be returned to this conversation")
        state.L["tasks"]["t"]["status"] = "done"
        self.assertFalse(snapshots.live("t"))
        state.L["agents"]["run-1"] = {"task": "t"}
        self.assertTrue(snapshots.live("t"), "a terminal task's surviving run can still issue a request")

    def test_orphaned_snapshots_are_forgotten_but_review_and_untasked_ones_kept(self):
        state.L["tasks"]["r"] = {"id": "r", "status": "review"}
        for name, owner in (("a", "gone"), ("b", "r"), ("c", "shared"), ("d", "coin"), ("e", "t")):
            state.L["snapshots"][name] = {"owner": owner}
        snapshots.forget_orphans()
        self.assertEqual(sorted(state.L["snapshots"]), ["b", "c", "d", "e"])
        self.assertEqual(self.forgotten, ["a"])

    def test_reconciliation_forgets_terminal_owners_but_preserves_surviving_runs(self):
        for name, status in (("accepted", "done"), ("failed", "failed"), ("finishing", "done"), ("review", "review")):
            state.L["tasks"][name] = {"id": name, "status": status, "branch": None, "record": None}
            state.L["snapshots"][name] = {"owner": name, "tier": "disk"}
        state.L["agents"]["finishing-run"] = {"task": "finishing"}
        state.L["tasks"]["t"].update(branch=None, record=None)
        lifecycle.reconcile()
        self.assertEqual(set(state.L["snapshots"]), {"finishing", "review"})
        self.assertEqual(set(self.forgotten), {"accepted", "failed"})

    def test_owner_retirement_during_spill_defers_cleanup_until_copy_finishes(self):
        state.L["snapshots"]["moving"] = {"owner": "t", "tier": "moving", "bytes": 123}
        def transfer(config, name):
            state.L["tasks"]["t"]["status"] = "done"
            snapshots.forget_orphans()
            self.assertEqual(self.forgotten, [])
            self.assertEqual(state.L["snapshots"][name]["bytes"], 123)
            self.assertTrue(state.L["snapshots"][name]["discard"])
        with mock.patch.object(snapshots.BACKEND, "spill", side_effect=transfer):
            snapshots.spill("moving")
        self.assertEqual(state.L["snapshots"], {})
        self.assertEqual(self.forgotten, ["moving"])

    def test_unspill_does_not_restore_a_retired_owner_or_a_discarded_live_prefix(self):
        for retire in (True, False):
            with self.subTest(retire=retire):
                state.L["tasks"]["t"]["status"] = "running"
                state.L["snapshots"]["disk"] = {"owner": "t", "tier": "disk", "bytes": 123}
                self.forgotten.clear()
                def transfer(config, name):
                    if retire:
                        state.L["tasks"]["t"]["status"] = "done"
                    snapshots.forget_owner("t")
                    self.assertEqual(self.forgotten, [])
                    self.assertEqual(state.L["snapshots"][name]["tier"], "moving")
                with mock.patch.object(snapshots.BACKEND, "unspill", side_effect=transfer):
                    self.assertFalse(snapshots.bring_back("disk"))
                self.assertEqual(state.L["snapshots"], {})
                self.assertEqual(self.forgotten, ["disk"])

    def test_unspill_error_is_a_cache_miss_and_cleans_the_failed_transfer(self):
        state.L["snapshots"]["disk"] = {"owner": "t", "tier": "disk", "bytes": 123}
        with mock.patch.object(snapshots.BACKEND, "unspill", side_effect=OSError("missing cache file")):
            self.assertFalse(snapshots.bring_back("disk"))
        self.assertEqual(state.L["snapshots"], {})
        self.assertEqual(self.forgotten, ["disk"])

    def test_startup_discards_interrupted_transfers_but_keeps_committed_tiers(self):
        for name, tier in (("copy", "moving"), ("ram", "memory"), ("disk", "disk")):
            state.L["snapshots"][name] = {"owner": "t", "tier": tier}
        snapshots.forget_transfers()
        self.assertEqual(set(state.L["snapshots"]), {"ram", "disk"})
        self.assertEqual(self.forgotten, ["copy"])

    def test_a_task_does_not_save_the_state_its_next_thought_has_left_behind(self):
        # The lane holds the end of t's last thought, which the conversation, as rendered
        # again for its next thought, does not go on from.
        state.L["lanes"][0]["resident"] = "t"
        lanes.HELD[0] = [1, 2, 3, 40, 41]
        lanes.switch(0, [1, 2, 3, 50, 51, 52], "t")
        self.assertEqual(state.L["snapshots"], {})

    def test_another_conversation_is_saved_when_switched_out(self):
        state.L["tasks"]["u"] = {"id": "u", "status": "running"}
        state.L["lanes"][0]["resident"] = "u"
        lanes.HELD[0] = [7, 8, 9]
        lanes.switch(0, [1, 2, 3], "t")
        self.assertEqual([s["owner"] for s in state.L["snapshots"].values()], ["u"])


if __name__ == "__main__":
    unittest.main()
