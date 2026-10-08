"""Test policy on real Git: what counts as production code, test immutability, and how a
registered command runs on an exact candidate."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from cointos import contracts, git


class Contracts(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.tree = self.root / "worker"
        self.review = self.root / "review"
        git.run(self.repo, "init", "-q", "-b", "main")
        git.run(self.repo, "config", "user.email", "test@example.invalid")
        git.run(self.repo, "config", "user.name", "Test")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/__init__.py").touch()
        (self.repo / "code.py").write_text("def a():\n    raise NotImplementedError\n\ndef b():\n    raise NotImplementedError\n")
        (self.repo / "tests/test_code.py").write_text(
            "import unittest\nimport code\nclass A(unittest.TestCase):\n"
            "    def test_a(self): self.assertEqual(code.a(), 42)\n"
            "class B(unittest.TestCase):\n    def test_b(self): self.assertEqual(code.b(), 7)\n")
        contracts = [{"covers": [f"code.py::{n.lower()}"],
                      "command": ["python3", "-m", "unittest", f"tests.test_code.{n}"]} for n in "AB"]
        (self.repo / "tests/contracts.json").write_text(json.dumps(contracts))
        self.base = self.commit(self.repo)
        git.run(self.repo, "worktree", "add", "-b", "work/item", str(self.tree))
        self.rules = {"manifest": "tests/contracts.json", "protected": ["tests/**", "pytest.ini"],
                      "non_code": ["*.md", ".knowledge/**"]}
        self.worker = {"id": "p:item", "kind": "item", "place": "p", "item": "item", "status": "review", "stage": "implementation",
                       "base_commit": self.base, "branch": "work/item", "worktree": str(self.tree)}

    def commit(self, path):
        git.run(path, "add", "-A")
        git.run(path, "commit", "-qm", "change")
        return git.head(path)

    def implement(self):
        p = self.tree / "code.py"
        p.write_text(p.read_text().replace("raise NotImplementedError", "return 42", 1))
        return self.commit(self.tree)

    def checks(self, commit):
        """An implementation candidate's test immutability, as the landing gate checks it."""
        contracts.packet_unchanged(self.repo, self.worker, self.base, commit, [], self.rules)

    def run_on(self, candidate, command, timeout=5):
        """One registered command on a fresh checkout of the exact candidate: (exit code, output)."""
        with contracts.checkout(self.repo, candidate) as path:
            return contracts._run(path, candidate, command, time.monotonic() + timeout)

    def test_production_is_every_changed_path_but_tests_and_documents(self):
        (self.tree / "code.py").write_text("def a(): return 1\n")
        (self.tree / "notes.md").write_text("notes\n")
        (self.tree / "tests/test_more.py").write_text("# more\n")
        (self.tree / "lib.c").write_text("int x;\n")
        self.assertEqual(contracts.production(self.repo, self.base, self.commit(self.tree), self.rules),
                         ["code.py", "lib.c"])

    def test_changed_code_failure_shows(self):
        self.implement()
        (self.tree / "code.py").write_text("def a(): return 0\n\ndef b(): raise NotImplementedError\n")
        candidate = self.commit(self.tree)
        code, output = self.run_on(candidate, ["python3", "-m", "unittest", "tests.test_code.A"])
        self.assertNotEqual(code, 0)
        self.assertIn("AssertionError", output)

    def test_test_edit_even_reverted_in_later_commit_is_rejected(self):
        path = self.tree / "tests/test_code.py"
        original = path.read_text()
        path.write_text(original + "\n# temporary change\n")
        self.commit(self.tree)
        path.write_text(original)
        self.commit(self.tree)
        candidate = self.implement()
        with self.assertRaisesRegex(ValueError, "protected tests"):
            self.checks(candidate)

    def test_test_add_delete_rename_and_manifest_edit_are_rejected(self):
        for operation in ("add", "delete", "rename", "manifest"):
            with self.subTest(operation=operation):
                git.run(self.tree, "reset", "--hard", self.base)
                p = self.tree / "tests/test_code.py"
                if operation == "add": (self.tree / "tests/extra.py").touch()
                elif operation == "delete": p.unlink()
                elif operation == "rename": p.rename(self.tree / "moved.py")
                else: (self.tree / "tests/contracts.json").write_text("[]")
                with self.assertRaisesRegex(ValueError, "protected tests"):
                    self.checks(self.commit(self.tree))

    def test_candidate_is_checked_without_untracked_workspace_helpers(self):
        candidate = self.implement()
        (self.tree / "local_only").touch()
        code, _ = self.run_on(candidate, ["python3", "-c", "from pathlib import Path; assert Path('local_only').exists()"])
        self.assertNotEqual(code, 0)
        with self.assertRaisesRegex(ValueError, "changed the checked-out candidate"):
            self.run_on(candidate, ["python3", "-c", "from pathlib import Path; Path('code.py').write_text('')"])

    def test_test_runner_timeout_is_bounded_and_checkout_removed(self):
        candidate = self.implement()
        with self.assertRaisesRegex(ValueError, "timed out"):
            self.run_on(candidate, ["python3", "-c", "import time; time.sleep(30)"], 0.05)
        self.assertNotIn("cointos-check-", git.run(self.repo, "worktree", "list"))

if __name__ == "__main__":
    unittest.main()
