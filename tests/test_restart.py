import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from cointos import api, checks, cli, daemon, gateway, git, landing, lifecycle, recovery, spawner, state
from tests import support
from tests.test_landing import Project


class LiveRestart(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self, {'paused': False})
        self.enterContext(patch.dict(state.ACTIVE, chats=0, landings=0))

    def test_drain_stops_spawns_but_existing_conversations_continue(self):
        entered, entered_twice, release = threading.Event(), threading.Event(), threading.Event()
        calls = 0
        def response(handler, body):
            nonlocal calls
            calls += 1
            entered.set()
            if calls == 2:
                entered_twice.set()
            release.wait(8)
            handler.reply(200, {'finished': True})
        self.enterContext(patch.object(gateway.Handler, 'stream_thought', response))
        server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
        result = []
        def request():
            with urllib.request.urlopen(url, data=b'{}', timeout=10) as r:
                result.append(json.load(r))
        client = threading.Thread(target=request)
        client.start()
        try:
            self.assertTrue(entered.wait(5))
            drained = api.dispatch('prepare-restart', {})
            self.assertFalse(drained['ready'], 'no thoughts does not mean final HTTP reply has been delivered')
            self.assertEqual(drained['active_requests'], 1)
            pending = threading.Thread(target=request)
            pending.start()
            self.assertTrue(entered_twice.wait(5), 'continuation thought must remain admitted while spawns drain')
            self.assertEqual(state.ACTIVE['chats'], 2)
            self.assertFalse(state.L['paused'])
            with patch.object(spawner, 'next_task') as next_task:
                spawner.spawn()
                next_task.assert_not_called()
        finally:
            release.set()
            client.join(10)
        pending.join(10)
        self.assertEqual(result, [{'finished': True}, {'finished': True}])
        # Receiving the bytes precedes the server's finally block which releases
        # its request count. Wait for that distinct boundary before testing drain.
        deadline = time.monotonic() + 2
        while state.ACTIVE['chats'] and time.monotonic() < deadline:
            time.sleep(.001)
        self.assertTrue(api.dispatch('prepare-restart', {})['ready'])
        self.assertFalse(state.fresh(state.L)['restarting'])
        api.dispatch('cancel-restart', {})
        self.assertFalse(pending.is_alive())

    def test_shutdown_rejects_thought_admission(self):
        stopping = threading.Event()
        self.enterContext(patch.object(gateway, 'STOPPING', stopping))
        handler = object.__new__(gateway.Handler)
        with patch.object(handler, 'reply') as reply, patch.object(handler, 'stream_thought') as stream:
            api.dispatch('prepare-restart', {})
            stopping.set()
            request = threading.Thread(target=handler.think, args=({},))
            request.start()
            try:
                request.join(2)
            finally:
                stopping.set()
                request.join(2)
            self.assertFalse(request.is_alive())
            self.assertEqual(reply.call_args.args[0], 503)
            stream.assert_not_called()

    def test_cancel_restores_silence_grace_without_changing_pause(self):
        state.L['agents']['a'] = {'last_activity': 0}
        api.dispatch('prepare-restart', {})
        self.assertEqual(checks.silent_agents(state.CONFIG, state.L, state.now()), ['a'])
        api.dispatch('cancel-restart', {})
        self.assertFalse(state.L['restarting'])
        self.assertFalse(state.L['paused'])
        self.assertGreater(state.L['agents']['a']['last_activity'], state.now() - 1)

    def test_cli_restarts_only_after_drain(self):
        with patch.object(cli, 'call', side_effect=[{'ready': False}, {'ready': True}]) as call, \
                patch.object(cli.time, 'sleep'), patch.object(cli, 'systemctl', return_value=0) as systemctl:
            cli.restart()
        self.assertEqual(call.call_count, 2)
        systemctl.assert_called_once_with('restart', 'cointosd.service')

    def test_cli_timeout_cancels_drain_without_stopping_processes(self):
        with patch.object(cli, 'call', return_value={'ready': False}) as call, \
                patch.object(cli.time, 'monotonic', side_effect=[0, 10000]), \
                patch.object(cli, 'systemctl') as systemctl:
            with self.assertRaises(SystemExit):
                cli.restart()
        call.assert_called_with('cancel-restart')
        systemctl.assert_not_called()

    def test_shutdown_obligations_are_independent(self):
        calls = []
        with patch.object(daemon, 'system_stopping', return_value=True), \
                patch.object(daemon.lanes, 'save_all', side_effect=RuntimeError('model gone')), \
                patch.object(daemon.snapshots, 'persist', side_effect=lambda: calls.append('persist')), \
                patch.object(daemon, 'save', side_effect=lambda: calls.append('save')), \
                patch.object(daemon.traceback, 'print_exc'):
            daemon.shutdown()
        self.assertEqual(calls, ['persist', 'save'])
        self.assertEqual(state.L['history'][-1]['event'], 'shutdown step failed')


