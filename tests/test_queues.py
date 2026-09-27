import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import queues, state, work


def item(name, status="queued", depends=(), decompose=False):
    return {"item": f"what/is/the/queued/{name}.md", "status": status, "depends": list(depends), "decompose": decompose}


class Depends(unittest.TestCase):
    def test_the_depends_on_line(self):
        text = "---\nstatus: green\n---\nStatus: queued\n\nDepends on: `what/is/the/queued/core.md`, docs\n\nBrief."
        self.assertEqual(queues.depends(text), ["what/is/the/queued/core.md", "docs"])

    def test_no_line_no_dependencies(self):
        self.assertEqual(queues.depends("Status: queued\n\nIt depends on nothing in particular."), [])


class Readiness(unittest.TestCase):
    """An item is ready once everything it depends on has landed: a landed item's leaf is gone
    and git names it in the landing commit's `Landed:` trailer."""

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


class Index(unittest.TestCase):
    """An index lists its endpoints in priority order; urgent work goes first."""

    TEXT = ("---\nstatus: green\n---\n\nWork queued, highest priority first.\n\n"
            "- `what/is/the/queued/a.md`\n- `what/is/the/queued/b.md`: why b\n")

    def test_entries_in_order(self):
        self.assertEqual(queues.entries(self.TEXT, "queued"), ["what/is/the/queued/a.md", "what/is/the/queued/b.md"])
        self.assertEqual(queues.entries(self.TEXT, "drafted"), [])

    def test_urgent_first_and_ordinary_last(self):
        first = queues.with_entry(self.TEXT, "what/is/the/queued/u.md", first=True)
        last = queues.with_entry(self.TEXT, "what/is/the/queued/z.md", first=False)
        self.assertEqual(queues.entries(first, "queued")[0], "what/is/the/queued/u.md")
        self.assertEqual(queues.entries(last, "queued")[-1], "what/is/the/queued/z.md")
        self.assertTrue(first.startswith("---\nstatus: green\n---\n\nWork queued"))

    def test_an_index_says_when_it_is_empty(self):
        text = queues.with_entry("Work, first first.\n\nNothing is queued.\n", "what/is/the/queued/a.md", first=False)
        self.assertEqual(queues.entries(text, "queued"), ["what/is/the/queued/a.md"])
        self.assertNotIn("Nothing is", text)
        emptied = queues.without_entry(text, "what/is/the/queued/a.md")
        self.assertTrue(emptied.endswith("Nothing is queued.\n"))

    def test_landing_removes_only_its_entry(self):
        text = queues.without_entry(self.TEXT, "what/is/the/queued/a.md")
        self.assertEqual(queues.entries(text, "queued"), ["what/is/the/queued/b.md"])
        self.assertIn("highest priority first", text)

    def test_needs_decomposition(self):
        self.assertTrue(queues.needs_decomposition("Status: blocked\n\nNeeds decomposition: split x and y"))
        self.assertFalse(queues.needs_decomposition("Status: blocked\n\nWaiting on David."))
        self.assertFalse(queues.needs_decomposition("Status: queued\n\nNeeds decomposition: later"))


class Admission(unittest.TestCase):
    """Index order is priority, and a worker's decomposition request dispatches a manager."""

    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.path / ".knowledge/what/is/the/queued").mkdir(parents=True)
        project = {"name": "p", "path": str(self.path), "main_branch": "main"}
        self.enterContext(patch.dict(work.CONFIG, projects=[project], trees=[]))
        self.enterContext(patch.object(queues, "landed", return_value=set()))
        state.L["last_survey"]["p"] = state.now()

    def queue(self, *items):
        (self.path / ".knowledge/what/is/queued.md").write_text(
            "".join(f"- `what/is/the/queued/{name}.md`\n" for name, _ in items))
        for name, text in items:
            (self.path / f".knowledge/what/is/the/queued/{name}.md").write_text(text)

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


if __name__ == "__main__":
    unittest.main()
