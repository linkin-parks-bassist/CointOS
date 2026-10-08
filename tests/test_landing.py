"""The landing gate, test packets, incorporation and the agents' landing commands, on real Git
repositories with tasks, runs and receipts made the way the daemon makes them."""
import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import api, cli, client, contracts, git, landing, lifecycle, queues, state, tasks
from tests import support

CODE = "def a():\n    raise NotImplementedError\n\ndef b():\n    return 7\n"
TESTS = "import unittest\nimport code\nclass B(unittest.TestCase):\n    def test_b(self): self.assertEqual(code.b(), 7)\n"
TESTS_A = ("import unittest\nimport code\n\n\nclass A(unittest.TestCase):\n"
           "    def test_a(self):\n        self.assertEqual(code.a(), 42)\n")
RULES = {"manifest": "tests/contracts.json", "protected": ["tests/**", "pytest.ini"], "non_code": ["*.md", ".knowledge/**"]}
B = ["python3", "-m", "unittest", "tests.test_code.B"]
A = ["python3", "-m", "unittest", "tests.test_a.A"]


class Project(unittest.TestCase):
    """Main holds code.b and its green test. A test packet for code.a waits on its own branch,
    hidden from the running implementer of item, which depends on it."""

    stage = "implementation"
    brief = "Implement A\nDepends on: tests-a"

    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.repo = support.repository(self, "repo")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/__init__.py").touch()
        (self.repo / "code.py").write_text(CODE)
        (self.repo / "tests/test_code.py").write_text(TESTS)
        (self.repo / "tests/contracts.json").write_text(json.dumps([{"covers": ["code.py::b"], "command": B}]))
        self.base = support.commit(self.repo)
        self.project = support.project(self, self.repo, test_policy=RULES)
        self.tests = self.packet("tests-a", {"tests/test_a.py": TESTS_A}, A)
        self.worker = support.queued(self.project, "item", self.brief, stage=self.stage)
        support.running(self.worker, "worker-1")
        self.worker["base_commit"] = self.base
        self.tree = Path(self.worker["worktree"])
        run = contracts._run  # unit tests need no user systemd session for the memory cap
        self.enterContext(patch.object(contracts, "_run", side_effect=lambda checkout, commit, command, deadline,
                                       memory_gb=None: run(checkout, commit, command, deadline)))

    def packet(self, name: str, files: dict, command: list[str]) -> str:
        """An accepted test packet: its commit on its own branch, off main."""
        git.run(self.repo, "checkout", "-q", "-b", f"work/{name}")
        for path, text in files.items():
            (self.repo / path).write_text(text)
        manifest = json.loads((self.repo / "tests/contracts.json").read_text())
        (self.repo / "tests/contracts.json").write_text(json.dumps(manifest + [{"covers": ["code.py::a"], "command": command}]))
        commit = support.commit(self.repo, f"tests for {name}")
        git.run(self.repo, "checkout", "-q", "main")
        queues.add(self.project, "queued", name, "Test A\nRelies on: a", "test-contract")
        queues.finish(state.L["queue"][f"p:{name}"], commit=commit, via="tests")
        return commit

    def implement(self, value: str = "42") -> str:
        path = self.tree / "code.py"
        path.write_text(path.read_text().replace("raise NotImplementedError", f"return {value}", 1))
        return support.commit(self.tree, "implement a")

    def finish(self) -> dict:
        return api.dispatch("finish", {"caller": support.caller(self.worker, "worker-1"), "outcome": "complete",
                                       "detail": "A implemented."})["receipt"]

    def submit(self) -> str:
        receipt = self.finish()
        lifecycle.release("worker-1", "run ended")
        return receipt["evidence"]["commit"]

    def integrate(self) -> dict:
        integration = tasks.create("integrate", self.project, "integrate-item", "Implement A", [2],
                                   item="item", worker=self.worker["id"])
        support.running(integration, "integrator-1")
        self.review = Path(integration["worktree"])
        return integration

    def landing(self) -> tuple[dict, str, str]:
        """A reviewed candidate, the packet's tests then its code: (integration, candidate, worker commit)."""
        self.implement()
        submitted = self.submit()
        integration = self.integrate()
        for commit in self.worker["receipt"]["evidence"]["tests"]:
            git.run(self.review, "merge", "--squash", commit)
            support.commit(self.review, "tests")
        git.run(self.review, "merge", "--squash", submitted)
        return integration, support.commit(self.review, "land a"), submitted

    def main(self) -> str:
        return git.head(self.repo, "main")


