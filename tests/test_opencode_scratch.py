"""Independent agent runs never compete for a fixed temporary checkout name."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from cointos import opencode


class RunScratch(unittest.TestCase):
    def launch(self, directory):
        task = {'id': 'system:audit', 'role': 'test-auditor', 'title': 'Audit',
                'worktree': str(directory.parent)}
        config = {'work_model': 'fixture', 'memory': {'agent_limit_gb': 1}}
        with mock.patch.object(opencode, 'run_dir', return_value=directory), \
                mock.patch.object(opencode, 'settings', return_value={}), \
                mock.patch.object(opencode.kt, 'readable_roots', return_value=[]), \
                mock.patch.object(opencode.subprocess, 'run') as unit:
            opencode.launch(config, directory.name, task, 'fixture-key', 'Audit.', [])
        unit.assert_called_once()
        return opencode.environment(directory, json.loads((directory / 'run.json').read_text()))

    def test_real_children_use_separate_scratch_and_preserve_earlier_work(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old = root / 'old-audit'; old.mkdir()
            (old / 'unfinished').write_text('preserve this work')
            outputs = []
            with mock.patch.dict(os.environ, {'TMPDIR': str(old), 'COINTOS_SCRATCH': str(old)}):
                for name in ('audit-one', 'audit-two'):
                    env = self.launch(root / name)
                    scratch = Path(env['COINTOS_SCRATCH'])
                    self.assertEqual(env['TMPDIR'], str(scratch))
                    self.assertEqual(scratch.stat().st_mode & 0o777, 0o700)
                    probe = subprocess.check_output(['mktemp', '-d'], env=env, text=True).strip()
                    self.assertEqual(Path(probe).parent, scratch)
                    output = scratch / 'audit-checkout'; output.mkdir()
                    (output / 'result').write_text(name)
                    outputs.append(output)
            self.assertNotEqual(*outputs)
            self.assertEqual([(p / 'result').read_text() for p in outputs], ['audit-one', 'audit-two'])
            self.assertEqual((old / 'unfinished').read_text(), 'preserve this work')

    def test_stationed_operator_grants_the_selected_versioned_store(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); checkout = root / 'station'; checkout.mkdir()
            run = root / 'run'; run.mkdir()
            store = root / 'agent-data' / 'task' / 'v2'; store.mkdir(parents=True)
            task = {'id': 'system:report', 'role': 'operator', 'worktree': str(checkout)}
            with mock.patch.object(opencode, 'confined_writes', return_value=True), \
                 mock.patch.object(opencode, 'observer', return_value=False), \
                 mock.patch.object(opencode.git, 'workspace_context', return_value=False), \
                 mock.patch.object(opencode.kt, 'prepare'), \
                 mock.patch.object(opencode, 'STATE', root / 'state'), \
                 mock.patch.object(Path, 'home', return_value=root / 'home'), \
                 mock.patch.object(opencode.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
                paths = opencode.write_paths(task, run, store)
            self.assertIn(str(store), paths)
            self.assertNotIn(str(store.parent.parent), paths)
            env = opencode.environment(run, {'task': task, 'command': ['opencode'], 'agent_data': str(store)})
            self.assertEqual(env['XDG_DATA_HOME'], str(store / 'data'))
            # Exercise the real confinement boundary using only the selected store
            # grant so the fixture's /tmp location cannot mask a missing grant.
            guard = Path(opencode.__file__).with_name('worktree_guard.py')
            import sys
            result = subprocess.run([sys.executable, str(guard), json.dumps([str(store), '/dev/null']),
                sys.executable, '-c', 'from pathlib import Path; import sys; Path(sys.argv[1]).mkdir(parents=True)',
                str(store / 'data/opencode/log')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((store / 'data/opencode/log').is_dir())

    def test_launch_refuses_existing_scratch_without_deleting_or_adopting_it(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            target = root / 'valuable'; target.mkdir()
            (target / 'unfinished').write_text('retain')
            for kind in ('directory', 'symlink', 'file'):
                with self.subTest(kind=kind):
                    directory = root / kind; directory.mkdir()
                    scratch = directory / 'scratch'
                    if kind == 'directory':
                        scratch.mkdir(); (scratch / 'unfinished').write_text('retain')
                    elif kind == 'symlink':
                        scratch.symlink_to(target, target_is_directory=True)
                    else:
                        scratch.write_text('retain')
                    with mock.patch.object(opencode.subprocess, 'run') as unit:
                        with self.assertRaises(FileExistsError):
                            self.launch(directory)
                        unit.assert_not_called()
                    self.assertEqual((target / 'unfinished').read_text(), 'retain')
                    if kind == 'file':
                        self.assertEqual(scratch.read_text(), 'retain')
                    else:
                        self.assertEqual((scratch / 'unfinished').read_text(), 'retain')
                    self.assertEqual(scratch.is_symlink(), kind == 'symlink')


if __name__ == '__main__':
    unittest.main()
