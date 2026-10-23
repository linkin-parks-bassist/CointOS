"""Real-Git evidence that advisory output locks do not isolate external builds."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cointos import contracts, git


@unittest.skipUnless(shutil.which('cc'), 'requires a native C compiler')
class ExternalValidation(unittest.TestCase):
    def test_external_build_can_replace_failed_candidate_binary_under_held_lock(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='cointos-external-build-')))
        repo = root / 'repo'
        repo.mkdir()
        git.run(repo, 'init', '-q', '-b', 'main')
        git.run(repo, 'config', 'user.name', 'Fixture')
        git.run(repo, 'config', 'user.email', 'fixture@example.invalid')
        (repo / 'tests').mkdir()
        shared, arm, ready, release = [root / name for name in ('shared-binary', 'arm', 'ready', 'release')]
        # The handshake chooses the compile/execute interleaving; the command otherwise
        # reproduces make's fixed host /tmp binary: compile candidate code, then run it.
        (repo / 'tests/check.py').write_text(
            'import pathlib, subprocess, sys, time\n'
            f'binary, arm, ready, release = map(pathlib.Path, {list(map(str, (shared, arm, ready, release)))!r})\n'
            "subprocess.run(['cc', 'behavior.c', '-o', str(binary)], check=True)\n"
            'if arm.exists():\n'
            '    ready.touch()\n'
            '    deadline = time.monotonic() + 10\n'
            '    while not release.exists():\n'
            '        if time.monotonic() >= deadline: raise RuntimeError("external fixture did not run")\n'
            '        time.sleep(.01)\n'
            'result = subprocess.run([str(binary)])\n'
            'if result.returncode: print("candidate self-test failed", flush=True)\n'
            'sys.exit(result.returncode)\n')
        (repo / 'tests/contracts.json').write_text(json.dumps([
            {'covers': ['behavior.c'], 'command': ['python3', 'tests/check.py']}]))
        (repo / 'behavior.c').write_text('int main(void) { return 0; }\n')
        git.run(repo, 'add', '-A')
        git.run(repo, 'commit', '-qm', 'passing main')
        main = git.head(repo)
        (repo / 'behavior.c').write_text('int main(void) { return 1; }\n')
        git.run(repo, 'add', 'behavior.c')
        git.run(repo, 'commit', '-qm', 'broken candidate')
        candidate = git.head(repo)
        rules = {'manifest': 'tests/contracts.json', 'protected': ['tests/**'], 'non_code': []}
        state = root / 'state'
        memory = 1 if os.environ.get('COINTOS_NATIVE_PIPELINE_PROBE') else None
        with patch.object(contracts.configuration, 'STATE', state):
            evidence, caused = contracts.suite(repo, main, candidate, rules, 20, memory)
            self.assertEqual(evidence, {'suite': 1, 'failed': 1, 'red_on_main': 0})
            self.assertEqual(len(caused), 1)
            self.assertIn('candidate self-test failed', caused[0][1])
            # An ordinary build does not acquire CointOS's private advisory lock.
            # Prove the lock is actually held, then compile main into the same host
            # output from a separate process with no production runner involvement.
            external_source = root / 'editor.c'
            external_source.write_text('int main(void) { return 0; }\n')
            arm.touch()
            script = (
                'import fcntl, pathlib, subprocess, sys, time\n'
                'ready, release, lock, source, output = map(pathlib.Path, sys.argv[1:])\n'
                'deadline = time.monotonic() + 10\n'
                'while not ready.exists():\n'
                '    if time.monotonic() >= deadline: raise RuntimeError("candidate did not compile")\n'
                '    time.sleep(.01)\n'
                'with lock.open("a") as held:\n'
                '    try: fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
                '    except BlockingIOError: print("publication test output lock is held", flush=True)\n'
                '    else: raise AssertionError("CointOS was not holding its output lock")\n'
                'subprocess.run(["cc", str(source), "-o", str(output)], check=True)\n'
                'release.touch()\n')
            external = subprocess.Popen(['python3', '-c', script, str(ready), str(release),
                                         str(state / 'test-output.lock'), str(external_source), str(shared)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                evidence, caused = contracts.suite(repo, main, candidate, rules, 20, memory)
                out, err = external.communicate(timeout=5)
                self.assertEqual(external.returncode, 0, err)
                self.assertIn('test output lock is held', out)
                # Current production gate reports a passing exact candidate even
                # though it executed the external build's different executable.
                self.assertEqual(evidence, {'suite': 1, 'failed': 0, 'red_on_main': 0})
                self.assertEqual(caused, [])
                self.assertEqual(git.head(repo), candidate)
                self.assertEqual(git.run(repo, 'diff', 'HEAD', '--name-only'), '')
            finally:
                if external.poll() is None:
                    external.kill()
                external.communicate()
            # A project-owned harness correction uses the candidate checkout's
            # unique output instead of the shared host name. The same external
            # overwrite then cannot turn the broken candidate green.
            check = repo / 'tests/check.py'
            check.write_text(check.read_text().replace(
                "subprocess.run(['cc', 'behavior.c'",
                "binary = pathlib.Path.cwd() / 'candidate-binary'\nsubprocess.run(['cc', 'behavior.c'", 1))
            git.run(repo, 'add', 'tests/check.py')
            git.run(repo, 'commit', '-qm', 'project-owned candidate output')
            corrected = git.head(repo)
            ready.unlink()
            release.unlink()
            external = subprocess.Popen(['python3', '-c', script, str(ready), str(release),
                                         str(state / 'test-output.lock'), str(external_source), str(shared)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                evidence, caused = contracts.suite(repo, main, corrected, rules, 20, memory)
                out, err = external.communicate(timeout=5)
                self.assertEqual(external.returncode, 0, err)
                self.assertIn('test output lock is held', out)
                self.assertEqual(evidence, {'suite': 1, 'failed': 1, 'red_on_main': 0})
                self.assertEqual(len(caused), 1)
                self.assertIn('candidate self-test failed', caused[0][1])
                self.assertEqual(git.head(repo), corrected)
                self.assertEqual(git.run(repo, 'diff', 'HEAD', '--name-only'), '')
            finally:
                if external.poll() is None:
                    external.kill()
                external.communicate()
