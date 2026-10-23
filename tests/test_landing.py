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
        write_json = state.configuration.write_json
        def unlocked_ledger(path, value, *args, **kwargs):
            if path == state.configuration.LEDGER:
                self.assertFalse(state.LOCK._is_owned(), 'ledger publication retains the state lock')
            return write_json(path, value, *args, **kwargs)
        self.enterContext(patch.object(state.configuration, 'write_json', side_effect=unlocked_ledger))
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
    def test_hold_during_intent_persistence_revokes_git_publication(self):
        integration, candidate, _ = self.landing()
        persist = landing.save
        def held_after_persistence():
            self.assertFalse(state.LOCK._is_owned())
            persist()
            with state.LOCK:
                self.worker['admission_hold'] = 'fixture owner hold during storage'
        with patch.object(landing, 'save', side_effect=held_after_persistence), \
             patch.object(git, 'publish') as publish:
            with self.assertRaisesRegex(ValueError, 'held'):
                landing.land(integration['id'], candidate, 'integrator-1')
            publish.assert_not_called()
        self.assertEqual(self.main(), self.base)
        self.assertEqual(self.worker['status'], 'review')

    def test_published_intent_recovers_after_restart_and_artifact_retirement(self):
        integration, candidate, submitted = self.landing()
        durable = self.repo / '.git/fixture-ledger.json'
        original = git.publish
        class ProcessLoss(BaseException):
            pass
        def publish(*args):
            original(*args)
            raise ProcessLoss()
        with patch.object(landing, 'save', side_effect=lambda: durable.write_text(json.dumps(state.L))):
            with patch.object(git, 'publish', side_effect=publish):
                with self.assertRaises(ProcessLoss):
                    landing.land(integration['id'], candidate, 'integrator-1')
        state.L.clear()
        state.L.update(json.loads(durable.read_text()))
        # Disposable checkouts/branches are gone; the immutable commits remain.
        for task in (self.worker, integration):
            git.run(self.repo, 'worktree', 'remove', '--force', task['worktree'])
            git.run(self.repo, 'branch', '-D', task['branch'])
        with patch.object(lifecycle, 'save'):
            self.assertEqual(lifecycle.recover_landings(), 1)
            self.assertEqual(lifecycle.recover_landings(), 0)
        worker = state.L['tasks'][self.worker['id']]
        self.assertEqual(worker['acceptance']['worker_commit'], submitted)
        self.assertEqual(worker['acceptance']['commit'], candidate)
        self.assertEqual(worker['acceptance']['gate'], {'suite': 2, 'failed': 0, 'red_on_main': 0})
        self.assertEqual(state.L['queue'][worker['record']]['done']['commit'], candidate)
        self.assertEqual(state.L['queue'][worker['record']]['done']['gate'], worker['acceptance']['gate'])
        self.assertEqual(state.L['tasks'][integration['id']]['receipt']['run'], 'integrator-1')

    def test_unpublished_or_superseded_intent_cannot_recover(self):
        integration, candidate, submitted = self.landing()
        integration['landing'] = {'commit': candidate, 'worker_commit': submitted,
                                  'receipt_run': self.worker['receipt']['run'],
                                  'record_version': self.worker['record_version'], 'run': 'integrator-1'}
        self.assertEqual(lifecycle.recover_landings(), 0)
        git.publish(self.repo, 'main', candidate, self.main())
        self.worker['record_version'] += 1
        self.assertEqual(lifecycle.recover_landings(), 0)
        self.assertIsNone(self.worker.get('acceptance'))

    def test_the_implementer_cannot_see_its_packets_tests(self):
        self.assertFalse((self.tree / "tests/test_a.py").exists())
        self.assertEqual(landing.tests_of(self.worker), [self.tests])

    def test_implementation_cannot_submit_without_an_independent_contract(self):
        state.L['queue'][self.worker['record']]['depends'] = []
        self.implement()
        with self.assertRaisesRegex(ValueError, 'accepted test-contract dependency'):
            self.finish()
        self.assertEqual(self.worker['status'], 'running')
        self.assertIsNone(self.worker['receipt'])
        self.assertFalse(self.worker.get('validating'))
        self.assertEqual(state.ACTIVE['landings'], 0)

    def test_landing_cannot_trust_an_empty_or_obsolete_packet_receipt(self):
        integration, candidate, submitted = self.landing()
        before = self.main()
        for tests in ([], ['0' * 40]):
            with self.subTest(tests=tests):
                self.worker['receipt']['evidence']['tests'] = tests
                with self.assertRaisesRegex(ValueError, 'test-contract'):
                    landing.land(integration['id'], candidate, 'integrator-1')
                self.assertEqual(self.main(), before)
                self.assertEqual(self.worker['status'], 'review')

    def test_legacy_zero_test_receipt_cannot_land_code_without_its_hidden_contract(self):
        submitted = self.implement()
        state.L['queue'][self.worker['record']]['depends'] = []
        # Recreate a receipt the previous daemon could issue, without using the
        # repaired submission boundary. Main's old suite alone is green here.
        lifecycle.submit(self.worker['id'], 'worker-1', 'complete', 'legacy submission',
                         {'commit': submitted, 'tests': [], 'packet_tests': 0})
        lifecycle.release('worker-1', 'run ended')
        integration = self.integrate()
        git.run(self.review, 'merge', '--no-edit', submitted)
        candidate, before = git.head(self.review), self.main()
        with self.assertRaisesRegex(ValueError, 'accepted test-contract dependency'):
            landing.land(integration['id'], candidate, 'integrator-1')
        self.assertEqual(self.main(), before)
        self.assertEqual(self.worker['status'], 'review')

    def test_hidden_assertions_in_an_existing_command_run_before_submission(self):
        shared = TESTS + "    def test_a(self): self.assertEqual(code.a(), 42)\n"
        packet = self.packet('shared-command', {'tests/test_code.py': shared}, B)
        state.L['queue'][self.worker['record']]['depends'] = ['shared-command']
        self.implement('41')
        with self.assertRaises(api.ApiError) as failed:
            self.finish()
        self.assertIn('self.assertEqual(code.a(), 42)', str(failed.exception))
        self.assertEqual(self.worker['status'], 'running')
        self.assertIsNone(self.worker['receipt'])
        self.assertEqual((self.tree / 'tests/test_code.py').read_text(), TESTS)
        path = self.tree / 'code.py'
        path.write_text(path.read_text().replace('return 41', 'return 42'))
        support.commit(self.tree, 'correct hidden shared-command assertion')
        receipt = self.finish()
        self.assertEqual(receipt['evidence']['tests'], [packet])
        self.assertEqual(receipt['evidence']['packet_tests'], 1)

    def test_new_command_does_not_hide_changes_to_an_existing_harness(self):
        changed = TESTS.replace('code.b(), 7', 'code.b(), 8')
        packet = self.packet('mixed-commands', {'tests/test_code.py': changed,
                                               'tests/test_a.py': TESTS_A}, A)
        state.L['queue'][self.worker['record']]['depends'] = ['mixed-commands']
        self.implement()
        self.assertEqual(contracts.packet_tests(self.repo, self.base, [packet], RULES), [B, A])
        with self.assertRaises(api.ApiError) as failed:
            self.finish()
        self.assertIn('self.assertEqual(code.b(), 8)', str(failed.exception))
        self.assertNotIn('self.assertEqual(code.a(), 42)', str(failed.exception))
        self.assertIsNone(self.worker['receipt'])

    def test_hold_during_validation_prevents_acceptance(self):
        integration, candidate, _ = self.landing()
        def held(*args):
            lifecycle.hold(self.worker["record"], "user")
            return {"commands": 1}, []
        with patch.object(contracts, "suite", side_effect=held):
            with self.assertRaisesRegex(ValueError, "not owned by run"):
                landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.main(), self.base)
        self.assertNotIn("acceptance", self.worker)
        self.assertEqual(integration["status"], "waiting")

    def test_failed_validation_from_killed_run_cannot_bundle_tests(self):
        integration, candidate, _ = self.landing()
        def killed(*args):
            lifecycle.kill("integrator-1")
            return {"commands": 1}, [(A, "failure", "test source")]
        before = list(self.worker.get("bundled", []))
        with patch.object(contracts, "suite", side_effect=killed):
            with self.assertRaises(ValueError):
                landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(self.worker.get("bundled", []), before)
        self.assertEqual(self.main(), self.base)

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

    def test_execution_failures_escalate_separately_from_product_refusals(self):
        self.implement()
        with patch.object(contracts, 'packet_check', side_effect=contracts.ExecutionError('command budget timed out')):
            for _ in range(2):
                with self.assertRaisesRegex(api.ApiError, 'timed out'):
                    self.finish()
        self.assertEqual(self.worker['submission_failure']['category'], 'execution')
        with patch.object(contracts, 'packet_check', side_effect=ValueError('assertion failed')):
            with self.assertRaisesRegex(api.ApiError, 'assertion failed'):
                self.finish()
        self.assertEqual(self.worker['submission_failure']['attempts'], 1)
        self.assertEqual(self.worker['submission_failure']['category'], 'product')
        with patch.object(contracts, 'packet_check', side_effect=contracts.ExecutionError('command budget timed out')):
            for _ in range(2):
                with self.assertRaisesRegex(api.ApiError, 'timed out'):
                    self.finish()
            receipt = self.finish()
        self.assertEqual(receipt['disposition'], 'blocked')
        self.assertIn('Validation infrastructure failed 3', receipt['summary'])
        self.assertEqual(self.worker['submission_failure']['category'], 'execution')
        self.assertIsNone(self.worker.get('acceptance'))
        self.assertNotIn('validating', self.worker)

    def test_success_after_transient_execution_failure_still_completes(self):
        self.implement()
        with patch.object(contracts, 'packet_check', side_effect=contracts.ExecutionError('unit failed')):
            with self.assertRaisesRegex(api.ApiError, 'unit failed'):
                self.finish()
        self.assertEqual(self.worker['status'], 'running')
        self.assertIsNone(self.worker['receipt'])
        self.assertNotIn('validating', self.worker)
        self.assertEqual(self.finish()['disposition'], 'complete')

    def test_unchanged_refusals_end_in_a_blocked_receipt_and_preserve_the_branch(self):
        self.implement()
        (self.tree / 'pytest.ini').write_text('[pytest]\n')
        candidate = support.commit(self.tree, 'illegal harness edit')
        for count in (1, 2):
            with self.assertRaisesRegex(api.ApiError, 'protected tests or harness'):
                self.finish()
            self.assertEqual(self.worker['submission_failure']['attempts'], count)
        restored = state.fresh(json.loads(json.dumps(state.L)))
        state.L.clear()
        state.L.update(restored)
        self.worker = state.L['tasks'][self.worker['id']]
        receipt = self.finish()
        self.assertEqual((receipt['disposition'], self.worker['status']), ('blocked', 'failed'))
        self.assertIn('Unchanged candidate refused 3 submissions', receipt['summary'])
        self.assertEqual(git.head(self.tree), candidate)
        self.assertTrue(queues.state(state.L['queue']['p:item'])['recoverable'])
        self.assertNotIn('acceptance', self.worker)
        self.assertIs(self.finish(), receipt, 'lost completion reply replays the actual blocked receipt')
        with self.assertRaises(ValueError):
            api.dispatch('finish', {'caller': support.caller(self.worker, 'foreign-run'),
                                   'outcome': 'complete', 'detail': 'A implemented.'})

    def test_empty_commits_do_not_refill_refused_submission_attempts_but_changed_inputs_do(self):
        self.implement('41')
        with self.assertRaises(api.ApiError): self.finish()
        git.run(self.tree, 'commit', '--allow-empty', '-qm', 'same content')
        with self.assertRaises(api.ApiError): self.finish()
        self.assertEqual(self.worker['submission_failure']['attempts'], 2)
        (self.repo / 'notes.md').write_text('new main observation\n')
        support.commit(self.repo, 'main changed')
        with self.assertRaises(api.ApiError): self.finish()
        self.assertEqual(self.worker['submission_failure']['attempts'], 1)
        (self.tree / 'code.py').write_text((self.tree / 'code.py').read_text().replace('return 41', 'return 40'))
        support.commit(self.tree, 'different candidate')
        with self.assertRaises(api.ApiError): self.finish()
        self.assertEqual(self.worker['submission_failure']['attempts'], 1)
        (self.tree / 'code.py').write_text((self.tree / 'code.py').read_text().replace('return 40', 'return 42'))
        support.commit(self.tree, 'correct candidate')
        self.assertEqual(self.finish()['disposition'], 'complete')
        self.assertNotIn('submission_failure', self.worker)

    def test_revoked_worker_validation_cannot_record_or_escalate_a_failure(self):
        self.implement('41')
        def revoked(*args):
            lifecycle.kill('worker-1')
            raise ValueError('old candidate failure')
        with patch.object(contracts, 'packet_check', side_effect=revoked):
            with self.assertRaisesRegex(api.ApiError, 'old candidate failure'): self.finish()
        self.assertNotIn('submission_failure', self.worker)
        self.assertIsNone(self.worker['receipt'])

    def writer(self, name: str, test: str, command: list[str], run="writer-1") -> dict:
        """A running test writer that has committed one registered test file."""
        writer = support.queued(self.project, name, "Test C\nRelies on: b", stage="test-contract")
        support.running(writer, run)
        writer["base_commit"] = self.base
        tree = Path(writer["worktree"])
        (tree / f"tests/test_{name.replace('-', '_')}.py").write_text(test)
        manifest = json.loads((tree / "tests/contracts.json").read_text())
        (tree / "tests/contracts.json").write_text(json.dumps(manifest + [{"covers": ["code.py::a"], "command": command}]))
        writer["commit"] = support.commit(tree, f"tests for {name}")
        return writer

    def finish_writer(self, writer: dict, run=None) -> dict:
        return api.dispatch("finish", {"caller": support.caller(writer, run or writer["agent"]), "outcome": "complete",
                                       "detail": "tests"})["receipt"]

    def review_writer(self, writer: dict, run="integrator-1") -> tuple[dict, str]:
        lifecycle.release(writer["receipt"]["run"], "run ended")
        integration = tasks.create("integrate", self.project, "integrate-" + writer["item"], "Review test contract", [2],
                                   item=writer["item"], worker=writer["id"])
        support.running(integration, run)
        review = Path(integration["worktree"])
        git.run(review, "merge", "--squash", writer["receipt"]["evidence"]["commit"])
        return integration, support.commit(review, "review test contract")

    def red_writer(self, name="tests-c", run="writer-1") -> dict:
        return self.writer(name, TESTS_A, ["python3", "-m", "unittest", "tests.test_" + name.replace("-", "_") + ".A"], run=run)

    def test_preflight_catches_production_changes_during_red_test_review(self):
        writer = self.red_writer()
        self.finish_writer(writer)
        integration, _ = self.review_writer(writer)
        caller = {'caller': support.caller(integration, 'integrator-1')}
        self.assertTrue(api.check_work(caller)['ok'])
        tree = Path(integration['worktree'])
        code = tree / 'code.py'
        original = code.read_text()
        code.write_text(original + '\n# reviewer tried to implement the red test\n')
        for committed in (False, True):
            if committed:
                support.commit(tree, 'reviewer implementation')
            checked = api.check_work(caller)
            self.assertFalse(checked['ok'])
            self.assertTrue(any('production code' in p and 'code.py' in p for p in checked['problems']))
        code.write_text(original)
        support.commit(tree, 'restore test-only candidate')
        self.assertTrue(api.check_work(caller)['ok'])
        (tree / 'invented-production.c').write_text('int unrelated;\n')
        checked = api.check_work(caller)
        self.assertFalse(checked['ok'])
        self.assertTrue(any('invented-production.c' in p for p in checked['problems']))

    def test_preflight_checks_staged_and_unstaged_review_without_mutation(self):
        writer = self.red_writer()
        self.finish_writer(writer)
        lifecycle.release(writer['receipt']['run'], 'run ended')
        integration = tasks.create('integrate', self.project, 'review-staged', 'Review tests', [2],
                                   item=writer['item'], worker=writer['id'])
        support.running(integration, 'integrator-1')
        tree = Path(integration['worktree'])
        git.run(tree, 'merge', '--squash', writer['receipt']['evidence']['commit'])
        caller = {'caller': support.caller(integration, 'integrator-1')}
        index = Path(git.run(tree, 'rev-parse', '--git-path', 'index'))
        before = (git.head(tree), index.read_bytes(), git.run(tree, 'status', '--porcelain=v1', '-z'))
        checked = api.check_work(caller)
        self.assertTrue(checked['ok'], checked)
        self.assertFalse(checked['worktree_clean'])
        self.assertEqual((git.head(tree), index.read_bytes(), git.run(tree, 'status', '--porcelain=v1', '-z')), before)
        self.assertIsNone(integration['receipt'])
        self.assertEqual(writer['status'], 'review')
        test = tree / 'tests/test_tests_c.py'
        original = test.read_text()
        for staged in (False, True):
            test.write_text(original + '\n# altered review packet\n')
            if staged:
                git.run(tree, 'add', str(test))
            checked = api.check_work(caller)
            self.assertFalse(checked['ok'], checked)
            self.assertTrue(any('candidate tests differ' in p for p in checked['problems']))
            test.write_text(original)
            git.run(tree, 'add', str(test))
        extra = tree / 'tests/unsubmitted.py'
        extra.write_text('unsubmitted protected content\n')
        self.assertFalse(api.check_work(caller)['ok'])
        extra.unlink()
        self.assertTrue(api.check_work(caller)['ok'])

    def test_a_failing_test_packet_requires_independent_review_before_hidden_acceptance(self):
        writer = self.red_writer()
        dependent = queues.add(self.project, "queued", "implement-c", "Implement C\nDepends on: tests-c", "implementation")
        receipt = self.finish_writer(writer)
        self.assertFalse(receipt["evidence"]["passing"])
        self.assertEqual(writer["status"], "review")
        self.assertNotIn("acceptance", writer)
        self.assertNotIn("tests-c", queues.landed("p"))
        self.assertEqual(queues.readiness(queues.live("p"), queues.landed("p"))[dependent], "waiting")
        integration, candidate = self.review_writer(writer)
        with patch.object(git, "publish") as publish:
            accepted = landing.land(integration["id"], candidate, "integrator-1")
            self.assertEqual(landing.land(integration["id"], candidate, "integrator-1"), accepted)
            publish.assert_not_called()
        self.assertEqual((writer["status"], writer["acceptance"]["via"]), ("done", "tests"))
        self.assertEqual(writer["acceptance"]["worker_commit"], writer["commit"])
        self.assertEqual(writer["acceptance"]["commit"], candidate)
        self.assertEqual(integration["receipt"]["evidence"], writer["acceptance"])
        self.assertEqual(state.L["queue"]["p:tests-c"]["done"]["commit"], candidate)
        self.assertEqual(queues.readiness(queues.live("p"), queues.landed("p"))[dependent], "ready")
        self.assertNotIn("landing", integration, "hidden acceptance has no publication intent")
        self.assertEqual(self.main(), self.base)
        self.assertFalse((self.repo / "tests/test_tests_c.py").exists())

    def test_reviewed_packet_with_a_shared_command_already_red_on_main_stays_hidden(self):
        (self.repo / "tests/test_a.py").write_text(TESTS_A)
        manifest = json.loads((self.repo / "tests/contracts.json").read_text())
        (self.repo / "tests/contracts.json").write_text(json.dumps(manifest + [{"covers": ["code.py::a"], "command": A}]))
        main = support.commit(self.repo, "existing unresolved assertion on main")
        writer = self.writer("tests-c", TESTS_A, A)
        self.finish_writer(writer)
        integration, candidate = self.review_writer(writer)
        suite = contracts.suite

        def checked(*args):
            counts, caused = suite(*args)
            self.assertFalse(caused, "shared command's failure already exists on main")
            self.assertGreater(counts["red_on_main"], 0)
            return counts, caused

        with patch.object(contracts, "suite", side_effect=checked), patch.object(git, "publish") as publish:
            landing.land(integration["id"], candidate, "integrator-1")
            publish.assert_not_called()
        self.assertEqual(writer["acceptance"]["via"], "tests")
        self.assertEqual(self.main(), main)
        self.assertFalse((self.repo / "tests/test_tests_c.py").exists())

    def test_hidden_acceptance_retries_a_failed_save_and_survives_restart(self):
        writer = self.red_writer()
        self.finish_writer(writer)
        integration, candidate = self.review_writer(writer)
        durable = []

        def persist():
            if not durable:
                durable.append(None)
                raise OSError("fixture ledger save failed")
            durable.append(json.loads(json.dumps(state.L)))

        with patch.object(landing, "save", side_effect=persist), patch.object(git, "publish") as publish:
            with self.assertRaisesRegex(OSError, "ledger save failed"):
                landing.land(integration["id"], candidate, "integrator-1")
            self.assertIsNone(durable[0])
            landing.land(integration["id"], candidate, "integrator-1")
            self.assertEqual(len(durable), 2, "retry must persist the already-settled acceptance")
            state.L.clear()
            state.L.update(durable[-1])
            landing.land(integration["id"], candidate, "integrator-1")
            publish.assert_not_called()
        restored = state.L["tasks"][writer["id"]]
        self.assertEqual(restored["acceptance"]["commit"], candidate)
        self.assertEqual(state.L["tasks"][integration["id"]]["receipt"]["evidence"], restored["acceptance"])
        self.assertEqual(state.L["queue"][writer["record"]]["done"]["commit"], candidate)
        self.assertEqual(self.main(), self.base)

    def test_review_merge_conflict_cannot_accept_a_test_requirement(self):
        writer = self.red_writer()
        self.finish_writer(writer)
        lifecycle.release("writer-1", "run ended")
        integration = tasks.create("integrate", self.project, "integrate-tests-c", "Review tests", [2],
                                   item=writer["item"], worker=writer["id"])
        support.running(integration, "integrator-1")
        review = Path(integration["worktree"])
        (review / "tests/contracts.json").write_text("[]\n")
        support.commit(review, "conflicting review draft")
        previous = os.getcwd()
        try:
            os.chdir(review)
            with patch.dict(os.environ, COINTOS_TASK_ID=integration["id"], COINTOS_AGENT="integrator-1"), \
                    patch.dict(cli.CONFIG, projects=[self.project], trees=[]), \
                    patch.object(cli, "ledger", side_effect=lambda: json.loads(json.dumps(state.L))), \
                    patch.object(cli, "call", side_effect=lambda action, body=None, **options:
                                 api.dispatch(action, {**(body or {}), "caller": client.caller()})):
                with self.assertRaises(SystemExit):
                    cli.review()
        finally:
            os.chdir(previous)
        self.assertTrue(git.run(review, "diff", "--name-only", "--diff-filter=U"))
        self.assertNotIn("acceptance", writer)
        self.assertNotIn("tests-c", queues.landed("p"))
        self.assertEqual(self.main(), self.base)

    def test_returning_a_flawed_test_witness_keeps_its_requirement_unaccepted(self):
        writer = self.red_writer()
        self.finish_writer(writer)
        integration, _ = self.review_writer(writer)
        lifecycle.returned(integration, "integrator-1", "Assertion witnesses the wrong required behavior")
        self.assertEqual(writer["status"], "waiting")
        self.assertNotIn("acceptance", writer)
        self.assertNotIn("tests-c", queues.landed("p"))
        self.assertEqual(self.main(), self.base)

    def test_red_packet_cannot_be_accepted_after_validation_authority_changes(self):
        suite = contracts.suite
        for change in ("hold", "receipt", "run", "main"):
            with self.subTest(change=change):
                writer = self.red_writer("tests-" + change, run="writer-" + change)
                integrator_run = "integrator-" + change
                self.finish_writer(writer)
                integration, candidate = self.review_writer(writer, run=integrator_run)
                before = self.main()

                def altered(*args):
                    result = suite(*args)
                    self.assertTrue(result[1], "fixture must exercise hidden acceptance")
                    if change == "hold":
                        lifecycle.hold(writer["record"], "user")
                    elif change == "receipt":
                        writer["receipt"]["detail"] = "changed during validation"
                    elif change == "run":
                        lifecycle.kill(integrator_run)
                    else:
                        (self.repo / "new-main.md").write_text("Concurrent main update\n")
                        support.commit(self.repo, "main advanced during review")
                    return result

                with patch.object(contracts, "suite", side_effect=altered):
                    with self.assertRaises(ValueError):
                        landing.land(integration["id"], candidate, integrator_run)
                self.assertNotIn("acceptance", writer)
                self.assertNotIn(writer["item"], queues.landed("p"))
                self.assertNotIn("landing", integration)
                if change != "main":
                    self.assertEqual(self.main(), before)
                if integrator_run in state.L["agents"]:
                    lifecycle.release(integrator_run, "fixture finished")

    def test_red_packet_validation_failure_or_invalid_candidate_cannot_accept(self):
        writer = self.red_writer()
        self.finish_writer(writer)
        integration, candidate = self.review_writer(writer)
        with patch.object(contracts, "suite", side_effect=TimeoutError("contract command timed out")):
            with self.assertRaises(TimeoutError):
                landing.land(integration["id"], candidate, "integrator-1")
        review = Path(integration["worktree"])
        (review / "unresolved.md").write_text("unresolved merge draft\n")
        with patch.object(contracts, "suite") as suite:
            with self.assertRaisesRegex(ValueError, "clean HEAD"):
                landing.land(integration["id"], candidate, "integrator-1")
            suite.assert_not_called()
        self.assertEqual(writer["status"], "review")
        self.assertNotIn("acceptance", writer)
        self.assertNotIn("tests-c", queues.landed("p"))
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
                                     ["python3", "-m", "unittest", f"tests.test_tests_{update}.A"], run="writer-" + update)
                integrator_run = "integrator-" + update
                tree = Path(writer["worktree"])
                (self.repo / f"{update}.py").write_text("def prerequisite(): return None\n")
                main = support.commit(self.repo, "land prerequisite after writer started")
                git.run(tree, update, "main")
                submitted = git.head(tree)
                receipt = self.finish_writer(writer)
                self.assertFalse(receipt["evidence"]["passing"])
                self.assertEqual(writer["base_commit"], self.base, "do not repair attribution by moving the base")
                self.assertEqual(writer["status"], "review")
                integration, candidate = self.review_writer(writer, run=integrator_run)
                landing.land(integration["id"], candidate, integrator_run)
                self.assertEqual((writer["status"], writer["acceptance"]["via"]), ("done", "tests"))
                self.assertEqual(writer["acceptance"]["worker_commit"], submitted)
                self.assertEqual(state.L["queue"][writer["id"]]["done"]["commit"], candidate)
                self.assertEqual(self.main(), main, "red tests stay off main")
                lifecycle.release(integrator_run, "run ended")

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
        self.assertEqual((self.main(), writer["status"]), (self.base, "failed"))

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
                                                     "via": "landing", "stage": "implementation",
                                                     "gate": {'suite': 2, 'failed': 0, 'red_on_main': 0}})
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
        result = landing.land(integration["id"], candidate, "integrator-1")
        self.assertEqual(result['acceptance']['gate'], {'suite': 2, 'failed': 1, 'red_on_main': 1})
        self.assertEqual(self.worker['acceptance']['gate'], result['acceptance']['gate'])
        self.assertEqual(state.L['queue'][self.worker['record']]['done']['gate'], result['acceptance']['gate'])
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
        self.assertEqual((self.main(), self.worker["status"]), (self.base, "failed"))

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
    def test_incorporation_cannot_bypass_missing_contract_authority(self):
        _, candidate, submitted = self.landing()
        git.run(self.repo, 'merge', '--ff-only', candidate)
        state.L['queue'][self.worker['record']]['depends'] = []
        self.worker['receipt']['evidence']['tests'] = []
        with self.assertRaisesRegex(ValueError, 'accepted test-contract dependency'):
            landing.incorporate(self.worker['id'], candidate, submitted, 'integrator-1')
        self.assertIsNone(self.worker.get('acceptance'))
        self.assertEqual(self.worker['status'], 'review')

    def test_cancelled_integration_cannot_complete_incorporation(self):
        integration, candidate, submitted = self.landing()
        git.run(self.repo, 'merge', '--ff-only', candidate)
        original = contracts.incorporated
        def cancelled(*args):
            original(*args)
            lifecycle.cancel_task(integration, 'user', 'withdraw review')
        with patch.object(contracts, 'incorporated', side_effect=cancelled):
            with self.assertRaises(ValueError):
                landing.incorporate(self.worker['id'], candidate, submitted, 'integrator-1')
        self.assertIsNone(self.worker.get('acceptance'))

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

    def test_review_locates_inactive_submitting_runs_probes_without_executing_them(self):
        self.implement()
        self.submit()
        self.assertIsNone(self.worker['agent'])
        receipt = json.loads(json.dumps(self.worker['receipt']))
        integration = self.integrate()
        self.act_as(integration)
        runtime = self.repo.parent / 'runtime'
        scratch = runtime / 'agents' / receipt['run'] / 'scratch'
        (scratch / 'vdo').mkdir(parents=True)
        probe = scratch / 'vdo/check.py'
        source = 'raise RuntimeError("diagnostic must only be located, not executed")\n'
        probe.write_text(source)
        other = runtime / 'agents' / 'older-attempt' / 'scratch'
        other.mkdir(parents=True)
        with patch.object(cli.opencode, 'STATE', runtime):
            result = self.run_command(cli.review)
        self.assertIn(str(scratch), result)
        self.assertNotIn(str(other), result)
        self.assertIn('own scratch', result)
        self.assertEqual(probe.read_text(), source)
        self.assertEqual(self.worker['receipt'], receipt)
        self.assertIsNone(integration['receipt'])

    def test_hidden_test_acceptance_is_not_reported_as_publication(self):
        self.worker['stage'] = 'test-contract'
        state.L['queue'][self.worker['record']]['stage'] = 'test-contract'
        (self.tree / 'tests/test_a.py').write_text(TESTS_A)
        manifest = json.loads((self.tree / 'tests/contracts.json').read_text())
        (self.tree / 'tests/contracts.json').write_text(json.dumps(manifest + [{'covers': ['code.py::a'], 'command': A}]))
        support.commit(self.tree, 'independent tests requiring missing implementation')
        self.submit()
        integration = self.integrate()
        self.act_as(integration)
        self.run_command(cli.review)
        before = self.main()
        result = self.run_command(cli.land, 'Review behavior contract')
        self.assertIn('accepted hidden test packet', result)
        self.assertIn('not published', result)
        self.assertNotIn('landed', result)
        self.assertEqual(self.main(), before)
        self.assertEqual(integration['receipt']['evidence']['gate']['suite'], 2)
        self.assertEqual(self.run_command(cli.land, 'Review behavior contract'), result)

    def test_cli_does_not_call_existing_failures_or_missing_measurements_green(self):
        (self.repo / 'tests/test_code.py').write_text(TESTS.replace('code.b(), 7', 'code.b(), 9'))
        self.base = support.commit(self.repo, 'existing failure on main')
        git.run(self.tree, 'merge', '--ff-only', 'main')
        self.implement()
        self.submit()
        integration = self.integrate()
        self.act_as(integration)
        self.run_command(cli.review)
        result = self.run_command(cli.land, 'Add behavior without causing the existing failure')
        self.assertIn('1 failed (1 already failed on main)', result)
        self.assertEqual(self.run_command(cli.land, 'Add behavior without causing the existing failure'), result)
        self.worker['acceptance'].pop('gate')  # legacy acceptance with no measurements
        historical = self.run_command(cli.land, 'Read historical acceptance')
        self.assertIn('Suite result not retained', historical)
        self.assertNotIn('0 failed', historical)

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

    def test_concurrent_packet_helpers_pass_finish_review_and_landing(self):
        self.worker["stage"] = "implementation"
        state.L["queue"][self.worker["record"]]["stage"] = "implementation"
        git.run(self.repo, "checkout", "work/tests-a")
        (self.repo / "tests/test_code.py").write_text("# packet helper\n" + TESTS)
        self.tests = support.commit(self.repo)
        state.L["queue"]["p:tests-a"]["done"]["commit"] = self.tests
        git.run(self.repo, "checkout", "main")
        (self.repo / "tests/test_code.py").write_text("# main helper\n" + TESTS)
        support.commit(self.repo)
        git.run(self.tree, "merge", "--ff-only", "main")
        self.implement()
        submitted = self.submit()
        integration = self.integrate()
        self.act_as(integration)
        self.run_command(cli.review)
        # A recovered integrator can already have a committed reviewed candidate, whose
        # squashed tests have no packet ancestry and whose message differs from land's.
        reviewed = support.commit(self.review, "Reviewed candidate before interruption")
        review = self.run_command(cli.review)
        self.assertIn("git diff main", review)
        self.assertIn("code.py", review, "review must show committed candidate changes")
        self.run_command(cli.review)
        self.assertEqual(git.head(self.review), reviewed)
        self.assertTrue(git.clean(self.review))
        self.assertEqual((self.review / "tests/test_code.py").read_text(), "# main helper\n# packet helper\n" + TESTS)
        self.run_command(cli.land, "Add a with both helpers")
        self.assertEqual((self.worker["status"], integration["status"]), ("done", "done"))
        self.assertEqual(self.worker["acceptance"]["worker_commit"], submitted)
        self.assertEqual((self.repo / "tests/test_code.py").read_text(), "# main helper\n# packet helper\n" + TESTS)
        self.assertIn("Worker: A implemented.", git.run(self.repo, "log", "-1", "--format=%B"))
        accepted = self.main()
        self.run_command(cli.land, "Retry with different wording")
        self.assertEqual(self.main(), accepted)

    def test_land_of_clean_main_still_requires_the_daemons_acceptance_gate(self):
        self.implement()
        self.submit()
        integration = self.integrate()
        self.act_as(integration)
        original = self.main()
        with self.assertRaisesRegex(ValueError, "without passing the landing gate"):
            self.run_command(cli.land, "A commit message cannot authorize landing")
        self.assertEqual(self.main(), original)
        self.assertEqual((self.worker["status"], integration["status"]), ("review", "running"))
        self.assertIsNone(self.worker.get("acceptance"))

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
        (Path(task["worktree"]) / ".knowledge").mkdir()
        (Path(task["worktree"]) / ".knowledge/plan.md").write_text("plan\n")
        support.commit(task["worktree"])
        (self.repo / "other.md").write_text("another agent landed meanwhile\n")
        support.commit(self.repo)
        self.run_command(cli.merge)
        self.assertTrue({".knowledge/plan.md", "other.md"} <= set(git.run(self.repo, "ls-files").split()))
        self.run_command(cli.finish, "complete", "Planned")
        self.assertEqual(task["status"], "done")

    def test_a_conflict_is_left_to_resolve_and_nothing_lands(self):
        task = self.manager()
        worktree = Path(task["worktree"])
        (worktree / ".knowledge").mkdir()
        (worktree / ".knowledge/plan.md").write_text("mine\n")
        support.commit(worktree)
        (self.repo / ".knowledge").mkdir()
        (self.repo / ".knowledge/plan.md").write_text("theirs\n")
        support.commit(self.repo)
        with self.assertRaises(SystemExit) as refused:
            self.run_command(cli.merge)
        self.assertIn(".knowledge/plan.md", str(refused.exception.code))
        self.assertEqual((self.repo / ".knowledge/plan.md").read_text(), "theirs\n")
        with self.assertRaises(SystemExit):
            self.run_command(cli.merge)  # still unresolved
        (worktree / ".knowledge/plan.md").write_text("theirs and mine\n")
        git.run(worktree, "add", ".knowledge/plan.md")
        git.run(worktree, "commit", "-q", "--no-edit")
        self.run_command(cli.merge)
        self.assertEqual((self.repo / ".knowledge/plan.md").read_text(), "theirs and mine\n")

    def test_manager_product_edits_and_reverted_edits_cannot_bypass_review(self):
        task=self.manager()
        original=self.main()
        (Path(task['worktree'])/'code.py').write_text('unreviewed implementation\n')
        support.commit(task['worktree'])
        with self.assertRaisesRegex(SystemExit,'only knowledge-tree'):
            self.run_command(cli.merge)
        self.assertEqual(self.main(),original)
        git.run(task['worktree'],'checkout',original,'--','code.py')
        support.commit(task['worktree'],'revert product edit')
        result=api.check_work({'caller':{'task':task['id'],'run':task['agent']}})
        self.assertFalse(result['ok'])
        self.assertTrue(any('code.py' in p for p in result['problems']))
        with self.assertRaisesRegex(ValueError,'only knowledge-tree'):
            api.dispatch('merge',{'commit':git.head(task['worktree']),
                                 'caller':{'task':task['id'],'run':task['agent']}})
        self.assertEqual(self.main(),original)

    def test_maintenance_publication_refuses_stale_run_and_candidate(self):
        task=self.manager()
        original=self.main()
        with self.assertRaisesRegex(ValueError,'not running'):
            api.dispatch('merge',{'commit':original,'caller':{'task':task['id'],'run':'stale'}})
        with self.assertRaisesRegex(ValueError,'current assigned'):
            api.dispatch('merge',{'commit':'wrong','caller':{'task':task['id'],'run':task['agent']}})
        self.assertEqual(self.main(),original)

    def test_a_worker_does_not_land_its_own_work(self):
        self.act_as(self.worker)
        self.implement()
        with self.assertRaisesRegex(SystemExit, "integrator"):
            self.run_command(cli.merge)
        self.assertEqual(self.main(), self.base)


if __name__ == "__main__":
    unittest.main()
