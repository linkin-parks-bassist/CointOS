"""Run budgets and fresh recovery, worker reports, superseded prerequisites, and the journal."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cointos import journal, lifecycle, opencode, prompts, queues, recovery, state, tasks
from tests import support


class Reports(unittest.TestCase):
    def test_headings_and_frontmatter_do_not_hide_completion(self):
        self.assertEqual(queues.status("---\nstatus: green\n---\n# Work report\n\n**Status:** done\nEvidence."), "done")

    def test_quoted_examples_do_not_submit_and_ambiguous_reports_fail(self):
        self.assertIsNone(queues.status("```md\nStatus: done\n```\n> Status: done"))
        self.assertIsNone(queues.status("Status: done\nStatus: blocked"))
        self.assertIsNone(queues.status("Status: done\nStatus: done"))
        self.assertEqual(queues.status("# Heading\nStatus: blocked\nNeeds decomposition: split"), "blocked")


class Replacement(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.project = support.project(self, support.repository(self))
        for name, brief in [("old", "Old"), ("new", "New"), ("next", "Depends on: old\nNext")]:
            queues.add(self.project, "queued", name, brief)
        tasks.create("item", self.project, "old", "Old", [4], item="old")["status"] = "failed"
        queues.update("p", "old", "blocked")

    def ready(self):
        return queues.readiness(queues.scan(self.project), queues.landed(self.project))

    def test_replacement_survives_restart_and_waits_for_real_acceptance(self):
        receipt = queues.supersede("p:old", ["new"], "Verified replacement")
        restored = json.loads(json.dumps(state.L))
        state.L.clear()
        state.L.update(state.fresh(restored))
        self.assertEqual(queues.supersede("p:old", ["new"], "Verified replacement"), receipt)
        self.assertEqual(state.L["tasks"]["p:old"]["status"], "failed")
        self.assertNotIn("old", queues.landed(self.project))
        self.assertEqual((state.L["queue"]["p:next"]["depends"], self.ready()["next"]), (["new"], "waiting"))
        queues.update("p", "new", "done")
        self.assertEqual(self.ready()["next"], "ready")

    def test_cycles_unknown_and_conflicting_retries_do_not_mutate(self):
        state.L["queue"]["p:new"]["depends"] = ["next"]
        before = copy.deepcopy(state.L["queue"])
        with self.assertRaisesRegex(ValueError, "cycle"):
            queues.supersede("p:old", ["new"], "Cycle")
        self.assertEqual(state.L["queue"], before)
        with self.assertRaisesRegex(ValueError, "same-project"):
            queues.supersede("p:old", ["q:new"], "Unknown")
        state.L["queue"]["p:new"]["depends"] = []
        queues.supersede("p:old", ["new"], "Good")
        with self.assertRaisesRegex(ValueError, "different replacement"):
            queues.supersede("p:old", ["next"], "Different")

    def test_dependency_aliases_follow_the_same_replacement(self):
        state.L["queue"]["p:next"]["depends"] = ["what/is/the/queued/old.md"]
        queues.supersede("p:old", ["new"], "Replacement")
        self.assertEqual(state.L["queue"]["p:next"]["depends"], ["new"])

    def test_a_failed_replacement_is_rejected(self):
        tasks.create("item", self.project, "new", "New", [4], item="new")["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "invalid same-project replacement"):
            queues.supersede("p:old", ["new"], "Still failed")
        self.assertEqual(state.L["queue"]["p:next"]["depends"], ["old"])


class Budgets(unittest.TestCase):
    """Generation alone is charged; exhaustion restarts fresh a bounded number of times."""

    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))
        self.task = support.running(support.queued(self.project, "item"), "worker-1")
        self.task["session"] = "old"
        self.agent = state.L["agents"]["worker-1"]
        self.agent.update(generation_seconds=0, generation_tokens=0)

    def spend(self, seconds=0, tokens=0):
        self.agent.update(generation_seconds=seconds, generation_tokens=tokens)
        recovery.enforce()

    def test_waits_and_prefill_cost_nothing_and_a_drain_never_recovers(self):
        self.spend()
        self.assertEqual(self.task["status"], "running")
        state.L["restarting"] = True
        self.spend(seconds=self.task["budget"]["generation_seconds"])
        self.assertEqual(self.task["status"], "running")

    def test_exhaustion_restarts_fresh_a_bounded_number_of_times(self):
        self.spend(tokens=self.task["budget"]["generation_tokens"])
        self.assertEqual((self.task["status"], self.task["session"], self.task["fresh_retries"]), ("waiting", None, 1))
        self.assertIn("generation budget reached", self.task["recovery_note"])
        self.task["fresh_retries"] = state.CONFIG["recovery"]["fresh_retries"]
        support.running(self.task, "worker-2", worktree=False)
        state.L["agents"]["worker-2"].update(generation_seconds=0, generation_tokens=self.task["budget"]["generation_tokens"])
        recovery.enforce()
        self.assertEqual(self.task["status"], "failed")
        self.assertIn("fresh retries exhausted", self.task["note"])

    def test_a_task_override_and_either_limit_triggers(self):
        self.task["budget"] = {"generation_tokens": 100, "generation_seconds": 10}
        self.spend(tokens=99, seconds=9)
        self.assertEqual(self.task["status"], "running")
        self.spend(seconds=10)
        self.assertEqual(self.task["status"], "waiting")

    def test_a_committed_report_without_a_receipt_does_not_win_over_the_budget(self):
        (Path(self.task["worktree"]) / queues.REPORT).write_text("Status: done\n")
        support.commit(self.task["worktree"])
        self.spend(seconds=self.task["budget"]["generation_seconds"])
        self.assertEqual((self.task["status"], self.task["fresh_retries"]), ("waiting", 1))

    def test_a_receipted_run_over_budget_is_released_without_retry(self):
        (Path(self.task["worktree"]) / queues.REPORT).write_text("Status: done\n")
        support.commit(self.task["worktree"])
        lifecycle.submit(self.task["id"], "worker-1", "complete", "Done")
        self.spend(seconds=self.task["budget"]["generation_seconds"])
        self.assertNotIn("worker-1", state.L["agents"])
        self.assertEqual((self.task["status"], self.task["session"], self.task.get("fresh_retries")), ("review", "old", None))

    def test_an_item_without_a_durable_artifact_recovers_at_its_checkpoint(self):
        with patch.object(recovery, "packet", return_value="useful evidence"):
            self.spend(seconds=state.CONFIG["recovery"]["artifact_seconds"])
        self.assertIn("durable-artifact checkpoint", self.task["recovery_note"])
        self.assertEqual((self.task["status"], self.task["recovery_context"]), ("waiting", "useful evidence"))

    def test_a_productive_item_may_use_its_full_budget(self):
        (Path(self.task["worktree"]) / "work.txt").write_text("progress\n")
        self.spend(seconds=state.CONFIG["recovery"]["artifact_seconds"])
        self.assertEqual(self.task["status"], "running")


class Evidence(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.project = support.project(self, support.repository(self))

    def test_the_packet_keeps_recent_tools_text_and_git_but_never_reasoning(self):
        task = support.running(support.queued(self.project, "item"), "worker-1")
        task["base_commit"] = support.git.head(task["worktree"])
        (Path(task["worktree"]) / "work.txt").write_text("useful dirty work\n")
        run = Path(self.enterContext(tempfile.TemporaryDirectory()))
        events = [{"part": {"type": "reasoning", "text": "SECRET INNER MONOLOGUE"}},
                  {"part": {"type": "text", "text": "Verified the parser contract."}},
                  {"part": {"type": "tool", "tool": "bash", "state": {"status": "completed",
                            "input": {"command": "python3 -m unittest"}, "output": "Ran 86 tests OK"}}}]
        (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        with patch.object(opencode, "run_dir", return_value=run):
            packet = recovery.packet("worker-1", task, {"generation_tokens": 20, "generation_seconds": 3})
        for expected in ("Verified the parser contract", "python3 -m unittest", "?? work.txt"):
            self.assertIn(expected, packet)
        self.assertNotIn("SECRET INNER MONOLOGUE", packet)
        self.assertLessEqual(len(packet), state.CONFIG["recovery"]["handoff_chars"])

    def test_first_and_recovery_prompts_end_with_the_budget_and_carry_the_packet(self):
        queues.add(self.project, "queued", "child", "Brief", budget={"generation_tokens": 1234, "generation_seconds": 56})
        task = tasks.create("item", self.project, "child", "Brief", [4], item="child", reasoning_effort="low")
        text = prompts.launch_text(task, self.project)
        self.assertIn("FYI — daemon-managed budget for this run: 1,234 generated tokens or 56 seconds", text)
        self.assertIn("reasoning block is limited to 256 tokens at low effort", text)
        self.assertGreater(text.rindex("FYI"), text.index("Brief"))
        self.assertTrue(text.endswith("do not expand scope."))
        task.update(recovery_note="checkpoint reached", recovery_context="Ran focused tests: OK")
        text = prompts.launch_text(task, self.project)
        self.assertIn("Recovery packet:\nRan focused tests: OK", text)
        self.assertIn("Treat packet claims as leads until verified", text)

    def test_a_recently_interrupted_run_gets_only_the_minimum_handoff(self):
        queues.add(self.project, "queued", "child", "Brief", budget={"generation_tokens": 1234, "generation_seconds": 56})
        task = {**tasks.create("item", self.project, "child", "Brief", [4], item="child"),
                "session": "old", "interrupted_at": 1000}
        run = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with patch.object(opencode, "run_dir", return_value=run), \
                patch.object(opencode.subprocess, "run") as systemd_run:
            opencode.launch(state.CONFIG, "worker-1", task, "key",
                            prompts.launch_text(task, self.project, at=1001), [])
        spec = json.loads((run / "run.json").read_text())
        self.assertEqual(spec["text"], "Continue.")
        self.assertEqual(spec["command"][-2:], ["--session", "old"])
        launched = systemd_run.call_args.args[0]
        self.assertIn("--property=Before=cointosd.service", launched)

    def test_a_session_interrupted_for_hours_gets_one_reorientation(self):
        queues.add(self.project, "queued", "child", "Brief")
        task = {**tasks.create("item", self.project, "child", "Brief", [4], item="child"),
                "session": "old", "interrupted_at": 1000}
        text = prompts.launch_text(task, self.project, at=1000 + prompts.REORIENT_AFTER_SECONDS)
        self.assertTrue(text.startswith("This assignment has been paused for several hours."))
        self.assertIn("daemon-managed budget", text)


class Journal(unittest.TestCase):
    def test_rotation_is_bounded_and_excludes_prompts(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with patch.object(journal, "STATE", root):
            for i in range(30):
                journal.write({"at": i, "event": "test", "task": "p:t", "prompt": "private"}, 300)
        files = list(root.iterdir())
        self.assertEqual(len(files), 2)
        for path in files:
            self.assertLessEqual(path.stat().st_size, 300)
            for line in path.read_text().splitlines():
                self.assertNotIn("prompt", json.loads(line))


if __name__ == "__main__":
    unittest.main()
