"""Durable wakes cross the actual Coin turn/service boundary without Telegram alerts."""
import copy
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cointos import coin, wakeups
from tests.test_coin import assistant, call


class WakeService(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        for target, name, value in [(coin, 'COIN_STATE', self.directory),
                                    (coin.kt_mcp, 'open_session', Mock(return_value=None)),
                                    (coin, 'report', Mock()), (coin, 'send', Mock()),
                                    (coin.traceback, 'print_exc', Mock())]:
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def register(self, user=7):
        return wakeups.create(self.directory / 'wakes', user, user * 10, 'Check the actual task receipt.',
                              {'kind': 'deadline', 'after_seconds': 0})

    def run_worker(self, completions, arrivals=(), failure=KeyboardInterrupt):
        inbox = Mock()
        from cointos import coin_input
        for index, (user, chat, text) in enumerate(arrivals):
            coin_input.accept(self.directory / 'inputs', {'update_id': index, 'message': {
                'from': {'id': user}, 'chat': {'id': chat}, 'text': text}}, {7})
            coin_input.receipted(self.directory / 'inputs', index, index + 1)
        inbox.get.side_effect = [queue.Empty(), KeyboardInterrupt()]
        inbox.get_nowait.side_effect = queue.Empty
        requests = []

        def complete(model, messages, **options):
            requests.append((copy.deepcopy(messages), options))
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

        replies = iter(completions)
        with patch.object(coin, 'complete', side_effect=complete):
            with self.assertRaises(failure):
                coin.worker('never-a-real-token', inbox, {7})
        return requests

    def test_overdue_wake_survives_restart_and_sends_through_actual_model_turn(self):
        record = self.register()
        # There is no surviving sleeper or watcher: only a newly opened registry.
        requests = self.run_worker([assistant(call('send', {'message': 'Checked quietly.'}), call('done'))])
        self.assertEqual(requests[0][1]['request_class'], 'background')
        self.assertIn('<cointos-wake>', requests[0][0][-2]['content'])
        self.assertNotIn(coin.INPUT_GUIDANCE, requests[0][0][-2]['content'])
        coin.send.assert_called_once_with('never-a-real-token', 70, 'Checked quietly.')
        self.assertFalse(wakeups.pending(self.directory / 'wakes', record['id']))
        self.assertEqual(coin.recent(7)[-1]['content'], 'Checked quietly.')
        coin.report.assert_any_call(False)

    def test_promised_explanation_uses_coin_priority_through_delivery_and_ack(self):
        coin.explain_notification(7, 'The pipeline implementation stopped.')
        record = wakeups.ready(self.directory / 'wakes')[0]
        requests = self.run_worker([
            assistant(call('status')),
            assistant(call('send', {'message': 'The worker stopped; recovery owns the repair.'}), call('done')),
        ])
        self.assertEqual(len(requests), 2)
        self.assertTrue(all('request_class' not in options for _, options in requests))
        coin.send.assert_called_once_with('never-a-real-token', 7,
                                         'The worker stopped; recovery owns the repair.')
        self.assertFalse(wakeups.pending(self.directory / 'wakes', record['id']))

    def test_failed_model_turn_remains_pending_and_replays_after_worker_restart(self):
        record = self.register()
        self.run_worker([RuntimeError('model unavailable')])
        self.assertTrue(wakeups.pending(self.directory / 'wakes', record['id']))
        coin.send.assert_not_called()
        self.run_worker([assistant(content='Receipt checked.')])
        self.assertEqual(wakeups.list(self.directory / 'wakes', 7), [])
        coin.send.assert_called_once_with('never-a-real-token', 70, 'Receipt checked.')

    def test_ack_failure_replays_event_instead_of_losing_it(self):
        record = self.register()
        with patch.object(wakeups, 'ack', side_effect=OSError('disk unavailable')):
            self.run_worker([assistant(content='Checked once.')], failure=OSError)
        self.assertTrue(wakeups.pending(self.directory / 'wakes', record['id']))
        requests = self.run_worker([assistant(content='Rechecked current state before acting.')])
        self.assertIn('Delivery may repeat', requests[0][0][-2]['content'])
        self.assertFalse(wakeups.pending(self.directory / 'wakes', record['id']))
        self.assertEqual(coin.send.call_count, 2)

    def test_failed_send_replays_without_an_unsent_assistant_reply(self):
        record = self.register()
        with patch.object(coin, 'send', side_effect=OSError('transport unavailable')):
            self.run_worker([assistant(content='Unsent report.')])
        self.assertTrue(wakeups.pending(self.directory / 'wakes', record['id']))
        self.assertFalse(any(m['role'] == 'assistant' for m in coin.recent(7)))
        requests = self.run_worker([assistant(content='Delivered report.')])
        self.assertFalse(any(m.get('content') == 'Unsent report.' for m in requests[0][0]))
        self.assertFalse(wakeups.pending(self.directory / 'wakes', record['id']))
        coin.send.assert_called_once_with('never-a-real-token', 70, 'Delivered report.')

    def test_cancel_between_selection_and_execution_skips_the_turn(self):
        record = self.register()
        actual_ready = wakeups.ready

        def cancelled(directory):
            ready = actual_ready(directory)
            wakeups.cancel(directory, 7, record['id'])
            return ready

        with patch.object(wakeups, 'ready', side_effect=cancelled):
            self.assertEqual(self.run_worker([]), [])
        coin.send.assert_not_called()

    def test_removed_user_does_not_get_background_actions_or_notifications(self):
        record = self.register(user=8)
        self.assertEqual(self.run_worker([]), [])
        self.assertTrue(wakeups.pending(self.directory / 'wakes', record['id']))
        coin.send.assert_not_called()

    def test_direct_message_runs_before_pending_wake_and_keeps_foreground_priority(self):
        self.register()
        requests = self.run_worker([assistant(content='Direct reply.'), assistant(call('done'))],
                                   arrivals=[(7, 70, 'What is happening?')])
        self.assertNotIn('request_class', requests[0][1])
        self.assertEqual(requests[1][1]['request_class'], 'background')
        self.assertEqual(requests[0][1]['user'], requests[1][1]['user'])
        coin.send.assert_called_once_with('never-a-real-token', 70, 'Direct reply.')

    def test_real_message_joining_wake_enables_only_subsequent_direct_replies(self):
        self.register()
        wake = wakeups.ready(self.directory / 'wakes')[0]
        requests = []
        replies = iter([assistant(call('send', {'message': 'Private check.'})), assistant(content='Reply to you.')])

        def complete(model, messages, **options):
            requests.append(options)
            return next(replies)

        with patch.object(coin, 'complete', side_effect=complete):
            coin.turn('never-a-real-token', 7, 70, [], lambda: ['How is it?'], None, wake=wake)
        self.assertEqual(requests[0]['request_class'], 'background')
        self.assertNotIn('request_class', requests[1])
        self.assertEqual([c.args for c in coin.send.call_args_list], [('never-a-real-token', 70, 'Private check.'), ('never-a-real-token', 70, 'Reply to you.')])

    def test_wake_tools_bind_identity_to_conversation_and_deduplicate_repeated_calls(self):
        arguments = {'message': 'Check later.', 'condition': {'kind': 'deadline', 'after_seconds': 10},
                     'user': 8, 'chat': 80}
        replies = iter([assistant(call('wake', arguments), call('wake', arguments, 'duplicate')), assistant(call('done'))])
        with patch.object(coin, 'complete', side_effect=lambda *args, **kwargs: next(replies)):
            coin.turn('never-a-real-token', 7, 70, ['Check later.'], lambda: [], None)
        records = wakeups.list(self.directory / 'wakes', 7)
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]['user'], records[0]['chat']), (7, 70))
        self.assertEqual(wakeups.list(self.directory / 'wakes', 8), [])
        result = coin.wake_tool('cancel_wake', {'id': records[0]['id']}, 7, 70)
        self.assertTrue(result['cancelled'])

    def test_unfinished_turn_does_not_ack_the_event(self):
        record = self.register()
        rounds = coin.SETTINGS['max_tool_rounds'] + coin.SETTINGS['finishing_rounds']
        self.run_worker([assistant(call('status')) for _ in range(rounds)])
        self.assertTrue(wakeups.pending(self.directory / 'wakes', record['id']))
        coin.send.assert_not_called()

    def test_torn_history_tail_recovers_but_complete_corruption_is_not_hidden(self):
        coin.remember(7, 'user', 'Earlier request.')
        path = coin.history_path(7)
        with path.open('ab') as stream:
            stream.write(b'{"content":"torn\xff')
        self.assertEqual([{k: v for k, v in entry.items() if k != 'at'} for entry in coin.recent(7)], [{'role': 'user', 'content': 'Earlier request.'}])
        coin.remember(7, 'assistant', 'Recovered.')
        self.assertEqual([entry['content'] for entry in coin.recent(7)], ['Earlier request.', 'Recovered.'])
        with path.open('ab') as stream:
            stream.write(b'bad complete record\n')
        with self.assertRaises(json.JSONDecodeError):
            coin.recent(7)

    def test_observation_persists_event_without_inbox_model_or_foreground_completion(self):
        record = self.register()
        with patch.object(coin.time, 'sleep', side_effect=KeyboardInterrupt), \
                patch.object(coin, 'complete') as model:
            with self.assertRaises(KeyboardInterrupt):
                coin.observe_wakes()
        self.assertTrue(wakeups.pending(self.directory / 'wakes', record['id']))
        model.assert_not_called()
        coin.send.assert_not_called()

    def test_observation_error_uses_existing_retry_interval_and_never_notifies(self):
        with patch.object(wakeups, 'ready', side_effect=OSError('authority unavailable')), \
                patch.object(coin.time, 'sleep', side_effect=KeyboardInterrupt) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                coin.observe_wakes()
        sleep.assert_called_once_with(coin.SETTINGS['error_pause_seconds'])
        coin.send.assert_not_called()

    def test_wake_can_use_tools_then_send_model_composed_reminder(self):
        record = self.register()
        with patch.object(coin, 'execute', return_value={'ok': True, 'output': 'ABB follow-up is still pending.'}) as execute:
            requests = self.run_worker([
                assistant(call('status')),
                assistant(call('send', {'message': 'Follow up ABB; it is still pending.'}), call('done')),
            ])
        execute.assert_called_once_with('status', {})
        self.assertEqual(requests[0][1]['request_class'], 'background')
        self.assertEqual(requests[1][1]['request_class'], 'background')
        coin.send.assert_called_once_with('never-a-real-token', 70, 'Follow up ABB; it is still pending.')
        self.assertFalse(wakeups.pending(self.directory / 'wakes', record['id']))

    def test_wake_send_failure_stays_pending_until_successful_model_replay(self):
        record = self.register()
        coin.send.side_effect = OSError('transport unavailable')
        self.run_worker([assistant(content='Follow up ABB.')])
        self.assertTrue(wakeups.pending(self.directory / 'wakes', record['id']))
        coin.send.side_effect = None
        self.run_worker([assistant(content='Follow up ABB.')])
        self.assertFalse(wakeups.pending(self.directory / 'wakes', record['id']))

    def test_wake_may_finish_without_sending_anything(self):
        record = self.register()
        requests = self.run_worker([assistant(call('done'))])
        self.assertEqual(requests[0][1]['request_class'], 'background')
        coin.send.assert_not_called()
        self.assertFalse(wakeups.pending(self.directory / 'wakes', record['id']))


if __name__ == '__main__':
    unittest.main()
