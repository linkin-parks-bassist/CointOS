import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from cointos import agents, checks, state, work


class Completion(unittest.TestCase):
    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.directory = Path(directory)
        self.enterContext(patch.object(agents, "agent_dir", return_value=self.directory))
        self.enterContext(patch.object(agents, "active", return_value=False))
        self.enterContext(patch.object(agents.time, "sleep"))
        self.enterContext(patch.object(agents, "stop"))
        self.enterContext(patch.object(agents, "remove_worktree", return_value=True))
        self.enterContext(patch.object(work, "keep_key"))
        self.enterContext(patch.object(work, "place", return_value={}))
        self.enterContext(patch.object(work.lanes, "cancel_agent"))
        self.enterContext(patch.object(work.lanes, "forget_owner"))
        self.enterContext(patch.object(work.threading, "Thread"))
        state.L["tasks"]["test"] = {
            "id": "test", "title": "test", "place": "sandbox", "kind": "survey",
            "status": "running", "runs": 1, "agent": "worker-test"}
        state.L["agents"]["worker-test"] = {
            "task": "test", "state": "running", "session": None, "repeats": 0,
            "thoughts": 1, "last_activity": state.now(), "started_at": state.now()}

    def test_exit_before_settlement_is_healthy_and_final_events_are_drained(self):
        events = [
            {"type": "text", "sessionID": "session", "part": {"type": "text", "text": "Done"}},
            {"type": "step_finish", "part": {"reason": "stop"}}]
        (self.directory / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (self.directory / "exit.json").write_text('{"code": 0}')
        # Force the exact production interleaving: no process, still in ledger, before watch settles.
        result = checks.evaluate(state.CONFIG, state.L, state.now(), {})
        self.assertTrue(all(c["ok"] for c in result), result)
        work.agent_thread("worker-test", None, None)
        task = state.L["tasks"]["test"]
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["result"], "Done")
        self.assertEqual(task["session"], "session")
        self.assertEqual(state.L["agents"], {})
        self.assertEqual(state.L["alerts"], [])

    def test_unexpected_unit_death_requeues_the_task(self):
        work.agent_thread("worker-test", None, None)
        self.assertEqual(state.L["tasks"]["test"]["status"], "waiting")
        self.assertEqual(state.L["agents"], {})

    def test_repeated_unfinished_runs_still_raise_a_real_failure(self):
        state.L["tasks"]["test"]["runs"] = state.CONFIG["spawner"]["max_runs_per_task"]
        work.agent_thread("worker-test", None, None)
        self.assertEqual(state.L["tasks"]["test"]["status"], "failed")
        self.assertEqual(len(state.L["alerts"]), 1)

    def item_run(self, on_branch, committed=True):
        """An item run that ended by itself, with its leaf's status on its branch."""
        branch = self.directory / "branch"
        leaf = branch / ".knowledge/what/is/queued/item.md"
        leaf.parent.mkdir(parents=True)
        leaf.write_text(f"Status: {on_branch}\n\nThe brief.\n")
        self.enterContext(patch.object(agents, "committed", return_value=committed))
        state.L["tasks"]["test"].update(kind="item", item="what/is/queued/item.md", worktree=str(branch))
        (self.directory / "exit.json").write_text('{"code": 0}')
        work.agent_thread("worker-test", None, None)
        return state.L["tasks"]["test"]

    def test_a_worker_hands_its_committed_item_to_review(self):
        self.assertEqual(self.item_run("done")["status"], "review")

    def test_a_blocked_item_is_reviewed_too(self):
        self.assertEqual(self.item_run("blocked")["status"], "review")

    def test_unfinished_or_uncommitted_work_requeues_the_task(self):
        self.assertEqual(self.item_run("in progress")["status"], "waiting")
        state.L["tasks"]["test"].update(status="running", agent="worker-test")
        state.L["agents"]["worker-test"] = {"task": "test", "state": "running", "session": None, "repeats": 0,
                                            "thoughts": 1, "last_activity": state.now(), "started_at": state.now()}
        (self.directory / "branch").rename(self.directory / "old")
        self.assertEqual(self.item_run("done", committed=False)["status"], "waiting")
        self.assertIn("uncommitted", state.L["tasks"]["test"]["note"])

    def garden_run(self, pending, merged=True, clean=True):
        state.L["tasks"]["test"].update(kind="garden", brief="what/is/selected.md", branch="test",
                                        worktree=str(self.directory))
        health = {"leaves": [f"yellow\tlocal:{p}\tunverified" for p in pending],
                  "brown": 0, "yellow": len(pending)}
        with patch.object(work, "place", return_value={"name": "sandbox", "path": "unused", "main_branch": "main"}), \
                patch.object(work.trees, "health", return_value=health), \
                patch.object(agents, "git", return_value=SimpleNamespace(returncode=0 if merged else 1)), \
                patch.object(agents, "committed", return_value=clean):
            work.settle("worker-test", {"finish": "stop"})
        return state.L["tasks"]["test"]["status"]

    def test_garden_batch_can_finish_with_other_leaves_still_yellow(self):
        self.assertEqual(self.garden_run(["what/is/other.md"]), "done")

    def test_garden_reports_unresolved_selected_leaves_instead_of_looping(self):
        self.assertEqual(self.garden_run(["what/is/selected.md"]), "done")
        self.assertIn("what/is/selected.md", state.L["alerts"][-1]["text"])

    def test_garden_cannot_finish_without_landing(self):
        self.assertEqual(self.garden_run([], merged=False), "waiting")

    def test_garden_cannot_finish_with_uncommitted_corrections(self):
        self.assertEqual(self.garden_run([], clean=False), "waiting")


if __name__ == "__main__":
    unittest.main()
