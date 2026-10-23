"""Test policy on real Git: what counts as production code, test immutability, and how a
registered command runs on an exact candidate."""
import json
import concurrent.futures
import os
import fcntl
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

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

    @unittest.skipUnless(os.environ.get("COINTOS_NATIVE_PIPELINE_PROBE"), "requires native systemd test units")
    def test_concurrent_commands_cannot_overwrite_each_others_tmp_binary(self):
        shared = Path("/tmp") / (self.root.name + "-binary")
        try:
            with contracts.checkout(self.repo, self.base) as first, contracts.checkout(self.repo, self.base) as second:
                script = ("import pathlib,sys,time,subprocess; "
                          "assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==sys.argv[2]; "
                          "p=pathlib.Path(sys.argv[1]); p.write_text('first'); pathlib.Path('ready').touch(); "
                          "time.sleep(1); assert p.read_text()=='first', 'another test overwrote this binary'")
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    first_run = pool.submit(contracts._run, first, self.base,
                        ["python3", "-c", script, str(shared), self.base], time.monotonic() + 20, 1)
                    deadline = time.monotonic() + 10
                    while not (first / "ready").exists() and not first_run.done() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue((first / "ready").exists(),
                                    first_run.result() if first_run.done() else "unit did not start")
                    second_run = pool.submit(contracts._run, second, self.base, ["python3", "-c",
                        "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('second')", str(shared)],
                        time.monotonic() + 20, 1)
                    for result in (first_run, second_run):
                        code, output = result.result()
                        self.assertEqual(code, 0, output)
        finally:
            shared.unlink(missing_ok=True)

    def test_production_is_every_changed_path_but_tests_and_documents(self):
        (self.tree / "code.py").write_text("def a(): return 1\n")
        (self.tree / "notes.md").write_text("notes\n")
        (self.tree / "tests/test_more.py").write_text("# more\n")
        (self.tree / "lib.c").write_text("int x;\n")
        self.assertEqual(contracts.production(self.repo, self.base, self.commit(self.tree), self.rules),
                         ["code.py", "lib.c"])

    def test_packet_composes_concurrent_helpers_and_preserves_exact_tests(self):
        original = (self.tree / "tests/test_code.py").read_text()
        (self.tree / "tests/test_code.py").write_text("# packet helper\n" + original)
        packet = self.commit(self.tree)
        git.run(self.tree, "reset", "--hard", self.base)
        (self.repo / "tests/test_code.py").write_text("# main helper\n" + original)
        main = self.commit(self.repo)
        git.run(self.tree, "merge", "--ff-only", "main")
        code = self.implement()
        with contracts.combined(self.repo, code, [packet], self.rules) as (path, head):
            self.assertEqual((path / "tests/test_code.py").read_text(),
                             "# main helper\n# packet helper\n" + original)
            self.assertEqual(contracts._run(path, head, ["python3", "-m", "unittest", "tests.test_code.A"],
                                           time.monotonic() + 5)[0], 0)
            candidate = head
        contracts.packet_unchanged(self.repo, self.worker, main, candidate, [packet], self.rules)
        with contracts.combined(self.repo, candidate, [packet, packet], self.rules) as (path, repeated):
            self.assertEqual(git.run(path, "diff", candidate, repeated), "")
            self.assertEqual((path / "tests/test_code.py").read_text(),
                             "# main helper\n# packet helper\n" + original)
        with contracts.checkout(self.repo, candidate) as path:
            (path / "tests/test_code.py").write_text("# main helper\n" + original)
            altered = self.commit(path)
        with self.assertRaisesRegex(ValueError, "differ from main"):
            contracts.packet_unchanged(self.repo, self.worker, main, altered, [packet], self.rules)
        self.assertEqual(git.head(self.repo), main)

    def test_packet_replacements_and_non_test_insertions_require_review(self):
        for name, replace in (("tests/test_code.py", True), ("notes.md", False)):
            with self.subTest(name=name):
                git.run(self.repo, "reset", "--hard", self.base)
                git.run(self.tree, "reset", "--hard", self.base)
                if name == "notes.md":
                    (self.repo / name).write_text("anchor\n")
                    base = self.commit(self.repo)
                    git.run(self.tree, "reset", "--hard", base)
                original = (self.tree / name).read_text()
                (self.tree / name).write_text("# packet\n" if replace else "# packet\n" + original)
                packet = self.commit(self.tree)
                (self.repo / name).write_text("# main\n" if replace else "# main\n" + original)
                main = self.commit(self.repo)
                with self.assertRaisesRegex(ValueError, "do not merge"):
                    with contracts.combined(self.repo, main, [packet], self.rules):
                        self.fail("unsafe conflict was composed")
                self.assertTrue(git.clean(self.repo))

    def test_protected_build_file_mismatch_identifies_content_not_stage(self):
        self.rules['protected'].append('Makefile')
        self.worker['stage'] = 'test-contract'
        (self.tree / 'Makefile').write_text('check:\n\tpython3 -m unittest\n')
        packet = self.commit(self.tree)
        contracts.packet_unchanged(self.repo, self.worker, self.base, packet, [packet], self.rules)
        (self.tree / 'Makefile').write_text('check:\n\ttrue\n')
        altered = self.commit(self.tree)
        with self.assertRaises(ValueError) as caught:
            contracts.packet_unchanged(self.repo, self.worker, self.base, altered, [packet], self.rules)
        message = str(caught.exception)
        self.assertIn('Makefile', message)
        self.assertIn('git diff ', message)
        self.assertIn(altered, message)
        self.assertIn('not a stage mismatch', message)
        self.assertIn('return defective packet changes to the worker', message)

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

    def test_a_test_writer_cannot_erase_a_production_edit_by_reverting_it(self):
        self.worker["stage"] = "test-contract"
        path = self.tree / "code.py"
        original = path.read_text()
        self.implement()
        path.write_text(original)
        self.commit(self.tree)
        with self.assertRaisesRegex(ValueError, "changes only tests.*code.py"):
            contracts.stage_history(self.repo, self.worker, self.base, self.rules)

    def test_a_merge_cannot_invent_changes_outside_its_stage(self):
        for stage, name in (("test-contract", "code.py"), ("implementation", "tests/test_code.py")):
            with self.subTest(stage=stage):
                git.run(self.tree, "reset", "--hard", self.base)
                git.run(self.repo, "reset", "--hard", self.base)
                self.worker["stage"] = stage
                (self.tree / "notes.md").write_text("worker notes\n")
                self.commit(self.tree)
                (self.repo / name).write_text("# accepted on main\n")
                main = self.commit(self.repo)
                git.run(self.tree, "merge", "--no-commit", "main")
                (self.tree / name).write_text("# invented in the merge\n")
                self.commit(self.tree)
                with self.assertRaisesRegex(ValueError, "changes.*" + name):
                    contracts.stage_history(self.repo, self.worker, main, self.rules)

    def test_a_merge_cannot_discard_inherited_changes_outside_its_stage(self):
        self.worker["stage"] = "test-contract"
        (self.tree / "notes.md").write_text("worker notes\n")
        self.commit(self.tree)
        (self.repo / "code.py").write_text("# landed prerequisite\n")
        main = self.commit(self.repo)
        git.run(self.tree, "merge", "-s", "ours", "--no-edit", "main")
        with self.assertRaisesRegex(ValueError, "changes only tests.*code.py"):
            contracts.stage_history(self.repo, self.worker, main, self.rules)

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

    def test_valid_suite_can_outlast_a_single_command_budget(self):
        commands = [["python3", "-c", "import time; time.sleep(.35)", str(i)] for i in range(2)]
        (self.tree / 'tests/contracts.json').write_text(json.dumps([
            {'covers': ['code.py'], 'command': command} for command in commands]))
        candidate = self.commit(self.tree)
        with patch.dict(contracts.TIMEOUTS, command_seconds=.6):
            counts, caused = contracts.suite(self.repo, self.base, candidate, self.rules, 3)
        self.assertEqual((counts['suite'], caused), (2, []))

    def test_command_timeout_is_not_a_red_packet_observation(self):
        (self.tree / 'tests/contracts.json').write_text(json.dumps([
            {'covers': ['code.py'], 'command': ['python3', '-c', 'import time; time.sleep(10)']}]))
        candidate = self.commit(self.tree)
        with patch.dict(contracts.TIMEOUTS, command_seconds=.1):
            with self.assertRaisesRegex(contracts.ExecutionError, 'command budget timed out'):
                contracts.passing(self.repo, self.base, [candidate], self.rules, 3)

    def test_output_lease_wait_does_not_consume_the_command_budget(self):
        with patch.object(contracts.configuration, 'STATE', self.root / 'state'), \
                patch.dict(contracts.TIMEOUTS, command_seconds=.2):
            contracts.configuration.STATE.mkdir()
            with (contracts.configuration.STATE/'test-output.lock').open('a') as lease:
                fcntl.flock(lease, fcntl.LOCK_EX)
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    future = pool.submit(self.run_on, self.base, ['python3', '-c', 'print("executed")'], 3)
                    time.sleep(.4)
                    self.assertFalse(future.done())
                    fcntl.flock(lease, fcntl.LOCK_UN)
                    code, output = future.result()
            self.assertEqual(code, 0, output)
            self.assertIn('executed', output)

    def test_ordinary_exit_124_is_preserved_as_assertion_evidence(self):
        code, _ = self.run_on(self.base, ['python3', '-c', 'raise SystemExit(124)'])
        self.assertEqual(code, 124)

    @unittest.skipUnless(os.environ.get('COINTOS_NATIVE_PIPELINE_PROBE'), 'requires native systemd test units')
    def test_native_timeouts_and_oom_are_execution_failures(self):
        with contracts.checkout(self.repo, self.base) as path, \
                patch.object(contracts.configuration, 'STATE', self.root/'state'):
            with patch.dict(contracts.TIMEOUTS, command_seconds=.2):
                with self.assertRaisesRegex(contracts.ExecutionError, 'command budget timed out'):
                    contracts._run(path, self.base, ['python3', '-c', 'import time; time.sleep(10)'],
                                   time.monotonic()+10, 1)
            for command in (['python3', '-c', 'x=bytearray(2*1024**3)'],
                            ['sh', '-c', 'python3 -c "x=bytearray(2*1024**3)"']):
                with self.subTest(command=command), self.assertRaises(contracts.ExecutionError):
                    contracts._run(path, self.base, command, time.monotonic()+10, 1)

if __name__ == "__main__":
    unittest.main()
