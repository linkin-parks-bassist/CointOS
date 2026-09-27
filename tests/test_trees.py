import unittest

from cointos import trees, work

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


class Ranks(unittest.TestCase):
    """Brown leaves go before urgent work, yellow before queued work, a routine pass with the
    surveys; the worse tree first."""

    def test_brown_before_urgent_and_yellow_before_queued(self):
        brown, yellow = trees.rank(trees.parse(SICK)), trees.rank({"brown": 0, "yellow": 2})
        self.assertLess(brown, work.RANKS["urgent"])
        self.assertLess(work.RANKS["urgent"], yellow)
        self.assertLess(yellow, work.RANKS["queued"])
        self.assertEqual(trees.rank(trees.parse(GREEN)), work.RANKS["survey"])

    def test_the_worse_tree_first(self):
        self.assertLess(trees.rank({"brown": 3, "yellow": 0}), trees.rank({"brown": 1, "yellow": 5}))
        self.assertLess(trees.rank({"brown": 0, "yellow": 4}), trees.rank({"brown": 0, "yellow": 1}))


if __name__ == "__main__":
    unittest.main()
