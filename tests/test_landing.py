"""The landing gate, incorporation and the agents' landing commands, on real Git repositories with
tasks, runs and receipts made the way the daemon makes them."""
import contextlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import api, cli, contracts, git, landing, lifecycle, queues, state, tasks
from tests import support

CODE = "def a():\n    raise NotImplementedError\n\ndef b():\n    raise NotImplementedError\n"
TESTS = ("import unittest\nimport code\nclass A(unittest.TestCase):\n"
         "    def test_a(self): self.assertEqual(code.a(), 42)\n"
         "class B(unittest.TestCase):\n    def test_b(self): self.assertEqual(code.b(), 7)\n")
RULES = {"manifest": "tests/contracts.json", "protected": ["tests/**", "pytest.ini"], "non_code": ["*.md", ".knowledge/**"]}


class Project(unittest.TestCase):
    """A project with accepted contracts for `code.a` and `code.b`, and a running worker on item."""

    stage = "implementation"
    brief = "Implement A"

    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.repo = support.repository(self, "repo")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/__init__.py").touch()
        (self.repo / "code.py").write_text(CODE)
        (self.repo / "tests/test_code.py").write_text(TESTS)
        (self.repo / "tests/contracts.json").write_text(json.dumps(
            [{"covers": [f"code.py::{n.lower()}"], "command": ["python3", "-m", "unittest", f"tests.test_code.{n}"]}
             for n in "AB"]))
        self.base = support.commit(self.repo)
        self.project = support.project(self, self.repo, test_policy=RULES)
        self.worker = support.queued(self.project, "item", self.brief, stage=self.stage)
        support.running(self.worker, "worker-1")
        self.worker["base_commit"] = self.base
        self.tree = Path(self.worker["worktree"])
        verify = contracts.verify  # unit tests need no user systemd session for the memory cap
        self.enterContext(patch.object(contracts, "verify", side_effect=lambda repo, commit, commands, timeout, memory:
                                       verify(repo, commit, commands, timeout)))

    def implement(self) -> str:
        path = self.tree / "code.py"
        path.write_text(path.read_text().replace("raise NotImplementedError", "return 42", 1))
        (self.tree / queues.REPORT).write_text("Status: done\n\nA implemented.\n")
        return support.commit(self.tree, "implement a")

    def submit(self) -> str:
        receipt = lifecycle.submit(self.worker["id"], "worker-1", "complete", "A implemented")
        lifecycle.release("worker-1", "run ended")
        return receipt["evidence"]["commit"]

    def integrate(self) -> dict:
        integration = tasks.create("integrate", self.project, "integrate-item", "Implement A", [2],
                                   item="item", worker=self.worker["id"])
        support.running(integration, "integrator-1")
        self.review = Path(integration["worktree"])
        return integration

    def landing(self) -> tuple[dict, str, str]:
        """A reviewed candidate: (integration, candidate commit, submitted worker commit)."""
        self.implement()
        submitted = self.submit()
        integration = self.integrate()
        git.run(self.review, "merge", "--squash", submitted)
        (self.review / queues.REPORT).unlink()
        return integration, support.commit(self.review, "land a"), submitted

    def main(self) -> str:
        return git.head(self.repo, "main")


