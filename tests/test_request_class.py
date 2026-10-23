"""HTTP scheduling demotion preserves gateway ownership and conversation identity."""
import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from cointos import gateway, keys, lanes, state
from tests import support


class RequestClass(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.model = state.CONFIG['work_model']
        state.L['models'][self.model]['up'] = True
        state.L['agents']['worker'] = {'task': 'worker-task'}
        self.enterContext(patch.dict(keys.OWNERS, {'coin-key': ('coin', 'coin'),
                                                  'worker-key': ('worker', 'background')}, clear=True))
        self.enterContext(patch.object(keys, 'ENDED', set()))
        for mapping in (lanes.RUNS, lanes.PROMPTS, lanes.BUSY, lanes.HELD):
            self.enterContext(patch.dict(mapping, {}, clear=True))
        self.enterContext(patch.dict(state.ACTIVE, chats=0, landings=0))
        self.enterContext(patch.object(lanes, 'schedule'))
        self.enterContext(patch.object(lanes, 'log'))
        self.enterContext(patch.object(lanes.snapshots, 'forget_diverged'))
        self.enterContext(patch.object(gateway.lifecycle, 'engaged'))
        self.render = self.enterContext(patch.object(gateway, 'render_request',
                                        return_value={'tokens': [1, 2], 'reader': {}}))
        self.observed = []
        def reply(handler, body, agent, model, rendered, thought):
            self.observed.append(copy.deepcopy(state.L['thoughts'][thought]))
            handler.reply(200, {'accepted': True})
        self.enterContext(patch.object(gateway.Handler, 'reply_thought', reply))
        # Receiving HTTP bytes can precede the handler's cancellation/finally.
        # Await request ownership ending before inspecting or resetting shared state.
        self.finished = threading.Event()
        original_think = gateway.Handler.think
        def think(handler, body):
            try:
                return original_think(handler, body)
            finally:
                self.finished.set()
        self.enterContext(patch.object(gateway.Handler, 'think', think))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, key, **body):
        self.finished.clear()
        body = {'model': self.model, **body}
        request = urllib.request.Request(
            f'http://127.0.0.1:{self.server.server_address[1]}/v1/chat/completions',
            json.dumps(body).encode(), {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return json.load(response)
        finally:
            self.assertTrue(self.finished.wait(2), 'gateway request ownership did not end')

    def test_omitted_and_equal_override_keep_each_gateway_class(self):
        for key, klass in [('coin-key', 'coin'), ('unissued-user-key', 'user'), ('worker-key', 'background')]:
            for fields in ({}, {'request_class': klass}):
                with self.subTest(key=key, fields=fields):
                    self.assertEqual(self.request(key, **fields), {'accepted': True})
                    self.assertEqual(self.observed[-1]['class'], klass)
        self.assertFalse(state.L['thoughts'])

    def test_coin_demotion_preserves_identity_context_and_template(self):
        before = dict(keys.OWNERS)
        self.request('coin-key', user='same-dialogue', reasoning_effort='medium',
                     chat_template_kwargs={'enable_thinking': True}, request_class='background')
        wake = self.observed[-1]
        self.request('coin-key', user='same-dialogue', reasoning_effort='medium',
                     chat_template_kwargs={'enable_thinking': True})
        direct = self.observed[-1]
        owner = 'coin/' + hashlib.sha256(b'same-dialogue').hexdigest()
        self.assertEqual((wake['agent'], wake['owner'], wake['class']), ('coin', owner, 'background'))
        self.assertEqual((direct['agent'], direct['owner'], direct['class']), ('coin', owner, 'coin'))
        self.assertEqual(keys.OWNERS, before)
        for call in self.render.call_args_list:
            self.assertEqual(call.args[1:4], ('coin', self.model, {'enable_thinking': True, 'reasoning_effort': 'medium'}))

    def test_upward_unknown_and_bad_type_requests_fail_before_rendering(self):
        cases = [('worker-key', 'coin'), ('worker-key', 'user'), ('unissued-user-key', 'coin'),
                 ('coin-key', 'unknown'), ('coin-key', None), ('coin-key', False),
                 ('coin-key', 1), ('coin-key', []), ('coin-key', {})]
        # Priority validation also precedes model availability checks.
        state.L['models'][self.model]['up'] = False
        for key, requested in cases:
            with self.subTest(key=key, requested=requested), self.assertRaises(urllib.error.HTTPError) as refused:
                self.request(key, request_class=requested)
            self.assertEqual(refused.exception.code, 400)
        self.render.assert_not_called()
        self.assertEqual(self.observed, [])
        self.assertFalse(state.L['thoughts'])

    def test_override_uses_configured_priority_order(self):
        with patch.dict(state.CONFIG, classes=['coin', 'background', 'user']):
            self.request('worker-key', request_class='user')
            self.assertEqual(self.observed[-1]['class'], 'user')
            self.render.reset_mock()
            with self.assertRaises(urllib.error.HTTPError) as refused:
                self.request('unissued-user-key', request_class='background')
            self.assertEqual(refused.exception.code, 400)
            self.render.assert_not_called()

    def test_demoting_an_ended_key_does_not_restore_its_authority(self):
        keys.ENDED.add('worker-key')
        with self.assertRaises(urllib.error.HTTPError) as refused:
            self.request('worker-key', request_class='background')
        self.assertEqual(refused.exception.code, 410)
        self.render.assert_not_called()
        self.assertFalse(state.L['thoughts'])


if __name__ == '__main__':
    unittest.main()
