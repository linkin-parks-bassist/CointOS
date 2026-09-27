import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import queues, state, work, gateway


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
    """Index order is priority, and a worker's decomposition request dispatches a manager."""

    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        project = {"name": "p", "path": str(self.path), "main_branch": "main"}
        self.enterContext(patch.dict(work.CONFIG, projects=[project], trees=[]))
        state.L["last_survey"]["p"] = state.now()
        self.enterContext(patch.object(gateway, "save"))
        self.enterContext(patch.object(queues, "publish"))

    def queue(self, *items):
        for name, text in items:
            record = item(name, queues.status(text), queues.depends(text), queues.needs_decomposition(text))
            state.L["queue"][f"p:{record['item']}"] = dict(record, project="p", kind="queued", brief=text, hash=name, priority=len(state.L["queue"]))

    def test_the_first_entry_runs_first(self):
        self.queue(("urgent", "Status: queued\n\nNow."), ("later", "Status: queued\n\nLater."))
        self.assertEqual(work.next_task(), "p:what/is/the/queued/urgent.md")

    def test_needs_decomposition_dispatches_a_manager_once(self):
        self.queue(("big", "Status: blocked\n\nNeeds decomposition: split lexing from parsing."),
                   ("after", "Status: queued\nDepends on: what/is/the/queued/big.md\n\nAfter."))
        task = state.L["tasks"][work.next_task()]
        self.assertEqual((task["kind"], task["role"], task["item"]), ("decompose", "manager", "what/is/the/queued/big.md"))
        self.assertEqual(state.L["dependency_problems"], {}, "its dependent waits instead of alerting")
        task["status"] = "running"
        self.assertIsNone(work.next_task())

    def test_api_queue_is_durable_on_restart_and_never_writes_project(self):
        gateway.api("queue", {"project": "p", "kind": "queued", "name": "core", "brief": "Build core"})
        gateway.api("queue", {"project": "p", "kind": "queued", "name": "ui", "brief": "Depends on: core\nBuild UI"})
        self.assertEqual(list(self.path.iterdir()), [])
        self.assertEqual(work.next_task(), "p:core")
        state.L["tasks"]["p:core"]["status"] = "review"
        self.assertEqual(work.next_task(), "p:integrate")
        queues.update("p", "core", "done")
        state.L["tasks"]["p:core"]["status"] = "done"
        restored = state.fresh(copy.deepcopy(state.L))
        self.assertEqual(restored["queue"]["p:core"]["status"], "done")
        state.L["tasks"]["p:integrate"]["status"] = "done"
        self.assertEqual(work.next_task(), "p:ui")

    def test_command_dispatch_and_retry_deduplication(self):
        body = {"project": "p", "kind": "command", "name": "plan", "brief": "Plan the next stage"}
        gateway.api("queue", body)
        gateway.api("queue", body)
        self.assertEqual(len(state.L["queue"]), 1)
        task = state.L["tasks"][work.next_task()]
        self.assertEqual((task["kind"], task["role"]), ("breakdown", "manager"))
        self.assertNotIn("CointOS", task["worktree"])

    def test_replacement_repoints_dependents(self):
        p = work.CONFIG["projects"][0]
        for name, brief in (("big", "Big"), ("after", "Depends on: big\nAfter"), ("small", "Small")):
            queues.add(p, "queued", name, brief)
        queues.update("p", "big", "blocked", "Status: blocked\nNeeds decomposition: split")
        task = state.L["tasks"][work.next_task()]
        gateway.api("replace", {"task": task["id"], "children": ["small"]})
        self.assertEqual(state.L["queue"]["p:after"]["depends"], ["small"])
        self.assertEqual(queues.landed(p), {"big"})


if __name__ == "__main__":
    unittest.main()
