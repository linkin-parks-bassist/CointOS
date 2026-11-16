"""A private session store imports exact retained history and never substitutes a fresh conversation."""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cointos import sessions


class Migration(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store, self.run = self.root / 'private', self.root / 'run'
        self.store.mkdir(); self.run.mkdir()
        self.task = {'id': 'p:work', 'session': 'ses_fixture', 'worktree': str(self.root)}
        self.original = {'info': {'id': 'ses_fixture', 'projectID': 'old-project', 'path': '', 'title': 'Original task'},
                         'messages': [{'info': {'id': 'message-one', 'role': 'user'}, 'parts': [
                             {'id': 'part-one', 'type': 'text', 'text': 'Original context ' * 10000}]},
                                      {'info': {'id': 'message-two', 'role': 'assistant'}, 'parts': [
                             {'id': 'part-two', 'type': 'tool', 'state': {'status': 'completed', 'output': 'Retain evidence'}}]}]}
        self.target, self.imports, self.exports = None, 0, []
        self.truncated, self.partial = False, False
        self.enterContext(patch.object(sessions, 'STATE', self.root / 'authority'))
        self.enterContext(patch.object(sessions.subprocess, 'run', side_effect=self.native))

    def native(self, command, **options):
        private = options['env'].get('XDG_DATA_HOME') == str(self.store / 'data')
        if command[1] == 'export':
            self.exports.append('private' if private else 'original')
            self.assertTrue(stat.S_ISREG(os.fstat(options['stdout'].fileno()).st_mode),
                            'native export must use a regular file, never an asynchronously captured pipe')
            value = self.target if private else self.original
            if value is None:
                return subprocess.CompletedProcess(command, 1, stderr=b'Error: Session not found: ses_fixture')
            encoded = json.dumps(value).encode()
            if self.truncated:
                encoded = encoded[:65536]
            options['stdout'].write(encoded)
            return subprocess.CompletedProcess(command, 0, stderr=b'')
        self.assertEqual(command[1:3], ['import', '--pure'])
        self.assertTrue(private)
        self.imports += 1
        self.target = json.loads(Path(command[3]).read_text())
        self.target['info'].update(projectID='global', path='workspace')
        if self.partial:
            self.target['messages'].pop()
        return subprocess.CompletedProcess(command, 0, stdout=b'Imported', stderr=b'')

    def prepare(self):
        sessions.prepare(self.task, self.run, self.store, 'opencode', 30)

    def test_large_history_tools_ids_and_user_inputs_survive_reprojection(self):
        original = copy.deepcopy(self.original)
        self.prepare()
        self.assertEqual(self.imports, 1)
        self.assertEqual(self.target['messages'], original['messages'])
        self.assertEqual(self.target['info']['id'], self.task['session'])
        self.assertEqual(self.original, original)
        self.assertEqual(self.exports, ['private', 'original', 'private'])
        receipts = list((self.root / 'authority').rglob('receipt.json'))
        self.assertEqual(len(receipts), 1)
        self.assertFalse(receipts[0].is_relative_to(self.store))
        self.target['messages'].append({'info': {'id': 'later'}, 'parts': []})
        self.prepare()
        self.assertEqual(self.imports, 1, 'a resumed conversation must not be overwritten by its older export')

    def test_existing_recorded_private_store_needs_no_legacy_access(self):
        self.task['session_store'] = str(self.store)
        self.target = copy.deepcopy(self.original)
        self.prepare()
        self.assertEqual(self.exports, ['private'])
        self.assertEqual(self.imports, 0)

    def test_truncated_successful_export_refuses_without_starting_a_new_history(self):
        self.truncated = True
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.prepare()
        self.assertEqual(self.imports, 0)
        self.assertIsNone(self.target)

    def test_partial_import_is_preserved_and_never_authorizes_launch_or_overwrite(self):
        self.partial = True
        with self.assertRaisesRegex(ValueError, 'changed conversation data'):
            self.prepare()
        partial = copy.deepcopy(self.target)
        self.assertFalse(list((self.root / 'authority').rglob('receipt.json')))
        with self.assertRaisesRegex(ValueError, 'unverified existing history'):
            self.prepare()
        self.assertEqual(self.target, partial)
        self.assertEqual(self.imports, 1)

    def test_lost_migration_acknowledgement_reconciles_exact_import(self):
        actual_write = sessions.write_json
        with patch.object(sessions, 'write_json', side_effect=OSError('storage unavailable')):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(self.imports, 1)
        with patch.object(sessions, 'write_json', side_effect=actual_write):
            self.prepare()
        self.assertEqual(self.imports, 1)
        self.assertTrue(list((self.root / 'authority').rglob('receipt.json')))

    def test_missing_private_history_cannot_be_replaced_by_an_older_global_copy(self):
        self.prepare()
        self.target = None
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.prepare()
        self.assertEqual(self.imports, 1)

    def test_new_assignments_do_not_export_or_import_any_session(self):
        self.task['session'] = None
        self.prepare()
        self.assertEqual(self.exports, [])
        self.assertEqual(self.imports, 0)
