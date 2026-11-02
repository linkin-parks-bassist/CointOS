"""Conversation flow uses actual delivery and original input, not inferred effects."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import coin, coin_followups
from tests.test_coin import assistant, call


class ConversationFlow(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.enterContext(patch.object(coin, 'report'))
        self.sent = []
        self.enterContext(patch.object(coin, 'send', side_effect=lambda *args: self.sent.append(args[-1])))

    def turn(self, replies, texts=None, arrivals=lambda: []):
        captured = []
        replies = iter(replies)
        def complete(model, messages, **options):
            captured.append(copy.deepcopy(messages))
            return next(replies)
        with patch.object(coin, 'complete', side_effect=complete):
            coin.turn('fixture', 7, 70, texts or [{'id': 1, 'text': 'Please update my record.'}], arrivals, None)
        return captured

    def test_unacknowledged_input_cannot_execute_or_finish_silently(self):
        with patch.object(coin, 'execute') as execute:
            captured = self.turn([
                assistant(call('run_command', {'command': 'exit 1'}), call('done')),
                assistant(call('send', {'message': 'I’ll pass that update on.'}), call('done'))])
        execute.assert_not_called()
        self.assertEqual(self.sent, ['I’ll pass that update on.'])
        results = [json.loads(m['content']) for m in captured[1] if m['role'] == 'tool']
        self.assertTrue(all(r['ok'] is False for r in results))

    def test_new_input_reopens_reply_obligation_and_keeps_same_owner(self):
        coin_followups.retain(self.root / 'followups', 7, 70, 'system:fitness-1', 'Update workout')
        arrivals = iter([[{'id': 2, 'text': '42.5x6, 42.5x9\nDeadlift 80x5'}], [], []])
        with patch.object(coin, 'call', return_value={'ok': True, 'delivery': 'inbox'}) as api:
            captured = self.turn([
                assistant(call('send', {'message': 'Passing on the first set.'})),
                assistant(call('update_work', {'task': 'system:fitness-1', 'instruction': 'Add these sets.', 'input_ids': [1, 2]}), call('done')),
                assistant(call('send', {'message': 'Including the extra sets and deadlift.'}),
                          call('update_work', {'task': 'system:fitness-1', 'instruction': 'Add these sets.', 'input_ids': [1, 2]}), call('done'))],
                texts=[{'id': 1, 'text': 'Press 42.5x6'}], arrivals=lambda: next(arrivals, []))
        api.assert_called_once()
        self.assertEqual(api.call_args.args[0], 'send')
        body = api.call_args.args[1]
        self.assertEqual(body['to'], 'system:fitness-1')
        originals = json.loads(body['text'].split(':\n', 1)[1])
        self.assertEqual([r['text'] for r in originals], ['Press 42.5x6', '42.5x6, 42.5x9\nDeadlift 80x5'])
        self.assertIn('<cointos-dispatched-work>', str(captured[0]))
        self.assertEqual(len(coin_followups.context(self.root / 'followups', 7, 70)), 1)

    def test_failed_acknowledgement_cannot_dispatch(self):
        with patch.object(coin, 'send', side_effect=OSError('offline')), patch.object(coin, 'execute') as execute:
            with self.assertRaisesRegex(OSError, 'offline'):
                self.turn([assistant(call('send', {'message': 'Passing that on.'}),
                                     call('run_agent', {'name': 'records', 'brief': 'Update records.'}))])
        execute.assert_not_called()

    def test_empty_send_is_not_a_receipt_and_done_content_is_delivered_once(self):
        self.turn([assistant(call('send', {'message': ''}), call('done'), content='Received your update.')])
        self.assertEqual(self.sent, ['Received your update.'])

    def test_refused_report_cannot_hide_an_unanswered_direct_message(self):
        self.turn([
            assistant(call('report_result', {'message': 'Already done'}), call('done'), content='Already done'),
            assistant(call('send', {'message': 'Received; I’ll arrange the update.'}), call('done'))])
        self.assertEqual(self.sent, ['Received; I’ll arrange the update.'])

    def test_originals_are_in_dispatch_and_followup_independently_of_summary(self):
        inputs = [{'id': 1, 'at': 10, 'text': 'press 42.5x6'},
                  {'id': 2, 'at': 11, 'text': '... 42.5x6, 42.5x9'}]
        for name, arguments, result in [
                ('run_agent', {'name': 'fitness', 'brief': 'Update workout.'}, {'ok': True, 'task': 'system:fitness-1'}),
                ('queue_item', {'project': 'p', 'brief': 'Update behaviour.'}, {'ok': True, 'item': 'behaviour'})]:
            with self.subTest(name=name), patch.object(coin, 'execute', return_value=result) as execute:
                reply = coin.invoke(name, {**arguments, 'input_ids': [1, 2]}, 'fixture', 7, 70, None, inputs=inputs)
            brief = execute.call_args.args[1]['brief']
            self.assertEqual(json.loads(brief.split(':\n', 1)[1]), inputs)
            self.assertEqual(arguments['brief'].count('Original user'), 0)
            self.assertEqual(reply['completion_followup'], 'durably registered')
        retained = coin_followups.context(self.root / 'followups', 7, 70)
        self.assertTrue(all('42.5x6' in item['description'] for item in retained))
        self.assertEqual(coin_followups.context(self.root / 'followups', 8, 70), [])
        self.assertEqual(coin_followups.context(self.root / 'followups', 7, 71), [])

    def test_update_requires_this_conversations_owner_and_live_user_input(self):
        coin_followups.retain(self.root / 'followups', 7, 70, 'system:fitness-1', 'Update records')
        arguments = {'task': 'system:fitness-1', 'instruction': 'Add another set.'}
        with patch.object(coin, 'call') as api:
            self.assertFalse(coin.invoke('update_work', arguments, 'fixture', 8, 70, None,
                                        inputs=[{'text': '42.5x6'}])['ok'])
            self.assertFalse(coin.invoke('update_work', arguments, 'fixture', 7, 71, None,
                                        inputs=[{'text': '42.5x6'}])['ok'])
            self.assertFalse(coin.invoke('update_work', arguments, 'fixture', 7, 70, None)['ok'])
            api.assert_not_called()

    def test_mixed_requests_need_explicit_source_binding_and_do_not_leak(self):
        inputs = [{'id': 1, 'text': 'Personal log entry.'}, {'id': 2, 'text': 'Fix project parsing.'}]
        arguments = {'project': 'p', 'brief': 'Fix parsing.'}
        with patch.object(coin, 'execute', return_value={'ok': True, 'item': 'parsing'}) as execute:
            for ids in (None, [], [99], [True], '2'):
                selected = {} if ids is None else {'input_ids': ids}
                self.assertFalse(coin.invoke('queue_item', {**arguments, **selected}, 'fixture', 7, 70,
                                             None, inputs=inputs)['ok'])
            execute.assert_not_called()
            result = coin.invoke('queue_item', {**arguments, 'input_ids': [2]}, 'fixture', 7, 70, None, inputs=inputs)
        self.assertTrue(result['ok'])
        forwarded = execute.call_args.args[1]
        self.assertNotIn('input_ids', forwarded)
        self.assertNotIn('Personal log entry.', forwarded['brief'])
        self.assertIn('Fix project parsing.', forwarded['brief'])

    def test_settled_owner_refusal_does_not_start_or_kill_another_run(self):
        coin_followups.retain(self.root / 'followups', 7, 70, 'system:fitness-1', 'Update records')
        with patch.object(coin, 'call', side_effect=ValueError('not an active task')) as api:
            self.turn([
                assistant(call('send', {'message': 'Passing on the correction.'}),
                          call('update_work', {'task': 'system:fitness-1', 'instruction': 'Add another set.'})),
                assistant(call('done'))])
        self.assertEqual([c.args[0] for c in api.call_args_list], ['send'])

    def test_waiting_operator_receives_update_in_real_daemon_inbox(self):
        from tests import support
        from cointos import api, state, tasks
        support.fresh_ledger(self)
        support.quiet(self)
        task = tasks.create('operator', tasks.SYSTEM, 'fitness', 'Update records.', [1])
        coin_followups.retain(self.root / 'followups', 7, 70, task['id'], task['brief'])
        with patch.object(coin, 'call', side_effect=lambda action, body: api.dispatch(action, body)):
            result = coin.invoke('update_work', {'task': task['id'], 'instruction': 'Include these sets.'},
                                 'fixture', 7, 70, None,
                                 inputs=[{'id': 12, 'text': '42.5x6, 42.5x6, 42.5x9'}])
        self.assertEqual(result['delivery'], 'inbox')
        self.assertEqual((task['status'], task['runs'], task['brief']), ('waiting', 0, 'Update records.'))
        self.assertEqual(len(state.L['tasks']), 1)
        message = state.L['messages'][-1]
        self.assertEqual((message['to'], message['read']), (task['id'], False))
        self.assertIn('42.5x6, 42.5x6, 42.5x9', message['text'])


if __name__ == '__main__':
    unittest.main()
