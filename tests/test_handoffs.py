"""Managers finish bounded stages; proposals come from running tasks within their role's rights;
stewards and test auditors rediscover concrete loose ends on their own cadence."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import api, cli, lifecycle, opencode, prompts, queues, schema, spawner, state, tasks
from tests import support


class Handoffs(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))
        state.L["cadence"]["steward:system"] = state.now()
        self.task = support.running(support.queued(self.project, "build", "Plan the product", kind="command"), "manager-1")

    def finish(self, outcome, detail, run="manager-1"):
        return lifecycle.submit(self.task["id"], run, outcome, detail)

    def test_a_stage_completes_while_its_queued_children_continue(self):
        api.dispatch("queue", {"project": "p", "kind": "queued", "name": "tests", "brief": "Write tests",
                               "proposed_by": self.task["id"], "run": "manager-1"})
        receipt = self.finish("complete", "Plan committed and tests queued")
        self.assertEqual((receipt["run"], receipt["disposition"]), ("manager-1", "complete"))
        self.assertEqual(receipt["evidence"]["commit"], support.git.head(self.task["worktree"]))
        self.assertEqual((self.task["status"], self.task["agent"]), ("done", None))
        self.assertEqual((state.L["queue"]["p:build"]["status"], state.L["queue"]["p:tests"]["status"]), ("done", "queued"))
        self.assertEqual(state.L["queue"]["p:tests"]["proposed_by"], self.task["id"])

    def test_a_disposition_must_suit_the_kind_without_mutation(self):
        with self.assertRaisesRegex(ValueError, "complete or blocked"):
            self.finish("continue", "Wait for tests")
        self.assertEqual((self.task["status"], self.task["receipt"]), ("running", None))
        self.assertEqual(state.L["queue"]["p:build"]["status"], "queued")

    def test_a_blocker_is_explicit(self):
        self.finish("blocked", "Need an external decision")
        self.assertEqual((state.L["queue"]["p:build"]["status"], state.L["queue"]["p:build"]["report"]),
                         ("blocked", "Need an external decision"))
        self.assertTrue(state.L["alerts"])

    def test_an_unlanded_plan_cannot_finish(self):
        support.commit(self.task["worktree"], "unlanded plan")
        with self.assertRaisesRegex(ValueError, "land your committed branch"):
            self.finish("complete", "Plan is done")
        self.assertEqual((self.task["status"], self.task["receipt"]), ("running", None))

    def test_a_finished_task_can_no_longer_propose(self):
        self.finish("complete", "Nothing left to queue")
        with self.assertRaisesRegex(ValueError, "current run"):
            api.dispatch("queue", {"project": "p", "kind": "queued", "name": "later", "brief": "Later",
                                   "proposed_by": self.task["id"], "run": "manager-1"})

    def running_as(self, kind, role_task_name="role"):
        task = tasks.create(kind, tasks.SYSTEM if schema.KINDS[kind]["scope"] == "system" else self.project,
                            role_task_name, "b", [6], worker=None)
        return support.running(task, f"{kind}-run", worktree=False)

    def propose(self, by, kind, name, project="p"):
        return api.dispatch("queue", {"project": project, "kind": kind, "name": name, "brief": "A concrete concern",
                                      "proposed_by": by["id"], "run": by["agent"]})

    def test_stewards_and_test_auditors_propose_only_manager_commands_in_any_project(self):
        other = {**self.project, "name": "q"}
        state.CONFIG["projects"].append(other)
        for kind in ("steward", "test-audit"):
            with self.subTest(kind=kind):
                by = self.running_as(kind)
                self.propose(by, "command", f"concern-{kind}", project="q")
                self.assertEqual(state.L["queue"][f"q:concern-{kind}"]["proposed_by"], by["id"])
                with self.assertRaisesRegex(ValueError, "scout/auditor"):
                    self.propose(by, "queued", f"implementation-{kind}")

    def test_an_integrator_proposes_one_same_project_command_kind(self):
        integrator = self.running_as("integrate", "integrate-x")
        self.propose(integrator, "command", "follow-up")
        with self.assertRaisesRegex(ValueError, "manager/integrator"):
            self.propose(integrator, "queued", "code")

    def test_a_proposal_must_come_from_the_proposing_tasks_current_run(self):
        with self.assertRaisesRegex(ValueError, "current run"):
            api.dispatch("queue", {"project": "p", "kind": "queued", "name": "x", "brief": "X",
                                   "proposed_by": self.task["id"], "run": "someone-else"})

    def test_scout_attention_becomes_a_coin_alert(self):
        steward = self.running_as("steward")
        api.dispatch("attention", {"proposed_by": steward["id"], "run": steward["agent"],
                                   "message": "Choose the recovery boundary"})
        self.assertIn("Choose the recovery boundary", state.L["alerts"][-1]["text"])
        with self.assertRaisesRegex(ValueError, "running scout or test auditor"):
            api.dispatch("attention", {"proposed_by": self.task["id"], "run": "manager-1", "message": "Hi"})

    def test_agent_commands_act_as_their_run(self):
        with patch.dict(os.environ, COINTOS_TASK_ID=self.task["id"], COINTOS_AGENT="manager-1"):
            self.assertEqual(cli.proposal({"x": 1}), {"x": 1, "proposed_by": self.task["id"], "run": "manager-1"})
        environment = opencode.environment(Path("/tmp/run"), {"task": {"id": "system:loose-ends-1"}})
        self.assertEqual(environment["COINTOS_TASK_ID"], "system:loose-ends-1")

    def test_a_long_paused_run_is_reoriented_toward_its_receipt(self):
        steward = tasks.create("steward", tasks.SYSTEM, "loose-ends", "Look", [6])
        steward["session"] = "session"
        steward["interrupted_at"] = 1000
        text = prompts.launch_text(steward, tasks.SYSTEM, at=1000 + prompts.REORIENT_AFTER_SECONDS)
        self.assertIn("its receipt", text)
        self.assertNotIn("plain-text final summary", text)

    def test_every_assignment_names_its_receipt(self):
        tree = {"name": "p", "path": self.project["path"], "main_branch": "main", "tree": ".knowledge"}
        for kind in schema.KINDS:
            with self.subTest(kind=kind):
                where = tasks.SYSTEM if schema.KINDS[kind]["scope"] == "system" else \
                    tree if schema.KINDS[kind]["scope"] == "tree" else self.project
                if schema.KINDS[kind]["record"]:
                    queues.add(self.project, "queued", f"item-{kind}", "b")
                task = tasks.create(kind, where, f"item-{kind}", "b", [1], item=f"item-{kind}" if schema.KINDS[kind]["record"] else None,
                                    worker="p:x", abilities=["standard"])
                self.assertIn("cointos finish --blocked", prompts.launch_text(task, where))


class PeriodicSteward(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        repo = support.repository(self)
        self.projects = [{"name": name, "path": str(repo), "main_branch": "main", "priority": 100, "enabled": True}
                         for name in ("p", "q")]
        self.enterContext(patch.dict(state.CONFIG, projects=self.projects, trees=[]))

    def test_one_global_cadence_spawns_a_steward_not_one_per_project(self):
        with patch.dict(state.CONFIG, spawner={**state.CONFIG["spawner"], "steward_every_seconds": 1}):
            task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"], task["place"], task["branch"]), ("steward", "steward", "system", None))
        self.assertEqual(task["worktree"], str(tasks.SYSTEM["path"]))
        self.assertIn("all configured projects (p, q)", task["brief"])
        self.assertEqual(sum(t["kind"] == "steward" for t in state.L["tasks"].values()), 1)
        text = prompts.launch_text(task, tasks.SYSTEM)
        self.assertNotIn("cointos merge", text)
        self.assertIn("system task with no project, branch or worktree", text)

    def test_a_manual_scout_request_is_immediate_and_deduplicated(self):
        first, second = api.dispatch("scout", {}), api.dispatch("scout", {})
        self.assertEqual((first["created"], second["created"], first["task"]), (True, False, second["task"]))
        task = state.L["tasks"][first["task"]]
        self.assertEqual((task["kind"], task["status"], task["place"]), ("steward", "waiting", "system"))
        self.assertGreater(tasks.last_created("steward", "system"), 0)

    def test_the_cadence_backs_off_with_active_or_queued_concerns(self):
        state.L["cadence"]["steward:system"] = state.now() - 15
        queues.add(self.projects[0], "queued", "work", "Work")
        with patch.dict(state.CONFIG, spawner={**state.CONFIG["spawner"], "steward_every_seconds": 10}):
            self.assertEqual(spawner.next_task()["id"], "p:work", "one concern doubles the interval to 20 seconds")

    def test_a_failed_command_blocks_its_record_and_does_not_suppress_the_steward(self):
        state.L["cadence"]["steward:system"] = state.now() - 11
        dead = support.queued(self.projects[0], "dead", "Old", kind="command")
        dead["status"] = "failed"
        with patch.dict(state.CONFIG, spawner={**state.CONFIG["spawner"], "steward_every_seconds": 10}):
            task = spawner.next_task()
        self.assertEqual(task["kind"], "steward")
        self.assertEqual(state.L["queue"]["p:dead"]["status"], "blocked")
        self.assertIn("Task failed", state.L["queue"]["p:dead"]["report"])

    def test_the_test_auditor_follows_recent_accepted_work_once(self):
        state.L["cadence"]["steward:system"] = state.now()
        support.queued(self.projects[0], "item")["status"] = "done"
        with patch.dict(state.CONFIG, spawner={**state.CONFIG["spawner"], "test_auditor_every_seconds": 1}):
            task = spawner.next_task()
            self.assertEqual((task["kind"], task["role"], task["place"]), ("test-audit", "test-auditor", "system"))
            self.assertIn("p:item", task["brief"])
            task["status"] = "done"
            self.assertIsNone(spawner.next_task())


if __name__ == "__main__":
    unittest.main()