class PublishedRestart(Project):
    def test_published_receipt_settles_before_exhausted_surviving_run_is_adopted(self):
        integration, candidate, submitted = self.landing()
        integration['fresh_retries'] = state.CONFIG['recovery']['fresh_retries']
        agent = state.L['agents']['integrator-1']
        agent['generation_tokens'] = integration['budget']['generation_tokens']
        durable = []
        publish = git.publish
        class ProcessLoss(BaseException):
            pass
        def interrupted(*args):
            publish(*args)
            raise ProcessLoss()
        with patch.object(landing, 'save', side_effect=lambda: durable.append(json.loads(json.dumps(state.L)))), \
                patch.object(git, 'publish', side_effect=interrupted):
            with self.assertRaises(ProcessLoss):
                landing.land(integration['id'], candidate, 'integrator-1')
        previous = durable[-1]
        self.assertEqual(previous['tasks'][self.worker['id']]['status'], 'review')
        self.assertEqual(self.main(), candidate)
        observed = []
        def adopt(recorded):
            # A surviving follower may report exhaustion as soon as adoption
            # starts. Acceptance must already be durable at this boundary.
            observed.append(state.L['tasks'][self.worker['id']]['status'])
            state.L['agents'].update(recorded['agents'])
            for run, restored in recorded['agents'].items():
                daemon.keys.adopt(run, restored['class'], daemon.keys.recorded()[run])
            recovery.enforce()
        saved = []
        state.L.clear()
        import tempfile
        from pathlib import Path
        directory = self.enterContext(tempfile.TemporaryDirectory())
        keyfile = Path(directory) / 'keys.json'
        keyfile.write_text(json.dumps({'coin': 'fixture-coin', 'agents': {run: 'fixture-' + run for run in previous['agents']}}))
        import subprocess
        real_run = subprocess.run
        def native(command, **options):
            if command[0] != 'systemctl':
                return real_run(command, **options)
            self.assertEqual(command[:3], ['systemctl', '--user', 'show'])
            run = command[3].removeprefix('cointos-agent-').removesuffix('.service')
            self.assertIn(run, previous['agents'])
            return subprocess.CompletedProcess(command, 0,
                'ActiveState=active\nMainPID=202\nInvocationID=fixture-'+run+'\nLoadState=loaded\n', '')
        with patch.object(daemon.keys, 'KEYS', keyfile), \
                patch.object(subprocess, 'run', side_effect=native), \
                patch.dict(daemon.keys.ISSUED, {}, clear=True), \
                patch.dict(daemon.keys.OWNERS, {}, clear=True), \
                patch.object(daemon.runs, 'adopt', side_effect=adopt), \
                patch.object(daemon.snapshots, 'recover_transfers'), patch.object(daemon.snapshots, 'forget_orphans'), \
                patch.object(daemon.snapshots, 'forget_untracked'), \
                patch.object(lifecycle, 'save', side_effect=lambda: saved.append(json.loads(json.dumps(state.L)))), \
                patch.object(daemon, 'save', side_effect=lambda: saved.append(json.loads(json.dumps(state.L)))), \
                patch.object(recovery, 'packet', return_value='exhausted surviving run'):
            daemon.restore(previous)
        self.assertEqual(observed, ['done'])
        worker = state.L['tasks'][self.worker['id']]
        settled = state.L['tasks'][integration['id']]
        self.assertEqual(worker['acceptance']['commit'], candidate)
        self.assertEqual(worker['acceptance']['worker_commit'], submitted)
        self.assertEqual(settled['receipt']['run'], 'integrator-1')
        self.assertEqual(settled['receipt']['disposition'], 'complete')
        self.assertEqual(saved[0]['queue'][worker['record']]['done']['commit'], candidate)
        self.assertEqual(lifecycle.recover_landings(), 0)


class Silence(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self, {'paused': False})

    def agent(self):
        state.L['agents']['x'] = {'id': 'x', 'state': 'running', 'task': None, 'repeats': 0,
                                  'last_activity': state.now() - 1000}

    def test_a_silent_agent_is_stopped(self):
        self.agent()
        with patch.object(daemon.lifecycle, 'stop') as stop:
            daemon.look_after_agents()
        stop.assert_called_once_with('x', 'silent too long', requeue=True)


class PromptRewrites(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)

    def begin(self, owner, tokens):
        from cointos import lanes
        with patch.object(lanes, "schedule"), patch.object(lanes.snapshots, "live", lambda o: True), \
             patch.object(lanes.threading, "Thread") as thread, state.LOCK:
            state.L["tasks"].setdefault(owner, {"id": owner})
            lanes.begin("agent", "background", owner, state.L["lanes"][0]["model"], {"tokens": tokens, "reader": {}}, {}, 10)
        return thread

    def test_a_conversation_that_grows_reports_nothing_but_a_rewritten_one_is_reported(self):
        from cointos import lanes
        self.addCleanup(lanes.PROMPTS.clear)
        self.assertFalse(self.begin("t", list(range(100))).called)
        self.assertFalse(self.begin("t", list(range(99)) + [7] * 20).called, "the last token is not in the checkpoint")
        self.assertTrue(self.begin("t", list(range(97)) + [7] * 30).called)
        thread = self.begin("t", [1] * 50)
        self.assertEqual(thread.call_args.kwargs["target"], lanes.report_rewrite)
