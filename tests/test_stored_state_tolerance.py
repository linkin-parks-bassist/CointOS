"""Stored Coin state written under yesterday's vocabulary keeps Coin working today.

Registration checks current vocabulary; reads check only shape. One renamed path,
retired role, changed keyword or removed timezone must not disable a whole registry.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cointos import coin, coin_followups, coin_input, wakeups


def store(directory, name, data):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(data))
    path.chmod(0o600)


class StoredStateTolerance(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_followup_with_stale_key_stays_readable_and_deduplicated(self):
        directory = self.root / 'followups'
        item = {'user': 7, 'chat': 70, 'task': 'renamed:task', 'description': 'd', 'created_at': 1.0}
        store(directory, 'followups.json', {'version': 1, 'items': {coin_followups.identity(7, 'old:task'): item}})
        self.assertEqual(coin_followups.context(directory, 7, 70), [item])
        coin_followups.retain(directory, 7, 70, 'renamed:task', 'again')
        self.assertEqual(len(coin_followups.context(directory, 7, 70)), 1)

    def test_intake_keeps_recorded_kind_and_stored_attachment_kind(self):
        directory = self.root / 'inputs'
        pending = {'id': 5, 'user': 7, 'chat': 70, 'text': 'st', 'kind': 'status', 'receipt': None,
                   'attachments': [{'kind': 'retired_media', 'file_id': 'f'}]}
        store(directory, 'intake.json', {'version': 1, 'offset': 6, 'inputs': {'5': pending}})
        self.assertEqual([i['id'] for i in coin_input.pending(directory)], [5])
        store(directory, 'intake.json', {'version': 1, 'offset': 6, 'inputs': {'5': {**pending, 'kind': 'bogus'}}})
        with self.assertRaises(ValueError):
            coin_input.pending(directory)

    def wake(self, **fields):
        record = {'id': 'a' * 32, 'user': 7, 'chat': 70, 'message': 'm', 'created_at': 1.0}
        record.update(fields)
        return record

    def test_wake_registry_survives_retired_role_states_outcomes_and_zone(self):
        directory = self.root / 'wakes'
        records = [
            self.wake(id='a' * 32, condition={'kind': 'deadline', 'at': '2026-01-01T00:00:00+00:00'},
                      agent={'name': 'n', 'brief': 'b', 'role': 'retired-role'}),
            self.wake(id='b' * 32, condition={'kind': 'unit-state', 'unit': 'x.service', 'state': 'renamed-state'}),
            self.wake(id='c' * 32, condition={'kind': 'task-change', 'state': 'renamed-status', 'project': None},
                      cursor=None, runs=0),  # malformed cursor: isolated at fire time
            self.wake(id='d' * 32, condition={'kind': 'schedule', 'cron': '0 18 * * 1-5', 'timezone': 'Gone/Zone'},
                      cursor='2026-01-01T07:00:00+00:00', runs=0),
            self.wake(id='e' * 32, condition={'kind': 'deadline', 'at': '2026-01-01T00:00:00+00:00'},
                      event={'at': 1.0, 'outcome': 'renamed-outcome', 'result': 'unknown', 'detail': 'd'}),
        ]
        store(directory, 'wakeups.json', {'version': 1, 'wakeups': {r['id']: r for r in records}})
        listed = {r['id']: r for r in wakeups.list(directory, 7)}
        self.assertEqual(len(listed), 5)
        self.assertIsNone(listed['d' * 32]['next_run'])
        self.assertIn('Gone/Zone', listed['d' * 32]['problem'])
        # Readiness still fires the healthy due deadline despite the unresolvable zone beside it.
        ready = {r['id'] for r in wakeups.ready(directory)}
        self.assertIn('a' * 32, ready)
        self.assertIn('e' * 32, ready)

    def test_registration_still_refuses_unknown_vocabulary(self):
        directory = self.root / 'wakes'
        with self.assertRaises(ValueError):
            wakeups.create(directory, 7, 70, 'm', {'kind': 'schedule', 'cron': '0 18 * * *', 'timezone': 'Gone/Zone'})
        with self.assertRaises(ValueError):
            wakeups.create(directory, 7, 70, 'm', {'kind': 'deadline', 'at': '2030-01-01T00:00:00Z'},
                           agent={'name': 'n', 'brief': 'b', 'role': 'retired-role'})


class FailureNotice(unittest.TestCase):
    def test_repeating_turn_failure_is_told_once_without_the_token(self):
        sent = []
        with patch.object(coin, 'send', side_effect=lambda token, chat, text: sent.append((chat, text))):
            failures, notified = {}, set()
            for _ in range(6):
                coin.notify_failure('SECRET', 70, ValueError('bad state SECRET'), failures, notified)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0][0], 70)
            self.assertIn('ValueError: bad state [redacted]', sent[0][1])
            self.assertNotIn('SECRET', sent[0][1])
            coin.notify_failure('SECRET', 70, OSError('other'), failures, notified)
            self.assertEqual(len(sent), 1)

    def test_failed_notice_does_not_raise(self):
        with patch.object(coin, 'send', side_effect=OSError('offline')):
            failures, notified = {}, set()
            for _ in range(3):
                coin.notify_failure('t', 70, ValueError('x'), failures, notified)


if __name__ == '__main__':
    unittest.main()
