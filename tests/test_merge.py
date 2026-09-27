import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import cli


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
        ledger = {"tasks": {"p:task": {"worktree": str(self.tree), "kind": "item", "place": "p"}}}
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


if __name__ == "__main__":
    unittest.main()
