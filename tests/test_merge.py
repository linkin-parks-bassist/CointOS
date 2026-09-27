import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import cli, queues


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class Landing(unittest.TestCase):
    """`cointos merge` brings the branch up to date with main itself and lands it; a conflict
    stays in the worktree with instructions, and nothing lands until it is resolved."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.main, self.tree = Path(temporary.name) / "project", Path(temporary.name) / "task"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "config", "user.email", "t@t"), git(self.main, "config", "user.name", "t")
        (self.main / "state.md").write_text("one\n")
        git(self.main, "add", "."), git(self.main, "commit", "-qm", "start")
        git(self.main, "worktree", "add", "-q", "-b", "cointos/task", str(self.tree))
        self.ledger = {"tasks": {"p:task": {"worktree": str(self.tree), "kind": "survey", "place": "p"}}}
        ledger = self.ledger
        self.enterContext(patch.object(cli, "ledger", return_value=ledger))
        self.api = self.enterContext(patch.object(cli, "call", return_value={"ok": True}))
        self.enterContext(patch.dict(cli.CONFIG, {"projects": [{"name": "p", "main_branch": "main"}]}))
        previous = os.getcwd()
        os.chdir(self.tree)
        self.addCleanup(os.chdir, previous)

    def commit(self, where, name, text):
        (where / name).write_text(text)
        git(where, "add", "."), git(where, "commit", "-qm", name)

    def land(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cli.merge()

    def test_a_branch_behind_main_is_brought_up_to_date_and_lands(self):
        self.commit(self.tree, "work.c", "int x;\n")
        self.commit(self.main, "other.c", "int y;\n")  # another agent landed meanwhile
        self.land()
        self.assertEqual(sorted(git(self.main, "ls-files").split()), ["other.c", "state.md", "work.c"])

    def test_a_conflict_is_left_to_resolve_and_nothing_lands(self):
        self.commit(self.tree, "state.md", "mine\n")
        self.commit(self.main, "state.md", "theirs\n")
        with self.assertRaises(SystemExit) as refused:
            self.land()
        self.assertIn("state.md", str(refused.exception.code))
        self.assertEqual((self.main / "state.md").read_text(), "theirs\n")
        with self.assertRaises(SystemExit):  # still unresolved
            self.land()
        (self.tree / "state.md").write_text("theirs and mine\n")
        git(self.tree, "add", "state.md"), git(self.tree, "commit", "-q", "--no-edit")
        self.land()
        self.assertEqual((self.main / "state.md").read_text(), "theirs and mine\n")


    def test_a_worker_does_not_land_its_own_work(self):
        self.ledger["tasks"]["p:task"]["kind"] = "item"
        self.commit(self.tree, "work.c", "int x;\n")
        with self.assertRaises(SystemExit) as refused:
            self.land()
        self.assertIn("integrator", str(refused.exception.code))
        self.assertNotIn("work.c", git(self.main, "ls-files"))


class Integration(unittest.TestCase):
    """Integration preserves a report in the commit and signals daemon settlement."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.main, self.worker, self.integrator = root / "project", root / "worker", root / "integrator"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "config", "user.email", "t@t"), git(self.main, "config", "user.name", "t")
        self.item = "parser"
        self.leaf = Path(queues.REPORT)
        (self.main / "README.md").write_text("Parser project\n")
        git(self.main, "add", "."), git(self.main, "commit", "-qm", "queue")
        git(self.main, "worktree", "add", "-q", "-b", "cointos/parser", str(self.worker))
        (self.worker / "parser.c").write_text("int parse;\n")
        (self.worker / self.leaf).write_text("Status: done\n\nparser.c parses; its tests pass.\n")
        git(self.worker, "add", "."), git(self.worker, "commit", "-qm", "wip")
        git(self.main, "worktree", "add", "-q", "-b", "cointos/integrate", str(self.integrator))
        ledger = {"tasks": {
            "p:parser": {"worktree": str(self.worker), "branch": "cointos/parser", "kind": "item",
                                           "place": "p", "item": self.item},
            "p:integrate": {"id": "p:integrate", "worktree": str(self.integrator), "kind": "integrate",
                            "place": "p", "item": self.item}}}
        self.enterContext(patch.object(cli, "ledger", return_value=ledger))
        self.api = self.enterContext(patch.object(cli, "call", return_value={"ok": True}))
        self.enterContext(patch.dict(cli.CONFIG, {"projects": [{"name": "p", "main_branch": "main"}]}))
        previous = os.getcwd()
        os.chdir(self.integrator)
        self.addCleanup(os.chdir, previous)

    def test_review_land_and_retry_signal_the_commit_without_report_on_main(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cli.review()
            cli.land("Add the parser")
            cli.land("Add the parser")  # API reply may have been lost
        self.assertEqual(sorted(git(self.main, "ls-files").split()), ["README.md", "parser.c"])
        message = git(self.main, "log", "-1", "--format=%B")
        self.assertIn("parser.c parses", message)
        self.assertNotIn("Landed:", message)
        self.api.assert_called_with("accept", {"task": "p:integrate", "commit": git(self.main, "rev-parse", "HEAD").strip()})
        self.assertEqual(len(git(self.main, "log", "--format=%h").split()), 2)

    def test_accept_verifies_landing_and_releases_dependency(self):
        import copy
        from cointos import state, work
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))
        project = {"name": "p", "path": str(self.main), "main_branch": "main"}
        self.enterContext(patch.dict(work.CONFIG, projects=[project]))
        self.enterContext(patch.object(work.lanes, "forget_owner"))
        queues.add(project, "queued", "parser", "Write a parser")
        worker = {"id": "p:parser", "place": "p", "item": "parser", "status": "review", "worktree": str(self.worker)}
        task = {"id": "p:integrate", "kind": "integrate", "place": "p", "item": "parser", "worktree": str(self.integrator)}
        state.L["tasks"].update({"p:parser": worker, "p:integrate": task})
        commit = git(self.worker, "rev-parse", "HEAD").strip()
        with self.assertRaises(ValueError):
            work.accept(task, commit)
        self.assertEqual(worker["status"], "review")
        with contextlib.redirect_stdout(io.StringIO()):
            cli.review()
            cli.land("Add the parser")
        commit = git(self.main, "rev-parse", "HEAD").strip()
        work.accept(task, commit)
        work.accept(task, commit)
        self.assertEqual(worker["status"], "done")
        self.assertEqual(queues.landed(project), {"parser"})


if __name__ == "__main__":
    unittest.main()
