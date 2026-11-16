import subprocess
import json
import os
import unittest
from unittest.mock import patch

from cointos import cli, frontier, git, landing
from tests import support


class UpstreamPush(unittest.TestCase):
    def setUp(self):
        self.repo = support.repository(self)
        self.remote = self.repo.parent / 'upstream.git'
        git.run(self.repo, 'init', '--bare', '-q', str(self.remote))
        git.run(self.repo, 'remote', 'add', 'publish', str(self.remote))

    def configure(self):
        git.run(self.repo, 'config', 'branch.main.remote', 'publish')
        git.run(self.repo, 'config', 'branch.main.merge', 'refs/heads/accepted')

    def test_no_upstream_is_a_noop(self):
        self.assertEqual(git.push_upstream(self.repo, 'main')['status'], 'skipped')
        self.assertEqual(git.run(self.remote, 'for-each-ref'), '')

    def test_pushes_accepted_main_to_its_upstream_not_checked_out_review(self):
        self.configure()
        accepted = git.head(self.repo, 'main')
        git.run(self.repo, 'checkout', '-q', '-b', 'unreviewed')
        unreviewed = support.commit(self.repo, 'not accepted')
        self.assertNotEqual(accepted, unreviewed)
        result = git.push_upstream(self.repo, 'main')
        self.assertEqual(result['status'], 'pushed')
        self.assertEqual(git.head(self.remote, 'refs/heads/accepted'), accepted)
        self.assertEqual(git.run(self.repo, 'branch', '--show-current'), 'unreviewed')

    def test_non_fast_forward_never_overwrites_remote(self):
        self.configure()
        self.assertEqual(git.push_upstream(self.repo, 'main')['status'], 'pushed')
        git.run(self.repo, 'checkout', '-q', '-b', 'other-history')
        remote_commit = support.commit(self.repo, 'remote work')
        git.run(self.repo, 'push', '-q', 'publish', f'{remote_commit}:refs/heads/accepted')
        result = git.push_upstream(self.repo, 'main')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(git.head(self.remote, 'refs/heads/accepted'), remote_commit)
        accepted = {'ok': True, 'acceptance': {'via': 'landing'}, 'push': result}
        shown = frontier.file_view(accepted)
        self.assertEqual(shown['push']['status'], 'failed')
        self.assertNotIn('refs/heads', json.dumps(shown))
        self.assertNotIn(result['error'], json.dumps(shown))
        with patch.dict(os.environ, {'COINTOS_AGENT': 'reviewer'}):
            message = cli.acceptance_text(accepted)
        self.assertIn('verified and published', message)
        self.assertIn('accepted work remains recorded', message)
        self.assertNotIn(result['error'], message)
        with patch.dict(os.environ):
            os.environ.pop('COINTOS_AGENT', None)
            self.assertIn(result['error'], cli.acceptance_text(accepted))
        self.assertEqual(accepted['push'], result)

    def test_hidden_acceptance_does_not_push(self):
        accepted = {'ok': True, 'commit': 'a' * 40, 'acceptance': {'via': 'tests'}}
        with patch.object(git, 'push_upstream') as push:
            self.assertEqual(landing.push_after_acceptance({}, accepted), accepted)
        push.assert_not_called()

    def test_journal_failure_does_not_bounce_a_successful_push(self):
        accepted = {'ok': True, 'commit': 'a' * 40, 'acceptance': {'via': 'landing'}}
        where = {'name': 'p', 'path': str(self.repo), 'main_branch': 'main'}
        with patch.object(git, 'push_upstream', return_value={'status': 'pushed'}), \
                patch.object(landing, 'log', side_effect=OSError('journal unavailable')):
            result = landing.push_after_acceptance(where, accepted)
        self.assertTrue(result['ok'])
        self.assertEqual(result['acceptance'], accepted['acceptance'])
        self.assertEqual(result['push']['status'], 'pushed')
