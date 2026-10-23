"""History rollover and native cache boundaries must agree, including changing clock tails."""
import copy
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from cointos import coin, config, gateway, lanes, snapshots, state


class HistoryBlocks(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.enterContext(patch.dict(coin.SETTINGS, history_messages=20, history_trim_messages=7))

    def test_twenty_message_window_trims_seven_only_at_rollover(self):
        for count in range(1, 43):
            coin.remember(7, 'user' if count % 2 else 'assistant', str(count), at=count)
            expected_start = 0 if count < 20 else ((count - 20) // 7 + 1) * 7
            actual = coin.recent(7)
            self.assertEqual([int(item['content']) for item in actual], list(range(expected_start + 1, count + 1)))
            self.assertEqual([item['at'] for item in actual], list(range(expected_start + 1, count + 1)))
        self.assertEqual(len(coin.history_path(7).read_text().splitlines()), 42)

    def test_block_size_is_configurable_and_user_histories_are_independent(self):
        with patch.dict(coin.SETTINGS, history_messages=8, history_trim_messages=3):
            for count in range(1, 9):
                coin.remember(7, 'user', str(count))
            coin.remember(8, 'user', 'other conversation')
            self.assertEqual([m['content'] for m in coin.recent(7)], ['4', '5', '6', '7', '8'])
            coin.remember(7, 'assistant', '9')
            self.assertEqual([m['content'] for m in coin.recent(7)], ['4', '5', '6', '7', '8', '9'])
            self.assertEqual([m['content'] for m in coin.recent(8)], ['other conversation'])

    def test_replay_retains_one_history_record_and_stable_prefix(self):
        for number in range(19):
            coin.remember(7, 'assistant', str(number), at=number)
        before = coin.recent(7, incoming=1)
        self.assertEqual(coin.remember(7, 'user', 'Quick?', at=20, input_id=123), 20)
        raw = coin.history_path(7).read_bytes()
        self.assertEqual(coin.remember(7, 'user', 'Quick?', at=30, input_id=123), 20)
        self.assertEqual(coin.history_path(7).read_bytes(), raw)
        self.assertEqual(coin.recent(7, incoming=1, exclude_inputs={123}), before)
        coin.remember(7, 'user', 'Quick?', at=40, input_id=124)
        self.assertEqual(len(coin.history_path(7).read_text().splitlines()), 21)
        coin.remember(8, 'user', 'Separate', at=50, input_id=123)
        self.assertEqual(coin.recent(8)[0]['content'], 'Separate')

    def test_uncommitted_final_record_cannot_suppress_replayed_input(self):
        path = coin.history_path(7)
        path.write_text(json.dumps({'role': 'user', 'content': 'partial', 'at': 1, 'input_id': 123}))
        coin.remember(7, 'user', 'Complete', at=2, input_id=123)
        self.assertEqual(coin.recent(7), [{'role': 'user', 'content': 'Complete', 'at': 2}])

    def test_legacy_captionless_photo_receipts_do_not_contaminate_new_conversation(self):
        coin.remember(7, 'user', 'Remember the destination', at=1)
        for ident in range(294):
            coin.remember(7, 'user', '\n\n<cointos-attachments>\n{}\n</cointos-attachments>', at=ident+2)
        coin.remember(7, 'user', 'Caption here\n\n<cointos-attachments>\n{}\n</cointos-attachments>', at=300)
        coin.remember(7, 'user', 'A new unrelated message', at=301)
        self.assertEqual([m['content'].splitlines()[0] for m in coin.recent(7)],
                         ['Remember the destination', 'Caption here', 'A new unrelated message'])
        self.assertEqual(len(coin.history_path(7).read_text().splitlines()), 297)

    def test_new_input_rolls_the_window_before_model_call_and_pins_unchanging_prefix(self):
        for count in range(1, 20):
            coin.remember(7, 'user' if count % 2 else 'assistant', str(count), at=count)
        requests = []
        def complete(model, messages, **options):
            requests.append((copy.deepcopy(messages), options))
            if len(requests) == 1:
                return {'role': 'assistant', 'tool_calls': [{'id': 'status', 'function': {
                    'name': 'status', 'arguments': '{}'}}]}
            return {'role': 'assistant', 'content': 'Checked.'}
        with patch.object(coin, 'complete', side_effect=complete), patch.object(coin, 'send'), \
                patch.object(coin, 'report'), patch.object(coin, 'execute', return_value={'ok': True}):
            coin.turn('token', 7, 70, ['20'], lambda: [], None)
        first, options = requests[0]
        self.assertEqual([m['content'] for m in first[1:13]], [str(i) for i in range(8,20)])
        self.assertTrue(first[13]['content'].startswith('20'))
        self.assertEqual(options['cache_prefix_messages'], 13)  # system plus twelve archived messages
        self.assertEqual(requests[1][1]['cache_prefix_messages'], 13)
        self.assertEqual(first[:13], requests[1][0][:13])

    def test_damaged_final_record_does_not_shift_the_block_counter(self):
        for count in range(1, 20):
            coin.remember(7, 'user', str(count))
        with coin.history_path(7).open('ab') as stream:
            stream.write(b'{"unfinished":')
        self.assertEqual(len(coin.recent(7)), 19)
        self.assertEqual([m['content'] for m in coin.recent(7, incoming=1)], [str(i) for i in range(8,20)])

    def test_invalid_block_size_is_rejected_during_configuration_load(self):
        settings = json.loads(Path('config/cointos.json').read_text())
        for value in (0, -1, True, 2.5, '7', 20, 21):
            settings['coin']['history_trim_messages'] = value
            path = self.root / 'cointos.json'
            path.write_text(json.dumps(settings))
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'history_trim_messages'):
                config.load(path)


class HistoryPrefix(unittest.TestCase):
    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))

    def test_gateway_derives_stable_history_boundary_from_native_tokens(self):
        # The template's suffix need not be a token prefix: the gateway compares
        # the actual render, rather than assuming character lengths or chat markers.
        rendered = iter([
            {'tokens': [1, 2, 3, 4, 5, 6, 7, 8], 'reader': {}},
            {'tokens': [1, 2, 30], 'reader': {}},
            {'tokens': [1, 2, 31], 'reader': {}},
            {'tokens': [1, 2, 3, 4, 50], 'reader': {}},
        ])
        body = {'cache_prefix_messages': 3, 'messages': [
            {'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'old question'},
            {'role': 'assistant', 'content': 'old answer'}, {'role': 'user', 'content': 'new question'},
            {'role': 'user', 'content': 'fresh clock/timeline'}]}
        with patch.object(gateway.BACKEND, 'render', side_effect=lambda *args: next(rendered)) as render:
            result = gateway.render_request(body, 'coin', state.CONFIG['coin']['model'], {})
        self.assertEqual(result['shared'], [2])
        self.assertEqual(result['retained_prefix'], 4)
        self.assertEqual(render.call_args.args[2]['messages'], body['messages'][:3] + [{'role': 'user', 'content': ''}])

    def test_shared_system_boundary_survives_a_rollover_to_assistant_first(self):
        body = {'messages': [{'role': 'system', 'content': 'system'},
                             {'role': 'assistant', 'content': 'old answer'},
                             {'role': 'user', 'content': 'new question'}]}
        with patch.object(gateway.BACKEND, 'render', side_effect=[
                {'tokens': [1, 2, 31, 4, 5], 'reader': {}},
                {'tokens': [1, 2, 30], 'reader': {}},
                {'tokens': [1, 2, 31, 40], 'reader': {}}]):
            result = gateway.render_request(body, 'coin', state.CONFIG['coin']['model'], {})
        self.assertEqual(result['shared'], [2])

    def test_prefix_contract_cannot_name_an_invalid_or_non_coin_boundary(self):
        messages = [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'question'}]
        for agent, count in [('coin', 0), ('coin', 2), ('coin', True), ('coin', '1'), ('user', 1)]:
            with self.subTest(agent=agent, count=count), self.assertRaisesRegex(ValueError, 'cache_prefix_messages'):
                gateway.render_request({'messages': messages, 'cache_prefix_messages': count}, agent,
                                       state.CONFIG['coin']['model'], {})
