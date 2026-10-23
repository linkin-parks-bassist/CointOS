"""Durable Coin cursor migration and retained input identity boundaries."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cointos import coin_input, privatejson


class InputAuthority(unittest.TestCase):
    def test_delayed_delivery_and_retry_preserve_telegram_message_time(self):
        with tempfile.TemporaryDirectory() as directory:
            update = {'update_id': 1, 'message': {'from': {'id': 7}, 'chat': {'id': 70},
                                                  'text': 'Yesterday', 'date': 100}}
            with patch.object(coin_input.time, 'time', return_value=10000):
                coin_input.accept(Path(directory), update, {7})
            with patch.object(coin_input.time, 'time', return_value=20000):
                replay = coin_input.accept(Path(directory), update, {7})
            self.assertEqual(replay['at'], 100)
            self.assertEqual(coin_input.pending(Path(directory))[0]['at'], 100)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='cointos-input-')))
        self.store = self.root / 'inputs'
        self.update = {'update_id': 123, 'message': {'from': {'id': 7}, 'chat': {'id': 70}, 'text': 'Check work'}}

    def test_legacy_cursor_migrates_once_and_never_overrides_new_owner(self):
        legacy = self.root / 'telegram-offset.json'
        legacy.write_text('123\n')
        self.assertEqual(coin_input.offset(self.store, legacy), 123)
        coin_input.accept(self.store, self.update, {7})
        legacy.write_text('0\n')
        self.assertEqual(coin_input.offset(self.store, legacy), 124)
        self.assertEqual([item['id'] for item in coin_input.pending(self.store)], [123])

    def test_present_damaged_legacy_cursor_cannot_initialize_defaults(self):
        for value in ('null', 'true', '-1', '{bad'):
            with self.subTest(value=value):
                legacy = self.root / 'legacy'
                legacy.write_text(value)
                with self.assertRaises(ValueError):
                    coin_input.offset(self.store, legacy)
                self.assertFalse((self.store / coin_input.FILE).exists())
                self.assertEqual(legacy.read_text(), value)

    def test_malformed_update_cannot_advance_cursor_or_change_pending_input(self):
        coin_input.accept(self.store, self.update, {7})
        before = (self.store / coin_input.FILE).read_bytes()
        for field, value in [('user', True), ('user', 0), ('chat', 0), ('chat', False)]:
            malformed = copy.deepcopy(self.update)
            malformed['update_id'] = 124
            malformed['message']['from' if field == 'user' else 'chat']['id'] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                coin_input.accept(self.store, malformed, {7})
            self.assertEqual((self.store / coin_input.FILE).read_bytes(), before)

    def test_present_invalid_store_is_preserved(self):
        coin_input.accept(self.store, self.update, {7})
        path = self.store / coin_input.FILE
        original = json.loads(path.read_text())
        for field in ('version', 'chat'):
            data = copy.deepcopy(original)
            if field == 'version': data['version'] = True
            else: data['inputs']['123']['chat'] = 0
            path.write_text(json.dumps(data))
            before = path.read_bytes()
            with self.subTest(field=field), self.assertRaises(ValueError):
                coin_input.offset(self.store)
            self.assertEqual(path.read_bytes(), before)

    def test_duplicate_retained_input_resyncs_and_rejects_changed_payload(self):
        item = coin_input.accept(self.store, self.update, {7})
        coin_input.receipted(self.store, 123, 51)
        with patch.object(privatejson, 'sync', wraps=privatejson.sync) as sync:
            replay = coin_input.accept(self.store, self.update, {7})
        sync.assert_called_once()
        self.assertEqual(replay['receipt'], {'message_id': 51})
        changed = copy.deepcopy(self.update)
        changed['message']['text'] = 'Different work'
        before = (self.store / coin_input.FILE).read_bytes()
        with self.assertRaises(ValueError): coin_input.accept(self.store, changed, {7})
        self.assertEqual((self.store / coin_input.FILE).read_bytes(), before)
        self.assertEqual(item['text'], replay['text'])

    def test_visible_failed_directory_commit_is_resynced_before_receipt(self):
        coin_input.offset(self.store)
        fsync = os.fsync
        failed = False
        def fail_directory_once(fd):
            nonlocal failed
            import stat
            if stat.S_ISDIR(os.fstat(fd).st_mode) and not failed and (self.store / coin_input.FILE).read_text().find('Check work') >= 0:
                failed = True
                raise OSError('fixture directory persistence failure')
            return fsync(fd)
        with patch.object(privatejson.os, 'fsync', side_effect=fail_directory_once):
            with self.assertRaises(OSError): coin_input.accept(self.store, self.update, {7})
        self.assertTrue(failed)
        with patch.object(privatejson, 'sync', wraps=privatejson.sync) as sync:
            pending = coin_input.pending(self.store)
        sync.assert_called_once()
        self.assertEqual(pending[0]['id'], 123)
        self.assertIsNone(pending[0]['receipt'])


if __name__ == '__main__':
    unittest.main()
