"""Refuse impossible assignments and bound planning recovery before it consumes more GPU."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import api, lifecycle, queues, recovery, schema, spawner, state, tasks
from tests import support


class BlockedWork(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        state.L["paused"] = False
        support.quiet(self)
        self.project = support.project(self, support.repository(self), test_policy={
            "manifest": "tests/contracts.json", "protected": ["tests/**", "Makefile"],
            "non_code": [".knowledge/**", "*.md"]})
        self.enterContext(patch.object(spawner, "periodic", return_value=[]))
        self.enterContext(patch.object(spawner, "tree_work", return_value=[]))
        self.manager = support.running(support.queued(self.project, "plan", "Plan one boundary", kind="command"),
                                       "manager-1")

    def test_structured_proposal_does_not_parse_dependency_explanations(self):
        body = {"project": "p", "name": "next", "brief": "Depends on: base (already on main, good)\nOne slice",
                "summary": "Build one slice", "dependencies": [], "stage": "implementation",
                "caller": support.caller(self.manager, "manager-1")}
        before = copy.deepcopy(state.L)
        self.assertEqual(api.dispatch("check-work", body)["problems"], [])
        self.assertEqual(state.L, before)
        api.dispatch("queue", body)
        record = state.L["queue"]["p:next"]
        self.assertEqual(record["depends"], [])
        self.assertEqual(record["summary"], "Build one slice")
        self.assertEqual(queues.depends(record["brief"]), [])

    def test_preflight_reports_missing_dependency_cycle_and_api_without_mutation(self):
        queues.add(self.project, "queued", "base", "Depends on: base\nExisting cyclic item")
        before = copy.deepcopy(state.L)
        body = {"project": "p", "name": "next", "brief": "One slice", "summary": "Build one slice",
                "dependencies": ["absent"], "stage": "implementation"}
        self.assertIn("unknown absent", api.dispatch("check-work", body)["problems"][0])
        body["dependencies"] = ["base"]
        self.assertIn("cycle", api.dispatch("check-work", body)["problems"][0])
        body.update(dependencies=[], stage="test-contract", relies_on=["missing_api"])
        self.assertIn("missing_api", api.dispatch("check-work", body)["problems"][0])
        body["dependencies"] = "not-an-array"
        self.assertIn("array", api.dispatch("check-work", body)["problems"][0])
        self.assertEqual(state.L, before)

    def test_manager_cannot_finish_with_a_dead_handoff_and_can_fix_it_in_the_same_run(self):
        body = {"project": "p", "name": "next", "brief": "One slice", "summary": "Build one slice",
                "dependencies": ["absent"], "caller": support.caller(self.manager, "manager-1")}
        api.dispatch("queue", body)
        with self.assertRaisesRegex(ValueError, "p:next: depends on unknown absent"):
            lifecycle.submit(self.manager["id"], "manager-1", "complete", "Queued the next slice")
        self.assertEqual(self.manager["status"], "running")
        self.assertIsNone(self.manager["receipt"])
        self.assertFalse(api.dispatch("check-work", {"caller": body["caller"]})["ok"])
        api.dispatch("revise", {"item": "p:next", "brief": "One slice", "reason": "No prerequisite needed",
                                "summary": "Build one slice", "dependencies": [], "caller": body["caller"]})
        self.assertTrue(api.dispatch("check-work", {"caller": body["caller"]})["ok"])
        lifecycle.submit(self.manager["id"], "manager-1", "complete", "Checked runnable handoff")
        self.assertEqual(self.manager["status"], "done")

    def test_worker_checks_real_edits_and_cannot_submit_a_protected_harness_to_an_integrator(self):
        worker = support.running(support.queued(self.project, "impl", "Implement one slice"), "worker-1")
        path = Path(worker["worktree"]) / "tests/harness.c"
        path.parent.mkdir()
        path.write_text("a protected harness edit\n")
        support.commit(worker["worktree"])
        caller = support.caller(worker, "worker-1")
        result = api.dispatch("check-work", {"caller": caller})
        self.assertFalse(result["ok"])
        self.assertIn("tests/harness.c", result["problems"][0])
        with self.assertRaisesRegex(ValueError, "protected tests or harness"):
            api.dispatch("finish", {"caller": caller, "outcome": "complete", "detail": "Ready"})
        self.assertEqual(worker["status"], "running")
        self.assertIsNone(worker["receipt"])
        self.assertFalse(any(t["kind"] == "integrate" for t in state.L["tasks"].values()))

    def test_dependency_annotations_are_refused_before_queue_mutation(self):
        before = copy.deepcopy(state.L)
        for name in ("base (already on main)", "base, already accepted", "src/base.c"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "only item IDs"):
                queues.add(self.project, "queued", "next", f"Depends on: {name}\nOne slice")
            self.assertEqual(state.L, before)
        queues.add(self.project, "queued", "next", "Depends on: future-base\nOne slice")
        self.assertEqual(state.L["queue"]["p:next"]["depends"], ["future-base"])

    def test_manager_exhaustion_goes_to_one_operator_without_fresh_planning(self):
        self.assertEqual(self.manager["budget"], schema.budget(state.CONFIG, role="manager"))
        state.L["agents"]["manager-1"]["generation_seconds"] = self.manager["budget"]["generation_seconds"]
        with patch.object(recovery, "packet", return_value="The same harness edit was refused"):
            recovery.enforce()
        self.assertEqual(self.manager["status"], "failed")
        self.assertEqual(self.manager["session"], None)
        operator = spawner.next_task()
        self.assertEqual(operator["repair_origin"]["task"], self.manager["id"])
        self.assertEqual(operator["budget"], schema.budget(state.CONFIG, role="operator"))
        lifecycle.fail(operator, "external decision remains")
        self.assertIsNone(spawner.next_task())
        self.assertEqual(sum(t["kind"] == "operator" for t in state.L["tasks"].values()), 1)

    def test_identical_revision_preserves_failure_budget_evidence_and_version(self):
        worker = support.queued(self.project, "failed", "Implement one slice")
        lifecycle.fail(worker, "scope too large")
        worker.update(fresh_retries=2, recovery_context="preserved evidence")
        before = copy.deepcopy(state.L)
        lifecycle.revise(worker["id"], "user", "try again", worker["brief"])
        self.assertEqual(state.L, before)
        lifecycle.revise(worker["id"], "user", "smaller scope", "Implement the first slice")
        self.assertEqual((worker["status"], worker["record_version"]), ("waiting", 2))

    def test_user_hold_stops_running_recovery_manager_and_preserves_its_session(self):
        worker = support.queued(self.project, "failed", "One slice")
        lifecycle.fail(worker, "cannot land harness edit")
        manager, _ = tasks.request_repair(worker)
        support.running(manager, "recovery-manager", worktree=False)
        manager["session"] = "existing-session"
        lifecycle.hold(worker["id"], "user")
        self.assertEqual((manager["status"], manager["session"]), ("waiting", "existing-session"))
        self.assertNotIn("recovery-manager", state.L["agents"])
        self.assertFalse(spawner.runnable(manager, {}))
        lifecycle.unhold(worker["id"], "user")
        self.assertTrue(spawner.runnable(manager, {}))

    def test_manager_holding_its_own_blocked_record_keeps_its_control_run(self):
        worker = support.queued(self.project, "failed", "One slice")
        lifecycle.fail(worker, "wrong scope")
        manager, _ = tasks.request_repair(worker)
        support.running(manager, "recovery-manager", worktree=False)
        lifecycle.hold(worker["id"], manager["id"])
        self.assertEqual(manager["status"], "running")

    def test_explicit_role_budget_override_wins_without_restoring_worker_budget_retries(self):
        with patch.dict(state.CONFIG['recovery'], role_budgets={'manager': {'generation_tokens': 456}}):
            task = tasks.create("breakdown", self.project, "explicit", "One decision", [5],
                                budget={"generation_seconds": 123})
        self.assertEqual(task["budget"]["generation_seconds"], 123)
        self.assertEqual(task["budget"]["generation_tokens"], 456)
        worker = support.queued(self.project, "worker", "One slice")
        self.assertEqual(schema.fresh_limit(state.CONFIG, worker), 0)
