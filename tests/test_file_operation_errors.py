"""Storage failures retain private diagnostics without sending agents into repository repair."""
import contextlib
import copy
import io
import json
import os
import unittest
from unittest.mock import patch

from cointos import api, cli, contracts, frontier, git, keys, projects, runs, state
from tests import support


class FileOperationErrors(unittest.TestCase):
    def test_composition_refusal_retains_paths_without_repository_repair_directions(self):
        error = contracts.CompositionError('CONFLICT: merge HEAD; fix conflicts and commit',
                                           main='a' * 40, packets=['b' * 40],
                                           failed_packet='b' * 40, paths=['tests/witness.c'])
        with patch.dict(runs.keys.ISSUED, {'author': 'fixture-key'}), \
                patch.object(runs, 'launch', side_effect=error), patch.object(runs, 'log') as log:
            runs.follow('author', self.worker, 'fixture-key')
        self.assertEqual(self.worker['note'], error.public)
        self.assertIn('tests/witness.c', self.worker['note'])
        self.assertTrue(any(c.kwargs.get('diagnostic') == str(error) for c in log.call_args_list))
        historical = {'task': {'note': str(error), 'composition_failure': error.evidence},
                      'composition_failure': error.evidence, 'queue': {'blocker': str(error)},
                      'failure': {'category': 'composition', 'error': str(error), 'composition': error.evidence}}
        shown = json.dumps(frontier.file_view(historical))
        self.assertIn('tests/witness.c', shown)
        for private in ('CONFLICT', 'HEAD', 'fix conflicts', 'a' * 40, 'b' * 40):
            self.assertNotIn(private, shown)

    def test_managed_jobs_do_not_republish_historical_composition_instructions(self):
        raw = 'CONFLICT: merge HEAD; fix conflicts and commit'
        task = {**self.worker, 'note': raw,
                'composition_failure': {'paths': ['tests/witness.c']}}
        before = dict(task)
        for managed in (False, True):
            with self.subTest(managed=managed), patch.dict(os.environ):
                os.environ.pop('COINTOS_AGENT', None)
                if managed: os.environ['COINTOS_AGENT'] = 'author'
                shown = cli.jobs_text({'tasks': {task['id']: task}})
                if managed:
                    self.assertIn('tests/witness.c', shown)
                    for token in ('CONFLICT', 'HEAD', 'commit'):
                        self.assertNotIn(token, shown)
                else:
                    self.assertIn(raw, shown)
        self.assertEqual(task, before)

    def test_completed_standalone_history_is_opt_in_but_queue_outcomes_and_failures_remain(self):
        closed = {**self.worker, 'id': 'p:old-repair', 'record': None, 'role': 'first-responder',
                  'status': 'done', 'note': 'obsolete packet abc versus landing def; reconstruct storage'}
        accepted = {**self.worker, 'id': 'p:accepted', 'status': 'done', 'note': 'accepted behavior'}
        active = {**closed, 'id': 'p:current-repair', 'status': 'running', 'note': 'diagnose current failure'}
        failed = {**closed, 'id': 'p:unresolved', 'status': 'failed', 'note': 'needs recovery'}
        state = {'tasks': {t['id']: t for t in [closed, accepted, active, failed]}}
        before = copy.deepcopy(state)
        with patch.dict(os.environ, {'COINTOS_AGENT': 'reader'}):
            shown = cli.jobs_text(state)
            self.assertNotIn(closed['id'], shown)
            self.assertNotIn('reconstruct storage', shown)
            for task in [accepted, active, failed]:
                self.assertIn(task['id'], shown)
            self.assertIn(closed['id'], cli.jobs_text(state, limit=None))
        with patch.dict(os.environ):
            os.environ.pop('COINTOS_AGENT', None)
            self.assertIn(closed['id'], cli.jobs_text(state))
        self.assertEqual(state, before)

    def test_task_inspection_exposes_only_the_readers_assigned_directory(self):
        reader = {'id': 'p:repair', 'role': 'first-responder', 'worktree': '/assigned/repair'}
        origin = {'id': 'p:worker', 'worktree': '/private/old-worker', 'retired': 'kept: uncommitted work',
                  'receipt': {'disposition': 'blocked', 'summary': 'required build failed',
                              'evidence': {'retired': 'product-specific evidence'}}}
        view = {'task': reader, 'origin_task': origin, 'binding_tests': [{'packet': 'p:tests'}]}
        before = copy.deepcopy(view)
        shown = frontier.agent_view(view, reader)
        self.assertEqual(shown['task']['workspace'], '/assigned/repair')
        self.assertNotIn('/private/old-worker', json.dumps(shown))
        self.assertNotIn('uncommitted work', json.dumps(shown))
        self.assertNotIn('retired', shown['origin_task'])
        self.assertEqual(shown['origin_task']['receipt'], origin['receipt'])
        self.assertEqual(shown['binding_tests'], view['binding_tests'])
        peer = frontier.agent_view({'task': origin}, reader)
        self.assertNotIn('workspace', peer['task'])
        self.assertEqual(view, before)

    def test_generated_landing_accounts_use_task_outcomes_without_storage_ids(self):
        commit = 'a' * 40
        account = 'work accepted at ' + commit
        task = {'item': 'work', 'note': 'complete: ' + account, 'result': account,
                'receipt': {'disposition': 'complete', 'summary': account,
                            'evidence': {'via': 'landing', 'commit': commit, 'suite': 7}}}
        shown = frontier.file_view(task)
        self.assertNotIn(commit, json.dumps(shown))
        self.assertEqual(shown['receipt']['summary'], 'work accepted')
        self.assertEqual(shown['receipt']['evidence']['suite'], 7)
        self.assertEqual(task['receipt']['summary'], account)

    def test_composition_api_refusal_has_private_operator_diagnostics(self):
        error = contracts.CompositionError('merge conflict with private artifact', paths=['tests/witness.c'])
        def refused(body):
            raise error
        with patch.dict(api.ACTIONS, {'fixture-composition': refused}), patch.object(api, 'log') as log:
            with self.assertRaises(api.ApiError) as caught:
                api.dispatch('fixture-composition', {'caller': support.caller(self.worker, 'author')})
            self.assertEqual(str(caught.exception), error.public)
            self.assertEqual(log.call_args.kwargs['diagnostic'], str(error))
            with self.assertRaises(contracts.CompositionError):
                api.dispatch('fixture-composition', {})

    def test_project_setup_failures_are_public_without_an_agent_caller(self):
        error = projects.SetupError('private Git identity diagnostic: commit HEAD')
        def refused(body):
            raise error
        with patch.dict(api.ACTIONS, {'fixture-setup': refused}), patch.object(api, 'log') as log:
            with self.assertRaises(api.ApiError) as caught:
                api.dispatch('fixture-setup', {})
            self.assertEqual(str(caught.exception), error.public)
            self.assertEqual(log.call_args.kwargs['diagnostic'], str(error))

    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        project = support.project(self, support.repository(self))
        self.worker = support.running(support.queued(project, 'work'), 'author', worktree=False)

    def test_agent_failure_is_file_level_while_operator_diagnostics_are_retained(self):
        def failed(body):
            return git.run('/nonexistent/cointos-test-repository', 'rev-parse', 'HEAD')
        with patch.dict(api.ACTIONS, {'fixture-storage-failure': failed}), patch.object(api, 'log') as log:
            with self.assertRaises(api.ApiError) as caught:
                api.dispatch('fixture-storage-failure', {'caller': support.caller(self.worker, 'author')})
            self.assertEqual(str(caught.exception), git.OperationError.public)
            self.assertNotIn('HEAD', str(caught.exception))
            self.assertIn('cannot change', log.call_args.kwargs['diagnostic'])
            with self.assertRaises(git.OperationError) as raw:
                api.dispatch('fixture-storage-failure', {})
            self.assertIn('cannot change', str(raw.exception))

    def test_launch_failure_receipt_does_not_expose_private_repository_diagnostics(self):
        with patch.dict(keys.ISSUED, {'author': 'fixture-key'}), \
             patch.object(runs, 'launch', side_effect=git.OperationError('fatal: object HEAD missing')), \
             patch.object(runs, 'log') as log:
            runs.follow('author', self.worker, 'fixture-key')
        self.assertEqual(self.worker['status'], 'failed')
        self.assertIn('CointOS could not complete file preparation', self.worker['note'])
        self.assertNotIn('HEAD', self.worker['note'])
        self.assertNotIn('fatal:', self.worker['note'])
        self.assertTrue(any(call.kwargs.get('diagnostic') == 'fatal: object HEAD missing' for call in log.call_args_list))

    def test_agent_receipt_presentation_keeps_handoff_evidence_but_hides_storage_identity(self):
        receipt = {'run': 'author', 'disposition': 'complete', 'summary': 'Continue the original obligation',
                   'evidence': {'commit': 'a' * 40, 'replacement': ['first'], 'suite': 7}}
        result = {'ok': True, 'receipt': receipt}
        with patch.object(cli, 'call', return_value=result):
            for managed in (False, True):
                with self.subTest(managed=managed), patch.dict(os.environ, clear=False):
                    os.environ.pop('COINTOS_AGENT', None)
                    if managed:
                        os.environ['COINTOS_AGENT'] = 'author'
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        cli.main(['replace', 'first'], acknowledge=False)
                    shown = json.loads(output.getvalue())['receipt']
                    self.assertEqual(shown['disposition'], 'complete')
                    self.assertEqual(shown['summary'], receipt['summary'])
                    self.assertEqual(shown['evidence']['replacement'], ['first'])
                    self.assertEqual(shown['evidence']['suite'], 7)
                    self.assertEqual('commit' in shown['evidence'], not managed)
