"""The kernel boundary catches direct tools, shells and redirected/symlinked writes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cointos import opencode
from cointos.kt_mcp import SERVER


class WriteBoundary(unittest.TestCase):
    @unittest.skipUnless(SERVER.is_file(), 'native knowledge-tree MCP is not installed')
    def test_fresh_checkout_can_add_answers_without_global_policy_write_access(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = Path(directory); checkout = root/'checkout'; run = root/'run'; run.mkdir()
            subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
            (checkout/'.knowledge').mkdir()
            global_root = root/'global'; (global_root/'.tools').mkdir(parents=True)
            policy = global_root/'.tools/roots.json'
            env = {**os.environ, 'KT_GLOBAL_ROOT': str(global_root), 'KT_CONFIG': str(policy)}
            task = {'id': 'p:author', 'role': 'worker', 'worktree': str(checkout)}
            with patch.dict(os.environ, env), patch.object(opencode, 'STATE', root/'state'):
                paths = opencode.write_paths(task, run)
            before = policy.read_bytes()
            registry = json.loads(before)
            self.assertEqual([row['access'] for row in registry['roots'].values()], ['ask'])
            self.assertFalse(registry['projects'])
            with patch.dict(os.environ, env):
                opencode.kt.prepare(checkout)
            self.assertEqual(policy.read_bytes(), before)
            messages = [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                    'protocolVersion': '2025-06-18', 'capabilities': {},
                    'clientInfo': {'name': 'cointos-fixture', 'version': '1'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
                    'name': 'kt_add', 'arguments': {'scope': 'local',
                    'question': 'what is the fixture', 'answer': 'A scratch fixture.'}}}]
            result = subprocess.run([
                sys.executable, str(Path(opencode.__file__).with_name('worktree_guard.py')),
                json.dumps(paths), sys.executable, str(SERVER)], cwd=checkout, env=env,
                input='\n'.join(map(json.dumps, messages))+'\n', capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            reply = next(json.loads(line) for line in result.stdout.splitlines()
                         if json.loads(line).get('id') == 2)
            self.assertFalse(reply['result'].get('isError'), reply)
            self.assertTrue((checkout/'.knowledge/what/is/the/fixture.md').is_file())
            self.assertEqual(policy.read_bytes(), before)
            denied = subprocess.run([
                sys.executable, str(Path(opencode.__file__).with_name('worktree_guard.py')),
                json.dumps(paths), sys.executable, '-c',
                'from pathlib import Path; import sys; Path(sys.argv[1]).write_text("bad")', str(policy)],
                capture_output=True, text=True)
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(policy.read_bytes(), before)

    def test_linked_checkout_can_commit_without_writing_main_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); main=root/'main'; assigned=root/'assigned'; run=root/'run'
            run.mkdir()
            subprocess.run(['git','init','-q',str(main)],check=True)
            subprocess.run(['git','-C',str(main),'-c','user.name=Fixture','-c','user.email=fixture@example.test',
                            'commit','-q','--allow-empty','-m','base'],check=True)
            subprocess.run(['git','-C',str(main),'worktree','add','-q','-b','worker',str(assigned)],check=True)
            paths=[str(assigned),str(main/'.git'),'/dev/null']
            script='from pathlib import Path; import subprocess; Path("artifact").write_text("ok"); subprocess.run(["git","add","artifact"],check=True); subprocess.run(["git","-c","user.name=Fixture","-c","user.email=fixture@example.test","commit","-q","-m","worker"],check=True)'
            result=subprocess.run([sys.executable,str(Path(opencode.__file__).with_name('worktree_guard.py')),
                                   json.dumps(paths),sys.executable,'-c',script],cwd=assigned,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((main/'artifact').exists())
            task={'role':'worker','worktree':str(assigned)}
            worker_paths=opencode.write_paths(task,run)
            self.assertIn(str(main/'.git'),worker_paths)
            knowledge=main/'.knowledge';knowledge.mkdir()
            self.assertNotIn(str(knowledge),opencode.write_paths(task,run))
            self.assertIn(str(knowledge),opencode.write_paths({**task,'role':'integrator'},run))
            self.assertIsNone(opencode.write_paths({**task,'role':'operator','place':'system'},run))

    def test_branch_maintenance_cannot_overwrite_preserved_worker_artifacts(self):
        for role in ('operator', 'gardener', 'tree-auditor'):
            with self.subTest(role=role):
                self.assert_maintenance_preserves_worker(role)

    def assert_maintenance_preserves_worker(self, role):
        # Outside /tmp: shared tool scratch is intentionally writable.
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = Path(directory)
            main, worker, operator, run = (root / name for name in ('main', 'worker', 'operator', 'run'))
            run.mkdir()
            subprocess.run(['git', 'init', '-q', str(main)], check=True)
            (main / 'source.c').write_text('old main\n')
            subprocess.run(['git', '-C', str(main), 'add', 'source.c'], check=True)
            subprocess.run(['git', '-C', str(main), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'base'], check=True)
            for branch, path in (('worker', worker), ('operator', operator)):
                subprocess.run(['git', '-C', str(main), 'worktree', 'add', '-qb', branch, str(path)], check=True)
            artifact = worker / 'source.c'
            artifact.write_text('preserved implementation\n')
            (operator / 'worker-link').symlink_to(worker, target_is_directory=True)
            task = {'id': 'p:repair', 'role': role, 'place': 'p', 'worktree': str(operator)}
            paths = opencode.write_paths(task, run)
            command = [sys.executable]
            if paths is not None:
                command += [str(Path(opencode.__file__).with_name('worktree_guard.py')), json.dumps(paths), sys.executable]
            script = '''
from pathlib import Path
import subprocess, sys
worker = Path(sys.argv[1]); target = worker/'source.c'
assert target.read_text() == 'preserved implementation\\n'
Path('own-note.md').write_text('allowed scoped maintenance')
for path in (target, Path('worker-link/source.c')):
    try: path.write_text('bad copy')
    except PermissionError: pass
    else: raise AssertionError('maintenance run overwrote preserved worker artifact')
assert subprocess.run(['cp', 'source.c', str(target)], capture_output=True).returncode != 0
assert subprocess.run(['git', '-C', str(worker), 'restore', 'source.c'], capture_output=True).returncode != 0
subprocess.run(['git', 'add', 'own-note.md'], check=True)
subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                'commit', '-qm', 'allowed maintenance'], check=True)
assert target.read_text() == 'preserved implementation\\n'
'''
            result = subprocess.run(command + ['-c', script, str(worker)], cwd=operator,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(artifact.read_text(), 'preserved implementation\n')
            self.assertEqual((main / 'source.c').read_text(), 'old main\n')
            config = {**opencode.load_config(), 'projects': [{'name': 'p', 'path': str(main)}]}
            permissions = opencode.settings(config, 'fixture', task, [])['permission']
            self.assertEqual(permissions['edit']['*'], 'deny')
            self.assertEqual(permissions['read'][str(main)], 'deny')

    def test_rewrite_database_is_writable_without_opening_global_access_policy(self):
        # Outside /tmp, which is deliberately writable tool scratch.
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = Path(directory); checkout = root/'checkout'; run = root/'run'; run.mkdir()
            subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
            access = root/'global-state'; access.mkdir()
            policy = access/'access.sqlite3'; policy.write_text('preserve authority')
            task = {'id': 'p:manager', 'role': 'manager', 'worktree': str(checkout)}
            with patch.object(opencode, 'STATE', root/'runtime-state'):
                paths = opencode.write_paths(task, run)
                env = opencode.environment(run, {'task': task, 'write_paths': paths})
            script = """
