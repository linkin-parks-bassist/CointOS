import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import state


class Persistence(unittest.TestCase):
    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        self.enterContext(patch.object(state, 'SAVE_SEQUENCE', 0))
        self.enterContext(patch.object(state, 'SAVED_SEQUENCE', 0))
        self.enterContext(patch.object(state, 'SAVED_VALUE', None))

    def test_telemetry_only_changes_do_not_rewrite_but_real_mutations_publish_immediately(self):
        state.L.clear()
        state.L.update(memory={'available_gb': 40}, agents={'run': {'last_activity': 1, 'generation_tokens': 10}},
                       tasks={'task': {'receipt': None}}, snapshots={}, queue={})
        with tempfile.TemporaryDirectory() as directory, patch.object(state.configuration, 'LEDGER', Path(directory)/'ledger.json'):
            state.save()
            path = state.configuration.LEDGER
            original = path.read_bytes(); identity = path.stat().st_ino
            state.L['memory']['available_gb'] = 35; state.L['agents']['run']['last_activity'] = 2
            state.save()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(path.stat().st_ino, identity)
            self.assertEqual(state.L['memory']['available_gb'], 35)
            for container, key, value in ((state.L['agents']['run'], 'generation_tokens', 11),
                                          (state.L['tasks']['task'], 'receipt', {'disposition': 'complete'}),
                                          (state.L['snapshots'], 'snapshot', {'position': 100}),
                                          (state.L['queue'], 'work', {'held_by': 'user'})):
                container[key] = value
                state.save()
                saved = json.loads(path.read_text())
                self.assertEqual(saved['agents']['run']['generation_tokens'], state.L['agents']['run']['generation_tokens'])
                self.assertEqual(saved['tasks'], state.L['tasks'])
                self.assertEqual(saved['snapshots'], state.L['snapshots'])
                self.assertEqual(saved['queue'], state.L['queue'])
                self.assertEqual(saved['memory']['available_gb'], 35)
                self.assertEqual(saved['agents']['run']['last_activity'], 2)

    def test_unchanged_values_publish_to_a_new_target_and_failed_changes_retry(self):
        state.L.clear(); state.L['value'] = 'old'
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory)/'first.json', Path(directory)/'second.json'
            with patch.object(state.configuration, 'LEDGER', first): state.save()
            with patch.object(state.configuration, 'LEDGER', second):
                state.save(); self.assertEqual(json.loads(second.read_text())['value'], 'old')
                state.L['value'] = 'new'
                with patch.object(state.configuration, 'write_json', side_effect=OSError('fixture failed')):
                    with self.assertRaises(OSError): state.save()
                self.assertEqual(json.loads(second.read_text())['value'], 'old')
                state.save(); self.assertEqual(json.loads(second.read_text())['value'], 'new')

    def test_blocked_storage_does_not_block_state_or_mutate_captured_snapshot(self):
        writing, release, acquired = threading.Event(), threading.Event(), threading.Event()
        written = []
        state.L.clear(); state.L['nested'] = {'value': 'old'}
        def write(path, value):
            writing.set(); release.wait(2); written.append(value)
        def update():
            with state.LOCK:
                state.L['nested']['value'] = 'new'; acquired.set()
        first = threading.Thread(target=state.save)
        second = threading.Thread(target=update)
        try:
            with patch.object(state.configuration, 'write_json', side_effect=write):
                first.start(); self.assertTrue(writing.wait(1)); second.start()
                self.assertTrue(acquired.wait(1))
                release.set(); first.join(2); second.join(2)
            self.assertFalse(first.is_alive())
            self.assertEqual(written[0]['nested']['value'], 'old')
            self.assertEqual(state.L['nested']['value'], 'new')
        finally:
            release.set(); first.join(2)
            if second.ident is not None: second.join(2)

    def test_snapshot_preserves_durable_json_normalization_and_detaches_aliases(self):
        class String(str):
            pass
        shared = {'text': 'literal \\ud83e 🦦\n', 'steps': [1, False, None]}
        value = {'tuple': (shared, shared), 'alias': shared,
                 'keys': {1: 'first', '1': 'last', None: {False: 'value'}},
                 'subclass': String('text'), 'float': float('inf')}
        state.L.clear(); state.L.update(value)
        with tempfile.TemporaryDirectory() as directory, patch.object(state, 'now', return_value=123):
            path = Path(directory) / 'ledger.json'
            expected = json.loads(json.dumps({**value, 'updated_at': 123}))
            state.configuration.write_json(path, expected)
            expected_bytes = path.read_bytes()
            with patch.object(state.configuration, 'LEDGER', path):
                state.save()
            self.assertEqual(path.read_bytes(), expected_bytes)
        captured = state._snapshot(value)
        shared['steps'].append('later')
        self.assertEqual(captured['alias']['steps'], [1, False, None])
        captured['tuple'][0]['steps'].append('only one alias')
        self.assertEqual(captured['tuple'][1]['steps'], [1, False, None])

    def test_invalid_snapshot_refuses_before_publication_or_sequence_advance(self):
        circular = []; circular.append(circular)
        for value, error in ((circular, ValueError), (object(), TypeError)):
            with self.subTest(error=error):
                state.L.clear(); state.L['invalid'] = value
                with patch.object(state.configuration, 'write_json') as write:
                    with self.assertRaises(error): state.save()
                    write.assert_not_called()
                self.assertEqual(state.SAVE_SEQUENCE, 0)
                self.assertEqual(state.SAVED_SEQUENCE, 0)

    def test_late_older_snapshot_cannot_replace_published_newer_state(self):
        captured, release = threading.Event(), threading.Event()
        original = state.SAVE_LOCK
        written = []
        class DelayedPublication:
            def __enter__(self):
                if threading.current_thread().name == 'older-save':
                    captured.set(); release.wait(2)
                original.acquire()
            def __exit__(self, *args): original.release()
        state.L.clear(); state.L['value'] = 'old'
        first = threading.Thread(target=state.save, name='older-save')
        try:
            with patch.object(state, 'SAVE_LOCK', DelayedPublication()), \
                 patch.object(state.configuration, 'write_json', side_effect=lambda p,v: written.append(v['value'])):
                first.start(); self.assertTrue(captured.wait(1))
                with state.LOCK: state.L['value'] = 'new'
                state.save(); release.set(); first.join(2)
            self.assertFalse(first.is_alive())
            self.assertEqual(written, ['new'])
        finally:
            release.set(); first.join(2)

    def test_failed_publication_is_not_acknowledged_and_retry_writes_current_state(self):
        state.L.clear(); state.L['value'] = 'old'
        written = []
        with patch.object(state.configuration, 'write_json', side_effect=OSError('storage unavailable')):
            with self.assertRaises(OSError): state.save()
        self.assertEqual(state.SAVED_SEQUENCE, 0)
        with state.LOCK: state.L['value'] = 'new'
        with patch.object(state.configuration, 'write_json', side_effect=lambda p,v: written.append(v['value'])):
            state.save()
        self.assertEqual(written, ['new'])

    def test_nested_caller_cannot_deadlock_writer_finishing_outside_state_lock(self):
        writing, release, nested = threading.Event(), threading.Event(), threading.Event()
        written = []
        state.L.clear(); state.L['value'] = 'old'
        def write(path, value):
            if value['value'] == 'old': writing.set(); release.wait(2)
            written.append(value['value'])
        def newer():
            with state.LOCK:
                state.L['value'] = 'new'; nested.set(); state.save()
        first = threading.Thread(target=state.save)
        second = threading.Thread(target=newer)
        try:
            with patch.object(state.configuration, 'write_json', side_effect=write):
                first.start(); self.assertTrue(writing.wait(1)); second.start()
                self.assertTrue(nested.wait(1)); release.set()
                first.join(2); second.join(2)
            self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
            self.assertEqual(written, ['old', 'new'])
        finally:
            release.set(); first.join(2)
            if second.ident is not None: second.join(2)

    def test_a_newer_save_cannot_overtake_an_older_write(self):
        previous = copy.deepcopy(state.L)
        first_writing = threading.Event()
        release_first = threading.Event()
        second_attempting = threading.Event()
        written = []

        def write(path, value):
            if value["value"] == "old":
                first_writing.set()
                release_first.wait(2)
            written.append(value["value"])

        def newer():
            second_attempting.set()
            with state.LOCK:
                state.L["value"] = "new"
            state.save()

        state.L.clear()
        state.L["value"] = "old"
        first = threading.Thread(target=state.save)
        second = threading.Thread(target=newer)
        try:
            with patch.object(state.configuration, "write_json", side_effect=write):
                first.start()
                self.assertTrue(first_writing.wait(1))
                second.start()
                self.assertTrue(second_attempting.wait(1))
                # The second writer must be unable to finish while the first is writing.
                second.join(0.1)
                self.assertTrue(second.is_alive())
                release_first.set()
                first.join(2)
                second.join(2)
            self.assertEqual(written, ["old", "new"])
        finally:
            release_first.set()
            first.join(2)
            if second.ident is not None:
                second.join(2)
            state.L.clear()
            state.L.update(previous)
