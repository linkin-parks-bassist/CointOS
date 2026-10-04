import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cointos import settings, state


class LiveSettings(unittest.TestCase):
    def setUp(self):
        original = copy.deepcopy(state.L), copy.deepcopy(state.CONFIG)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(original[0]),
                                 state.CONFIG.clear(), state.CONFIG.update(original[1])))
        state.L.clear()
        state.L.update(state.fresh({}))
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / 'config.json'
        self.enterContext(patch.object(settings.configuration, 'CONFIG', self.path))
        self.schedule = self.enterContext(patch.object(settings.lanes, 'schedule'))
        self.document = copy.deepcopy(state.CONFIG)
        self.write(self.document)

    def write(self, document):
        self.path.write_text(json.dumps(document))

    def test_poll_changes_only_slice_and_retains_other_active_settings(self):
        old = state.CONFIG['spawner']['max_agents']
        self.document['scheduler']['slice_seconds'] = 7
        self.document['spawner']['max_agents'] = 999
        self.write(self.document)
        with state.LOCK:
            settings.refresh()
        self.assertEqual(state.CONFIG['scheduler']['slice_seconds'], 7)
        self.assertEqual(state.L['scheduler']['slice_seconds'], 7)
        self.assertEqual(state.CONFIG['spawner']['max_agents'], old)
        self.schedule.assert_called_once()
        with state.LOCK:
            settings.refresh()
        self.schedule.assert_called_once()  # unchanged ticks do not reschedule

    def test_bad_or_partial_edit_keeps_last_value_and_recovers(self):
        old = state.CONFIG['scheduler']['slice_seconds']
        for invalid in ('{', '{}', '{"scheduler": null}', '{"scheduler":{"slice_seconds":false}}',
                        '{"scheduler":{"slice_seconds":0}}', '{"scheduler":{"slice_seconds":NaN}}'):
            self.path.write_text(invalid)
            with state.LOCK:
                settings.refresh()
            self.assertEqual(state.CONFIG['scheduler']['slice_seconds'], old)
            self.assertTrue(state.L['config_error'])
        self.document['scheduler']['slice_seconds'] = 12
        self.write(self.document)
        with state.LOCK:
            settings.refresh()
        self.assertIsNone(state.L['config_error'])
        self.assertEqual(state.L['scheduler']['slice_seconds'], 12)

    def test_dashboard_persists_only_requested_field_and_shortens_existing_grace(self):
        self.document['untouched'] = {'custom': True}
        self.write(self.document)
        self.path.chmod(0o600)
        lane = state.L['lanes'][0]
        lane.update(held_for='a', held_until=125, turn_since=100)
        with state.LOCK:
            settings.set_scheduler({'slice_seconds': 5})
        saved = json.loads(self.path.read_text())
        self.document['scheduler']['slice_seconds'] = 5
        self.assertEqual(saved, self.document)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(lane['held_until'], 105)
        self.assertEqual(lane['turn_since'], 100)
        self.assertEqual(state.L['scheduler']['slice_seconds'], 5)

    def test_rejected_api_or_failed_write_never_changes_active_value(self):
        before = self.path.read_bytes()
        old = state.CONFIG['scheduler']['slice_seconds']
        for value in (True, None, '5', 0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                settings.set_scheduler({'slice_seconds': value})
        with patch.object(settings.configuration, 'write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                settings.set_scheduler({'slice_seconds': 7})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(state.CONFIG['scheduler']['slice_seconds'], old)

    def test_chunk_changes_validate_atomically_and_preserve_disk_settings(self):
        old = settings.effective()
        for value in (True, None, 0, -1, 1.5, '32'):
            self.document['scheduler'].update(slice_seconds=17, chunk_tokens=value)
            self.write(self.document)
            settings.refresh()
            self.assertEqual(settings.effective(), old)
            self.assertTrue(state.L['config_error'])
        self.document['scheduler']['chunk_tokens'] = 32
        self.write(self.document)
        settings.refresh()
        self.assertEqual(settings.effective(), dict(slice_seconds=17, chunk_tokens=32))
        result = settings.set_scheduler({'chunk_tokens': 16})
        self.assertEqual(result['slice_seconds'], 17)
        self.assertEqual(result['chunk_tokens'], 16)
        self.document['scheduler']['chunk_tokens'] = 16
        self.assertEqual(json.loads(self.path.read_text()), self.document)
        before = self.path.read_bytes()
        for value in (False, 0, 1.5):
            with self.assertRaises(ValueError):
                settings.set_scheduler({'chunk_tokens': value})
        self.assertEqual(self.path.read_bytes(), before)
