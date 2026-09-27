import unittest

from cointos import queues


def item(name, status="queued", depends=()):
    return {"item": f"what/is/queued/{name}.md", "status": status, "depends": list(depends)}


class Depends(unittest.TestCase):
    def test_the_depends_on_line(self):
        text = "---\nstatus: green\n---\nStatus: queued\n\nDepends on: `what/is/queued/core.md`, docs\n\nBrief."
        self.assertEqual(queues.depends(text), ["what/is/queued/core.md", "docs"])

    def test_no_line_no_dependencies(self):
        self.assertEqual(queues.depends("Status: queued\n\nIt depends on nothing in particular."), [])


class Readiness(unittest.TestCase):
    """An item is ready once everything it depends on has landed: a landed item's leaf is gone
    and git names it in the landing commit's `Landed:` trailer."""

    def test_an_item_waits_until_what_it_depends_on_has_landed(self):
        items = [item("core"), item("rest", depends=["what/is/queued/core.md"])]
        self.assertEqual(queues.readiness(items, set()),
                         {"what/is/queued/core.md": "ready", "what/is/queued/rest.md": "waiting"})
        landed = {"what/is/queued/core.md"}
        self.assertEqual(queues.readiness(items[1:], landed), {"what/is/queued/rest.md": "ready"})

    def test_bare_names_resolve_and_chains_hold(self):
        items = [item("b", depends=["a"]), item("c", depends=["b"])]
        ready = queues.readiness(items, {"what/is/queued/a.md"})
        self.assertEqual(ready["what/is/queued/b.md"], "ready")
        self.assertEqual(ready["what/is/queued/c.md"], "waiting")

    def test_an_unknown_dependency_is_a_problem(self):
        self.assertIn("unknown", queues.readiness([item("x", depends=["nosuch"])], set())["what/is/queued/x.md"])

    def test_a_blocked_dependency_is_a_problem(self):
        ready = queues.readiness([item("a", "blocked"), item("b", depends=["a"])], set())
        self.assertIn("blocked", ready["what/is/queued/b.md"])

    def test_a_cycle_is_a_problem(self):
        ready = queues.readiness([item("a", depends=["b"]), item("b", depends=["a"])], set())
        self.assertIn("cycle", ready["what/is/queued/a.md"])
        self.assertIn("cycle", ready["what/is/queued/b.md"])


if __name__ == "__main__":
    unittest.main()
