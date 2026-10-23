"""Real loopback control HTTP, Git and ledger writes on disposable repositories.

COINTOS_NATIVE_PIPELINE_PROBE=1 retains production systemd test-command caps.
Run with COINTOS_STATE pointing to a disposable directory. Scripted run identities
are declared fixtures, not evidence of autonomous model work.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from cointos import contracts, gateway, git, lifecycle, queues, recovery, state, tasks
from tests.test_landing import Project, TESTS_A
from tests import support

Thread = threading.Thread


class PipelineHTTP(Project):
    def setUp(self):
        native_run = contracts._run
        super().setUp()
        # The fixture never acknowledges delivery to a non-existent agent unit.
        # Restore actual HTTP threads, which Project suppresses for reducer tests.
        self.enterContext(patch.object(threading, 'Thread', Thread))
        if os.environ.get('COINTOS_NATIVE_PIPELINE_PROBE') == '1':
            self.enterContext(patch.object(contracts, '_run', native_run))
        self.private = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(state.configuration, 'LEDGER', self.private / 'ledger.json'))
        self.enterContext(patch.object(state.journal, 'STATE', self.private))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        self.server.daemon_threads = True
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, action, body):
        request = urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}/api/{action}',
                                         json.dumps(body).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def test_blocked_ledger_write_leaves_dashboard_available_but_does_not_acknowledge_early(self):
        state.L['messages'] = [{'from':'fixture','to':'mailbox:fixture','text':'fixture',
                                'at':1,'read':False}]
        writing, release = threading.Event(), threading.Event()
        result, errors = [], []
        persist = state.configuration.write_json
        def blocked(path, value, *args, **kwargs):
            if path == state.configuration.LEDGER:
                self.assertFalse(state.LOCK._is_owned())
                writing.set()
                if not release.wait(5): raise TimeoutError('fixture did not release storage')
            return persist(path, value, *args, **kwargs)
        def control():
            try: result.append(self.request('inbox', {'mailbox':'fixture'}))
            except BaseException as error: errors.append(error)
        worker = Thread(target=control)
        try:
            with patch.object(state.configuration, 'write_json', side_effect=blocked):
                worker.start(); self.assertTrue(writing.wait(2))
                with urllib.request.urlopen(f'http://127.0.0.1:{self.server.server_port}/api/ledger', timeout=1) as response:
                    snapshot = json.load(response)
                self.assertTrue(snapshot['messages'][0]['read'])
                self.assertFalse(result, 'control response preceded ledger publication')
                self.assertTrue(worker.is_alive())
                release.set(); worker.join(3)
            self.assertFalse(worker.is_alive()); self.assertFalse(errors, errors)
            self.assertEqual(result[0]['messages'][0]['text'], 'fixture')
            durable = json.loads((self.private/'ledger.json').read_text())
            self.assertTrue(durable['messages'][0]['read'])
        finally:
            release.set()
            if worker.ident is not None: worker.join(3)

    def test_http_red_packet_requires_review_and_saves_hidden_acceptance_with_safe_retry(self):
        writer = support.queued(self.project, 'tests-http', 'Test A\nRelies on: a', stage='test-contract')
        support.running(writer, 'writer-http')
        writer['base_commit'] = self.base
        tree = Path(writer['worktree'])
        (tree / 'tests/test_http.py').write_text(TESTS_A)
        manifest = json.loads((tree / 'tests/contracts.json').read_text())
        command = ['python3', '-m', 'unittest', 'tests.test_http.A']
        (tree / 'tests/contracts.json').write_text(json.dumps(manifest + [{'covers': ['code.py::a'], 'command': command}]))
        submitted = support.commit(tree, 'submit independent test witness')
        dependent = queues.add(self.project, 'queued', 'implement-http', 'Implement A\nDepends on: tests-http', 'implementation')
        receipt = self.request('finish', {'caller': support.caller(writer, 'writer-http'), 'outcome': 'complete',
                                          'detail': 'Submitted failing witness for review'})['receipt']
        self.assertFalse(receipt['evidence']['passing'])
        self.assertEqual(writer['status'], 'review')
        self.assertIsNone(writer.get('acceptance'))
        self.assertNotIn('tests-http', queues.landed('p'))
        self.assertEqual(queues.readiness(queues.live('p'), queues.landed('p'))[dependent], 'waiting')
        lifecycle.release('writer-http', 'fixture run ended')
        integration = tasks.create('integrate', self.project, 'integrate-tests-http', 'Review witness', [2],
                                   item=writer['item'], worker=writer['id'])
        support.running(integration, 'integrator-http')
        review = Path(integration['worktree'])
        git.run(review, 'merge', '--squash', submitted)
        candidate = support.commit(review, 'reviewed hidden witness')
        body = {'caller': support.caller(integration, 'integrator-http'), 'commit': candidate}
        with patch.object(git, 'publish') as publish:
            self.assertEqual(self.request('land', body)['commit'], candidate)
            self.assertEqual(self.request('land', body)['commit'], candidate)
            publish.assert_not_called()
        self.assertEqual(self.main(), self.base)
        self.assertEqual(git.head(tree), submitted)
        self.assertEqual(git.head(review), candidate)
        self.assertFalse((self.repo / 'tests/test_http.py').exists())
        self.assertEqual(queues.readiness(queues.live('p'), queues.landed('p'))[dependent], 'ready')
        durable = json.loads((self.private / 'ledger.json').read_text())
        acceptance = durable['tasks'][writer['id']]['acceptance']
        self.assertEqual(acceptance, {'commit': candidate, 'worker_commit': submitted,
                                     'via': 'tests', 'stage': 'test-contract',
                                     'gate': {'suite': 2, 'failed': 1, 'red_on_main': 0}})
        self.assertEqual(durable['tasks'][integration['id']]['receipt']['evidence'], acceptance)
        self.assertEqual(durable['tasks'][integration['id']]['receipt']['disposition'], 'complete')
        self.assertEqual(durable['queue'][writer['record']]['done']['commit'], candidate)
        self.assertNotIn('landing', durable['tasks'][integration['id']])

    def test_dirty_checkout_lands_and_retry_keeps_exact_acceptance(self):
        integration, candidate, submitted = self.landing()
        (self.repo / 'code.py').write_bytes(b'local editor\0work')
        git.run(self.repo, 'add', 'code.py')
        staged = git.run(self.repo, 'write-tree')
        (self.repo / 'tests/test_a.py').write_text('untracked local collision')
        body = {'caller': support.caller(integration, 'integrator-1'), 'commit': candidate}
        self.assertEqual(self.request('land', body)['commit'], candidate)
        self.assertEqual(self.request('land', body)['commit'], candidate)
        self.assertEqual(self.main(), candidate)
        self.assertEqual((self.repo / 'code.py').read_bytes(), b'local editor\0work')
        self.assertEqual((self.repo / 'tests/test_a.py').read_text(), 'untracked local collision')
        self.assertEqual(git.run(self.repo, 'write-tree'), staged)
        self.assertTrue(git.run(self.repo, 'branch', '--show-current').startswith('work/draft-'))
        durable = json.loads((self.private / 'ledger.json').read_text())
        self.assertEqual(durable['tasks'][self.worker['id']]['acceptance']['worker_commit'], submitted)
        self.assertEqual(durable['queue'][self.worker['record']]['done']['commit'], candidate)

    def test_stale_http_run_cannot_land(self):
        integration, candidate, _ = self.landing()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('land', {'caller': support.caller(integration, 'expired-run'), 'commit': candidate})
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.main(), self.base)
        self.assertIsNone(self.worker.get('acceptance'))

    def test_live_publication_holder_refuses_without_stranding_validation(self):
        integration, candidate, submitted = self.landing()
        receipt = json.loads(json.dumps(self.worker['receipt']))
        code = '''import signal,sys
from cointos import git
with git.repository_lock(sys.argv[1]):
    print("OWNED",flush=True)
    signal.pause()
'''
        holder = subprocess.Popen([sys.executable, '-c', code, str(self.repo)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'OWNED')
            body = {'caller': support.caller(integration, 'integrator-1'), 'commit': candidate}
            with self.assertRaises(urllib.error.HTTPError) as refused:
                self.request('land', body)
            self.assertEqual(refused.exception.code, 400)
            self.assertIn('another CointOS publication owns this repository', refused.exception.read().decode())
            self.assertIsNone(holder.poll(), 'the fixture must still own the actual lock')
            self.assertEqual(state.ACTIVE['landings'], 0)
            self.assertNotIn('validating', integration)
            self.assertNotIn('validating', self.worker)
            self.assertEqual(integration['status'], 'running')
            self.assertEqual(self.worker['status'], 'review')
            self.assertEqual(self.worker['receipt'], receipt)
            self.assertIsNone(self.worker.get('acceptance'))
            self.assertEqual(self.main(), self.base)
            self.assertEqual(git.head(self.tree), submitted)
            self.assertEqual(git.head(integration['worktree']), candidate)
            self.assertTrue(self.request('prepare-restart', {})['ready'])
            self.request('cancel-restart', {})
            with state.LOCK:
                state.L['agents']['integrator-1']['generation_tokens'] = integration['budget']['generation_tokens'] - 1
                recovery.enforce()
            self.assertTrue(state.L['agents']['integrator-1'].get('budget_warned'),
                            'ordinary run budgets must resume after a refused validation')
            holder.kill()
            holder.communicate(timeout=5)
            self.assertEqual(self.request('land', body)['commit'], candidate)
            self.assertEqual(self.worker['receipt'], receipt)
            self.assertEqual(self.worker['acceptance']['worker_commit'], submitted)
        finally:
            if holder.poll() is None:
                holder.kill()
            holder.communicate(timeout=5)

    def test_restart_settles_published_work_before_later_hold(self):
        integration, candidate, _ = self.landing()
        original = git.publish
        def interrupted(*args):
            result = original(*args)
            raise ValueError('fixture process interruption after publication')
        with patch.object(git, 'publish', side_effect=interrupted):
            with self.assertRaises(urllib.error.HTTPError):
                self.request('land', {'caller': support.caller(integration, 'integrator-1'), 'commit': candidate})
        durable = json.loads((self.private / 'ledger.json').read_text())
        self.assertEqual(durable['tasks'][self.worker['id']]['status'], 'review')
        state.L.clear()
        state.L.update(state.fresh(durable))
        for task in (self.worker, integration):
            git.run(self.repo, 'worktree', 'remove', '--force', task['worktree'])
            git.run(self.repo, 'branch', '-D', task['branch'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('hold', {'task': self.worker['id']})
        saved = json.loads((self.private / 'ledger.json').read_text())
        self.assertEqual(saved['tasks'][self.worker['id']]['status'], 'done')
        self.assertEqual(saved['queue'][self.worker['record']]['done']['commit'], candidate)


if __name__ == '__main__':
    unittest.main()
