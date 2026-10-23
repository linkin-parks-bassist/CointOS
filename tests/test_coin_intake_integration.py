"""Actual Coin intake and worker interruption, with Telegram/model transport isolated."""
import queue
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cointos import coin, coin_input


class DurableIntakeIntegration(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='coin-intake-integration-')))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.enterContext(patch.object(coin, 'credentials', return_value=('fixture-only-token', {7})))
        self.enterContext(patch.object(coin, 'service_thread'))
        self.enterContext(patch.object(coin, 'report'))
        self.enterContext(patch.object(coin.kt_mcp, 'open_session', return_value=None))
        self.enterContext(patch.object(coin.traceback, 'print_exc'))
        self.directory = self.root / 'inputs'
        self.update = {'update_id': 123, 'message': {'from': {'id': 7}, 'chat': {'id': 70},
                                                  'text': 'Inspect the current task.'}}

    def poll(self, updates):
        requests = []
        responses = iter([updates, KeyboardInterrupt()])
        def telegram(token, method, body, *args, **kwargs):
            self.assertEqual(method, 'getUpdates')
            requests.append(body.copy())
            result = next(responses)
            if isinstance(result, BaseException):
                raise result
            return result
        with patch.object(coin, 'telegram', side_effect=telegram), self.assertRaises(KeyboardInterrupt):
            coin.main()
        return requests



    def test_poll_saves_input_and_cursor_without_canned_reply(self):
        with patch.object(coin, 'complete') as model, patch.object(coin, 'send') as send:
            requests = self.poll([self.update])
        model.assert_not_called()
        send.assert_not_called()
        self.assertEqual(requests[-1]['offset'], 124)
        pending = coin_input.pending(self.directory)
        self.assertEqual([item['text'] for item in pending], [self.update['message']['text']])
        self.assertIsNone(pending[0]['receipt'])

    def test_restarted_worker_clears_stale_presence_even_when_idle(self):
        inbox = unittest.mock.Mock()
        inbox.get.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-only-token', inbox, {7})
        coin.report.assert_called_once_with(False)

    def test_restart_reloads_unreceipted_saved_input_without_resending_ack(self):
        self.poll([self.update])
        with patch.object(coin, 'send') as send:
            requests = self.poll([])
        self.assertEqual(requests[0]['offset'], 124)
        send.assert_not_called()
        self.assertEqual(len(coin_input.pending(self.directory)), 1)

    def test_poll_accepts_other_chat_without_any_delivery_dependency(self):
        other = {'update_id': 124, 'message': {**self.update['message'], 'chat': {'id': 71}}}
        with patch.object(coin, 'send', side_effect=AssertionError('poller must not send')):
            self.poll([self.update, other])
        self.assertEqual([item['chat'] for item in coin_input.pending(self.directory)], [70, 71])

    def test_status_is_saved_and_answered_by_model_without_canned_response(self):
        status = {**self.update, 'message': {**self.update['message'], 'text': '/status'}}
        with patch.object(coin, 'send') as send, patch.object(coin, 'status_text') as mechanical:
            self.poll([status])
        send.assert_not_called()
        mechanical.assert_not_called()
        inbox = unittest.mock.Mock()
        inbox.get.side_effect = KeyboardInterrupt
        with patch.object(coin, 'complete', return_value={'role': 'assistant', 'content': 'Model status explanation.'}) as model, \
                patch.object(coin, 'send') as send, self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-only-token', inbox, {7})
        self.assertIn('/status', str(model.call_args.args[1]))
        send.assert_called_once_with('fixture-only-token', 70, 'Model status explanation.')
        self.assertEqual(coin_input.pending(self.directory), [])

    def test_unallowed_input_is_not_saved_or_acknowledged(self):
        forbidden = {**self.update, 'message': {**self.update['message'], 'from': {'id': 8}}}
        with patch.object(coin, 'send') as send:
            self.poll([forbidden])
        send.assert_not_called()
        self.assertEqual(coin_input.pending(self.directory), [])
        self.assertEqual(coin_input.offset(self.directory, self.root / 'telegram-offset.json'), 124)

    def test_polling_stays_independent_of_notification_delivery_and_warnings_are_not_forwarded(self):
        warnings = {'alerts': [{'id': 1, 'text': 'worker blocked'},
                               {'id': 2, 'text': 'self-check failed'},
                               {'id': 3, 'text': 'memory pressure'}]}
        with patch.object(coin, 'ledger', return_value=warnings) as ledger, \
                patch.object(coin, 'send') as send, patch.object(coin, 'service_thread') as start:
            self.poll([])
        ledger.assert_not_called()
        send.assert_not_called()
        self.assertEqual([call.args[0] for call in start.call_args_list],
                         [coin.observe_wakes, coin.observe_attachments, coin.observe_notifications, coin.worker])
        with patch.object(coin, 'ledger', return_value=warnings), patch.object(coin, 'send') as send, \
                patch.object(coin.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): coin.observe_notifications('fixture-only-token', {7})
        send.assert_not_called()



    def test_worker_interruption_retains_input_and_next_worker_completes_it(self):
        coin_input.offset(self.directory, self.root / 'telegram-offset.json')
        record = coin_input.accept(self.directory, self.update, {7})
        with patch.object(coin, 'complete', side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-only-token', queue.Queue(), {7})
        self.assertEqual([r['id'] for r in coin_input.pending(self.directory)], [record['id']])
        actual_pending = coin_input.pending
        def stop_when_completed(directory):
            records = actual_pending(directory)
            if not records:
                raise KeyboardInterrupt()
            return records
        with patch.object(coin_input, 'pending', side_effect=stop_when_completed), \
             patch.object(coin, 'complete', return_value={'role': 'assistant', 'content': 'Checked the current task.'}), \
             patch.object(coin, 'send', return_value={'message_id': 459}) as send, \
             self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-only-token', queue.Queue(), {7})
        self.assertEqual(actual_pending(self.directory), [])
        send.assert_called_once_with('fixture-only-token', 70, 'Checked the current task.')

    def test_failed_reply_for_one_user_does_not_starve_another_saved_request(self):
        coin_input.offset(self.directory, self.root / 'telegram-offset.json')
        bad = coin_input.accept(self.directory, self.update, {7, 8})
        good = coin_input.accept(self.directory, {'update_id': 124, 'message': {
            'from': {'id': 8}, 'chat': {'id': 80}, 'text': 'My separate requested action.'}}, {7, 8})
        for item in (bad, good):
            coin_input.receipted(self.directory, item['id'], 456 + item['id'])
        bad_calls, delivered, good_seen = [], [], []
        def complete(model, messages, **options):
            if options['user'] == hashlib.sha256(b'7').hexdigest():
                bad_calls.append(True)
                if len(bad_calls) > 1:
                    raise KeyboardInterrupt()  # bound a broken immediate replay loop
                raise RuntimeError('fixture model failure')
            good_seen.append(True)
            return {'role': 'assistant', 'content': 'The separate action was checked.'}
        def send(token, chat, text):
            if chat == 70:
                raise RuntimeError('fixture reply transport failed')
            delivered.append(chat)
            return {'message_id': 461}
        actual_pending = coin_input.pending
        def stop_after_good_completion(directory):
            records = actual_pending(directory)
            if good_seen and good['id'] not in {item['id'] for item in records}:
                raise KeyboardInterrupt()
            return records
        with patch.object(coin_input, 'pending', side_effect=stop_after_good_completion), \
             patch.object(coin, 'complete', side_effect=complete), \
             patch.object(coin, 'send', side_effect=send), self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-only-token', queue.Queue(), {7, 8})
        self.assertEqual(delivered, [80])
        self.assertEqual([item['id'] for item in actual_pending(self.directory)], [bad['id']])

    def test_storage_failure_after_success_does_not_invent_a_model_failure_reply(self):
        coin_input.offset(self.directory, self.root / 'telegram-offset.json')
        record = coin_input.accept(self.directory, self.update, {7})
        with patch.object(coin, 'complete', return_value={
                'role': 'assistant', 'content': 'Checked the current task.'}), \
             patch.object(coin, 'send', return_value={'message_id': 462}) as send, \
             patch.object(coin_input, 'complete', side_effect=[OSError('fixture durable commit failed'),
                                                            KeyboardInterrupt()]), \
             self.assertRaises((OSError, KeyboardInterrupt)) as stopped:
            coin.worker('fixture-only-token', queue.Queue(), {7})
        self.assertIsInstance(stopped.exception, OSError)
        send.assert_called_once_with('fixture-only-token', 70, 'Checked the current task.')
        self.assertEqual([item['id'] for item in coin_input.pending(self.directory)], [record['id']])

    def test_large_media_backlog_never_enters_the_model_queue(self):
        coin_input.offset(self.directory, self.root / 'telegram-offset.json')
        for ident in range(294):
            coin_input.accept(self.directory, {'update_id': ident, 'message': {
                'from': {'id': 7}, 'chat': {'id': 70},
                'photo': [{'file_id': str(ident), 'file_unique_id': str(ident),
                           'width': 100, 'height': 100}]}}, {7})
        coin_input.accept(self.directory, {'update_id': 294, 'message': {
            'from': {'id': 7}, 'chat': {'id': 70}, 'text': 'Quick?'}}, {7})
        batches = []
        def turn(token, user, chat, texts, arrivals, knowledge, **kwargs):
            batches.append([item['id'] for item in texts])
            self.assertEqual(arrivals(), [])  # existing backlog is not new input
        inbox = unittest.mock.Mock()
        inbox.get.side_effect = KeyboardInterrupt
        with patch.object(coin, 'turn', side_effect=turn), self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-only-token', inbox, {7})
        self.assertEqual(batches, [[294]])
        self.assertEqual([item['id'] for item in coin_input.pending(self.directory)], list(range(294)))

    def test_new_arrivals_are_bounded_without_losing_deferred_input(self):
        self.poll([self.update])
        def turn(token, user, chat, texts, arrivals, knowledge, **kwargs):
            for ident in range(124, 154):
                coin_input.accept(self.directory, {'update_id': ident, 'message': {
                    'from': {'id': 7}, 'chat': {'id': 71}, 'text': str(ident)}}, {7})
            self.assertEqual([item['id'] for item in arrivals()], list(range(124, 134)))
            self.assertEqual([item['id'] for item in arrivals()], list(range(134, 143)))
            self.assertEqual(arrivals(), [])
        actual = coin_input.pending
        def stop_after_commit(directory):
            items = actual(directory)
            if items and items[0]['id'] == 143:
                raise KeyboardInterrupt()
            return items
        with patch.object(coin, 'turn', side_effect=turn), \
                patch.object(coin_input, 'pending', side_effect=stop_after_commit), self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-only-token', queue.Queue(), {7})
        self.assertEqual([item['id'] for item in actual(self.directory)], list(range(143, 154)))
