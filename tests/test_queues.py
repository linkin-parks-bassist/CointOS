import copy
import unittest

from cointos import api, lifecycle, queues, spawner, state, tasks
from tests import support


class Depends(unittest.TestCase):
    def test_the_depends_on_line(self):
        self.assertEqual(queues.depends("Depends on: `core`, docs\n\nBrief."), ["core", "docs"])

    def test_placeholders_and_sentence_punctuation_name_nothing(self):
        self.assertEqual(queues.depends("Depends on: none."), [])
        self.assertEqual(queues.depends("Depends on: (none)"), [])
        self.assertEqual(queues.depends("Depends on: [core]"), ["core"])
        self.assertEqual(queues.depends("Depends on: `core`, docs., core"), ["core", "docs"])

    def test_no_line_no_dependencies(self):
        self.assertEqual(queues.depends("It depends on nothing in particular."), [])


class Queue(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.repo = support.repository(self)
        self.project = support.project(self, self.repo)
        state.L["cadence"]["steward:system"] = state.now()

    def add(self, name, brief=None, kind="queued"):
        queues.add(self.project, kind, name, brief or name.upper())
        return queues.records()[f"p:{name}"]

    def failed(self, name, brief=None):
        """A record whose worker item failed: it awaits its one recovery controller."""
        record = self.add(name, brief)
        task = tasks.create("item", self.project, name, record["brief"], [4], item=name, record_version=record["version"])
        lifecycle.fail(task, "worker gave up")
        return record

    def stuck(self, name, brief=None):
        """A failed item whose controller also gave up: blocked at this assignment version."""
        record = self.failed(name, brief)
        manager, _ = tasks.request_repair(state.L["tasks"][queues.key(record)])
        lifecycle.fail(manager, "manager gave up")
        return record


class State(Queue):
    """Where a record stands is derived from its tasks; only `done` is stored."""

    def test_a_new_record_is_queued(self):
        self.assertEqual(queues.state(self.add("a")), {"status": "queued", "blocker": None, "recoverable": False})

    def test_a_failed_item_awaits_its_manager_then_a_failed_manager_blocks_it(self):
        record = self.failed("a")
        found = queues.state(record)
        self.assertEqual((found["status"], found["recoverable"]), ("blocked", True))
        self.assertIn("worker gave up", found["blocker"])
        self.stuck("b")
        found = queues.state(queues.records()["p:b"])
        self.assertEqual((found["status"], found["recoverable"], found["blocker"]), ("blocked", False, "manager gave up"))

    def test_a_revision_makes_the_failed_task_history(self):
        record = self.failed("a")
        queues.revise(record, "A, but smaller.")
        self.assertEqual((queues.status(record), record["version"]), ("queued", 2))

    def test_done_and_replaced_are_terminal(self):
        record = self.add("a")
        queues.finish(record, commit="abc")
        self.assertEqual(queues.status(record), "done")
        self.assertEqual(queues.landed("p"), {"a"})
        self.add("b")
        replaced = self.failed("c")
        queues.replace(replaced, ["b"], "smaller")
        self.assertEqual(queues.status(replaced), "replaced")

    def test_the_served_view_carries_each_records_state(self):
        self.failed("a")
        view = queues.view()["p:a"]
        self.assertEqual((view["status"], view["recoverable"]), ("blocked", True))
        self.assertNotIn("status", queues.records()["p:a"], "the stored record holds no state")

    def test_new_queue_record_cannot_claim_existing_maintenance_task_identity(self):
        for kind, base in (("garden", "garden"), ("tree-audit", "tree-audit")):
            with self.subTest(kind=kind):
                maintenance = tasks.create(kind, self.project, base, "Maintain the owned tree", [6])
                name = maintenance["id"].partition(":")[2]
                with self.assertRaisesRegex(ValueError, "already|used|task|identity"):
                    self.add(name, "A new product assignment")
                self.assertNotIn(maintenance["id"], queues.records())
                self.assertIs(state.L["tasks"][maintenance["id"]], maintenance)

    def test_identical_queue_retry_and_revision_reuse_their_owned_task_identity(self):
        worker = support.queued(self.project, "owned", "Original concern")
        record = queues.records()[worker["record"]]
        before = copy.deepcopy(record)
        self.assertEqual(queues.add(self.project, "queued", "owned", "Original concern"), "owned")
        self.assertEqual(record, before)
        lifecycle.revise(worker["id"], "user", "Corrected the concern", "Corrected assignment")
        self.assertEqual(record["version"], 2)
        self.assertIs(queues.current(record), worker)
        self.assertEqual((worker["id"], worker["brief"], worker["record_version"]),
                         ("p:owned", "Corrected assignment", 2))
        self.assertEqual(queues.add(self.project, "queued", "owned", "Corrected assignment"), "owned")

    def test_cancelled_task_history_cannot_be_requeued_as_a_fresh_version_one(self):
        worker = support.queued(self.project, "old", "Old concern")
        lifecycle.cancel([worker["record"]], "user", "User withdrew the old concern")
        self.assertNotIn(worker["record"], queues.records())
        self.assertTrue(worker.get("cancelled"))
        with self.assertRaisesRegex(ValueError, "already|used|task|identity"):
            self.add("old", "Different new concern")
        self.assertNotIn(worker["record"], queues.records())
        self.assertIs(state.L["tasks"][worker["id"]], worker)


class Readiness(Queue):
    """An item is ready once the daemon confirms its prerequisites are done."""

    def ready(self):
        return queues.readiness(queues.live("p"), queues.landed("p"))

    def test_an_item_waits_until_what_it_depends_on_is_done(self):
        core, _ = self.add("core"), self.add("rest", "Depends on: core\nRest")
        self.assertEqual(self.ready(), {"core": "ready", "rest": "waiting"})
        queues.finish(core)
        self.assertEqual(self.ready(), {"rest": "ready"})

    def test_an_unknown_dependency_is_a_problem(self):
        self.add("x", "Depends on: nosuch\nX")
        self.assertIn("unknown", self.ready()["x"])

    def test_a_blocked_dependency_is_a_problem(self):
        self.stuck("a")
        self.add("b", "Depends on: a\nB")
        self.assertIn("blocked", self.ready()["b"])

    def test_dependency_alert_survives_restart_and_rearms_after_resolution(self):
        record = self.add("b", "Depends on: missing\nB")
        spawner.refresh()
        alerts = copy.deepcopy(state.L["alerts"])
        restarted = state.fresh(copy.deepcopy(state.L))
        state.L.clear()
        state.L.update(restarted)
        record = queues.records()["p:b"]
        spawner.refresh()
        self.assertEqual(state.L["alerts"], alerts)
        queues.revise(record, "B without prerequisites.")
        spawner.refresh()
        self.assertEqual(state.L["dependency_problems"], {})
        queues.revise(record, "Depends on: missing\nB")
        spawner.refresh()
        self.assertEqual(len(state.L["alerts"]), len(alerts) + 1)

    def test_a_cycle_is_a_problem(self):
        self.add("a", "Depends on: b\nA")
        self.add("b", "Depends on: a\nB")
        self.assertIn("cycle", self.ready()["a"])
        self.assertIn("cycle", self.ready()["b"])

    def test_a_dependency_awaiting_recovery_keeps_dependents_waiting(self):
        self.failed("a")
        self.add("b", "Depends on: a\nB")
        self.assertEqual(self.ready()["b"], "waiting")


class Admission(Queue):
    """Queue order is priority, and a failed worker item dispatches one controller."""

    def test_the_first_entry_runs_first(self):
        self.add("urgent", "Now.")
        self.add("later", "Later.")
        self.assertEqual(spawner.next_task()["id"], "p:urgent")

    def test_a_failed_item_dispatches_a_controller_once(self):
        self.failed("big", "Big.")
        self.add("after", "Depends on: big\n\nAfter.")
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"], task["item"], task["record"]), ("operator", "operator", "big", None))
        self.assertIn("worker gave up", task["brief"])
        self.assertEqual(state.L["dependency_problems"], {}, "its dependent waits instead of alerting")
        task["status"] = "running"
        self.assertIsNone(spawner.next_task())

    def test_the_user_reorders_a_project_queue(self):
        for name in ("a", "b", "c"):
            self.add(name)
        order = lambda: [r["item"] for r in sorted(state.L["queue"].values(), key=lambda r: r["priority"])]
        self.assertEqual(api.dispatch("move", {"item": "p:c", "to": "up"})["position"], 1)
        self.assertEqual(order(), ["a", "c", "b"])
        api.dispatch("move", {"item": "p:b", "to": "top"})
        self.assertEqual(order(), ["b", "a", "c"])
        api.dispatch("move", {"item": "p:b", "to": "bottom"})
        self.assertEqual(order(), ["a", "c", "b"])
        with self.assertRaisesRegex(ValueError, "move must be"):
            api.dispatch("move", {"item": "p:a", "to": "sideways"})

    def test_a_brief_carries_its_summary_and_agents_must_write_one(self):
        self.assertEqual(self.add("plain", "Do it.\nSummary: Explains the task in five words.")["summary"],
                         "Explains the task in five words.")
        self.assertIsNone(self.add("ask", "Decide something.", "command")["summary"], "commands and user briefs may omit it")
        for brief in ("Do it.", "Do it.\nSummary: Too short.", "Summary: " + "word " * 21):
            with self.subTest(brief=brief), self.assertRaisesRegex(ValueError, "Summary"):
                queues.require_summary(brief)

    def test_a_test_contract_brief_must_name_what_it_relies_on(self):
        with self.assertRaisesRegex(ValueError, "Relies on"):
            queues.add(self.project, "queued", "tests", "Test parse.", "test-contract")
        self.assertEqual(queues.relies_on("Depends on: x\nRelies on: `src/a.h::pigen_a`, src/b.c\n"),
                         ["src/a.h::pigen_a", "src/b.c"])

    def test_a_brief_relying_on_absent_apis_is_refused_before_any_run_and_goes_to_a_manager(self):
        (self.repo / "api.h").write_text("int pigen_present(void);\nint pigen_presently(void);\n")
        support.commit(self.repo, "api")
        queues.add(self.project, "queued", "bad", "Relies on: pigen_present, pigen_pres, other.h::pigen_presently, nope.h\nTest.",
                   "test-contract")
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["item"]), ("operator", "bad"), "the refused item's manager runs next")
        refused = state.L["tasks"]["p:bad"]
        self.assertEqual((refused["status"], refused["runs"]), ("failed", 0), "no worker run was spent")
        found = queues.state(state.L["queue"]["p:bad"])
        self.assertEqual((found["status"], found["recoverable"]), ("blocked", True))
        self.assertIn("pigen_pres, nope.h, absent on main", found["blocker"])

    def test_a_brief_relying_on_present_apis_dispatches(self):
        (self.repo / "api.h").write_text("int pigen_present(void);\n")
        support.commit(self.repo, "api")
        queues.add(self.project, "queued", "good",
                   "Relies on: pigen_present., `wrong/file.c::pigen_present`; , `api.h`.\nTest.", "test-contract")
        self.assertEqual(spawner.next_task()["id"], "p:good")

    def test_api_queue_is_durable_on_restart_and_never_writes_project(self):
        api.dispatch("queue", {"project": "p", "kind": "queued", "name": "core", "brief": "Build core"})
        api.dispatch("queue", {"project": "p", "kind": "queued", "name": "ui", "brief": "Depends on: core\nBuild UI"})
        self.assertEqual(support.git.run(self.repo, "status", "--porcelain"), "")
        core = spawner.next_task()
        self.assertEqual(core["id"], "p:core")
        core["status"] = "review"
        integration = spawner.next_task()
        self.assertEqual((integration["id"], integration["worker"]), ("p:integrate-core-1", "p:core"))
        queues.finish(state.L["queue"]["p:core"], commit="abc")
        core["status"] = integration["status"] = "done"
        restored = state.fresh(copy.deepcopy(state.L))
        self.assertEqual(restored["queue"]["p:core"]["done"]["commit"], "abc")
        self.assertEqual(spawner.next_task()["id"], "p:ui")

    def test_command_dispatch_and_retry_deduplication(self):
        body = {"project": "p", "kind": "command", "name": "plan", "brief": "Plan the next stage"}
        api.dispatch("queue", body)
        api.dispatch("queue", body)
        self.assertEqual(len(state.L["queue"]), 1)
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"], task["stage"]), ("breakdown", "manager", None))
        self.assertNotIn("CointOS", task["worktree"])

    def test_a_completed_command_is_done_and_a_blocked_one_is_blocked(self):
        for name in ("plan", "stuck"):
            self.add(name, "Plan.", "command")
        for name, outcome in (("plan", "complete"), ("stuck", "blocked")):
            task = spawner.next_task()
            self.assertEqual(task["item"], name)
            support.running(task, f"m-{name}", worktree=False)
            task["branch"] = None
            lifecycle.submit(task["id"], f"m-{name}", outcome, "Planned" if outcome == "complete" else "Needs the user")
        self.assertEqual(queues.status(queues.records()["p:plan"]), "done")
        self.assertEqual(queues.state(queues.records()["p:stuck"])["blocker"], "Needs the user")

    def test_replacement_repoints_dependents_and_marks_the_item_replaced(self):
        self.failed("big", "Big")
        self.add("after", "Depends on: big\nAfter")
        self.add("small", "Small")
        task = spawner.next_task()
        with self.assertRaisesRegex(ValueError, "not running"):
            api.dispatch("replace", {"caller": support.caller(task, "someone"), "children": ["small"]})
        support.running(task, "manager-1")
        result = api.dispatch("replace", {"caller": support.caller(task, "manager-1"), "children": ["small"]})
        self.assertEqual(state.L["queue"]["p:after"]["depends"], ["small"])
        self.assertEqual(queues.status(state.L["queue"]["p:big"]), "replaced")
        self.assertEqual((task['status'], result['receipt']['disposition']), ('done', 'complete'))
        self.assertEqual(queues.landed("p"), set(), "replaced, never accepted")

    def test_a_child_naming_its_parent_inherits_the_parents_dependencies(self):
        self.add("base", "Base")
        self.failed("big", "Depends on: base\nBig")
        for name, brief in (("after", "Depends on: big\nAfter"), ("a", "Depends on: big\nA"), ("b", "Depends on: a\nB")):
            self.add(name, brief)
        queues.replace(queues.records()["p:big"], ["a", "b"], "split")
        self.assertEqual(state.L["queue"]["p:a"]["depends"], ["base"])
        self.assertEqual(state.L["queue"]["p:b"]["depends"], ["a"])
        self.assertEqual(state.L["queue"]["p:after"]["depends"], ["a", "b"])

    def test_replacement_keeps_dependency_metadata_and_dispatched_briefs_consistent(self):
        queues.finish(self.add("base"))
        parent = self.failed("big", "Depends on: base\nBig")
        child = self.add("small", "Summary: Implements a smaller slice of the requested behavior.\n"
                         "**Depends on:** `big`\nRelies on: existing_api\nKeep this narrative.")
        after = self.add("after", "Depends on: big\nAfter")
        changed = queues.replace(parent, ["small"], "split")
        self.assertEqual(set(changed), {"p:small", "p:after"})
        self.assertEqual(child["version"], 2)
        self.assertEqual(queues.depends(child["brief"]), ["base"])
        self.assertIn("Relies on: existing_api\nKeep this narrative.", child["brief"])
        worker = spawner.dispatch("item", self.project, child, [4])
        self.assertEqual((worker["brief"], worker["record_version"]), (child["brief"], 2))
        queues.revise(after, after["brief"])
        self.assertEqual(after["depends"], ["small"])
        self.assertEqual(queues.readiness(queues.live("p"), queues.landed("p"))["after"], "waiting")

    def test_replacement_preserves_terminal_history_and_explicit_holds(self):
        parent = self.failed("big")
        self.add("small")
        accepted = self.add("old", "Depends on: big\nOld")
        queues.finish(accepted)
        held = self.add("after", "Depends on: big\nAfter")
        held["held_by"] = "user"
        before = copy.deepcopy(accepted)
        self.assertEqual(queues.replace(parent, ["small"], "split"), ["p:after"])
        self.assertEqual(accepted, before)
        self.assertEqual(held["held_by"], "user")

    def test_replacement_preflight_rejection_changes_no_records(self):
        parent = self.failed("big")
        self.add("small")
        self.add("after", "Depends on: big\nAfter")
        before = copy.deepcopy(queues.records())

        def reject(changed):
            self.assertEqual(changed, ["p:after"])
            raise ValueError("an integration is reviewing the affected assignment")

        with self.assertRaisesRegex(ValueError, "integration"):
            queues.replace(parent, ["small"], "split", preflight=reject)
        self.assertEqual(queues.records(), before)

    def test_the_user_supersedes_blocked_work_without_accepting_it(self):
        self.stuck("old")
        self.add("new", "New")
        self.add("after", "Depends on: old\nAfter")
        api.dispatch("supersede", {"task": "p:old", "replacements": ["new"], "reason": "a better plan"})
        self.assertEqual(state.L["queue"]["p:after"]["depends"], ["new"])
        self.assertEqual(state.L["tasks"]["p:old"]["replaced_by"], ["new"])
        with self.assertRaisesRegex(ValueError, "only blocked work"):
            api.dispatch("supersede", {"task": "p:new", "replacements": ["after"], "reason": "no"})

    def test_clear_history_keeps_only_terminal_records_needed_by_live_work(self):
        queues.finish(self.add("old"))
        queues.finish(self.add("needed"))
        self.add("next", "Depends on: needed\n\nNext.")
        self.stuck("dead")
        self.assertEqual(set(queues.clear_history(set())), {"p:old", "p:dead"})
        self.assertEqual(set(state.L["queue"]), {"p:needed", "p:next"})


if __name__ == "__main__":
    unittest.main()
