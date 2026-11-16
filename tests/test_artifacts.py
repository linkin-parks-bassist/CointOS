"""The agent-facing lifecycle needs files and behavioral decisions, never Git commands."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cointos import api, artifacts, git, lifecycle, opencode, state
from tests import support
from tests.test_landing import CODE, Project


class Files(Project):
    def request(self, task, action, **body):
        return api.dispatch(action, {'caller': support.caller(task, task['agent']), **body})

    def submit_files(self):
        (self.tree / 'code.py').write_text(CODE.replace('raise NotImplementedError', 'return 42'))
        return self.request(self.worker, 'finish', outcome='complete', detail='A implemented.')

    def test_files_submit_review_and_accept_without_client_commits(self):
        git.insulate(self.tree)
        self.assertFalse((self.tree / '.git').exists())
        before = git.head(self.tree)
        submitted = self.submit_files()['receipt']
        self.assertNotEqual(submitted['evidence']['commit'], before)
        lifecycle.release('worker-1', 'receipt delivered')
        integration = self.integrate()
        git.insulate(self.review)
        report = self.request(integration, 'review')
        self.assertIn('return 42', report['changes'])
        self.assertNotIn('diff --git ', report['changes'])
        self.assertNotIn('\nindex ', report['changes'])
        self.assertTrue((self.review / 'tests/test_a.py').is_file())
        result = self.request(integration, 'land', summary='Reviewed A and its tests.')
        self.assertEqual(result['acceptance']['via'], 'landing')
        self.assertEqual(self.worker['status'], 'done')
        self.assertEqual(git.show(self.repo, 'main', 'code.py'), CODE.replace('raise NotImplementedError', 'return 42'))


    def test_submission_retry_reuses_exact_capture_and_receipt(self):
        first = self.submit_files()
        original = git.head(self.tree)
        second = api.dispatch('finish', {'caller': support.caller(self.worker, 'worker-1'),
                                        'outcome': 'complete', 'detail': 'A implemented.'})
        self.assertEqual(first, second)
        self.assertEqual(git.head(self.tree), original)

    def test_capture_refuses_protected_edits_without_staging_or_losing_files(self):
        original = git.head(self.tree)
        protected = self.tree / 'tests/test_code.py'
        protected.write_text('invalid replacement')
        with self.assertRaisesRegex(ValueError, 'outside the assigned stage'):
            self.submit_files()
        self.assertEqual(git.head(self.tree), original)
        self.assertEqual(protected.read_text(), 'invalid replacement')
        self.assertTrue(git.ok(self.tree, 'diff', '--cached', '--quiet'))

    def test_new_accepted_product_requires_renewed_review(self):
        self.submit_files()
        lifecycle.release('worker-1', 'receipt delivered')
        integration = self.integrate()
        self.request(integration, 'review')
        (self.repo / 'README.md').write_text('Accepted independent work.\n')
        support.commit(self.repo)
        with self.assertRaisesRegex(ValueError, 'inspect cointos_review'):
            self.request(integration, 'land', summary='Stale approval')
        self.assertEqual(self.worker['status'], 'review')
        report = self.request(integration, 'review')
        self.assertNotIn('README.md', report['changes'])
        self.request(integration, 'land', summary='Reviewed against current product')
        self.assertEqual(self.worker['status'], 'done')

    def test_failed_composition_never_leaves_markers_in_reviewer_workspace(self):
        self.submit_files()
        lifecycle.release('worker-1', 'receipt delivered')
        integration = self.integrate()
        original = git.head(self.review)
        (self.repo / 'code.py').write_text(CODE.replace('raise NotImplementedError', 'return 99'))
        support.commit(self.repo)
        with self.assertRaisesRegex(ValueError, 'behavioral reconciliation.*code.py'):
            self.request(integration, 'review')
        self.assertEqual(git.head(self.review), original)
        self.assertTrue(git.clean(self.review))
        self.assertNotIn('<<<<<<<', (self.review / 'code.py').read_text())

    def test_blocked_worker_can_preserve_unfinished_files_without_committing(self):
        before = git.head(self.tree)
        (self.tree / 'unfinished.txt').write_text('Preserve this partial investigation')
        result = self.request(self.worker, 'finish', outcome='blocked', detail='Prerequisite is missing')
        self.assertEqual(result['receipt']['disposition'], 'blocked')
        self.assertEqual(git.head(self.tree), before)
        self.assertTrue((self.tree / 'unfinished.txt').exists())


class SourceIsolation(unittest.TestCase):
    def test_kernel_allows_source_work_but_denies_git_and_other_workspace_reads_and_writes(self):
        support.fresh_ledger(self)
        repo = support.repository(self)
        (repo / 'source.txt').write_text('accepted source')
        support.commit(repo)
        root = repo.parent
        tree, directory = root / 'assigned', root / 'run'
        directory.mkdir()
        git.add_worktree(repo, str(tree), 'work/assigned', 'main')
        git.insulate(tree)
        metadata = git.workspace_context(tree)[1]
        (tree / 'escape').symlink_to(repo, target_is_directory=True)
        task = {'id': 'p:assigned', 'kind': 'item', 'role': 'worker', 'stage': 'implementation',
                'place': 'p', 'worktree': str(tree), 'branch': 'work/assigned'}
        writes = opencode.write_paths(task, directory)
        reads = opencode.read_paths(task, directory)
        script = '''
import pathlib, subprocess, sys
repo, metadata = map(pathlib.Path, sys.argv[1:])
assert pathlib.Path('source.txt').read_text() == 'accepted source'
pathlib.Path('result.txt').write_text('new work')
for path in (repo / 'source.txt', repo / '.git/config', metadata / 'HEAD', pathlib.Path('escape/source.txt')):
    try: path.read_bytes()
    except PermissionError: pass
    else: raise AssertionError('external read succeeded: ' + str(path))
for path in (repo / 'source.txt', metadata / 'HEAD'):
    try: path.write_text('damage')
    except PermissionError: pass
    else: raise AssertionError('external write succeeded: ' + str(path))
for command in (['git', 'status'], ['git', '--git-dir=' + str(metadata), 'log', '-1']):
    result = subprocess.run(command, capture_output=True)
    assert result.returncode != 0, command
'''
        guard = Path(opencode.__file__).with_name('worktree_guard.py')
        result = subprocess.run([sys.executable, str(guard), json.dumps(writes), sys.executable, '-c', script,
                                 str(repo), str(metadata)], cwd=tree,
                                env={**os.environ, 'COINTOS_READ_PATHS': json.dumps(reads)},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((tree / 'result.txt').read_text(), 'new work')
        self.assertEqual((repo / 'source.txt').read_text(), 'accepted source')
        git.remove_worktree(repo, str(tree))
        self.assertFalse(tree.exists())

    def test_capture_thaws_after_failure_and_recovery_only_thaws_owned_freezes(self):
        with tempfile.TemporaryDirectory() as root, patch.object(opencode, 'STATE', Path(root)):
            directory = opencode.run_dir('fixture')
            directory.mkdir(parents=True)
            with patch.object(opencode.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'capture failed'):
                    with opencode.quiesce('fixture'):
                        raise ValueError('capture failed')
                self.assertEqual([c.args[0][2] for c in run.call_args_list], ['freeze', 'thaw'])
                run.reset_mock()
                opencode.thaw_capture('fixture')
                run.assert_not_called()
                (directory / 'capture-freeze.json').write_text(json.dumps({'run': 'fixture'}))
                opencode.thaw_capture('fixture')
                self.assertEqual(run.call_args.args[0][2], 'thaw')

