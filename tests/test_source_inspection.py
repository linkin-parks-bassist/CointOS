"""Daemon-owned source views preserve editor work and private boundaries."""
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from cointos import api, artifacts, cli, frontier, git, inspection, mcp, opencode, state, tasks
from tests import support


class SourceInspection(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.repo = support.repository(self)
        (self.repo / 'code.txt').write_text('accepted\nsecond\nthird\n')
        secret = self.repo / '.knowledge/answer.md'
        secret.parent.mkdir()
        secret.write_text('maintained answer\n')
        support.commit(self.repo)
        self.project = support.project(self, self.repo)
        self.worker = support.running(support.queued(self.project, 'source'), 'worker')
        self.tree = Path(self.worker['worktree'])
        self.manager = support.running(support.queued(self.project, 'manager', kind='command'), 'manager', worktree=False)
        self.caller = support.caller(self.manager, 'manager')

    def read(self, **body):
        return api.dispatch('source', {'caller': self.caller, **body})

    def test_project_reads_accepted_files_and_never_editor_drafts(self):
        (self.repo / 'code.txt').write_text('private editor draft\n')
        (self.repo / 'draft.txt').write_text('unpublished\n')
        self.assertEqual(self.read(project='p')['files'], ['code.txt'])
        result = self.read(project='p', path='code.txt', start=2, limit=1)
        self.assertEqual(result['lines'], ['second'])
        self.assertEqual(result['next'], 3)
        self.assertEqual((self.repo / 'code.txt').read_text(), 'private editor draft\n')

    def test_task_lists_authored_files_and_reads_its_current_text(self):
        (self.tree / 'code.txt').write_text('unfinished\n')
        (self.tree / 'extra.txt').write_text('new\n')
        self.assertEqual(self.read(task=self.worker['id'], limit=1)['files'], ['code.txt'])
        self.assertEqual(self.read(task=self.worker['id'], start=2)['files'], ['extra.txt'])
        self.assertEqual(self.read(task=self.worker['id'], path='code.txt')['lines'], ['unfinished'])

    def test_traversal_metadata_knowledge_and_symlink_escapes_are_refused(self):
        (self.tree / 'outside').symlink_to(self.repo / 'code.txt')
        (self.tree / 'answer-alias').symlink_to('.knowledge/answer.md')
        (self.tree / 'allowed-alias').symlink_to('code.txt')
        for path in ('../code.txt', str(self.repo / 'code.txt'), '.git/config', '.knowledge/answer.md',
                     'outside', 'answer-alias'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.read(task=self.worker['id'], path=path)
        self.assertEqual(self.read(task=self.worker['id'], path='allowed-alias')['lines'][0], 'accepted')
        (self.tree / 'binary').write_bytes(b'\xff')
        with self.assertRaisesRegex(ValueError, 'UTF-8'):
            self.read(task=self.worker['id'], path='binary')

    def test_replaced_link_during_open_cannot_escape(self):
        original = inspection.os.open
        def swapped(path, flags, **kwargs):
            if path == 'code.txt' and 'dir_fd' in kwargs:
                (self.tree / 'code.txt').unlink()
                (self.tree / 'code.txt').symlink_to(self.repo / 'code.txt')
            return original(path, flags, **kwargs)
        with patch.object(inspection.os, 'open', side_effect=swapped), self.assertRaisesRegex(ValueError, 'unavailable'):
            self.read(task=self.worker['id'], path='code.txt')

    def test_retained_material_survives_workspace_removal(self):
        (self.tree / 'code.txt').write_text('retained unfinished\n')
        self.worker['agent'] = None
        with patch.object(opencode, 'active', return_value=False):
            saved = artifacts.preserved(self.worker, self.project)
        self.worker.setdefault('material_snapshots', {})[artifacts.material_key(artifacts.source_reference(self.worker))] = saved
        shutil.rmtree(self.tree)
        self.assertEqual(self.read(task=self.worker['id'], path='code.txt')['lines'], ['retained unfinished'])

    def test_validation_and_worker_boundary(self):
        for body in ({}, {'task': self.worker['id'], 'project': 'p'}, {'project': 'p', 'start': 0},
                     {'project': 'p', 'limit': True}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.read(**body)
        caller = support.caller(self.worker, 'worker')
        with self.assertRaisesRegex(ValueError, 'own prepared files'):
            api.dispatch('source', {'caller': caller, 'project': 'p'})
        self.assertEqual(api.dispatch('source', {'caller': caller, 'task': self.worker['id'],
                                               'path': 'code.txt'})['lines'][0], 'accepted')

    def test_recovery_prepares_retained_files_without_changing_author_or_editor_drafts(self):
        import contextlib
        import subprocess
        import sys
        (self.tree / 'check.py').write_text('print("retained diagnostic")\n')
        (self.tree / 'code.txt').write_text('unfinished\n')
        git.run(self.tree, 'add', 'code.txt')
        (self.tree / 'code.txt').write_text('unfinished plus unstaged\n')
        (self.repo / 'code.txt').write_text('private editor draft\n')
        before = (git.head(self.tree), git.run(self.tree, 'diff', '--cached'), git.run(self.tree, 'diff'))
        self.worker.update(agent=None, status='failed', receipt={'run': 'worker', 'disposition': 'blocked'})
        responder = support.running(tasks.create('first-response', self.project, 'recover', 'Diagnose.', [1],
                                   repair_origin=frontier.origin(self.worker)), 'responder', worktree=False)
        scratch = opencode.run_dir('responder') / 'scratch'
        scratch.mkdir(parents=True, exist_ok=True)
        body = {'caller': support.caller(responder, 'responder')}
        with patch.object(opencode, 'quiesce', return_value=contextlib.nullcontext()), \
                patch.object(opencode, 'active', return_value=False):
            result = api.dispatch('diagnostic', body)
        prepared = Path(result['directory'])
        self.assertTrue(prepared.is_relative_to(scratch))
        self.assertIn('Retained assignment files', result['note'])
        self.assertEqual((prepared / 'code.txt').read_text(), 'unfinished plus unstaged\n')
        self.assertFalse((prepared / '.git').exists())
        self.assertFalse((prepared / '.knowledge').exists())
        check = subprocess.run([sys.executable, 'check.py'], cwd=prepared, capture_output=True, text=True)
        self.assertEqual((check.returncode, check.stdout.strip()), (0, 'retained diagnostic'))
        self.assertEqual(before, (git.head(self.tree), git.run(self.tree, 'diff', '--cached'), git.run(self.tree, 'diff')))
        self.assertEqual((self.repo / 'code.txt').read_text(), 'private editor draft\n')
        for extra in ({'project': 'p'}, {'path': 'check.py'}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'stopped current assignment'):
                api.dispatch('diagnostic', {**body, **extra})
        for field, value in (('agent', 'still-running'), ('cancelled', True), ('status', 'done')):
            previous = self.worker.get(field)
            self.worker[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'stopped current assignment'):
                api.dispatch('diagnostic', body)
            self.worker[field] = previous
        state.L['queue'][self.worker['record']]['version'] += 1
        with self.assertRaisesRegex(ValueError, 'stopped current assignment'):
            api.dispatch('diagnostic', body)

    def test_read_does_not_hold_ledger_lock_and_cli_mcp_have_one_surface(self):
        def read(*args, **kwargs):
            self.assertFalse(state.LOCK._is_owned())
            return {'start': 1, 'lines': ['evidence'], 'next': None}
        with patch.object(inspection, 'files', side_effect=read):
            self.assertEqual(self.read(project='p')['lines'], ['evidence'])
        args = cli.parser().parse_args(['source', '--project', 'p', '--path', 'code.txt'])
        with patch.object(cli, 'call', return_value={'start': 1, 'lines': ['evidence'], 'next': 2}):
            self.assertEqual(cli.source_files(args), '1: evidence\nContinue with --start 2.')
        self.assertIn('source', [tool['name'] for tool in mcp.catalogue('manager')])
        self.assertNotIn('source', [tool['name'] for tool in mcp.catalogue('worker')])
