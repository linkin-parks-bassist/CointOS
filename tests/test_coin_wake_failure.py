"""A real message joining a wake retains ordinary failure replies and wake retry."""
import copy
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

from cointos import coin, coin_input, wakeups
from tests.test_coin import assistant, call


class MixedWakeFailure(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='cointos-mixed-wake-')))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.enterContext(patch.object(coin.kt_mcp, 'open_session', return_value=None))
        self.enterContext(patch.object(coin, 'report'))
        self.sent = self.enterContext(patch.object(coin, 'send'))
        self.enterContext(patch.object(coin.traceback, 'print_exc'))
        self.record = wakeups.create(self.root / 'wakes', 7, 70, 'Recheck useful work',
                                     {'kind': 'deadline', 'after_seconds': 0})

    def run_worker(self, arrival, later_reply=None):
        inbox = Mock()
        inbox.get.side_effect = [queue.Empty(), KeyboardInterrupt()]
        replies = iter([assistant(call('send', {'message': 'Private wake check.'})),
                        RuntimeError('fixture model failure after arrival'), *([later_reply] if later_reply else [])])
        requests = []
        def complete(model, messages, **options):
            requests.append((copy.deepcopy(messages), options))
            if len(requests) == 1:
                user, chat, text = arrival
                coin_input.accept(self.root / 'inputs', {'update_id': 1, 'message': {
                    'from': {'id': user}, 'chat': {'id': chat}, 'text': text}}, {7, 8})
                coin_input.receipted(self.root / 'inputs', 1, 101)
            result = next(replies)
            if isinstance(result, Exception):
                raise result
            return result
        with patch.object(coin, 'complete', side_effect=complete), self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-only-token', inbox, {7, 8})
        return requests

    def test_same_user_arrival_model_failure_retains_input_without_canned_reply(self):
        requests = self.run_worker((7, 71, 'Please explain the result.'))
        self.assertEqual(requests[0][1]['request_class'], 'background')
        self.assertNotIn('request_class', requests[1][1])
        self.assertIn('Please explain the result.', str(requests[1][0]))
        self.sent.assert_called_once_with('fixture-only-token', 70, 'Private wake check.')
        self.assertTrue(wakeups.pending(self.root / 'wakes', self.record['id']))
        self.assertEqual([item['text'] for item in coin_input.pending(self.root / 'inputs')], ['Please explain the result.'])
        self.assertNotIn('fixture model failure after arrival', coin.recent(7)[-1]['content'])

    def test_other_user_arrival_is_queued_without_sending_failure_to_wake_owner(self):
        requests = self.run_worker((8, 80, 'My separate question.'), assistant(content='Your separate reply.'))
        self.assertEqual(requests[0][1]['request_class'], 'background')
        self.assertEqual(requests[1][1]['request_class'], 'background')
        self.assertNotIn('My separate question.', str(requests[1][0]))
        self.assertNotIn('request_class', requests[2][1])
        self.assertEqual([c.args for c in self.sent.call_args_list], [
            ('fixture-only-token', 70, 'Private wake check.'),
            ('fixture-only-token', 80, 'Your separate reply.')])
        self.assertTrue(wakeups.pending(self.root / 'wakes', self.record['id']))
        self.assertEqual(coin_input.pending(self.root / 'inputs'), [])


if __name__ == '__main__':
    unittest.main()
