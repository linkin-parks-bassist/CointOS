"""Actual blocked-frontier delivery, durable retries and ownership boundaries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, coin, coin_input, coin_notifications as notifications, queues, state, wakeups
from tests import support


class ProgressDelivery(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'delivery'
        self.ledger = {'messages': [], 'queue': {'p:step': {'version': 1}}, 'tasks': {},
                       'work_frontier': [], 'paused': False}
        self.sent, self.acked = [], []

    def send(self, user, text):
        self.sent.append((user, text))
        return {'message_id': len(self.sent)}

    def deliver(self, now, users=None, send=None, ack=None):
        return notifications.deliver(self.root, self.ledger, {7} if users is None else users,
            send or self.send, now, 60, ack or self.acked.append)

    def block(self, **changes):
        row = {'item': 'p:step', 'status': 'blocked', 'blocker': 'Cannot continue: choose A or B.',
               'owner': None, 'continuations': [], 'held_by': None, 'admission_hold': None}
        row.update(changes)
        self.ledger['work_frontier'] = [row]

    def test_blocked_recovery_notifies_without_model_and_does_not_repeat_after_restart(self):
        self.block()
        self.deliver(100)
        self.deliver(159)
        self.assertEqual(self.sent, [])
        self.deliver(160)
        self.assertIn('choose A or B', self.sent[0][1])
        self.deliver(200)
        self.assertEqual(len(self.sent), 1)
        self.ledger['work_frontier'] = []
        self.deliver(201)
        self.block()
        self.deliver(202)
        self.deliver(262)
        self.assertEqual(len(self.sent), 2)

    def test_recovery_holds_and_pause_cancel_pending_escalation(self):
        for changes in ({'owner': 'repair'}, {'continuations': ['p:fix']}, {'held_by': 'user'},
                        {'admission_hold': 'explicit hold'}):
            self.block()
            self.deliver(100)
            self.block(**changes)
            self.deliver(200)
        self.block()
        self.ledger['paused'] = True
        self.deliver(400)
        self.assertEqual(self.sent, [])

    def test_full_question_survives_journal_removal_failed_send_and_ack_failure(self):
        text = 'A full question: ' + 'evidence ' * 700 + 'Recommendation: A.'
        self.ledger['messages'] = [{'to': 'user', 'from': 'p:repair', 'at': 99, 'read': False, 'text': text}]
        def offline(*args): raise OSError('offline')
        self.assertEqual(self.deliver(100, send=offline), ['offline'])
        self.ledger['messages'] = []
        def ack_offline(*args): raise OSError('daemon unavailable')
        with self.assertRaises(OSError): self.deliver(101, ack=ack_offline)
        self.assertEqual(self.sent, [(7, text)])
        self.deliver(102)
        self.assertEqual(self.sent, [(7, text)])
        self.assertEqual(self.acked, [{'from': 'p:repair', 'at': 99}])

    def test_failure_of_one_recipient_does_not_starve_another_and_removed_users_are_excluded(self):
        self.block()
        def sender(user, text):
            if user == 7: raise OSError('offline')
            return self.send(user, text)
        self.deliver(100)
        self.deliver(160, {7, 8}, sender)
        self.assertEqual([u for u, _ in self.sent], [8])
        self.deliver(170, {8})
        self.assertEqual(len(self.sent), 1)

    def test_worker_message_stays_local_while_recovery_or_continuation_can_act(self):
        self.ledger['messages'] = [{'to': 'user', 'from': 'p:step', 'at': 99,
                                   'read': False, 'text': 'The worker made a mistake.'}]
        self.block(owner='p:repair')
        self.deliver(100)
        self.assertEqual(self.sent, [])
        self.ledger['tasks'] = {'p:repair': {'repair_origin': {'task': 'p:step'}}}
        self.ledger['messages'][0]['from'] = 'p:repair'
        self.deliver(101)
        self.assertEqual(self.sent, [])
        self.block(continuations=['p:fix'])
        self.deliver(102)
        self.assertEqual(self.sent, [])
        self.block()
        self.deliver(103)
        self.assertEqual(len(self.sent), 1)

    def test_old_dashboard_history_is_not_broadcast(self):
        self.ledger['messages'] = [{'to': 'user', 'from': 'old', 'at': 10, 'read': True, 'text': 'old'}]
        self.ledger['alerts'] = [{'text': 'memory diagnostic'}]
        self.deliver(100)
        self.assertEqual(self.sent, [])


class MessageDeliveryAuthority(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)

    def test_dashboard_inbox_is_not_delivery_and_unaccepted_questions_survive_history_bounds(self):
        with patch.dict(state.CONFIG, messages_kept=1):
            api.send({'to': 'user', 'text': 'Choose A or B'})
            first = dict(state.L['messages'][0])
            api.inbox({})
            self.assertFalse(state.L['messages'][0]['read'])
            api.send({'to': 'user', 'text': 'Another question'})
            self.assertEqual(len(state.L['messages']), 2)
            api.message_delivered(first)
            self.assertTrue(state.L['messages'][0]['read'])
            api.send({'to': 'user', 'text': 'Third question'})
            self.assertNotIn(first, state.L['messages'])

    def test_agent_cannot_forge_user_delivery(self):
        with patch.object(api, 'running', return_value={'id': 'agent'}):
            with self.assertRaises(api.ApiError): api.message_delivered({'from': 'x', 'at': 0})


class NotificationExposition(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.report = 'PROJECT:task-17 ac567a1 REQUIRE(rc==0): six laws, four witnesses.'

    def test_report_queues_one_durable_explanation_without_placeholder_message(self):
        with patch.object(coin, 'send') as send:
            receipt = coin.notify('fixture-token', 7, self.report)
            self.assertEqual(coin.notify('fixture-token', 7, self.report), receipt)
        records = wakeups.list(self.root / 'wakes', 7)
        self.assertEqual(len(records), 1)
        self.assertEqual(receipt, {'explanation_id': records[0]['id']})
        self.assertIn(self.report, records[0]['message'])
        self.assertIn('trade-off', records[0]['message'])
        send.assert_not_called()

    def test_observer_acknowledges_only_after_durable_explanation_handoff(self):
        ledger = {'messages': [{'to': 'user', 'from': 'worker', 'at': 10,
                                'read': False, 'text': self.report}]}
        acknowledged = []
        directory = self.root / 'notifications'
        with patch.object(coin, 'send') as send:
            errors = notifications.deliver(directory, ledger, {7},
                lambda user, text: coin.notify('fixture-token', user, text), 11, 0,
                acknowledged.append)
        self.assertEqual(errors, [])
        self.assertEqual(acknowledged, [{'from': 'worker', 'at': 10}])
        self.assertEqual(len(wakeups.ready(self.root / 'wakes')), 1)
        send.assert_not_called()
        with patch.object(coin, 'explain_notification', side_effect=OSError('disk unavailable')):
            acknowledged.clear()
            errors = notifications.deliver(directory, ledger, {7},
                lambda user, text: coin.notify('fixture-token', user, text), 12, 0,
                acknowledged.append)
        self.assertEqual(errors, ['disk unavailable'])
        self.assertEqual(acknowledged, [])

    def test_failed_durable_handoff_does_not_send_a_placeholder(self):
        with patch.object(coin.wakeups, 'create', side_effect=OSError('disk unavailable')), \
                patch.object(coin, 'send') as send:
            with self.assertRaises(OSError): coin.notify('fixture-token', 7, self.report)
        send.assert_not_called()


class ConversationLoop(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root / 'coin'))
        self.enterContext(patch.object(coin, 'report'))
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))

    def test_delivered_question_answer_scoped_action_and_verified_response_share_one_context(self):
        support.queued(self.project, 'step', 'Summary: Builds the parser front end.\nBuild it')
        api.hold({'item': 'p:step'})
        question = ('Pigen is adding pipeline execution. Its tests need an ordering decision. '
                    'I recommend continuing with the existing requirements. Shall I resume the held work?')
        coin.remember(7, 'assistant', 'Your workout was logged.', at=1)
        with patch.object(coin, 'send', return_value={'message_id': 42, 'date': 2}):
            coin.deliver_text('fixture-token', 7, 70, question)
        record = coin_input.accept(self.root / 'inputs', {'update_id': 10, 'message': {
            'from': {'id': 7}, 'chat': {'id': 70}, 'text': 'Yes, use your recommendation.', 'date': 3,
            'reply_to_message': {'message_id': 42, 'text': question, 'date': 2,
                                 'from': {'is_bot': True}}}}, {7})
        self.assertEqual(coin_input.pending(self.root / 'inputs')[0]['reply_to']['message_id'], 42)
        requests = []
        def complete(model, messages, **options):
            requests.append(messages[:])
            text = '\n'.join(m.get('content') or '' for m in messages)
            self.assertIn(question, text)
            self.assertIn('Yes, use your recommendation.', text)
            self.assertIn('<cointos-reply-to>', text)
            if len(requests) == 1:
                return {'role': 'assistant', 'tool_calls': [{'id': 'release', 'function': {
                    'name': 'hold_item', 'arguments': '{"item":"p:step","release":true}'}}]}
            self.assertIsNone(state.L['queue']['p:step']['held_by'])
            return {'role': 'assistant', 'content': 'Pigen can continue; I released the held work.'}
        with patch.object(coin, 'complete', side_effect=complete), \
                patch.object(coin, 'call', side_effect=api.dispatch), \
                patch.object(coin, 'send', return_value={'message_id': 43}):
            coin.turn('fixture-token', 7, 70, [record], lambda: [], None)
        self.assertIsNone(state.L['queue']['p:step']['held_by'])
        self.assertEqual(coin.recent(7)[-1]['content'], 'Pigen can continue; I released the held work.')

    def test_notification_sent_mid_turn_is_in_the_next_prompt_and_reply_history(self):
        requests = []
        def complete(model, messages, **options):
            requests.append([dict(m) for m in messages])
            if len(requests) == 1:
                coin.deliver_text('fixture-token', 7, 70, 'Pigen recovery has stopped. Your work is preserved.')
                return {'role': 'assistant', 'tool_calls': [{'id': 'check', 'function': {
                    'name': 'status', 'arguments': '{}'}}]}
            self.assertIn('Pigen recovery has stopped.', '\n'.join(m.get('content') or '' for m in messages))
            return {'role': 'assistant', 'content': 'The new notice concerns Pigen, not your workout.'}
        with patch.object(coin, 'complete', side_effect=complete), \
                patch.object(coin, 'execute', return_value={'ok': True}), \
                patch.object(coin, 'send', return_value={'message_id': 51}):
            coin.turn('fixture-token', 7, 70, ['What happened?'], lambda: [], None)

    def test_internal_wakes_do_not_displace_telegram_messages_from_the_agreed_window(self):
        for i in range(19): coin.remember(7, 'assistant', 'Telegram ' + str(i), at=i+1)
        for i in range(30): coin.remember(7, 'user', '<cointos-wake>internal</cointos-wake>', at=i+100)
        self.assertEqual(len(coin.recent(7)), 19)
        self.assertEqual(coin.recent(7, incoming=1)[0]['content'], 'Telegram 7')

    def test_reply_reference_remains_when_the_quoted_message_has_rolled_out(self):
        quoted = 'Pigen question about preserving required pipeline behaviour.'
        for i in range(40): coin.remember(7, 'assistant', 'Later ' + str(i), at=i+1)
        record = coin_input.accept(self.root / 'inputs', {'update_id': 1, 'message': {
            'from': {'id': 7}, 'chat': {'id': 70}, 'text': 'Choose A.',
            'reply_to_message': {'message_id': 9, 'text': quoted, 'date': 1, 'from': {'is_bot': True}}}}, {7})
        self.assertIn(quoted, coin.input_text('fixture-token', record))

    def test_a_successful_first_part_remains_in_history_when_a_later_part_fails(self):
        text = 'x' * coin.TELEGRAM_LIMIT + 'The final part.'
        with patch.object(coin, 'send', side_effect=[{'message_id': 61, 'date': 100}, OSError('offline')]):
            with self.assertRaises(OSError): coin.deliver_text('fixture-token', 7, 70, text)
        self.assertEqual(coin.recent(7), [{'role': 'assistant', 'content': 'x' * coin.TELEGRAM_LIMIT, 'at': 100}])

    def test_telegram_delivery_identity_is_scoped_to_chat(self):
        with patch.object(coin, 'send', return_value={'message_id': 10}):
            coin.deliver_text('fixture-token', 7, 7, 'Private message')
            coin.deliver_text('fixture-token', 7, -70, 'Group message')
        self.assertEqual([m['content'] for m in coin.recent(7)], ['Private message', 'Group message'])


class ConcurrentHistory(unittest.TestCase):
    def test_prompt_context_does_not_wait_for_a_notification_network_send(self):
        from concurrent.futures import ThreadPoolExecutor
        from cointos import privatejson
        root = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'notifications'
        data = {'version': 1, 'after': 100, 'pending': {'blocked:one': {
            'kind': 'blocked', 'text': 'Pigen is waiting for recovery.', 'since': 100,
            'delivered': {'7': 12}, 'source': None}}}
        with ThreadPoolExecutor(max_workers=1) as worker:
            with privatejson.registry(root, notifications._read) as (fd, _):
                privatejson.write(fd, notifications.FILE, data, notifications._validate)
                result = worker.submit(notifications.context, root, 7).result(timeout=2)
                self.assertEqual(result, [{'message_id': 12, 'evidence': 'Pigen is waiting for recovery.'}])

    def test_concurrent_outgoing_messages_keep_complete_history_records(self):
        from concurrent.futures import ThreadPoolExecutor
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', root))
        coin.ensure_state()
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda n: coin.remember(7, 'assistant', str(n), delivery_id=n+1), range(16)))
        self.assertEqual(len(coin.recent(7)), 16)
        self.assertEqual({m['content'] for m in coin.recent(7)}, {str(n) for n in range(16)})


if __name__ == '__main__':
    unittest.main()
