"""Retiring settled work: no task leaves its worktree behind, landed branches are deleted, dead
unlanded branches are archived with their commits reachable, and revivable work keeps its branch."""
from pathlib import Path
import unittest

from cointos import git, lifecycle, queues, state, tasks
from tests import support


class Retirement(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.repo = support.repository(self)
        self.project = support.project(self, self.repo)

    def worked(self, name="impl", changed=True):
        """A worker that ran, committed on its branch and whose run has gone."""
        task = support.running(support.queued(self.project, name), f"run-{name}")
        if changed:
            (Path(task["worktree"]) / f"{name}.txt").write_text("work\n")
        support.commit(task["worktree"])
        state.L["agents"].pop(f"run-{name}")
        return task

    def branch(self, ref):
        return git.ok(self.repo, "rev-parse", "--verify", "--quiet", ref)

    def test_a_failed_revivable_item_loses_its_checkout_but_keeps_its_branch(self):
        task = self.worked()
        lifecycle.fail(task, "budget")
        lifecycle.reconcile()
        self.assertFalse(Path(task["worktree"]).exists())
        self.assertTrue(self.branch(f"refs/heads/{task['branch']}"))
        self.assertEqual(task["retired"], "kept")

    def test_a_revived_task_gets_its_checkout_back_from_the_kept_branch(self):
        task = self.worked()
        tip = git.head(self.repo, task["branch"])
        lifecycle.fail(task, "budget")
        lifecycle.reconcile()
        git.add_worktree(self.repo, task["worktree"], task["branch"], "main")
        self.assertEqual(git.head(task["worktree"]), tip)

    def test_a_superseded_failed_item_is_archived_with_its_commits_reachable(self):
        task = self.worked()
        tip = git.head(self.repo, task["branch"])
        lifecycle.fail(task, "budget")
        queues.records()[task["record"]]["replaced_by"] = ["better"]
        lifecycle.reconcile()
        self.assertFalse(Path(task["worktree"]).exists())
        self.assertFalse(self.branch(f"refs/heads/{task['branch']}"))
        self.assertEqual(git.head(self.repo, git.ARCHIVE + task["branch"]), tip)
        self.assertEqual(task["retired"], "archived")

    def test_a_branch_main_contains_is_deleted_not_archived(self):
        task = self.worked()
        git.run(self.repo, "merge", "-q", "--ff-only", task["branch"])
        lifecycle._settle(task, "done", "landed")
        lifecycle.reconcile()
        self.assertFalse(Path(task["worktree"]).exists())
        self.assertFalse(self.branch(f"refs/heads/{task['branch']}"))
        self.assertFalse(self.branch(git.ARCHIVE + task["branch"]))
        self.assertEqual(task["retired"], "landed")

    def test_a_squash_landed_worker_is_archived(self):
        task = self.worked()
        lifecycle._settle(task, "done", "accepted via squash")
        lifecycle.reconcile()
        self.assertEqual(task["retired"], "archived")

    def test_uncommitted_work_keeps_the_checkout_and_branch(self):
        task = self.worked()
        (Path(task["worktree"]) / "unsaved.txt").write_text("draft\n")
        lifecycle.fail(task, "budget")
        queues.records()[task["record"]]["replaced_by"] = ["better"]
        lifecycle.reconcile()
        self.assertTrue((Path(task["worktree"]) / "unsaved.txt").exists())
        self.assertTrue(self.branch(f"refs/heads/{task['branch']}"))
        self.assertEqual(task["retired"], "kept: uncommitted work")

    def test_a_task_whose_run_is_still_exiting_is_not_retired(self):
        task = support.running(support.queued(self.project, "impl"), "run-1")
        lifecycle._settle(task, "done", "receipt")
        lifecycle.reconcile()
        self.assertTrue(Path(task["worktree"]).exists())
        self.assertNotIn("retired", task)

    def test_retirement_is_bounded_per_pass_and_finishes_over_passes(self):
        settled = [self.worked(f"t{i}") for i in range(lifecycle.RETIRE_PER_TICK + 2)]
        for task in settled:
            lifecycle.fail(task, "budget")
        lifecycle.reconcile()
        self.assertEqual(sum("retired" in t for t in settled), lifecycle.RETIRE_PER_TICK)
        lifecycle.reconcile()
        self.assertTrue(all("retired" in t for t in settled))

    def test_settling_again_retires_again(self):
        task = self.worked()
        lifecycle.fail(task, "budget")
        lifecycle.reconcile()
        git.add_worktree(self.repo, task["worktree"], task["branch"], "main")
        lifecycle._settle(task, "waiting", "revised")
        self.assertNotIn("retired", task)
        lifecycle.fail(task, "budget again")
        lifecycle.reconcile()
        self.assertFalse(Path(task["worktree"]).exists())

    def test_a_task_of_an_unconfigured_project_is_left_alone(self):
        task = self.worked()
        lifecycle.fail(task, "budget")
        state.CONFIG["projects"] = []
        lifecycle.reconcile()
        self.assertTrue(Path(task["worktree"]).exists())
        self.assertEqual(task["retired"], "kept: place no longer configured")


if __name__ == "__main__":
    unittest.main()
