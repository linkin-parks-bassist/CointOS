"""The implementation test-contract analysis: which checks a change must pass, on real Git."""
import json
from pathlib import Path
import tempfile
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
        (self.tree / ".work-report.md").write_text("Status: done\n\nA implemented.\n")
        return self.commit(self.tree)

    def checks(self, commit):
        return contracts.implementation_checks(self.repo, self.worker, self.base, commit, self.rules)

    def test_unrelated_red_function_in_same_file_does_not_block(self):
        candidate = self.implement()
        checks = self.checks(candidate)
        self.assertEqual(checks, [["python3", "-m", "unittest", "tests.test_code.A"]])
        contracts.verify(self.repo, candidate, checks, 5)
        with self.assertRaisesRegex(ValueError, "test command failed"):
            contracts.verify(self.repo, candidate, [["python3", "-m", "unittest", "discover"]], 5)

    def test_legacy_manifest_only_policy_still_enforces_coverage(self):
        self.rules = {"manifest": "tests/contracts.json"}
        path = self.tree / "code.py"
        path.write_text(path.read_text().replace("raise NotImplementedError", "return 42", 1))
        candidate = self.commit(self.tree)
        checks = self.checks(candidate)
        self.assertEqual(checks, [["python3", "-m", "unittest", "tests.test_code.A"]])
        contracts.verify(self.repo, candidate, checks, 5)
        (self.tree / "extra.py").write_text("def uncovered(): return 1\n")
        with self.assertRaisesRegex(ValueError, "no accepted test contract: extra.py::uncovered"):
            self.checks(self.commit(self.tree))
        self.assertTrue(contracts.protected("tests/contracts.json", self.rules))

    def test_imports_and_private_helper_select_only_callers(self):
        p = self.tree / "code.py"
        p.write_text("import json\nimport os\n"
                     "def _positive(n): return isinstance(n, int) and n > 0\n"
                     "def a(): return json.loads('42') if _positive(os.getpid()) else 0\n"
                     "def b(): raise NotImplementedError\n")
        candidate = self.commit(self.tree)
        checks = self.checks(candidate)
        self.assertEqual(checks, [["python3", "-m", "unittest", "tests.test_code.A"]])
        contracts.verify(self.repo, candidate, checks, 5)

    def test_shared_helper_change_selects_transitive_callers(self):
        p = self.tree / "code.py"
        p.write_text("def _h(): return 0\ndef _middle(): return _h()\n"
                     "def a(): return _middle()\ndef b(): return _h()\n")
        before = self.commit(self.tree)
        p.write_text(p.read_text().replace("return 0", "return 1"))
        after = self.commit(self.tree)
        self.assertEqual(contracts.affected(self.repo, before, after, self.rules, inherit_private=True),
                         {"code.py::a", "code.py::b"})
        self.assertIn("code.py::_h", contracts.affected(self.repo, before, after, self.rules))

    def test_changed_import_binding_selects_unchanged_users(self):
        p = self.tree / "code.py"
        p.write_text("from math import floor as op\ndef a(): return op(1.5)\n"
                     "def b(): raise NotImplementedError\n")
        before = self.commit(self.tree)
        p.write_text(p.read_text().replace("floor", "ceil"))
        after = self.commit(self.tree)
        self.assertEqual(contracts.affected(self.repo, before, after, self.rules), {"code.py::a"})

    def test_unused_private_helper_and_public_helper_require_coverage(self):
        for name in ("_orphan", "public"):
            with self.subTest(name=name):
                git.run(self.tree, "reset", "--hard", self.base)
                self.implement()
                p = self.tree / "code.py"
                p.write_text(p.read_text() + f"\ndef {name}(): return 1\n")
                with self.assertRaisesRegex(ValueError, "no accepted test contract"):
                    self.checks(self.commit(self.tree))

    def test_import_module_use_and_wildcard_remain_whole_file(self):
        for prefix in ("import os\nROOT = os.getcwd()\n", "from math import *\n",
                       "from __future__ import annotations\n", "import os\n"):
            with self.subTest(prefix=prefix):
                git.run(self.tree, "reset", "--hard", self.base)
                p = self.tree / "code.py"
                p.write_text(prefix + p.read_text())
                self.assertEqual(contracts.affected(self.repo, self.base, self.commit(self.tree), self.rules),
                                 {"code.py"})

    def test_changed_code_failure_blocks(self):
        candidate = self.implement()
        (self.tree / "code.py").write_text("def a(): return 0\n\ndef b(): raise NotImplementedError\n")
        candidate = self.commit(self.tree)
        with self.assertRaisesRegex(ValueError, "test command failed"):
            contracts.verify(self.repo, candidate, self.checks(candidate), 5)

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

    def test_new_function_needs_coverage_and_module_change_runs_all_file_contracts(self):
        self.implement()
        p = self.tree / "code.py"
        p.write_text(p.read_text() + "\ndef c(): return 9\n")
        with self.assertRaisesRegex(ValueError, "no accepted test contract: code.py::c"):
            self.checks(self.commit(self.tree))
        git.run(self.tree, "reset", "--hard", self.base)
        p.write_text("CONSTANT = 1\n" + p.read_text())
        self.assertEqual(len(self.checks(self.commit(self.tree))), 2)

    def test_candidate_is_checked_without_untracked_workspace_helpers(self):
        candidate = self.implement()
        (self.tree / "local_only").touch()
        with self.assertRaisesRegex(ValueError, "test command failed"):
            contracts.verify(self.repo, candidate, [["python3", "-c", "from pathlib import Path; assert Path('local_only').exists()"]], 5)
        with self.assertRaisesRegex(ValueError, "changed the checked-out candidate"):
            contracts.verify(self.repo, candidate, [["python3", "-c", "from pathlib import Path; Path('code.py').write_text('')"]], 5)

    def test_test_runner_timeout_is_bounded_and_checkout_removed(self):
        candidate = self.implement()
        with self.assertRaisesRegex(ValueError, "timed out"):
            contracts.verify(self.repo, candidate, [["python3", "-c", "import time; time.sleep(30)"]], 0.05)
        self.assertNotIn("cointos-check-", git.run(self.repo, "worktree", "list"))


if __name__ == "__main__":
    unittest.main()
