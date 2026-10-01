"""Receipt-driven completion: one typed receipt per run; process exit only reconciles."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, checks, git, lifecycle, opencode, queues, runs, snapshots, spawner, state, tasks, trees
from tests import support


class Completion(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.run_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(opencode, "run_dir", return_value=self.run_dir))
        self.enterContext(patch.object(opencode, "active", return_value=False))
        self.project = support.project(self, support.repository(self))
        self.task = support.running(tasks.create("steward", tasks.SYSTEM, "loose-ends", "Look around", [6]), "run-1")

    def end(self, *events, code=0, agent="run-1"):
        """The run's unit has exited having written these events; its observer reports it."""
        (self.run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (self.run_dir / "exit.json").write_text(json.dumps({"code": code}))
        runs.follow(agent, None, None)

    # ------------------------------------------------ process exit only reconciles

    def test_exit_after_receipt_releases_the_run_and_keeps_the_settlement(self):
        lifecycle.submit(self.task["id"], "run-1", "complete", "Nothing fell between owners")
        self.assertEqual((self.task["status"], self.task["agent"]), ("done", None))
        # A normal exit precedes the observer's release: not an invariant violation.
        self.assertTrue(all(c["ok"] for c in checks.evaluate(state.CONFIG, state.L, state.now(), {})))
        self.end({"type": "text", "part": {"type": "text", "text": "Done"}},
                 {"type": "step_finish", "part": {"reason": "tool-calls"}})
        self.assertEqual((self.task["status"], self.task["result"]), ("done", "Nothing fell between owners"))
        self.assertEqual((state.L["agents"], state.L["alerts"]), ({}, []))

    def test_receipt_keeps_the_active_conversation_warm_until_release(self):
        state.L["snapshots"]["warm"] = {"owner": self.task["id"]}
        with patch.object(snapshots.BACKEND, "forget") as forget:
            lifecycle.submit(self.task["id"], "run-1", "complete", "Done")
            self.assertIn("warm", state.L["snapshots"])
            lifecycle.release("run-1", "run ended")
        self.assertNotIn("warm", state.L["snapshots"])
        forget.assert_called_once_with(state.CONFIG, "warm")

    def test_receipt_delivery_schedules_the_exact_run_for_retirement(self):
        lifecycle.submit(self.task["id"], "run-1", "complete", "Done")
        with patch.object(lifecycle.threading, "Thread") as thread:
            lifecycle.receipt_delivered(self.task["id"], "run-1")
        target = thread.call_args.kwargs["target"]
        with patch.object(lifecycle, "stop") as stop, patch.object(lifecycle, "save"):
            target()
        stop.assert_called_once_with("run-1", "completion receipt delivered", requeue=False, charge=False)

    def test_receipt_delivery_rejects_another_run(self):
        lifecycle.submit(self.task["id"], "run-1", "complete", "Done")
        with self.assertRaisesRegex(ValueError, "no completion receipt"):
            lifecycle.receipt_delivered(self.task["id"], "run-2")

    def test_final_text_and_a_stop_marker_without_a_receipt_are_not_completion(self):
        self.end({"type": "text", "part": {"type": "text", "text": "Complete final summary"}},
                 {"type": "step_finish", "part": {"reason": "stop"}})
        self.assertEqual((self.task["status"], self.task["receipt"]), ("waiting", None))
        self.assertIn("without a completion receipt (finish marker stop, exit code 0)", self.task["note"])

    def test_a_transcript_ending_after_tool_calls_is_decided_by_the_receipt_alone(self):
        lifecycle.submit(self.task["id"], "run-1", "complete", "Queued one command")
        self.end({"type": "step_start", "part": {"type": "step-start"}},
                 {"type": "step_finish", "part": {"reason": "tool-calls"}}, code=1)
        self.assertEqual(self.task["status"], "done")

    def test_an_unexpected_unit_death_requeues_the_task(self):
        runs.follow("run-1", None, None)
        self.assertEqual((self.task["status"], state.L["agents"]), ("waiting", {}))

    def test_runner_errors_are_diagnostics_on_the_retry(self):
        with patch.object(opencode, "watch", side_effect=RuntimeError("serve failed")):
            runs.follow("run-1", None, None)
        self.assertEqual(self.task["status"], "waiting")
        self.assertIn("RuntimeError: serve failed", self.task["note"])

    def test_launch_failures_are_uncharged_bounded_and_held(self):
        self.task["runs"] = 1
        state.L["agents"]["run-1"]["engaged"] = False
        self.end(code=1)
        self.assertEqual((self.task["status"], self.task["runs"], self.task["launch_failures"]),
                         ("waiting", 0, 1))
        support.running(self.task, "run-2", worktree=False)
        state.L["agents"]["run-2"]["engaged"] = False
        self.end(code=1, agent="run-2")
        self.assertEqual((self.task["status"], self.task["runs"], self.task["launch_failures"]),
                         ("waiting", 0, 2))
        self.assertEqual(self.task["admission_hold"], "repeated infrastructure launch failure")
        self.assertIn("before reaching the model", state.L["alerts"][-1]["text"])

    def test_first_gateway_admission_clears_launch_failures_in_the_reducer(self):
        self.task["launch_failures"] = 1
        state.L["agents"]["run-1"]["engaged"] = False
        lifecycle.engaged("run-1")
        self.assertTrue(state.L["agents"]["run-1"]["engaged"])
        self.assertEqual(self.task["launch_failures"], 0)

    def test_every_kind_shares_one_bounded_retry_limit(self):
        limit = state.CONFIG["spawner"]["max_runs_per_task"]
        for attempt in range(2, limit + 1):
            runs.follow(f"run-{attempt - 1}", None, None)
            self.assertEqual(self.task["status"], "waiting")
            support.running(self.task, f"run-{attempt}", worktree=False)
        runs.follow(f"run-{limit}", None, None)
        self.assertEqual((self.task["status"], len(state.L["alerts"])), ("failed", 1))

    def test_a_session_learned_by_the_observer_belongs_to_the_current_run_only(self):
        runs.observed("run-1", "session", "session-a")
        self.assertEqual(self.task["session"], "session-a")
        lifecycle.submit(self.task["id"], "run-1", "complete", "Done")
        runs.observed("run-1", "session", "session-b")
        self.assertEqual(self.task["session"], "session-a")

    # ------------------------------------------------ receipts

    def test_a_lost_reply_retry_returns_the_recorded_receipt(self):
        first = lifecycle.submit(self.task["id"], "run-1", "complete", "Clean finding")
        self.assertIs(lifecycle.submit(self.task["id"], "run-1", "complete", "Clean finding"), first)
        with self.assertRaisesRegex(ValueError, "different completion receipt"):
            lifecycle.submit(self.task["id"], "run-1", "blocked", "Clean finding")

    def test_a_stale_run_cannot_submit_or_disturb_a_newer_run(self):
        lifecycle.stop("run-1", "silent too long", requeue=True)
        support.running(self.task, "run-2", worktree=False)
        with self.assertRaisesRegex(ValueError, "only its current run"):
            lifecycle.submit(self.task["id"], "run-1", "complete", "Late summary")
        state.L["agents"]["run-1"] = {**state.L["agents"]["run-2"], "id": "run-1"}  # its late exit report
        lifecycle.ended("run-1", {"finish": "stop", "code": 0})
        self.assertEqual((self.task["status"], self.task["agent"]), ("running", "run-2"))
        self.assertNotIn("run-1", state.L["agents"])

    def test_a_directed_stop_after_the_receipt_does_not_requeue(self):
        lifecycle.submit(self.task["id"], "run-1", "blocked", "David must choose the boundary")
        lifecycle.stop("run-1", "stopped by David", requeue=True, charge=False)
        self.assertEqual((self.task["status"], self.task["runs"], self.task["receipt"]["disposition"]), ("done", 1, "blocked"))
        self.assertIn("David must choose the boundary", state.L["alerts"][-1]["text"])

    def test_a_directed_stop_before_the_receipt_is_uncharged(self):
        lifecycle.stop("run-1", "system halted", requeue=True, charge=False)
        self.assertEqual((self.task["status"], self.task["runs"]), ("waiting", 0))

    def test_killing_a_run_never_decides_its_task_failed(self):
        api.kill_agent({"agent": "run-1"})
        self.assertEqual((self.task["status"], self.task["runs"], self.task["receipt"]), ("waiting", 0, None))
        self.assertNotIn("run-1", state.L["agents"])

    def test_a_receipt_needs_its_kinds_disposition_and_a_summary(self):
        with self.assertRaisesRegex(ValueError, "needs a summary"):
            lifecycle.submit(self.task["id"], "run-1", "complete", " ")
        with self.assertRaisesRegex(ValueError, "complete or blocked"):
            lifecycle.submit(self.task["id"], "run-1", "returned", "No")
        self.assertEqual(self.task["status"], "running")

    # ------------------------------------------------ evidence by kind

    def worker(self, report: str, commit=True) -> dict:
        worker = support.running(support.queued(self.project, "parser"), "worker-1")
        (Path(worker["worktree"]) / queues.REPORT).write_text(report)
        if commit:
            support.commit(worker["worktree"])
        return worker

    def test_a_worker_receipt_submits_its_committed_branch_for_review(self):
        worker = self.worker("Status: done\n\nParser exists.\n")
        receipt = lifecycle.submit(worker["id"], "worker-1", "complete", "Parser exists")
        self.assertEqual(worker["status"], "review")
        self.assertEqual(receipt["evidence"], {"commit": support.git.head(worker["worktree"]), "report": "done"})
        lifecycle.release("worker-1", "run ended")
        self.assertTrue(Path(worker["worktree"]).is_dir(), "the integrator still needs the worker's branch")

    def test_a_blocked_worker_is_reviewed_too(self):
        worker = self.worker("Status: blocked\n\nNeeds decomposition: split.\n")
        lifecycle.submit(worker["id"], "worker-1", "blocked", "Needs decomposition")
        self.assertEqual(worker["status"], "review")

    def test_a_worker_receipt_must_match_one_committed_report(self):
        worker = self.worker("Status: done\n")
        with self.assertRaisesRegex(ValueError, "Status: blocked"):
            lifecycle.submit(worker["id"], "worker-1", "blocked", "Stuck")
        (Path(worker["worktree"]) / queues.REPORT).write_text("Status: in progress\n")
        support.commit(worker["worktree"])
        with self.assertRaisesRegex(ValueError, "Status: done"):
            lifecycle.submit(worker["id"], "worker-1", "complete", "Done")
        self.assertEqual((worker["status"], worker["receipt"]), ("running", None))

    def test_an_uncommitted_worker_cannot_finish(self):
        worker = self.worker("Status: done\n", commit=False)
        with self.assertRaisesRegex(ValueError, "commit"):
            lifecycle.submit(worker["id"], "worker-1", "complete", "Done")

    def gardener(self, pending: list[str]) -> dict:
        tree = {"name": "p", "path": self.project["path"], "main_branch": "main", "tree": ".knowledge"}
        self.enterContext(patch.dict(state.CONFIG, trees=[tree]))
        health = {"leaves": [f"yellow\tlocal:{p}\tunverified" for p in pending], "brown": 0, "yellow": len(pending)}
        self.enterContext(patch.object(trees, "health", return_value=health))
        return support.running(tasks.create("garden", tree, "garden", "what/is/selected.md", [3]), "gardener-1")

    def test_a_garden_batch_can_finish_with_other_leaves_still_yellow(self):
        garden = self.gardener(["what/is/other.md"])
        lifecycle.submit(garden["id"], "gardener-1", "complete", "Checked the batch")
        self.assertEqual(garden["status"], "done")

    def test_a_garden_reports_unresolved_selected_leaves_instead_of_looping(self):
        garden = self.gardener(["what/is/selected.md"])
        receipt = lifecycle.submit(garden["id"], "gardener-1", "complete", "Checked the batch")
        self.assertEqual(receipt["evidence"]["unresolved"], ["what/is/selected.md"])
        self.assertIn("what/is/selected.md", state.L["alerts"][-1]["text"])

    def test_a_garden_cannot_finish_without_landing_or_with_uncommitted_corrections(self):
        garden = self.gardener([])
        (Path(garden["worktree"]) / "leaf.md").write_text("corrected\n")
        with self.assertRaisesRegex(ValueError, "commit"):
            lifecycle.submit(garden["id"], "gardener-1", "complete", "Corrected")
        support.commit(garden["worktree"])
        with self.assertRaisesRegex(ValueError, "cointos merge"):
            lifecycle.submit(garden["id"], "gardener-1", "complete", "Corrected")
        support.git.run(self.project["path"], "merge", "--ff-only", garden["branch"])
        lifecycle.submit(garden["id"], "gardener-1", "complete", "Corrected")
        lifecycle.release("gardener-1", "run ended")
        self.assertFalse(Path(garden["worktree"]).exists(), "a landed worktree is removed")

    def test_a_system_operator_needs_only_its_summary(self):
        operator = support.running(tasks.request_operator("look", "Look.", None, None, None, None), "operator-1")
        lifecycle.submit(operator["id"], "operator-1", "complete", "Restarted the viewer")
        self.assertEqual(operator["status"], "done")

    # ------------------------------------------------ integrators

    def integration(self) -> tuple[dict, dict]:
        worker = self.worker("Status: done\n")
        lifecycle.submit(worker["id"], "worker-1", "complete", "Done")
        lifecycle.release("worker-1", "run ended")
        integration = tasks.create("integrate", self.project, "integrate-parser", worker["brief"], [2],
                                   item="parser", worker=worker["id"])
        return support.running(integration, "integrator-1"), worker

    def acceptance(self, worker, commit="main"):
        return {"commit": commit, "worker_commit": worker["receipt"]["evidence"]["commit"], "via": "landing"}

    def test_an_integrator_completes_only_through_a_landing(self):
        integration, worker = self.integration()
        with self.assertRaisesRegex(ValueError, "cointos land"):
            lifecycle.submit(integration["id"], "integrator-1", "complete", "Looks good")
        with self.assertRaisesRegex(ValueError, "not the one its receipt submitted"):
            lifecycle.landed(integration, "integrator-1", worker, {**self.acceptance(worker), "worker_commit": "other"})
        lifecycle.landed(integration, "integrator-1", worker, self.acceptance(worker))
        self.assertEqual((worker["status"], integration["status"]), ("done", "done"))
        self.assertEqual(integration["receipt"]["evidence"]["commit"], "main")
        (Path(integration["worktree"]) / "note.md").write_text("an edit that never landed\n")
        unlanded = support.commit(integration["worktree"])
        lifecycle.release("integrator-1", "run ended")
        self.assertFalse(Path(worker["worktree"]).exists(), "an accepted worker's checkout is retired")
        self.assertFalse(Path(integration["worktree"]).exists(), "a settled integration's checkout is retired")
        repo = tasks.place(integration)["path"]
        self.assertEqual(git.head(repo, git.ARCHIVE + integration["branch"]), unlanded,
                         "an unlanded integration commit stays reachable in the archive")

    def test_a_landing_from_another_run_is_refused(self):
        integration, worker = self.integration()
        with self.assertRaisesRegex(ValueError, "only its current run"):
            lifecycle.landed(integration, "integrator-0", worker, self.acceptance(worker))
        self.assertEqual(worker["status"], "review")

    def test_a_return_is_the_integrators_receipt(self):
        integration, worker = self.integration()
        lifecycle.returned(integration, "integrator-1", "Handle empty input")
        lifecycle.returned(integration, "integrator-1", "Handle empty input")  # a lost reply is safe
        self.assertEqual((worker["status"], worker["review"], worker["rejections"], worker["receipt"]),
                         ("waiting", "Handle empty input", 1, None))
        self.assertEqual((integration["status"], integration["receipt"]["disposition"]), ("done", "returned"))

    def test_a_blocked_integrator_fails_its_worker_instead_of_respawning(self):
        integration, worker = self.integration()
        lifecycle.submit(integration["id"], "integrator-1", "blocked", "Main checkout is dirty")
        self.assertEqual((integration["status"], worker["status"]), ("failed", "failed"))

    def test_verified_blocker_dispatches_one_manager_without_magic_words(self):
        worker = self.worker("Status: blocked\n\nIdentical inputs share identity; requested output is impossible.\n")
        lifecycle.submit(worker["id"], "worker-1", "blocked", "Contract mismatch")
        lifecycle.release("worker-1", "run ended")
        integration = support.running(tasks.create("integrate", self.project, "integrate-parser", worker["brief"],
                                                   [2], item="parser", worker=worker["id"]), "integrator-1")
        lifecycle.submit(integration["id"], "integrator-1", "blocked", "Verified identity mismatch; repair the brief")
        lifecycle.release("integrator-1", "run ended")
        record = queues.records()[worker["record"]]
        self.assertEqual((record["status"], record["decompose"]), ("blocked", True))
        self.assertEqual(state.L["alerts"], [], "a manager-handleable blocker does not interrupt David")
        manager = spawner.next_task()
        self.assertEqual((manager["role"], manager["item"]), ("manager", "parser"))
        self.assertIn("Contract mismatch", manager["brief"])
        self.assertIn("Verified identity mismatch", manager["brief"])
        self.assertIn(worker["brief"], manager["brief"])
        self.assertIs(spawner.next_task(), manager, "reconciliation must not create a second manager")
        support.running(manager, "manager-1")
        lifecycle.submit(manager["id"], "manager-1", "blocked", "David must choose the public contract")
        self.assertFalse(record["decompose"])
        self.assertIn("David must choose", state.L["alerts"][-1]["text"])
        self.assertNotEqual((spawner.next_task() or {}).get("kind"), "decompose")

    def test_exhausted_worker_routes_to_manager_but_exhausted_manager_does_not_loop(self):
        worker = support.queued(self.project, "exhausted", "Build one bounded concern")
        lifecycle.fail(worker, "fresh retries exhausted")
        manager = spawner.next_task()
        self.assertEqual((manager["kind"], manager["item"]), ("decompose", "exhausted"))
        lifecycle.fail(manager, "manager retries exhausted")
        self.assertFalse(queues.records()[worker["record"]]["decompose"])
        self.assertNotEqual((spawner.next_task() or {}).get("kind"), "decompose")

    def test_manager_can_correct_a_brief_without_accepting_the_failed_work(self):
        worker = support.queued(self.project, "wrong", "Impossible contract")
        lifecycle.fail(worker, "contract mismatch")
        manager = support.running(spawner.next_task(), "manager-1")
        api.dispatch("hold", {"item": worker["id"], "proposed_by": manager["id"], "run": "manager-1"})
        api.dispatch("revise", {"item": worker["id"], "brief": "Corrected contract", "reason": "Identity is shared",
                                "proposed_by": manager["id"], "run": "manager-1"})
        lifecycle.submit(manager["id"], "manager-1", "complete", "Corrected the contract")
        self.assertEqual((worker["status"], queues.records()[worker["record"]]["status"]), ("waiting", "queued"))
        self.assertNotIn("wrong", queues.landed(self.project))
        lifecycle.reconcile()
        self.assertEqual(queues.records()[worker["record"]]["brief"], "Corrected contract")

    def test_failed_assignment_dependencies_do_not_prevent_manager_repair(self):
        worker = support.queued(self.project, "wrong-edge", "Depends on: missing\nBuild core")
        lifecycle.fail(worker, "bad prerequisite")
        manager = spawner.next_task()
        self.assertEqual((manager["kind"], manager["item"]), ("decompose", "wrong-edge"))

    # ------------------------------------------------ daemon replacement

    def test_a_run_lost_in_a_daemon_replacement_waits_again(self):
        state.L["agents"].clear()
        with patch.object(opencode, "find_processes", return_value={}):
            runs.adopt({})
        self.assertEqual((self.task["status"], self.task["agent"]), ("waiting", None))

    def test_a_run_that_outlived_the_daemon_is_followed_again(self):
        previous = {"agents": dict(state.L["agents"])}
        state.L["agents"].clear()
        with patch.object(runs.keys, "recorded", return_value={"run-1": "key"}), \
                patch.object(opencode, "active", return_value=True), \
                patch.object(opencode, "find_processes", return_value={}), patch.object(runs.threading, "Thread") as thread:
            runs.adopt(previous)
        self.assertEqual((self.task["status"], list(state.L["agents"])), ("running", ["run-1"]))
        thread.assert_called_once_with(target=runs.follow, args=("run-1", None, None), daemon=True)

    def test_a_keyed_run_whose_unit_died_during_shutdown_is_orphaned_uncharged(self):
        previous = {"agents": dict(state.L["agents"])}
        before = self.task["runs"]
        state.L["agents"].clear()
        with patch.object(runs.keys, "recorded", return_value={"run-1": "key"}), \
                patch.object(opencode, "active", return_value=False), \
                patch.object(opencode, "find_processes", return_value={}):
            runs.adopt(previous)
        self.assertEqual((self.task["status"], self.task["agent"], self.task["runs"]),
                         ("waiting", None, before))


if __name__ == "__main__":
    unittest.main()
