"""Streamed token text reaches reply deltas without detokenizing the whole step each time."""
import io
import json
import queue
import unittest
from unittest.mock import patch

from cointos import gateway, lanes, state
from tests import support


class GatewayStreaming(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.enterContext(patch.dict(lanes.RUNS, clear=True))
        self.enterContext(patch.object(gateway, 'show'))

    def reply(self, items, final):
        pending = queue.Queue()
        for item in items:
            pending.put(item)
        pending.put({'end': 'done'})
        handler = gateway.Handler.__new__(gateway.Handler)
        handler.wfile = io.BytesIO()
        handler.peer_closed = lambda: False
        handler.send_response = lambda code: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        with patch.dict(lanes.RUNS, fixture={'queue': pending}), \
             patch.object(gateway.BACKEND, 'read', return_value=final):
            handler.reply_thought({'stream': True}, 'fixture', state.CONFIG['work_model'],
                                  {'tokens': [1, 2], 'reader': {'thinking': False}}, 'fixture')
        return [json.loads(line[6:]) for line in handler.wfile.getvalue().decode().splitlines()
                if line.startswith('data: ') and line != 'data: [DONE]']

    def test_each_streamed_fragment_becomes_its_own_delta(self):
        final = {'reasoning': '', 'content': 'Hi there', 'tool_calls': [], 'phase': 'writing'}
        frames = self.reply([([3], 'Hi '), ([4], 'there')], final)
        deltas = [frame['choices'][0]['delta'].get('content', '') for frame in frames]
        self.assertEqual(''.join(deltas), 'Hi there')
        self.assertEqual([delta for delta in deltas if delta], ['Hi ', 'there'])
