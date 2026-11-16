"""Branchless coordination has private scratch, policy-selected knowledge and source brokers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from cointos import api, cli, kt, metrics, opencode, prompts, runs, state, tasks
from tests import support


class ObserverIsolation(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.repo = support.repository(self)
        (self.repo / 'check.py').write_text('print("accepted suite")\n')
        support.commit(self.repo)
        self.project = support.project(self, self.repo)
        self.runtime = self.repo.parent / 'runtime'
        self.enterContext(patch.object(opencode, 'STATE', self.runtime))
        self.observer = support.running(tasks.create('test-audit', tasks.SYSTEM, 'audit', 'Audit.', [6]),
                                        'audit', worktree=False)
        self.run = opencode.run_dir('audit')
        (self.run / 'scratch').mkdir(parents=True)

    def prepare_launch(self):
        with patch.object(opencode, 'launch', return_value=None) as launched:
            runs.launch('audit', self.observer, 'fixture')
        return launched.call_args

    def test_launch_uses_stable_private_workspace_without_repository_discovery(self):
        called = self.prepare_launch()
        workspace = Path(self.observer['worktree'])
        self.assertEqual(workspace, opencode.agent_data(self.observer) / 'workspace')
        self.assertEqual(state.L['tasks'][self.observer['id']]['worktree'], str(workspace))
        self.assertFalse((workspace / '.git').exists())
        self.assertEqual(called.args[2]['worktree'], str(workspace))
        (workspace / 'note').write_text('retain evidence')
        self.prepare_launch()
        self.assertEqual((workspace / 'note').read_text(), 'retain evidence')
        guide = prompts.place_text(self.observer, tasks.SYSTEM)
        self.assertIn('cointos_source', guide)
        self.assertNotIn('installed CointOS runtime', guide)

    def test_replaced_workspace_cannot_turn_launch_into_shared_runtime_access(self):
        self.prepare_launch()
        workspace = Path(self.observer['worktree'])
        workspace.rmdir()
        workspace.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'private working directory is a link'):
            self.prepare_launch()

    def test_kernel_denies_peer_source_and_metadata_but_allows_scratch_and_permitted_knowledge(self):
        self.prepare_launch()
        workspace = Path(self.observer['worktree'])
        knowledge = self.repo.parent / 'allowed-knowledge'
        knowledge.mkdir()
        (knowledge / 'answer.md').write_text('authorized answer')
        (knowledge / '.git').mkdir()
        (knowledge / '.git/HEAD').write_text('private metadata')
        (workspace / 'escape').symlink_to(self.repo, target_is_directory=True)
        writes = opencode.write_paths(self.observer, self.run)
        with patch.object(kt, 'readable_roots', return_value=[knowledge]) as roots:
            reads = opencode.read_paths(self.observer, self.run)
        roots.assert_called_once_with(opencode.ROOT)
        script = '''
from pathlib import Path
import subprocess, sys
repo, knowledge, scratch = map(Path, sys.argv[1:])
Path('note').write_text('local evidence')
(scratch / 'probe').write_text('scratch result')
assert (knowledge / 'answer.md').read_text() == 'authorized answer'
for path in (repo / 'check.py', repo / '.git/config', knowledge / '.git/HEAD', Path('escape/check.py')):
    try: path.read_bytes()
    except PermissionError: pass
    else: raise AssertionError('unexpected read: ' + str(path))
for path in (repo / 'check.py', knowledge / 'answer.md'):
    try: path.write_text('damage')
    except PermissionError: pass
    else: raise AssertionError('unexpected write: ' + str(path))
assert subprocess.run(['git', 'status'], capture_output=True).returncode != 0
'''
        guard = Path(opencode.__file__).with_name('worktree_guard.py')
        result = subprocess.run([sys.executable, str(guard), json.dumps(writes), sys.executable, '-c', script,
                                 str(self.repo), str(knowledge), str(self.run / 'scratch')], cwd=workspace,
                                env={**os.environ, 'COINTOS_READ_PATHS': json.dumps(reads)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_registry_replacement_remains_readable_without_policy_write_access(self):
        self.prepare_launch()
        home = self.repo.parent / 'home'
        tools = home / '.knowledge/.tools'
        tools.mkdir(parents=True)
        registry = tools / 'roots.json'
        registry.write_text('old policy')
        writes = opencode.write_paths(self.observer, self.run)
        with patch.object(Path, 'home', return_value=home), \
                patch.object(kt, 'readable_roots', return_value=[]):
            reads = opencode.read_paths(self.observer, self.run)
        script = '''
from pathlib import Path
import sys
registry = Path(sys.argv[1])
assert registry.read_text() == 'old policy'
print('ready', flush=True)
sys.stdin.readline()
assert registry.read_text() == 'new policy'
try: registry.write_text('unauthorized policy')
except PermissionError: pass
else: raise AssertionError('policy write permitted')
'''
        guard = Path(opencode.__file__).with_name('worktree_guard.py')
        process = subprocess.Popen([sys.executable, str(guard), json.dumps(writes),
                                    sys.executable, '-c', script, str(registry)],
                                   cwd=self.observer['worktree'], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env={**os.environ, 'COINTOS_READ_PATHS': json.dumps(reads)})
        try:
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            replacement = tools / 'replacement'
            replacement.write_text('new policy')
            replacement.replace(registry)
            _, stderr = process.communicate('continue\n', timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(registry.read_text(), 'new policy')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_auditor_prepares_accepted_files_and_runs_suite_without_editor_or_storage_data(self):
        self.prepare_launch()
        (self.repo / 'check.py').write_text('raise RuntimeError("editor draft")\n')
        (self.repo / 'private').write_text('editor-only')
        def pause(agent):
            self.assertFalse(state.LOCK._is_owned())
            self.assertEqual(agent, 'audit')
            import contextlib
            return contextlib.nullcontext()
        with patch.object(opencode, 'quiesce', side_effect=pause):
            result = api.dispatch('diagnostic', {'caller': support.caller(self.observer, 'audit'), 'project': 'p'})
        prepared = Path(result['directory'])
        self.assertTrue(prepared.is_relative_to(self.run / 'scratch'))
        self.assertFalse((prepared / '.git').exists())
        self.assertFalse((prepared / 'private').exists())
        test = subprocess.run([sys.executable, 'check.py'], cwd=prepared, capture_output=True, text=True)
        self.assertEqual(test.returncode, 0, test.stderr)
        self.assertEqual(test.stdout.strip(), 'accepted suite')
        self.assertIn('editor draft', (self.repo / 'check.py').read_text())
        worker = support.running(support.queued(self.project, 'implement'), 'worker', worktree=False)
        with self.assertRaisesRegex(ValueError, 'requires a test auditor'):
            api.dispatch('diagnostic', {'caller': support.caller(worker, 'worker'), 'project': 'p'})
        import shutil
        shutil.rmtree(self.run / 'scratch')
        (self.run / 'scratch').symlink_to(self.repo, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'owned diagnostic scratch'):
            api.dispatch('diagnostic', {'caller': support.caller(self.observer, 'audit'), 'project': 'p'})
        self.assertEqual(sorted(path.name for path in self.repo.iterdir()), ['.git', 'check.py', 'private'])

    def test_knowledge_context_stays_runtime_rooted_without_adding_access_grants(self):
        self.prepare_launch()
        server = {'type': 'local', 'command': ['kt-mcp'], 'environment': {'KEEP': 'yes'}}
        with patch.object(opencode.stations, 'servers', return_value={'knowledgetrees': server}):
            settings = opencode.settings(state.CONFIG, 'key', self.observer, [], 'audit')
        self.assertEqual(settings['mcp']['knowledgetrees']['environment'],
                         {'KEEP': 'yes', 'KT_MCP_PROJECT_DIR': str(opencode.ROOT)})
        self.assertEqual(settings['permission']['shell']['git *'], 'deny')
        self.assertEqual(settings['permission']['edit'][str(self.run.resolve()) + '/scratch/**'], 'allow')
        with patch.object(kt.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0,
                          f'allowed\tallow\t{self.repo}\nsecret\tforce-private\t(restricted)\nother\task\t(restricted)\n')):
            self.assertEqual(kt.readable_roots(opencode.ROOT), [self.repo])

    def test_explicit_system_operator_keeps_its_assigned_infrastructure_scope(self):
        operator = tasks.request_operator('infra', 'Inspect services.', None, None, None, None)
        self.assertFalse(opencode.observer(operator))
        self.assertFalse(opencode.confined_writes(operator))
        self.assertIsNone(opencode.read_paths(operator, self.run))

    def test_system_first_responder_uses_private_brokers_without_product_edit_permission(self):
        responder = support.running(tasks.create('first-response', tasks.SYSTEM, 'runtime-repair',
                                                  'Diagnose runtime failure.', [1]), 'responder', worktree=False)
        with patch.object(opencode, 'launch', return_value=None):
            runs.launch('responder', responder, 'fixture')
        self.assertEqual(Path(responder['worktree']), opencode.agent_data(responder) / 'workspace')
        self.assertTrue(opencode.observer(responder))
        self.assertTrue(opencode.confined_writes(responder))
        settings = opencode.settings(state.CONFIG, 'fixture', responder, [], 'responder')
        self.assertEqual(settings['permission']['edit'], {'*': 'deny'})
        self.assertNotIn('cointos_diagnostic', prompts.place_text(responder, tasks.SYSTEM))

    def test_pipeline_observation_is_proxied_without_local_journal_reads_or_ledger_lock(self):
        def report(hours):
            self.assertFalse(state.LOCK._is_owned())
            self.assertEqual(hours, 4)
            return 'retained coverage'
        with patch.object(metrics, 'report', side_effect=report):
            result = api.dispatch('metrics', {'caller': support.caller(self.observer, 'audit'), 'hours': 4})
        self.assertEqual(result['text'], 'retained coverage')
        for hours in (0, -1, True, float('inf'), float('nan')):
            with self.subTest(hours=hours), self.assertRaisesRegex(ValueError, 'positive finite'):
                api.dispatch('metrics', {'caller': support.caller(self.observer, 'audit'), 'hours': hours})
        with patch.dict(os.environ, {'COINTOS_AGENT': 'audit'}), \
             patch.object(cli, 'call', return_value=result), \
             patch.object(metrics, 'report', side_effect=AssertionError('local runtime read')):
            args = cli.parser().parse_args(['metrics', '--hours', '4'])
            self.assertEqual(cli.COMMANDS['metrics'](args), 'retained coverage')