class Gate(Project):
    def test_exact_checked_commit_lands_and_a_retry_is_idempotent(self):
        integration, candidate, submitted = self.landing()
        result = landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual((result["commit"], self.main()), (candidate, candidate))
        self.assertEqual(landing.land(integration["id"], candidate, "integrator-1"), result)
        self.assertEqual(self.worker["status"], "done")
        self.assertEqual(self.worker["acceptance"], {"commit": candidate, "worker_commit": submitted,
                                                     "via": "landing", "stage": "implementation"})
        self.assertEqual((integration["status"], integration["receipt"]["run"]), ("done", "integrator-1"))
        self.assertEqual(queues.landed(self.project), {"item"})

    def test_verified_acceptance_overrides_a_provisional_blocked_record(self):
        integration, candidate, _ = self.landing()
        queues.update("p", "item", "blocked", "Status: blocked\n\nWaiting on a test correction.\n")
        landing.land(integration["id"], candidate, "integrator-1")
        record = state.L["queue"]["p:item"]
        self.assertEqual((record["status"], record["commit"]), ("done", candidate))
        self.assertNotIn("report", record)

    def test_protected_tests_cannot_change_in_an_implementation_landing(self):
        integration, _, _ = self.landing()
        (self.review / "tests/test_code.py").write_text("# weakened\n")
        candidate = support.commit(self.review)
        with self.assertRaisesRegex(ValueError, "protected tests"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), self.base)

    def test_a_commit_already_on_main_without_the_gate_is_refused(self):
        integration, candidate, _ = self.landing()
        git.run(self.repo, "merge", "--ff-only", candidate)
        with self.assertRaisesRegex(ValueError, "without passing the landing gate"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.worker["status"], "review")

    def test_a_worker_moving_during_the_check_prevents_landing(self):
        integration, candidate, _ = self.landing()

        def moved(*args):
            (self.tree / "extra.py").write_text("x = 1\n")
            support.commit(self.tree)
        with patch.object(contracts, "verify", side_effect=moved):
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

    def test_only_the_integrations_current_run_can_land(self):
        integration, candidate, _ = self.landing()
        with self.assertRaisesRegex(ValueError, "only its current run"):
            landing.land(integration["id"], candidate, "integrator-0")
        self.assertEqual(self.main(), self.base)

    def test_a_failing_implementation_returns_to_its_worker(self):
        integration, _, _ = self.landing()
        path = self.review / "code.py"
        path.write_text(path.read_text().replace("return 42", "return -1"))
        candidate = support.commit(self.review)
        with self.assertRaisesRegex(ValueError, "test command failed"):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), self.base)
        self.assertEqual((self.worker["status"], self.worker["receipt"]), ("waiting", None))
        self.assertIn("test command failed", self.worker["review"])
        self.assertEqual((integration["status"], integration["receipt"]["disposition"]), ("done", "returned"))
        self.assertEqual(queues.landed(self.project), set())


class IntegrationStage(Project):
    stage = "integration"

    def test_integration_cannot_carry_failing_production_or_weaken_tests(self):
        integration, _, _ = self.landing()
        path = self.review / "code.py"
        path.write_text(path.read_text().replace("return 42", "return -1"))
        with self.assertRaisesRegex(ValueError, "test command failed"):
            landing.land(integration["id"], support.commit(self.review), "integrator-1")
        self.assertEqual(self.main(), self.base)
        self.assertEqual(self.worker["status"], "review", "only implementations return automatically")
        (self.review / "tests/test_code.py").write_text("# weakened\n")
        with self.assertRaisesRegex(ValueError, "existing protected tests"):
            landing.land(integration["id"], support.commit(self.review), "integrator-1")


