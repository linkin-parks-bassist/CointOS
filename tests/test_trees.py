import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import config, schema, spawner, state, trees
from tests import support

GREEN = "green=15 yellow=0 brown=0\n"
SICK = ("brown\tlocal:what/is/the/state.md\tbrown: priority-one incident\n"
        "yellow\tlocal:what/is/next.md\tmarked yellow for re-verification\n"
        "yellow\tlocal:where/am/i.md\tmarked yellow for re-verification\n"
        "green=12 yellow=2 brown=1\n")


class Health(unittest.TestCase):
    def test_a_green_tree_has_nothing_to_tend(self):
        health = trees.parse(GREEN)
        self.assertEqual((health["brown"], health["yellow"], health["leaves"]), (0, 0, []))

    def test_leaves_needing_care_are_counted_and_named(self):
        health = trees.parse(SICK)
        self.assertEqual((health["brown"], health["yellow"], len(health["leaves"])), (1, 2, 3))
        self.assertNotEqual(health["hash"], trees.parse(GREEN)["hash"])

    def test_bounded_selection_prioritizes_repairs_and_samples_without_repeats(self):
        self.assertEqual(trees.select(trees.parse(SICK), [], 1), ["what/is/the/state.md"])
        leaves = [f"what/is/{n}.md" for n in range(10)]
        selected = trees.select(trees.parse(GREEN), leaves, 3)
        self.assertEqual(len(set(selected)), 3)
        self.assertTrue(set(selected) <= set(leaves))
        self.assertEqual(trees.select(trees.parse(GREEN), ["one.md"], 3), ["one.md"])
        self.assertEqual(trees.select(trees.parse(GREEN), [], 3), [])


class Ranks(unittest.TestCase):
    """Brown leaves go before landing and all queued work, yellow before queued work (even the
    top of the queue), a routine pass with structural audits; the worse tree first."""

    def test_brown_before_landing_and_yellow_before_queued(self):
        brown, yellow = trees.rank(trees.parse(SICK)), trees.rank({"brown": 0, "yellow": 2})
        self.assertLess(brown, [schema.KINDS["integrate"]["rank"]])
        self.assertLess([schema.KINDS["integrate"]["rank"]], yellow)
        self.assertLess(yellow, [schema.KINDS["item"]["rank"], 0])
        self.assertEqual(trees.rank(trees.parse(GREEN)), [schema.KINDS["tree-audit"]["rank"]])

    def test_the_worse_tree_first(self):
        self.assertLess(trees.rank({"brown": 3, "yellow": 0}), trees.rank({"brown": 1, "yellow": 5}))
        self.assertLess(trees.rank({"brown": 0, "yellow": 4}), trees.rank({"brown": 0, "yellow": 1}))


class GardeningTasks(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory) / ".knowledge"
        self.root.mkdir()
        for n in range(5):
            (self.root / f"{n}.md").write_text("A test answer.")
        tree = {"name": "test", "path": directory, "tree": ".knowledge", "main_branch": "main"}
        self.enterContext(patch.dict(state.CONFIG, projects=[], trees=[tree]))
        self.health = self.enterContext(patch.object(spawner, "tree_health", return_value=trees.parse(GREEN)))

    def test_routine_batch_is_fixed_at_creation_and_blocks_an_overlapping_audit(self):
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"]), ("garden", "gardener"))
        self.assertEqual(len(task["brief"].splitlines()), state.CONFIG["garden"]["leaves_per_pass"])
        task["status"] = "running"
        self.assertIsNone(spawner.next_task())

    def test_structural_audit_has_its_own_role_and_cadence(self):
        state.L["cadence"]["garden:test"] = state.now()
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"]), ("tree-audit", "tree-auditor"))
        self.assertEqual(task["brief"], "")
        task["status"] = "done"
        self.assertIsNone(spawner.next_task())

    def test_changed_remaining_health_schedules_another_bounded_batch(self):
        self.health.return_value = trees.parse(SICK)
        task = spawner.next_task()
        self.assertEqual(task["brief"].splitlines()[0], "what/is/the/state.md")
        task["status"] = "done"
        self.health.return_value = trees.parse("yellow\tlocal:what/is/other.md\tunverified\n")
        following = spawner.next_task()
        self.assertNotEqual(following["id"], task["id"])
        self.assertEqual(following["brief"], "what/is/other.md")

    def test_registered_project_trees_are_gardened_without_manual_tree_entries(self):
        project = {"name": "project", "path": str(self.root.parent), "main_branch": "main"}
        (self.root.parent / ".knowledge").mkdir(exist_ok=True)
        with patch.dict(state.CONFIG, projects=[project], trees=[]):
            self.assertEqual([tree["name"] for tree in config.managed_trees(state.CONFIG)], ["project"])


if __name__ == "__main__":
    unittest.main()
