"""Delivered guidance yields reasoning without truncating writing or invoking abort."""
import io
import json
import queue
import unittest
from unittest.mock import patch

from cointos import gateway, lanes, messages, state
from tests import support


class Interruption(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.enterContext(patch.dict(lanes.RUNS, clear=True))

    def test_only_complete_reasoning_is_interruptible(self):
        run = {'message_pending': True, 'reader': {'thinking': True}}
        for phase, content, calls, expected in [
                ('reasoning', '', [], True), ('writing', '', [], False),
                ('writing', '', [{'function': {}}], False),
                ('reasoning', 'output', [], False)]:
            with self.subTest(phase=phase, content=content, calls=calls):
                with patch.object(lanes.BACKEND, 'read', return_value={
                        'phase': phase, 'content': content, 'tool_calls': calls}) as read:
                    self.assertEqual(lanes.message_boundary('fixture', run, [1, 2, 3]), expected)
                    read.assert_called_once_with(state.CONFIG, 'fixture', run['reader'], [1, 2, 3], False)
        with patch.object(lanes.BACKEND, 'read') as read:
            self.assertFalse(lanes.message_boundary('fixture', run, []))
            self.assertFalse(lanes.message_boundary('fixture', {}, [1]))
            read.assert_not_called()

    def test_post_must_succeed_before_exact_existing_request_can_yield(self):
        state.L['tasks']['p:work'] = {'agent': 'worker'}
        state.L['agents']['worker'] = {'url': 'server', 'session': 'session'}
        state.L['thoughts'].update({'old': {'agent': 'worker'}, 'other': {'agent': 'another'}})
        lanes.RUNS.update({'old': {}, 'other': {}})
        message = {'to': 'p:work', 'from': 'p:supervisor', 'posting': True, 'read': False}
        with patch.object(messages, 'post', side_effect=OSError('offline')):
            messages.deliver(message, 'guidance', 'server', 'session', None)
        self.assertFalse(message['read'])
        self.assertFalse(lanes.RUNS['old'])
        def posted(*args):
            self.assertFalse(lanes.RUNS['old'])
            # A request started after posting is not retroactively interrupted.
            state.L['thoughts']['new'] = {'agent': 'worker'}
            lanes.RUNS['new'] = {}
        with patch.object(messages, 'post', side_effect=posted):
            messages.deliver(message, 'guidance', 'server', 'session', None)
        self.assertTrue(message['read'])
        self.assertTrue(lanes.RUNS['old']['message_pending'])
        self.assertFalse(lanes.RUNS['other'])
        self.assertFalse(lanes.RUNS['new'])

    def test_gateway_unknown_finish_preserves_reasoning_and_continues_without_pre_stop(self):
        for streaming in (False, True):
            with self.subTest(stream=streaming):
                channel = queue.Queue()
                channel.put(([1], 'unfinished reasoning'))
                channel.put({'end': 'message'})
                lanes.RUNS['fixture'] = {'queue': channel}
                handler = gateway.Handler.__new__(gateway.Handler)
                handler.wfile = io.BytesIO()
                final = {'reasoning': 'unfinished reasoning', 'content': '', 'tool_calls': [], 'phase': 'reasoning'}
                with patch.object(handler, 'peer_closed', return_value=False), \
                     patch.object(handler, 'send_response'), patch.object(handler, 'send_header'), \
                     patch.object(handler, 'end_headers'), patch.object(handler, 'reply') as reply, \
                     patch.object(gateway.BACKEND, 'read', return_value=final), \
                     patch.object(gateway.backend_chat, 'read', return_value=final), \
                     patch.object(gateway, 'pre_stop_check') as pre_stop, \
                     patch.object(gateway, '_remember_tool_history', return_value=None):
                    handler.reply_thought({'stream': streaming}, 'worker', 'fixture',
                                          {'tokens': [2], 'reader': {}}, 'fixture')
                    pre_stop.assert_not_called()
                    if streaming:
                        output = handler.wfile.getvalue().decode()
                        self.assertIn('"finish_reason": "unknown"', output)
                        self.assertIn('[DONE]', output)
                        self.assertNotIn('incomplete_response', output)
                    else:
                        response = reply.call_args.args[1]
                        self.assertEqual(response['choices'][0]['finish_reason'], 'unknown')
                        self.assertEqual(response['choices'][0]['message']['reasoning_content'], 'unfinished reasoning')
