import copy
import unittest

from cointos import api, lifecycle, queues, spawner, state
from tests import support


def item(name, status="queued", depends=(), decompose=False):
    return {"item": f"what/is/the/queued/{name}.md", "status": status, "depends": list(depends), "decompose": decompose}


class Depends(unittest.TestCase):
    def test_the_depends_on_line(self):
        text = "---\nstatus: green\n---\nStatus: queued\n\nDepends on: `what/is/the/queued/core.md`, docs\n\nBrief."
        self.assertEqual(queues.depends(text), ["what/is/the/queued/core.md", "docs"])

    def test_no_line_no_dependencies(self):
        self.assertEqual(queues.depends("Status: queued\n\nIt depends on nothing in particular."), [])


class Readiness(unittest.TestCase):
    """An item is ready once the daemon confirms its prerequisites are accepted."""

    def test_an_item_waits_until_what_it_depends_on_has_landed(self):
        items = [item("core"), item("rest", depends=["what/is/the/queued/core.md"])]
        self.assertEqual(queues.readiness(items, set()),
                         {"what/is/the/queued/core.md": "ready", "what/is/the/queued/rest.md": "waiting"})
        landed = {"what/is/the/queued/core.md"}
        self.assertEqual(queues.readiness(items[1:], landed), {"what/is/the/queued/rest.md": "ready"})

    def test_bare_names_resolve_and_chains_hold(self):
        items = [item("b", depends=["a"]), item("c", depends=["b"])]
        ready = queues.readiness(items, {"what/is/the/queued/a.md"})
        self.assertEqual(ready["what/is/the/queued/b.md"], "ready")
        self.assertEqual(ready["what/is/the/queued/c.md"], "waiting")

    def test_an_unknown_dependency_is_a_problem(self):
        self.assertIn("unknown", queues.readiness([item("x", depends=["nosuch"])], set())["what/is/the/queued/x.md"])

    def test_a_blocked_dependency_is_a_problem(self):
        ready = queues.readiness([item("a", "blocked"), item("b", depends=["a"])], set())
        self.assertIn("blocked", ready["what/is/the/queued/b.md"])

    def test_a_cycle_is_a_problem(self):
        ready = queues.readiness([item("a", depends=["b"]), item("b", depends=["a"])], set())
        self.assertIn("cycle", ready["what/is/the/queued/a.md"])
        self.assertIn("cycle", ready["what/is/the/queued/b.md"])

    def test_a_dependency_awaiting_decomposition_keeps_dependents_waiting(self):
        ready = queues.readiness([item("a", "blocked", decompose=True), item("b", depends=["a"])], set())
        self.assertEqual(ready["what/is/the/queued/b.md"], "waiting")


class Admission(unittest.TestCase):
    """Queue order is priority, and a worker's decomposition request dispatches a manager."""

    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.repo = support.repository(self)
        self.project = support.project(self, self.repo)
        state.L["cadence"]["steward:system"] = state.now()

    def queue(self, *entries):
        for name, brief, status, report in entries:
            queues.add(self.project, "queued", name, brief)
            if status != "queued":
                queues.update("p", name, status, report)

    def test_the_first_entry_runs_first(self):
        self.queue(("urgent", "Now.", "queued", ""), ("later", "Later.", "queued", ""))
        self.assertEqual(spawner.next_task()["id"], "p:urgent")

    def test_needs_decomposition_dispatches_a_manager_once(self):
        self.queue(("big", "Big.", "blocked", "Status: blocked\n\nNeeds decomposition: split lexing from parsing."),
                   ("after", "Depends on: big\n\nAfter.", "queued", ""))
        queues.update("p", "big", "blocked", "Split lexing from parsing", decompose=True)
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"], task["item"], task["record"]), ("decompose", "manager", "big", "p:big"))
        self.assertEqual(state.L["dependency_problems"], {}, "its dependent waits instead of alerting")
        task["status"] = "running"
        self.assertIsNone(spawner.next_task())

    def test_api_queue_is_durable_on_restart_and_never_writes_project(self):
        api.dispatch("queue", {"project": "p", "kind": "queued", "name": "core", "brief": "Build core"})
        api.dispatch("queue", {"project": "p", "kind": "queued", "name": "ui", "brief": "Depends on: core\nBuild UI"})
        self.assertEqual(support.git.run(self.repo, "status", "--porcelain"), "")
        core = spawner.next_task()
        self.assertEqual(core["id"], "p:core")
        core["status"] = "review"
        integration = spawner.next_task()
        self.assertEqual((integration["id"], integration["worker"]), ("p:integrate-core-1", "p:core"))
        queues.update("p", "core", "done")
        core["status"] = integration["status"] = "done"
        restored = state.fresh(copy.deepcopy(state.L))
        self.assertEqual(restored["queue"]["p:core"]["status"], "done")
        self.assertEqual(spawner.next_task()["id"], "p:ui")

    def test_acceptance_reconciles_a_stale_blocked_queue_record(self):
        worker = support.queued(self.project, "stale")
        queues.update("p", "stale", "blocked", "Status: blocked\n\nOld attempt")
        worker.update(status="done", acceptance={"commit": "abc", "worker_commit": "def", "via": "landing"})
        _, _, changed = spawner.refresh()
        record = state.L["queue"]["p:stale"]
        self.assertTrue(changed)
        self.assertEqual((record["status"], record["commit"]), ("done", "abc"))
        self.assertNotIn("report", record)

    def test_command_dispatch_and_retry_deduplication(self):
        body = {"project": "p", "kind": "command", "name": "plan", "brief": "Plan the next stage"}
        api.dispatch("queue", body)
        api.dispatch("queue", body)
        self.assertEqual(len(state.L["queue"]), 1)
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"], task["stage"]), ("breakdown", "manager", None))
        self.assertNotIn("CointOS", task["worktree"])

    def test_replacement_repoints_dependents_and_the_receipt_retires_the_item(self):
        for name, brief in (("big", "Big"), ("after", "Depends on: big\nAfter"), ("small", "Small")):
            queues.add(self.project, "queued", name, brief)
        queues.update("p", "big", "blocked", "Split the scope", decompose=True)
        task = spawner.next_task()
        with self.assertRaisesRegex(ValueError, "running decomposition manager"):
            api.dispatch("replace", {"task": task["id"], "run": "someone", "children": ["small"]})
        support.running(task, "manager-1")
        api.dispatch("replace", {"task": task["id"], "run": "manager-1", "children": ["small"]})
        self.assertEqual(state.L["queue"]["p:after"]["depends"], ["small"])
        self.assertEqual(queues.landed(self.project), set(), "replaced, not settled")
        lifecycle.submit(task["id"], "manager-1", "complete", "Split into small")
        self.assertEqual(queues.landed(self.project), {"big"})

    def test_clear_history_keeps_only_terminal_records_needed_by_live_work(self):
        self.queue(("old", "Old.", "done", ""), ("needed", "Needed.", "done", ""),
                   ("next", "Depends on: needed\n\nNext.", "queued", ""), ("dead", "No replacement.", "blocked", ""))
        self.assertEqual(set(queues.clear_history(set())), {"p:old", "p:dead"})
        self.assertEqual(set(state.L["queue"]), {"p:needed", "p:next"})


if __name__ == "__main__":
    unittest.main()
