import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from cointos import api, checks, cli, daemon, gateway, spawner, state
from tests import support


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
            release.wait(3)
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
            with urllib.request.urlopen(url, data=b'{}', timeout=4) as r:
                result.append(json.load(r))
        client = threading.Thread(target=request)
        client.start()
        try:
            self.assertTrue(entered.wait(1))
            drained = api.dispatch('prepare-restart', {})
            self.assertFalse(drained['ready'], 'no thoughts does not mean final HTTP reply has been delivered')
            self.assertEqual(drained['active_requests'], 1)
            pending = threading.Thread(target=request)
            pending.start()
            self.assertTrue(entered_twice.wait(1), 'continuation thought must remain admitted while spawns drain')
            self.assertEqual(state.ACTIVE['chats'], 2)
            self.assertFalse(state.L['paused'])
            with patch.object(spawner, 'next_task') as next_task:
                spawner.spawn()
                next_task.assert_not_called()
        finally:
            release.set()
            client.join(4)
        pending.join(4)
        self.assertEqual(result, [{'finished': True}, {'finished': True}])
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

    def test_quiesce_rejects_new_thoughts_without_changing_ordinary_drain(self):
        handler = object.__new__(gateway.Handler)
        with patch.object(handler, 'reply') as reply, patch.object(handler, 'stream_thought') as stream:
            api.dispatch('prepare-restart', {'quiesce': True})
            handler.think({})
        self.assertTrue(state.L['restarting'])
        self.assertTrue(state.L['quiescing'])
        self.assertEqual(reply.call_args.args[0], 503)
        stream.assert_not_called()
        api.dispatch('cancel-restart', {})
        self.assertFalse(state.L['quiescing'])

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


class QuiescenceIsNotSilence(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self, {'paused': False})

    def agent(self):
        state.L['agents']['x'] = {'id': 'x', 'state': 'running', 'task': None, 'repeats': 0,
                                  'last_activity': state.now() - 1000}

    def test_an_agent_blocked_by_deployment_quiescence_is_not_stopped_as_silent(self):
        self.agent()
        state.L['quiescing'] = True
        with patch.object(daemon.lifecycle, 'stop') as stop:
            daemon.look_after_agents()
        stop.assert_not_called()
        self.assertGreater(state.L['agents']['x']['last_activity'], state.now() - 5)

    def test_without_quiescence_a_silent_agent_is_still_stopped(self):
        self.agent()
        with patch.object(daemon.lifecycle, 'stop') as stop:
            daemon.look_after_agents()
        stop.assert_called_once_with('x', 'silent too long', requeue=True)
