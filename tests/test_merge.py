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
    """The integrator brings a worker's branch in as one change, drops the finished item's leaf,
    and lands one commit whose trailer names the item; git keeps the account."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.main, self.worker, self.integrator = root / "project", root / "worker", root / "integrator"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "config", "user.email", "t@t"), git(self.main, "config", "user.name", "t")
        self.item = "what/is/the/queued/parser.md"
        self.leaf = Path(".knowledge") / self.item
        (self.main / self.leaf).parent.mkdir(parents=True)
        (self.main / self.leaf).write_text("Status: queued\n\nWrite a parser.\n")
        self.index = Path(".knowledge/what/is/queued.md")
        (self.main / self.index).write_text("Work queued, first first.\n\n- `what/is/the/queued/parser.md`\n"
                                            "- `what/is/the/queued/docs.md`\n")
        git(self.main, "add", "."), git(self.main, "commit", "-qm", "queue")
        git(self.main, "worktree", "add", "-q", "-b", "cointos/parser", str(self.worker))
        (self.worker / "parser.c").write_text("int parse;\n")
        (self.worker / self.leaf).write_text("Status: done\n\nparser.c parses; its tests pass.\n")
        git(self.worker, "add", "."), git(self.worker, "commit", "-qm", "wip")
        git(self.main, "worktree", "add", "-q", "-b", "cointos/integrate", str(self.integrator))
        ledger = {"tasks": {
            "p:what/is/the/queued/parser.md": {"worktree": str(self.worker), "branch": "cointos/parser", "kind": "item",
                                           "place": "p", "item": self.item},
            "p:integrate": {"id": "p:integrate", "worktree": str(self.integrator), "kind": "integrate",
                            "place": "p", "item": self.item}}}
        self.enterContext(patch.object(cli, "ledger", return_value=ledger))
        self.enterContext(patch.dict(cli.CONFIG, {"projects": [{"name": "p", "main_branch": "main"}]}))
        previous = os.getcwd()
        os.chdir(self.integrator)
        self.addCleanup(os.chdir, previous)

    def test_review_then_land_makes_one_commit_and_prunes_the_item_and_its_entry(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cli.review()
            cli.land("Add the parser")
        self.assertEqual(sorted(git(self.main, "ls-files").split()), [".knowledge/what/is/queued.md", "parser.c"])
        self.assertEqual(queues.entries((self.main / self.index).read_text(), "queued"), ["what/is/the/queued/docs.md"])
        message = git(self.main, "log", "-1", "--format=%B")
        self.assertIn("parser.c parses", message)
        self.assertEqual(queues.landed({"path": str(self.main), "main_branch": "main"}), {self.item})
        self.assertEqual(len(git(self.main, "log", "--format=%h").split()), 2, "one commit for the item")

    def test_a_trailer_naming_items_still_on_main_does_not_land_them(self):
        # A manager queueing items once named them in its commit's trailer, comma-joined.
        (self.main / ".knowledge/what/is/the/queued/docs.md").write_text("Status: queued\n\nDocument it.\n")
        git(self.main, "add", "."), git(self.main, "commit", "-qm",
                                        f"Queue work\n\nLanded: {self.item}, what/is/the/queued/docs.md")
        self.assertEqual(queues.landed({"path": str(self.main), "main_branch": "main"}), set())


if __name__ == "__main__":
    unittest.main()