class Packets(Project):
    def test_the_implementer_cannot_see_its_packets_tests(self):
        self.assertFalse((self.tree / "tests/test_a.py").exists())
        self.assertEqual(landing.tests_of(self.worker), [self.tests])

    def test_finishing_runs_the_hidden_tests_and_reveals_only_failures(self):
        self.implement("41")
        with self.assertRaises(api.ApiError) as failed:
            self.finish()
        message = str(failed.exception)
        self.assertIn("1 of the packet's 1 tests fail", message)
        self.assertIn("tests/test_a.py", message)
        self.assertIn("self.assertEqual(code.a(), 42)", message)
        self.assertEqual((self.worker["status"], self.worker["receipt"]), ("running", None))
        self.assertFalse((self.tree / "tests/test_a.py").exists(), "revealed in the message, not the worktree")
        path = self.tree / "code.py"
        path.write_text(path.read_text().replace("return 41", "return 42"))
        support.commit(self.tree, "fix a")
        receipt = self.finish()
        self.assertEqual((self.worker["status"], receipt["evidence"]["tests"]), ("review", [self.tests]))

    def test_a_receipt_without_the_packet_check_is_refused(self):
        self.implement()
        with self.assertRaisesRegex(ValueError, "have not run on this commit"):
            lifecycle.submit(self.worker["id"], "worker-1", "complete", "A implemented")

    def writer(self, name: str, test: str, command: list[str]) -> dict:
        """A running test writer that has committed one registered test file."""
        writer = support.queued(self.project, name, "Test C\nRelies on: b", stage="test-contract")
        support.running(writer, "writer-1")
        writer["base_commit"] = self.base
        tree = Path(writer["worktree"])
        (tree / f"tests/test_{name.replace('-', '_')}.py").write_text(test)
        manifest = json.loads((tree / "tests/contracts.json").read_text())
        (tree / "tests/contracts.json").write_text(json.dumps(manifest + [{"covers": ["code.py::a"], "command": command}]))
        writer["commit"] = support.commit(tree, f"tests for {name}")
        return writer

    def finish_writer(self, writer: dict) -> dict:
        return api.dispatch("finish", {"caller": support.caller(writer, "writer-1"), "outcome": "complete",
                                       "detail": "tests"})["receipt"]

    def test_a_failing_test_packet_is_accepted_without_landing(self):
        writer = self.writer("tests-c", TESTS_A, ["python3", "-m", "unittest", "tests.test_tests_c.A"])
        receipt = self.finish_writer(writer)
        self.assertFalse(receipt["evidence"]["passing"])
        self.assertEqual((writer["status"], writer["acceptance"]["via"]), ("done", "tests"))
        self.assertEqual(state.L["queue"]["p:tests-c"]["done"]["commit"], writer["commit"])
        self.assertEqual(self.main(), self.base)

    def test_a_test_packet_that_already_passes_on_main_is_reviewed_and_lands(self):
        writer = self.writer("tests-c", TESTS, ["python3", "-m", "unittest", "tests.test_tests_c.B"])
        receipt = self.finish_writer(writer)
        self.assertTrue(receipt["evidence"]["passing"])
        self.assertEqual(writer["status"], "review")
        lifecycle.release("writer-1", "run ended")
        integration = tasks.create("integrate", self.project, "integrate-tests-c", "Test C", [2],
                                   item="tests-c", worker=writer["id"])
        support.running(integration, "integrator-1")
        review = Path(integration["worktree"])
        git.run(review, "merge", "--squash", writer["commit"])
        candidate = support.commit(review, "land tests c")
        landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), candidate)
        self.assertIn("tests/test_tests_c.py", git.run(self.repo, "ls-files").split())
        self.assertEqual((writer["status"], writer["acceptance"]["via"]), ("done", "landing"))

    def test_a_test_packet_receipt_without_its_check_is_refused(self):
        writer = self.writer("tests-c", TESTS, ["python3", "-m", "unittest", "tests.test_tests_c.B"])
        with self.assertRaisesRegex(ValueError, "have not run on this commit"):
            lifecycle.submit(writer["id"], "writer-1", "complete", "tests")

    def test_a_test_packet_cannot_change_code(self):
        writer = support.queued(self.project, "tests-c", "Test C\nRelies on: b", stage="test-contract")
        support.running(writer, "writer-1")
        writer["base_commit"] = self.base
        tree = Path(writer["worktree"])
        (tree / "code.py").write_text(CODE + "\ndef c(): return 1\n")
        support.commit(tree, "sneaky code")
        with self.assertRaisesRegex(ValueError, "changes only tests"):
            lifecycle.submit(writer["id"], "writer-1", "complete", "tests for c")

    def test_a_packet_inherits_landed_prerequisites_without_owning_their_code(self):
        for update in ("merge", "rebase"):
            with self.subTest(update=update):
                name = "tests-" + update
                writer = self.writer(name, TESTS_A,
                                     ["python3", "-m", "unittest", f"tests.test_tests_{update}.A"])
                tree = Path(writer["worktree"])
                (self.repo / f"{update}.py").write_text("def prerequisite(): return None\n")
                main = support.commit(self.repo, "land prerequisite after writer started")
                git.run(tree, update, "main")
                submitted = git.head(tree)
                receipt = self.finish_writer(writer)
                self.assertFalse(receipt["evidence"]["passing"])
                self.assertEqual(writer["base_commit"], self.base, "do not repair attribution by moving the base")
                self.assertEqual((writer["status"], writer["acceptance"]["via"]), ("done", "tests"))
                self.assertEqual(state.L["queue"][writer["id"]]["done"]["commit"], submitted)
                self.assertEqual(self.main(), main, "red tests stay off main")
                lifecycle.release("writer-1", "run ended")

    def test_a_blocked_test_writer_cannot_land_even_if_the_suite_passes(self):
        writer = self.writer("tests-c", TESTS, ["python3", "-m", "unittest", "tests.test_tests_c.B"])
        lifecycle.submit(writer["id"], "writer-1", "blocked", "Submission needs infrastructure repair")
        lifecycle.release("writer-1", "run ended")
        integration = tasks.create("integrate", self.project, "integrate-tests-c", "Test C", [2],
                                   item="tests-c", worker=writer["id"])
        support.running(integration, "integrator-1")
        review = Path(integration["worktree"])
        git.run(review, "merge", "--squash", writer["commit"])
        candidate = support.commit(review, "land tests")
        with patch.object(contracts, "suite") as suite:
            with self.assertRaisesRegex(ValueError, "finished blocked"):
                landing.land(integration["id"], candidate, "integrator-1")
            suite.assert_not_called()
        self.assertEqual((self.main(), writer["status"]), (self.base, "review"))

    def test_review_cannot_add_production_code_to_a_passing_test_packet(self):
        writer = self.writer("tests-c", TESTS, ["python3", "-m", "unittest", "tests.test_tests_c.B"])
        self.finish_writer(writer)
        lifecycle.release("writer-1", "run ended")
        integration = tasks.create("integrate", self.project, "integrate-tests-c", "Test C", [2],
                                   item="tests-c", worker=writer["id"])
        support.running(integration, "integrator-1")
        review = Path(integration["worktree"])
        git.run(review, "merge", "--squash", writer["commit"])
        (review / "code.py").write_text(CODE.replace("raise NotImplementedError", "return 42"))
        candidate = support.commit(review, "tests plus unsolicited implementation")
        with self.assertRaisesRegex(ValueError, "test packet landing changes production code"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual((self.main(), writer["status"]), (self.base, "review"))

    def test_passing_packet_review_cannot_omit_or_weaken_the_submitted_tests(self):
        writer = self.writer("tests-c", TESTS, ["python3", "-m", "unittest", "tests.test_tests_c.B"])
        self.finish_writer(writer)
        lifecycle.release("writer-1", "run ended")
        integration = tasks.create("integrate", self.project, "integrate-tests-c", "Test C", [2],
                                   item="tests-c", worker=writer["id"])
        support.running(integration, "integrator-1")
        review = Path(integration["worktree"])
        for omission in (True, False):
            with self.subTest(omission=omission):
                git.run(review, "reset", "--hard", "main")
                if not omission:
                    git.run(review, "merge", "--squash", writer["commit"])
                    (review / "tests/test_tests_c.py").write_text("# assertions removed\n")
                (review / "notes.md").write_text("reviewed\n")
                candidate = support.commit(review, "claim tests landed")
                with patch.object(contracts, "suite") as suite:
                    with self.assertRaisesRegex(ValueError, "differ from main plus the accepted packet"):
                        landing.land(integration["id"], candidate, "integrator-1")
                    suite.assert_not_called()
                self.assertEqual((self.main(), writer["status"]), (self.base, "review"))


class Gate(Project):
    def test_exact_checked_commit_lands_with_its_tests_and_a_retry_is_idempotent(self):
        integration, candidate, submitted = self.landing()
        result = landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual((result["commit"], self.main()), (candidate, candidate))
        self.assertIn("tests/test_a.py", git.run(self.repo, "ls-files").split())
        self.assertEqual(landing.land(integration["id"], candidate, "integrator-1"), result)
        self.assertEqual(self.worker["status"], "done")
        self.assertEqual(self.worker["acceptance"], {"commit": candidate, "worker_commit": submitted,
                                                     "via": "landing", "stage": "implementation"})
        self.assertEqual((integration["status"], integration["receipt"]["run"]), ("done", "integrator-1"))
        self.assertEqual(queues.landed("p"), {"tests-a", "item"})

    def test_a_verified_landing_is_the_records_terminal_fact(self):
        integration, candidate, _ = self.landing()
        landing.land(integration["id"], candidate, "integrator-1")
        record = state.L["queue"]["p:item"]
        self.assertEqual((queues.status(record), record["done"]["commit"], record["done"]["via"]),
                         ("done", candidate, "landing"))

    def test_protected_tests_cannot_change_in_an_implementation_landing(self):
        integration, _, _ = self.landing()
        (self.review / "tests/test_code.py").write_text("# weakened\n")
        candidate = support.commit(self.review)
        with self.assertRaisesRegex(ValueError, "differ from main plus the accepted packet"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), self.base)

    def test_landing_cannot_omit_all_or_part_of_its_accepted_test_packet(self):
        integration, complete, _ = self.landing()
        for omitted in (("tests",), ("tests/test_a.py",), ("tests/contracts.json",)):
            with self.subTest(omitted=omitted):
                git.run(self.review, "reset", "--hard", complete)
                git.run(self.review, "restore", "--source=main", "--staged", "--worktree", "--", *omitted)
                candidate = support.commit(self.review, "omit part of the packet")
                with patch.object(contracts, "suite") as suite:
                    with self.assertRaisesRegex(ValueError, "packet"):
                        landing.land(integration["id"], candidate, "integrator-1")
                    suite.assert_not_called()
                self.assertEqual((self.main(), self.worker["status"]), (self.base, "review"))

    def test_a_failure_main_already_has_is_not_the_packets(self):
        (self.repo / "tests/test_code.py").write_text(TESTS.replace("code.b(), 7", "code.b(), 9"))
        self.base = support.commit(self.repo, "a red test reached main")
        git.run(self.tree, "merge", "-q", "--ff-only", "main")
        integration, candidate, _ = self.landing()
        landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), candidate)

    def test_a_commit_already_on_main_without_the_gate_is_refused(self):
        integration, candidate, _ = self.landing()
        git.run(self.repo, "merge", "--ff-only", candidate)
        with self.assertRaisesRegex(ValueError, "without passing the landing gate"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.worker["status"], "review")

    def test_a_worker_moving_during_the_check_prevents_landing(self):
        integration, candidate, _ = self.landing()

        def moved(*args, **options):
            (self.tree / "extra.py").write_text("x = 1\n")
            support.commit(self.tree)
            return {"suite": 0, "red_on_main": 0}, []
        with patch.object(contracts, "suite", side_effect=moved):
            with self.assertRaisesRegex(ValueError, "refs changed"):
                landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), self.base)

    def test_landing_requires_the_commit_the_worker_receipt_submitted(self):
        integration, candidate, _ = self.landing()
        (self.tree / "late.txt").write_text("after the receipt\n")
        support.commit(self.tree)
        with self.assertRaisesRegex(ValueError, "its completion receipt submitted"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual((self.main(), self.worker["status"]), (self.base, "review"))

    def test_an_implementation_finished_blocked_cannot_land_untested(self):
        self.implement()
        lifecycle.submit(self.worker["id"], "worker-1", "blocked", "Done, but the packet would not merge")
        lifecycle.release("worker-1", "run ended")
        integration = self.integrate()
        git.run(self.review, "merge", "--squash", self.worker["receipt"]["evidence"]["commit"])
        candidate = support.commit(self.review, "land a")
        with self.assertRaisesRegex(ValueError, "completion checks have not passed"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual((self.main(), self.worker["status"]), (self.base, "review"))

    def test_only_the_integrations_current_run_can_land(self):
        integration, candidate, _ = self.landing()
        with self.assertRaisesRegex(ValueError, "only its current run"):
            landing.land(integration["id"], candidate, "integrator-0")
        self.assertEqual(self.main(), self.base)

    def test_breaking_a_test_green_on_main_returns_the_packet_with_that_test_bundled(self):
        integration, _, _ = self.landing()
        path = self.review / "code.py"
        path.write_text(path.read_text().replace("return 7", "return 8"))
        candidate = support.commit(self.review)
        with self.assertRaisesRegex(ValueError, "broke tests that pass on main"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), self.base)
        self.assertEqual((self.worker["status"], self.worker["receipt"]), ("waiting", None))
        self.assertEqual(self.worker["bundled"], [B])
        self.assertIn("code.b(), 7", self.worker["review"])
        self.assertEqual((integration["status"], integration["receipt"]["disposition"]), ("done", "returned"))
        self.assertEqual(queues.landed("p"), {"tests-a"})


class Incorporation(Project):
    """Settling an implementation already on main needs its exact behaviour there and green checks;
    neither prose nor a green suite alone suffices."""

    def test_already_landed_work_gets_an_exact_receipt_once(self):
        integration, candidate, submitted = self.landing()
        git.run(self.repo, "merge", "--ff-only", candidate)
        result = landing.incorporate(self.worker["id"], candidate, submitted, "integrator-1")
        self.assertEqual((self.worker["status"], result["via"]), ("done", "incorporation"))
        self.assertEqual(landing.incorporate(self.worker["id"], candidate, submitted, "integrator-1"), result)
        self.assertEqual((integration["status"], integration["receipt"]["evidence"]["via"]), ("done", "incorporation"))

    def test_the_worker_commit_must_be_its_receipts(self):
        integration, candidate, submitted = self.landing()
        git.run(self.repo, "merge", "--ff-only", candidate)
        with self.assertRaisesRegex(ValueError, "completion receipt submitted"):
            landing.incorporate(self.worker["id"], candidate, candidate, "integrator-1")

    def test_green_but_different_code_is_not_incorporation(self):
        _, _, submitted = self.landing()
        path = self.review / "code.py"
        path.write_text(path.read_text().replace("return 42", "return 40 + 2"))
        different = support.commit(self.review)
        git.run(self.repo, "merge", "--ff-only", different)
        with self.assertRaisesRegex(ValueError, "exact submitted behavior"):
            landing.incorporate(self.worker["id"], different, submitted, "integrator-1")
        self.assertEqual(self.worker["status"], "review")

    def test_later_changes_elsewhere_do_not_hide_incorporated_work(self):
        _, _, submitted = self.landing()
        (self.review / "other.py").write_text("def unrelated(): return 99\n")
        candidate = support.commit(self.review)
        git.run(self.repo, "merge", "--ff-only", candidate)
        landing.incorporate(self.worker["id"], candidate, submitted, "integrator-1")
        self.assertEqual(self.worker["status"], "done")

    def test_a_rewritten_file_needs_a_landing_not_incorporation(self):
        _, _, submitted = self.landing()
        path = self.review / "code.py"
        path.write_text('"""Documentation now reflects completed A."""\n' + path.read_text())
        candidate = support.commit(self.review)
        git.run(self.repo, "merge", "--ff-only", candidate)
        with self.assertRaisesRegex(ValueError, "exact submitted behavior: code.py"):
            landing.incorporate(self.worker["id"], candidate, submitted, "integrator-1")

    def test_a_historical_green_commit_cannot_settle_a_changed_main(self):
        _, candidate, submitted = self.landing()
        git.run(self.repo, "merge", "--ff-only", candidate)
        (self.repo / "code.py").write_text("def a(): return -1\ndef b(): return 7\n")
        support.commit(self.repo)
        with self.assertRaisesRegex(ValueError, "current main HEAD"):
            landing.incorporate(self.worker["id"], candidate, submitted, "integrator-1")
        self.assertEqual(self.worker["status"], "review")

    def test_accepted_test_history_on_main_is_not_a_worker_test_edit(self):
        self.implement()
        (self.repo / "tests/new_test.py").write_text("# accepted new contract\n")
        accepted = support.commit(self.repo)
        git.run(self.tree, "merge", "--no-edit", "main")
        contracts.stage_history(self.repo, self.worker, accepted, RULES)


class Commands(Project):
    """The agents' landing commands, run as their agent run against the daemon in-process."""

    stage = "skeleton"

    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(cli, "call", side_effect=lambda action, body=None, **options:
                                       api.dispatch(action, {**(body or {}), "caller": client.caller()})))
        self.enterContext(patch.object(cli, "ledger", side_effect=lambda: json.loads(json.dumps(state.L))))
        self.enterContext(patch.dict(cli.CONFIG, projects=[self.project], trees=[]))
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)

    def act_as(self, task: dict):
        os.chdir(task["worktree"])
        self.enterContext(patch.dict(os.environ, COINTOS_TASK_ID=task["id"], COINTOS_AGENT=task["agent"]))

    def run_command(self, function, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return function(*args)

    def test_review_and_land_commit_the_workers_account_and_a_retry_is_safe(self):
        self.implement()
        self.submit()
        integration = self.integrate()
        self.act_as(integration)
        self.run_command(cli.review)
        self.run_command(cli.land, "Add a")
        self.run_command(cli.land, "Add a")  # the API reply may have been lost
        self.assertEqual(sorted(git.run(self.repo, "ls-files").split()),
                         ["code.py", "tests/__init__.py", "tests/contracts.json", "tests/test_code.py"])
        self.assertNotIn("tests/test_a.py", git.run(self.repo, "ls-files").split(), "a skeleton carries no packet")
        message = git.run(self.repo, "log", "-1", "--format=%B")
        self.assertIn("Add a", message)
        self.assertIn("Worker: A implemented.", message)
        self.assertEqual((self.worker["status"], integration["status"]), ("done", "done"))

    def manager(self) -> dict:
        task = support.queued(self.project, "plan", "Plan it", kind="command")
        support.running(task, "manager-1")
        self.act_as(task)
        return task

    def test_land_conflict_resumes_through_land_and_preserves_both_sides(self):
        self.worker["stage"] = "implementation"
        state.L["queue"][self.worker["record"]]["stage"] = "implementation"
        self.implement()
        submitted = self.submit()
        integration = self.integrate()
        self.act_as(integration)
        self.run_command(cli.review)
        (self.review / "plan.md").write_text("reviewed worker boundary\n")
        (self.repo / "plan.md").write_text("concurrent main frontier\n")
        current_main = support.commit(self.repo)
        with self.assertRaises(SystemExit) as refused:
            self.run_command(cli.land, "Add a")
        self.assertIn('cointos land "<same summary>"', str(refused.exception.code))
        self.assertNotIn('cointos merge', str(refused.exception.code))
        self.assertEqual(self.main(), current_main)
        self.assertEqual((self.worker["status"], integration["status"]), ("review", "running"))
        with self.assertRaises(SystemExit):
            self.run_command(cli.land, "Add a")  # unresolved conflicts still refuse
        (self.review / "plan.md").write_text("concurrent main frontier\nreviewed worker boundary\n")
        git.run(self.review, "add", "plan.md")
        self.run_command(cli.land, "Add a")  # no manual commit or alternate command
        accepted = self.worker["acceptance"]
        self.assertEqual((accepted["commit"], accepted["worker_commit"]), (self.main(), submitted))
        self.assertEqual((self.worker["status"], integration["status"]), ("done", "done"))
        self.assertEqual((self.repo / "plan.md").read_text(),
                         "concurrent main frontier\nreviewed worker boundary\n")
        self.assertIn("tests/test_a.py", git.run(self.repo, "ls-files").split(), "review lands the packet's tests")
        self.assertIn("A implemented.", git.run(self.repo, "log", "-1", "--format=%B"))
        self.run_command(cli.land, "Add a")
        self.assertEqual(self.main(), accepted["commit"])

    def test_merge_brings_a_branch_behind_main_up_to_date_and_lands_it(self):
        task = self.manager()
        (Path(task["worktree"]) / "plan.md").write_text("plan\n")
        support.commit(task["worktree"])
        (self.repo / "other.md").write_text("another agent landed meanwhile\n")
        support.commit(self.repo)
        self.run_command(cli.merge)
        self.assertTrue({"plan.md", "other.md"} <= set(git.run(self.repo, "ls-files").split()))
        self.run_command(cli.finish, "complete", "Planned")
        self.assertEqual(task["status"], "done")

    def test_a_conflict_is_left_to_resolve_and_nothing_lands(self):
        task = self.manager()
        worktree = Path(task["worktree"])
        (worktree / "code.py").write_text("mine\n")
        support.commit(worktree)
        (self.repo / "code.py").write_text("theirs\n")
        support.commit(self.repo)
        with self.assertRaises(SystemExit) as refused:
            self.run_command(cli.merge)
        self.assertIn("code.py", str(refused.exception.code))
        self.assertEqual((self.repo / "code.py").read_text(), "theirs\n")
        with self.assertRaises(SystemExit):
            self.run_command(cli.merge)  # still unresolved
        (worktree / "code.py").write_text("theirs and mine\n")
        git.run(worktree, "add", "code.py")
        git.run(worktree, "commit", "-q", "--no-edit")
        self.run_command(cli.merge)
        self.assertEqual((self.repo / "code.py").read_text(), "theirs and mine\n")

    def test_a_worker_does_not_land_its_own_work(self):
        self.act_as(self.worker)
        self.implement()
        with self.assertRaisesRegex(SystemExit, "integrator"):
            self.run_command(cli.merge)
        self.assertEqual(self.main(), self.base)


if __name__ == "__main__":
    unittest.main()