import os, sqlite3, sys
from pathlib import Path
rewrite = Path(os.environ['KT_REWRITE_STATE_DIR'])/'rewrite-bounces.sqlite3'
for _ in range(2):
    with sqlite3.connect(rewrite) as db:
        db.execute('CREATE TABLE IF NOT EXISTS bounces (leaf TEXT PRIMARY KEY, count INTEGER)')
        db.execute("INSERT INTO bounces VALUES ('leaf',1) ON CONFLICT(leaf) DO UPDATE SET count=count+1")
with sqlite3.connect(rewrite) as db:
    assert db.execute('SELECT count FROM bounces').fetchone()[0] == 2
try: Path(sys.argv[1]).write_text('bad')
except PermissionError: pass
else: raise AssertionError('global access policy became writable')
"""
            result = subprocess.run([sys.executable, str(Path(opencode.__file__).with_name('worktree_guard.py')),
                                     json.dumps(paths), sys.executable, '-c', script, str(policy)],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(policy.read_text(), 'preserve authority')

    def test_child_writes_checkout_but_cannot_modify_other_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assigned, other = root / 'assigned', root / 'main'
            assigned.mkdir(); other.mkdir()
            target = other / 'existing'
            target.write_text('preserve')
            (assigned / 'link').symlink_to(other, target_is_directory=True)
            script = '''
from pathlib import Path
import subprocess,sys
assigned,other=map(Path,sys.argv[1:])
(assigned/'allowed').write_text('ok')
assert (other/'existing').read_text()=='preserve'
for action in (lambda: (other/'new').write_text('bad'),
               lambda: (other/'existing').write_text('bad'),
               lambda: (other/'existing').unlink(),
               lambda: (assigned/'link/new').write_text('bad'),
               lambda: (other/'existing').rename(assigned/'stolen')):
    try: action()
    except PermissionError: pass
    else: raise AssertionError('write escaped')
assert subprocess.run(['sh','-c','echo bad > "$1/existing"','sh',str(other)],capture_output=True).returncode
'''
            result = subprocess.run([sys.executable, str(Path(opencode.__file__).with_name('worktree_guard.py')),
                                     json.dumps([str(assigned), '/dev/null']), sys.executable, '-c', script,
                                     str(assigned), str(other)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_text(), 'preserve')
            self.assertEqual((assigned/'allowed').read_text(), 'ok')

    def test_unusable_policy_does_not_execute_command(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'executed'
            result=subprocess.run([sys.executable,str(Path(opencode.__file__).with_name('worktree_guard.py')),
                                   json.dumps([str(marker)]),sys.executable,'-c',
                                   'from pathlib import Path; import sys; Path(sys.argv[1]).touch()',str(marker)],
                                  capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(marker.exists())
