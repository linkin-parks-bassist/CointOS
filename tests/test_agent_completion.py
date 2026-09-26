import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.enterContext(patch.object(work, "project_named", return_value={}))
        self.enterContext(patch.object(work.lanes, "cancel_agent"))
        self.enterContext(patch.object(work.lanes, "forget_owner"))
        self.enterContext(patch.object(work.threading, "Thread"))
        state.L["tasks"]["test"] = {
            "id": "test", "title": "test", "project": "sandbox", "kind": "survey",
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


if __name__ == "__main__":
    unittest.main()
