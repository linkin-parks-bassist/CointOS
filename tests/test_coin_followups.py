import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cointos import coin, coin_followups, wakeups


class CompletionFollowups(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))

    def test_dispatch_registers_queue_and_operator_results_with_transport_identity(self):
        for name, arguments, result, task in [
                ('run_agent', {'brief': 'Transcribe the recording'}, {'ok': True, 'task': 'system:audio'}, 'system:audio'),
                ('queue_item', {'project': 'p', 'brief': 'Build the requested feature'}, {'ok': True, 'item': 'build'}, 'p:build')]:
            with patch.object(coin, 'execute', return_value=result):
                reply = coin.invoke(name, arguments, 'not-a-token', 7, 70, None)
            self.assertEqual(reply['completion_followup'], 'durably registered')
            with coin_followups._registry(self.root / 'followups') as (_, data):
                item = data['items'][coin_followups.identity(7, task)]
                self.assertEqual((item['user'], item['chat']), (7, 70))

    def test_restart_failed_work_and_removed_recipients_do_not_announce_completion(self):
        coin_followups.retain(self.root / 'followups', 7, 70, 'system:audio', 'Transcribe the recording')
        for status in ['running', 'failed']:
            coin_followups.observe(self.root / 'followups', self.root / 'wakes',
                                   {'tasks': {'system:audio': {'status': status}}}, {7})
            self.assertEqual(wakeups.list(self.root / 'wakes', 7), [])
        ledger = {'tasks': {'system:audio': {'status': 'done'}}}
        coin_followups.observe(self.root / 'followups', self.root / 'wakes', ledger, {8})
        self.assertEqual(wakeups.list(self.root / 'wakes', 7), [])
        for _ in range(2):
            coin_followups.observe(self.root / 'followups', self.root / 'wakes', ledger, {7})
        records = wakeups.list(self.root / 'wakes', 7)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['chat'], 70)
        self.assertIn('verify the deliverables', records[0]['message'])
        self.assertIn('significant usable deliverable', records[0]['message'])

    def test_failed_handoff_preserves_followup(self):
        coin_followups.retain(self.root / 'followups', 7, 70, 'system:audio', 'Transcribe')
        with patch.object(wakeups, 'create', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                coin_followups.observe(self.root / 'followups', self.root / 'wakes',
                    {'tasks': {'system:audio': {'status': 'done'}}}, {7})
        with coin_followups._registry(self.root / 'followups') as (_, data):
            self.assertEqual(len(data['items']), 1)

    def test_factory_handoffs_are_observed_without_intermediate_coin_turns(self):
        coin_followups.retain(self.root / 'followups', 7, 70, 'p:plan', 'Build feature')
        ledger = {'tasks': {'p:plan': {'status': 'done', 'place': 'p', 'receipt': {
            'evidence': {'handoff': [{'name': 'review'}]}}}}, 'queue': {
            'p:plan': {'project': 'p', 'done': {'commit': 'plan'}},
            'p:review': {'project': 'p', 'proposed_by': 'p:plan'},
            'p:implementation': {'project': 'p', 'proposed_by': 'p:review'}}}
        for key in ('p:review', 'p:implementation'):
            coin_followups.observe(self.root / 'followups', self.root / 'wakes', ledger, {7})
            self.assertEqual(wakeups.list(self.root / 'wakes', 7), [])
            self.assertEqual(len(coin_followups.context(self.root / 'followups', 7, 70)), 1)
            ledger['queue'][key]['done'] = {'commit': key}
        coin_followups.observe(self.root / 'followups', self.root / 'wakes', ledger, {7})
        self.assertEqual(len(wakeups.list(self.root / 'wakes', 7)), 1)
        self.assertEqual(coin_followups.context(self.root / 'followups', 7, 70), [])

    def test_missing_declared_handoff_and_pending_replacement_are_not_completion(self):
        ledger = {'tasks': {'p:plan': {'status': 'done', 'place': 'p', 'receipt': {
            'evidence': {'handoff': [{'name': 'missing'}]}}}}}
        self.assertFalse(coin_followups.settled('p:plan', ledger))
        ledger = {'queue': {'p:old': {'project': 'p', 'replaced_by': ['new']},
                            'p:new': {'project': 'p'}}}
        self.assertFalse(coin_followups.settled('p:old', ledger))
        ledger['queue']['p:new']['done'] = {'commit': 'landed'}
        self.assertTrue(coin_followups.settled('p:old', ledger))
