"""A wrong accepted witness can be corrected without bypassing independent review."""
import copy
from pathlib import Path
from unittest.mock import patch

from cointos import api, git, landing, lifecycle, packets, queues, runs, spawner, state, tasks
from tests import support
from tests.test_landing import Project


class Corrections(Project):
    def recovery_request(self):
        lifecycle.submit(self.worker['id'], 'worker-1', 'blocked', 'The accepted witness contradicts the contract')
        lifecycle.release('worker-1', 'blocked')
        operator, _ = tasks.request_repair(self.worker)
        support.running(operator, 'repair-run')
        body = {'project': 'p', 'packet': 'p:tests-a', 'name': 'correct-a',
                'brief': 'Correct the witness to the specified answer 41.',
                'summary': 'Correct the answer witness to the specified value',
                'relies_on': ['a'], 'reason': 'The contract says 41, not 42.',
                'caller': support.caller(operator, 'repair-run')}
        return operator, body

    def test_recovery_correction_request_completes_controller_without_accepting_product(self):
        operator, body = self.recovery_request()
        old_acceptance = copy.deepcopy(queues.records()['p:tests-a']['done'])
        result = api.dispatch('correct-tests', body)
        self.assertEqual((operator['status'], result['receipt']['disposition']), ('done', 'complete'))
        self.assertEqual(result['receipt']['evidence']['test_correction'], result['item'])
        self.assertEqual(self.worker['status'], 'failed')
        self.assertEqual(queues.records()['p:tests-a']['done'], old_acceptance)
        self.assertEqual(landing.tests_of(self.worker), [self.tests])
        lifecycle.release('repair-run', 'delivered')
        self.assertEqual(api.dispatch('correct-tests', body), result)
        for changed in ({'reason': 'Different evidence'}, {'caller': support.caller(operator, 'foreign')}):
            with self.assertRaises(ValueError):
                api.dispatch('correct-tests', {**body, **changed})

    def test_correction_handoff_refuses_dirty_artifacts_without_creating_partial_work(self):
        operator, body = self.recovery_request()
        (Path(operator['worktree']) / 'repair-note').write_text('Uncommitted diagnosis')
        before = copy.deepcopy(state.L)
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            api.dispatch('correct-tests', body)
        self.assertEqual(state.L, before)

    def test_existing_correction_is_a_terminal_handoff_without_duplicate_work(self):
        operator, body = self.recovery_request()
        existing = self.propose()
        result = api.dispatch('correct-tests', body)
        self.assertEqual(result['item'], existing['item'])
        self.assertEqual(operator['receipt']['disposition'], 'complete')
        self.assertEqual(sum(bool(r.get('correction')) for r in queues.records().values()), 1)

    def test_held_existing_correction_cannot_complete_recovery(self):
        operator, body = self.recovery_request()
        existing = self.propose()
        queues.records()[existing['item']]['held_by'] = 'user'
        before = copy.deepcopy(state.L)
        with self.assertRaisesRegex(ValueError, 'handback'):
            api.dispatch('correct-tests', body)
        self.assertEqual(state.L, before)

    def propose(self, name='correct-a'):
        return api.dispatch('correct-tests', {
            'project': 'p', 'packet': 'p:tests-a', 'name': name,
            'brief': 'The specified answer is 41; correct the witness and preserve B.',
            'summary': 'Correct the answer witness to the specified value',
            'relies_on': ['a'], 'reason': 'The independent contract says 41, not 42.'})

    def correction(self):
        result = self.propose()
        record = queues.records()[result['item']]
        task = tasks.create('item', self.project, record['item'], record['brief'], [4],
                            item=record['item'], record_version=record['version'])
        support.running(task, 'test-author', worktree=False)
        with patch.object(runs.opencode, 'launch'):
            runs.launch('test-author', task, 'fixture-key')
        return task, Path(task['worktree'])

    def test_invalid_packet_is_binding_until_review_then_preserved_code_resumes(self):
        code = self.implement('41')
        with self.assertRaisesRegex(ValueError, 'fail'):
            self.finish()
        lifecycle.submit(self.worker['id'], 'worker-1', 'blocked', 'The accepted witness expects the wrong answer')
        lifecycle.release('worker-1', 'blocked')
        old_receipt = copy.deepcopy(queues.records()['p:tests-a']['done'])
        task, tree = self.correction()
        self.assertEqual(task['base_commit'], self.tests)
        self.assertEqual(git.head(tree), self.tests, 'test author starts with the exact hidden packet')
        witness = tree / 'tests/test_a.py'
        witness.write_text(witness.read_text().replace('42', '41'))
        corrected = support.commit(tree, 'correct invalid witness independently')
        api.dispatch('finish', {'caller': support.caller(task, 'test-author'),
                               'outcome': 'complete', 'detail': 'Witness corrected against the contract'})
        self.assertEqual(landing.tests_of(self.worker), [self.tests], 'submission is not review')
        self.assertEqual(self.worker['status'], 'failed')
        reviewer = tasks.create('integrate', self.project, 'integrate-correction', task['brief'], [2],
                                item=task['item'], worker=task['id'])
        support.running(reviewer, 'test-reviewer')
        git.run(reviewer['worktree'], 'merge', '--no-edit', corrected)
        candidate = git.head(reviewer['worktree'])
        landing.land(reviewer['id'], candidate, 'test-reviewer')
        self.assertEqual(queues.records()['p:tests-a']['done'], old_receipt)
        self.assertEqual(queues.records()['p:tests-a']['corrected_by'], task['record'])
        self.assertEqual(self.worker['status'], 'waiting')
        self.assertEqual(git.head(self.tree), code, 'review correction cannot rewrite the implementation')
        self.assertEqual(landing.tests_of(self.worker), [candidate])
        support.running(self.worker, 'worker-2')
        receipt = api.dispatch('finish', {'caller': support.caller(self.worker, 'worker-2'),
                                         'outcome': 'complete', 'detail': 'Preserved implementation passes corrected contract'})['receipt']
        self.assertEqual(receipt['evidence']['commit'], code)
        self.assertEqual(self.worker['status'], 'review')

    def test_correction_launch_refuses_reset_branch_without_spending_or_rewriting_work(self):
        task, tree = self.correction()
        # A repair moved the worker's branch to main, losing the hidden packet.
        git.run(tree, 'reset', '--hard', self.base)
        (tree / 'preserved-draft').write_text('unfinished work')
        before = copy.deepcopy(state.L)
        for existing_checkout in (True, False):
            with self.subTest(existing_checkout=existing_checkout):
                if not existing_checkout:
                    (tree / 'preserved-draft').unlink()
                    git.remove_worktree(self.repo, str(tree))
                with patch.object(runs.opencode, 'launch') as launch:
                    with self.assertRaisesRegex(ValueError, 'does not contain accepted packet'):
                        runs.launch('test-author', task, 'fixture-key')
                    launch.assert_not_called()
                self.assertEqual(git.head(tree), self.base)
                self.assertEqual(state.L, before)
                if existing_checkout:
                    self.assertEqual((tree / 'preserved-draft').read_text(), 'unfinished work')

    def test_correction_relaunch_retains_valid_descendant_and_uncommitted_work(self):
        task, tree = self.correction()
        witness = tree / 'tests/test_a.py'
        witness.write_text(witness.read_text().replace('42', '41'))
        corrected = support.commit(tree, 'preserved correction')
        (tree / 'preserved-draft').write_text('unfinished work')
        with patch.object(runs.opencode, 'launch') as launch:
            runs.launch('test-author', task, 'fixture-key')
            launch.assert_called_once()
        self.assertEqual(git.head(tree), corrected)
        self.assertEqual(task['base_commit'], self.tests)
        self.assertEqual((tree / 'preserved-draft').read_text(), 'unfinished work')

    def test_duplicate_requests_share_the_same_correction_and_history_retains_both_packets(self):
        first = self.propose()
        self.assertEqual(self.propose('another-name')['item'], first['item'])
        self.assertEqual(sum(bool(r.get('correction')) for r in queues.records().values()), 1)
        protected = queues.history_frontier({self.worker['id']})
        self.assertIn('p:tests-a', protected)
        self.assertIn(first['item'], protected)

    def test_brief_revision_cannot_readmit_consumers_before_correction_review(self):
        self.implement('41')
        with self.assertRaisesRegex(ValueError, 'fail'):
            self.finish()
        lifecycle.submit(self.worker['id'], 'worker-1', 'blocked', 'The accepted witness is incorrect')
        lifecycle.release('worker-1', 'blocked')
        task, tree = self.correction()
        independent = queues.add(self.project, 'queued', 'independent', 'Independent implementation')
        api.dispatch('revise', {'item': self.worker['record'], 'brief': self.worker['brief'] +
                               '\nResume the preserved implementation after the pending correction.',
                               'reason': 'Preserve code while repairing its contract'})
        record = queues.records()[self.worker['record']]
        ready = {'p': queues.readiness(queues.live('p'), queues.landed('p'))}
        self.assertEqual(self.worker['status'], 'waiting')
        self.assertEqual(ready['p'][record['item']], 'waiting')
        self.assertFalse(spawner.runnable(self.worker, ready))
        self.assertEqual(ready['p'][task['item']], 'ready', 'a correction never waits on itself')
        self.assertEqual(ready['p'][independent], 'ready', 'unrelated work remains eligible')
        self.assertEqual(landing.tests_of(self.worker), [self.tests], 'old acceptance stays binding')

        witness = tree / 'tests/test_a.py'
        witness.write_text(witness.read_text().replace('42', '41'))
        corrected = support.commit(tree, 'correct independently')
        api.dispatch('finish', {'caller': support.caller(task, 'test-author'),
                               'outcome': 'complete', 'detail': 'Witness corrected against the contract'})
        self.assertFalse(spawner.runnable(self.worker, {'p': queues.readiness(queues.live('p'), queues.landed('p'))}))
        reviewer = tasks.create('integrate', self.project, 'review-correction', task['brief'], [2],
                                item=task['item'], worker=task['id'])
        support.running(reviewer, 'test-reviewer')
        git.run(reviewer['worktree'], 'merge', '--no-edit', corrected)
        landing.land(reviewer['id'], git.head(reviewer['worktree']), 'test-reviewer')
        self.assertTrue(spawner.runnable(self.worker, {'p': queues.readiness(queues.live('p'), queues.landed('p'))}))

    def test_waiting_consumer_review_cannot_occupy_the_correction_review_slot(self):
        self.implement('42')
        self.finish()
        consumer = tasks.create('integrate', self.project, 'review-consumer', self.worker['brief'], [2],
                                item=self.worker['item'], worker=self.worker['id'])
        correction, tree = self.correction()
        witness = tree / 'tests/test_a.py'
        witness.write_text(witness.read_text().replace('42', '41'))
        support.commit(tree, 'correct independently')
        api.dispatch('finish', {'caller': support.caller(correction, 'test-author'),
                               'outcome': 'complete', 'detail': 'Witness corrected against the contract'})
        ready = {'p': queues.readiness(queues.live('p'), queues.landed('p'))}
        self.assertFalse(spawner.runnable(consumer, ready))
        options = spawner.integrations()
        self.assertEqual(len(options), 1)
        selected = options[0][1]()
        self.assertEqual(selected['worker'], correction['id'])
        self.assertTrue(spawner.runnable(selected, ready))

    def test_cancelling_a_correction_removes_only_its_admission_wait(self):
        correction = self.propose()['item']
        ready = queues.readiness(queues.live('p'), queues.landed('p'))
        self.assertEqual(ready[self.worker['item']], 'waiting')
        api.dispatch('cancel', {'items': [correction], 'reason': 'Correction withdrawn'})
        ready = queues.readiness(queues.live('p'), queues.landed('p'))
        self.assertEqual(ready[self.worker['item']], 'ready')
        self.assertEqual(landing.tests_of(self.worker), [self.tests])

    def test_correction_cannot_be_accepted_against_a_changed_contract(self):
        task, tree = self.correction()
        queues.records()['p:tests-a']['done']['commit'] = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'changed'):
            packets.require_current(task)

    def test_commentary_without_a_test_change_cannot_replace_the_accepted_contract(self):
        task, tree = self.correction()
        (tree / 'README.md').write_text('The witness should be corrected.\n')
        commit = support.commit(tree, 'diagnosis only')
        with self.assertRaisesRegex(ValueError, 'must change the accepted tests'):
            packets.require_changed_tests(task, str(tree), commit, self.project['test_policy'])

    def test_correction_preserves_explicit_hold_and_refreshes_only_once(self):
        self.implement('41')
        lifecycle.hold(self.worker['id'], 'user')
        task, tree = self.correction()
        witness = tree / 'tests/test_a.py'
        witness.write_text(witness.read_text().replace('42', '41'))
        commit = support.commit(tree, 'correct witness')
        record = queues.records()[task['record']]
        queues.finish(record, commit=commit, via='tests')
        lifecycle.activate_correction(record, task['id'])
        owned = queues.records()[self.worker['record']]
        self.assertEqual(owned['held_by'], 'user')
        self.assertEqual(owned['version'], 2)
        lifecycle.activate_correction(record, task['id'])
        self.assertEqual(owned['version'], 2)
        self.assertEqual(self.worker['record_version'], 2)

    def test_implementer_cannot_request_replacement_of_its_acceptance_tests(self):
        with self.assertRaisesRegex(ValueError, 'owning manager'):
            api.dispatch('correct-tests', {'project': 'p', 'caller': support.caller(self.worker, 'worker-1')})
