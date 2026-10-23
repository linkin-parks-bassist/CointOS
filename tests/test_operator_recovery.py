import copy
import unittest
from unittest.mock import patch

from cointos import frontier, lifecycle, queues, schema, spawner, state, tasks
from tests import support


class OperatorRecovery(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        state.L["paused"] = False
        support.quiet(self)
        self.repo = support.repository(self)
        self.project = support.project(self, self.repo)
        self.enterContext(patch.object(spawner, "periodic", return_value=[]))
        self.enterContext(patch.object(spawner, "tree_work", return_value=[]))

    def blocked_manager(self):
        manager = support.queued(self.project, "broken", "Plan the intended behavior", kind="command")
        support.running(manager, "manager-1", worktree=False)
        manager["branch"] = None
        lifecycle.submit(manager["id"], "manager-1", "blocked", "planning could not resolve the contract")
        return manager, manager

    def test_blocked_planner_gets_independently_funded_control_enabled_operator(self):
        worker, manager = self.blocked_manager()
        repair = spawner.next_task()
        self.assertEqual(repair["kind"], "operator")
        self.assertEqual(repair["repair_origin"], {"task": manager["id"], "version": 1})
        self.assertEqual(repair["abilities"], list(schema.ABILITIES))
        self.assertEqual(repair["budget"], schema.budget(state.CONFIG, role="operator"))
        self.assertEqual(repair["reasoning_effort"], state.CONFIG["reasoning"]["manager"])
        self.assertNotIn("granted", state.L["agents"]["manager-1"])
        self.assertEqual(worker["receipt"]["disposition"], "blocked")

    def manager_with_handoff(self, *, dependency=None):
        manager = support.queued(self.project, 'broken', 'Plan the next boundary', kind='command')
        child = queues.add(self.project, "queued", "bounded-child", "Build one bounded repair",
                           dependency_ids=[] if dependency is None else [dependency])
        record = queues.records()[f"p:{child}"]
        record['proposed_by'] = manager['id']
        lifecycle.fail(manager, "generation budget reached")
        return manager, record

    def test_exhausted_manager_defers_operator_during_child_execution_and_review(self):
        manager, record = self.manager_with_handoff()
        child = spawner.next_task()
        self.assertEqual(child['id'], queues.key(record))
        self.assertFalse(any(t.get('repair_origin') for t in state.L['tasks'].values()))
        child.update(status='review')
        self.assertIsNone(frontier.reason(manager))
        record['done'] = {'at': 1, 'by': 'integrator'}
        child.update(status='done')
        repair, created = tasks.request_repair(manager)
        self.assertTrue(created)
        self.assertEqual(repair['repair_origin']['task'], manager['id'])
        self.assertEqual(manager['status'], 'failed', 'a handoff never accepts the manager')

    def test_handoff_does_not_hide_dead_dependencies_or_terminal_child_failure(self):
        for dependency in ('missing', 'bounded-child', 'broken'):
            with self.subTest(dependency=dependency):
                manager, record = self.manager_with_handoff(dependency=dependency)
                self.assertIsNotNone(frontier.reason(manager))
                queues.records().pop(queues.key(record))
                for name in {'p:broken', manager['id']}:
                    state.L['tasks'].pop(name, None)
                queues.records().pop('p:broken')
        manager, record = self.manager_with_handoff()
        record['held_by'] = 'user'
        self.assertIsNotNone(frontier.reason(manager))
        record['held_by'] = None
        record['revised_by'] = 'user'
        self.assertIsNotNone(frontier.reason(manager))
        record.pop('revised_by')
        child = spawner.next_task()
        lifecycle.fail(child, 'child failed')
        ordinary = spawner.next_task()
        self.assertEqual(ordinary['role'], 'operator')
        lifecycle.fail(ordinary, 'ordinary child recovery failed')
        self.assertIsNotNone(frontier.reason(manager))

    def test_queued_operator_waits_for_later_handoff_without_losing_episode(self):
        _, manager = self.blocked_manager()
        repair = spawner.next_task()
        child = queues.add(self.project, 'queued', 'later-child', 'Build one bounded repair')
        record = queues.records()[f'p:{child}']
        record['proposed_by'] = manager['id']
        self.assertFalse(spawner.runnable(repair, {}))
        record['done'] = {'at': 1, 'by': 'integrator'}
        self.assertTrue(spawner.runnable(repair, {}))
        self.assertEqual(tasks.request_repair(manager), (repair, False))
        record.pop('done')
        repair['runs'] = 1
        self.assertTrue(spawner.runnable(repair, {}), 'an already-started repair keeps its context')

    def test_repair_dedup_survives_restart_and_terminal_failure_without_recursion(self):
        _, manager = self.blocked_manager()
        repair = spawner.next_task()
        lifecycle.fail(repair, "operator exhausted its own recovery")
        saved = copy.deepcopy(state.L)
        state.L.clear()
        state.L.update(state.fresh(saved))
        self.assertIsNone(spawner.next_task())
        same, created = tasks.request_repair(state.L["tasks"][manager["id"]])
        self.assertFalse(created)
        self.assertEqual(same["id"], repair["id"])
        self.assertEqual(sum(t["kind"] == "operator" for t in state.L["tasks"].values()), 1)

    def test_changed_assignment_can_have_a_new_recovery_episode(self):
        worker, manager = self.blocked_manager()
        old = spawner.next_task()
        record = queues.records()[worker["record"]]
        queues.revise(record, "Corrected assignment")
        worker.update(record_version=record["version"], status="failed")
        manager.update(record_version=record["version"])
        new, created = tasks.request_repair(manager)
        self.assertTrue(created)
        self.assertNotEqual(new["id"], old["id"])
        self.assertEqual(new["repair_origin"]["version"], 2)

    def test_taskless_unknown_dependency_and_cycle_get_repair_without_fake_worker(self):
        for name, brief in (("unknown", "Depends on: absent\nResolve the missing edge"),
                            ("cycle", "Depends on: cycle\nResolve the cycle")):
            queues.add(self.project, "queued", name, brief)
        spawner.refresh()
        operators = [t for t in state.L["tasks"].values() if t["kind"] == "operator"]
        self.assertEqual({t["repair_origin"]["task"] for t in operators}, {"p:unknown", "p:cycle"})
        self.assertNotIn("p:unknown", state.L["tasks"])
        self.assertNotIn("p:cycle", state.L["tasks"])

    def test_ordinary_dependency_wait_does_not_summon_operator(self):
        queues.add(self.project, "queued", "base", "Build base")
        queues.add(self.project, "queued", "after", "Depends on: base\nUse base")
        spawner.refresh()
        self.assertFalse(state.L["tasks"])

    def test_infrastructure_hold_gets_repair_but_explicit_hold_does_not(self):
        worker = support.queued(self.project, "broken")
        worker["admission_hold"] = "repeated infrastructure launch failure"
        repair = spawner.next_task()
        self.assertEqual(repair["repair_origin"]["task"], worker["id"])
        worker["admission_hold"] = "killed by user"
        self.assertFalse(spawner.runnable(repair, {}))

    def test_pause_disabled_project_and_record_hold_prevent_creation(self):
        _, manager = self.blocked_manager()
        state.L["paused"] = True
        self.assertEqual(tasks.request_repair(manager), (None, False))
        state.L["paused"] = False
        self.project["enabled"] = False
        self.assertEqual(tasks.request_repair(manager), (None, False))
        self.project["enabled"] = True
        queues.records()[manager["record"]]["held_by"] = "user"
        self.assertEqual(tasks.request_repair(manager), (None, False))

    def test_queued_repair_respects_later_hold_and_obsolete_version(self):
        worker, manager = self.blocked_manager()
        repair = spawner.next_task()
        record = queues.records()[worker["record"]]
        record["held_by"] = "user"
        self.assertFalse(spawner.runnable(repair, {}))
        record["held_by"] = None
        queues.revise(record, "Now repairable")
        self.assertFalse(spawner.runnable(repair, {}))
        self.assertEqual(tasks.request_repair(manager), (repair, False))
        repair["runs"] = 1
        record["revised_by"] = repair["id"]
        self.assertTrue(spawner.runnable(repair, {}), "an interrupted repair can hand back after its own progress")

    def test_exhausted_gardener_and_scout_also_get_nonrecursive_repair(self):
        for kind in ("garden", "steward"):
            source = tasks.create(kind, tasks.SYSTEM, kind, "Inspect this runtime concern", [6])
            lifecycle.fail(source, "ordinary recovery exhausted")
            repair, created = tasks.request_repair(source)
            self.assertTrue(created)
            self.assertIsNone(repair["branch"])
            self.assertEqual(repair["repair_origin"]["task"], source["id"])
            self.assertEqual(tasks.request_repair(repair), (None, False))

    def test_cancelled_sources_and_removed_projects_do_not_trigger_repair(self):
        _, manager = self.blocked_manager()
        manager["cancelled"] = "user withdrew this concern"
        self.assertEqual(tasks.request_repair(manager), (None, False))
        manager.pop("cancelled")
        with patch.dict(state.CONFIG, projects=[]):
            self.assertEqual(tasks.request_repair(manager), (None, False))
        queues.records().pop(manager["record"])
        self.assertEqual(tasks.request_repair(manager), (None, False))

    def test_newer_maintenance_and_scout_attempt_supersedes_old_failures(self):
        for kind in ("garden", "tree-audit", "steward", "test-audit"):
            old = tasks.create(kind, tasks.SYSTEM, kind, "Old concern", [6])
            lifecycle.fail(old, "old unsuccessful attempt")
            current = tasks.create(kind, tasks.SYSTEM, kind, "Current concern", [6])
            self.assertEqual(tasks.request_repair(old), (None, False))
            current.update(status="done", receipt={"disposition": "complete"})
            self.assertEqual(tasks.request_repair(old), (None, False))
            self.assertEqual(tasks.request_repair(current), (None, False))


if __name__ == "__main__":
    unittest.main()