class TestContractStage(Project):
    """A test-contract candidate's declared reds are run and no accepted green check may turn red."""

    stage = "test-contract"
    brief = "Test A\nRelies on: code.py::a"
    RED = "Expected red: python3 -m unittest tests.test_d => NotImplementedError"

    def setUp(self):
        super().setUp()
        (self.repo / "code.py").write_text(CODE + "\ndef c():\n    return 1\n")
        (self.repo / "tests/test_c.py").write_text(
            "import unittest\nimport code\nclass C(unittest.TestCase):\n    def test_c(self): self.assertEqual(code.c(), 1)\n")
        manifest = json.loads((self.repo / "tests/contracts.json").read_text())
        manifest.append({"covers": ["code.py::c"], "command": ["python3", "-m", "unittest", "tests.test_c.C"]})
        (self.repo / "tests/contracts.json").write_text(json.dumps(manifest))
        self.base = support.commit(self.repo, "accepted green c")
        git.run(self.tree, "merge", "-q", "--ff-only", "main")
        gate = contracts.red_gate
        self.enterContext(patch.object(contracts, "red_gate", side_effect=lambda repo, parent, commit, report, rules,
                                       timeout, memory: gate(repo, parent, commit, report, rules, timeout)))

    def contract(self, report: str, tests: dict | None = None) -> tuple[dict, str]:
        files = {"tests/test_d.py": "import unittest\nimport code\nclass D(unittest.TestCase):\n"
                                    "    def test_a(self): self.assertEqual(code.a(), 42)\n"} if tests is None else tests
        for path, text in files.items():
            (self.tree / path).write_text(text)
        (self.tree / queues.REPORT).write_text("Status: done\n\nTests for a.\n\n" + report + "\n")
        support.commit(self.tree, "tests for a")
        submitted = lifecycle.submit(self.worker["id"], "worker-1", "complete", "tests for a")["evidence"]["commit"]
        lifecycle.release("worker-1", "run ended")
        integration = self.integrate()
        git.run(self.review, "merge", "--squash", submitted)
        (self.review / queues.REPORT).unlink()
        return integration, support.commit(self.review, "land tests")

    def rejected(self, report: str, message: str, tests: dict | None = None) -> None:
        integration, candidate = self.contract(report, tests)
        with self.assertRaisesRegex(ValueError, message):
            landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), self.base)
        self.assertEqual(self.worker["status"], "waiting", "a failed test-contract gate returns to the worker")
        self.assertIn(message.split("(")[0].strip(), self.worker["review"])

    def test_a_declared_red_with_its_output_lands(self):
        integration, candidate = self.contract(self.RED)
        landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), candidate)

    def test_a_red_appended_to_an_accepted_green_target_lands_when_declared(self):
        staged = (self.repo / "tests/test_c.py").read_text() + "    def test_a(self): self.assertEqual(code.a(), 42)\n"
        integration, candidate = self.contract(
            "Expected red: `python3 -m unittest tests.test_c.C` => NotImplementedError", {"tests/test_c.py": staged})
        landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), candidate)

    def test_a_report_without_declared_reds_is_returned(self):
        self.rejected("All good.", "declares no")

    def test_a_red_failing_for_another_reason_is_returned(self):
        self.rejected("Expected red: python3 -m unittest tests.test_d => AssertionError", "without its declared output")

    def test_a_declared_red_that_passes_is_returned(self):
        self.rejected("Expected red: python3 -m unittest tests.test_c.C => anything", "passes on the candidate")

    def test_turning_an_accepted_green_check_red_is_returned(self):
        broken = (self.repo / "tests/test_c.py").read_text().replace("code.c(), 1", "code.c(), 2")
        self.rejected(self.RED, "turns accepted green checks red",
                      {"tests/test_c.py": broken, "tests/test_d.py": "import unittest\nimport code\n"
                       "class D(unittest.TestCase):\n    def test_a(self): self.assertEqual(code.a(), 42)\n"})

    def test_expected_red_lines_parse_outside_fences_only(self):
        self.assertEqual(contracts.expected_reds("- Expected red: `make t` => x.c:3\n```\nExpected red: no\n```\n"),
                         [(["make", "t"], "x.c:3")])
        self.assertEqual(contracts.expected_reds("Expected red: none\n"), [])
        with self.assertRaisesRegex(ValueError, "malformed"):
            contracts.expected_reds("Expected red: make t\n")


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

    def test_later_docs_and_unrelated_definitions_do_not_duplicate_accepted_work(self):
        _, _, submitted = self.landing()
        path = self.review / "code.py"
        path.write_text('"""Documentation now reflects completed A."""\n' + path.read_text() + "\ndef unrelated(): return 99\n")
        candidate = support.commit(self.review)
        git.run(self.repo, "merge", "--ff-only", candidate)
        landing.incorporate(self.worker["id"], candidate, submitted, "integrator-1")
        self.assertEqual(self.worker["status"], "done")

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
        contracts.implementation_history(self.repo, self.worker, accepted, RULES)


class Commands(Project):
    """The agents' landing commands, run as their agent run against the daemon in-process."""

    stage = "skeleton"

    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(cli, "call", side_effect=lambda action, body=None, **options:
                                       api.dispatch(action, body or {})))
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
        message = git.run(self.repo, "log", "-1", "--format=%B")
        self.assertIn("Add a", message)
        self.assertIn("A implemented.", message)
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
        self.assertEqual(contracts.verify.call_args.args[2],
                         [["python3", "-m", "unittest", "tests.test_code.A"]])
        accepted = self.worker["acceptance"]
        self.assertEqual((accepted["commit"], accepted["worker_commit"]), (self.main(), submitted))
        self.assertEqual((self.worker["status"], integration["status"]), ("done", "done"))
        self.assertEqual((self.repo / "plan.md").read_text(),
                         "concurrent main frontier\nreviewed worker boundary\n")
        self.assertNotIn(queues.REPORT, git.run(self.repo, "ls-files").split())
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

    def test_the_worker_report_cannot_land_from_another_task(self):
        task = self.manager()
        (Path(task["worktree"]) / queues.REPORT).write_text("Status: done\n\nMaintenance report.\n")
        support.commit(task["worktree"])
        with self.assertRaisesRegex(SystemExit, "may never land from a breakdown task"):
            self.run_command(cli.merge)
        self.assertNotIn(queues.REPORT, git.run(self.repo, "ls-files").split())


if __name__ == "__main__":
    unittest.main()
