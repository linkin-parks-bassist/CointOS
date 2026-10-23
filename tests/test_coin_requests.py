"""Ongoing user work outlives chat rollover without leaking between users."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cointos import coin, coin_requests


class Requests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.directory = self.root / 'requests'

    def test_retain_replays_after_reopening_and_finishing_is_user_scoped(self):
        a = coin_requests.retain(self.directory, 7, 70, 'Save all 294 pictures to ~/Pictures/AOW.')
        b = coin_requests.retain(self.directory, 8, 80, 'A different user request')
        self.assertEqual(coin_requests.retain(self.directory, 7, 70, '  ' + a['instruction'] + '  '), a)
        a['instruction'] = 'mutated copy'
        retained = coin_requests.active(self.directory, 7)
        self.assertEqual(len(retained), 1)
        self.assertIn('294', retained[0]['instruction'])
        self.assertFalse(coin_requests.finish(self.directory, 8, retained[0]['id']))
        self.assertTrue(coin_requests.finish(self.directory, 7, retained[0]['id']))
        self.assertFalse(coin_requests.finish(self.directory, 7, retained[0]['id']))
        self.assertEqual(coin_requests.active(self.directory, 7), [])
        self.assertEqual(coin_requests.active(self.directory, 8), [b])
        self.assertEqual((self.directory / 'requests.json').stat().st_mode & 0o777, 0o600)

    def test_private_storage_refuses_symlink_and_invalid_instruction(self):
        other = self.root / 'other'
        other.write_text('do not replace')
        self.directory.mkdir(mode=0o700)
        (self.directory / 'requests.json').symlink_to(other)
        with self.assertRaises(OSError):
            coin_requests.retain(self.directory, 7, 70, 'ongoing request')
        self.assertEqual(other.read_text(), 'do not replace')
        for value in ('', '  ', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                coin_requests.retain(self.directory, 7, 70, value)

    def test_original_instruction_survives_294_messages_without_changing_history_policy(self):
        instruction = 'Save all 294 arriving pictures to ~/Pictures/AOW. Finish only after all are verified.'
        request = coin.invoke('retain_request', {'instruction': instruction}, 'token', 7, 70, None)['request']
        coin_requests.retain(self.directory, 8, 80, 'private other-user instruction')
        for n in range(294):
            coin.remember(7, 'user', 'photo ' + str(n), at=n)
        history = copy.deepcopy(coin.recent(7, incoming=1))
        calls = []
        def complete(model, messages, **options):
            calls.append((copy.deepcopy(messages), options))
            if len(calls) == 1:
                return {'role': 'assistant', 'tool_calls': [{'id': 'finish', 'function': {
                    'name': 'finish_request', 'arguments': json.dumps({'id': request['id']})}}]}
            return {'role': 'assistant', 'content': 'Verified.'}
        with patch.object(coin, 'complete', side_effect=complete), patch.object(coin, 'send'), patch.object(coin, 'report'):
            coin.turn('token', 7, 70, ['Final batch'], lambda: [], None)
        messages, options = calls[0]
        boundary = 1 + len(history)
        self.assertEqual(options['cache_prefix_messages'], boundary)
        self.assertEqual(messages[1:boundary], history)
        self.assertIn(instruction, messages[boundary]['content'])
        self.assertNotIn('private other-user', str(messages))
        self.assertFalse(any('<cointos-active-requests>' in str(m.get('content')) for m in calls[1][0]))
        self.assertEqual(coin_requests.active(self.directory, 7), [])

    def test_request_registered_during_turn_reaches_next_round_and_next_turn(self):
        rounds = []
        def complete(model, messages, **options):
            rounds.append(copy.deepcopy(messages))
            if len(rounds) == 1:
                return {'role': 'assistant', 'tool_calls': [{'id': 'retain', 'function': {
                    'name': 'retain_request', 'arguments': json.dumps({'instruction': 'Save later batches to ~/album'})}}]}
            return {'role': 'assistant', 'content': 'Ready.'}
        with patch.object(coin, 'complete', side_effect=complete), patch.object(coin, 'send'), patch.object(coin, 'report'):
            coin.turn('token', 7, 70, ['Save later batches to ~/album'], lambda: [], None)
            coin.turn('token', 7, 70, ['Another batch'], lambda: [], None)
        for messages in rounds[1:]:
            active = [m for m in messages if '<cointos-active-requests>' in str(m.get('content'))]
            self.assertEqual(len(active), 1)
            self.assertIn('Save later batches', active[0]['content'])
        self.assertEqual(len(coin_requests.active(self.directory, 7)), 1)
