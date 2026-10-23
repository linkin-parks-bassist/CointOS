"""Blocked cache disposal must preserve service, ownership and physical accounting."""
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cointos import config, gateway, lanes, memory, snapshots, snapshot_cleanup as cleanup, state
from tests import support


class SnapshotCleanup(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(state.CONFIG, snapshots=str(self.root/'ram'), disk_snapshots=str(self.root/'disk')))
        self.work = state.CONFIG['work_model']
        self.enterContext(patch.dict(state.CONFIG['models'][self.work], backend='gufo'))
        self.ram, self.disk = self.root/'ram/gufo', self.root/'disk/gufo'
        self.ram.mkdir(parents=True); self.disk.mkdir(parents=True)
        self.data = b'cached-state' * 4096
        for table in (snapshots.RESERVED, cleanup.ACTIVE, cleanup.PINS, lanes.RUNS, lanes.HELD, lanes.BUSY, lanes.PROMPTS):
            self.enterContext(patch.dict(table, {}, clear=True))
        transfers = set(snapshots.TRANSFERS)
        snapshots.TRANSFERS.clear()
        self.addCleanup(lambda: snapshots.TRANSFERS.update(transfers))
        stopped = state.STOPPING.is_set(); state.STOPPING.clear()
        self.addCleanup(state.STOPPING.set if stopped else state.STOPPING.clear)
        self.enterContext(patch.object(state.BACKEND, 'budget', return_value=None))
        self.enterContext(patch.object(memory, 'measure', return_value={
            'available_gb': state.CONFIG['memory']['reserve_gb'] + 10}))
        state.L['memory']['headroom_gb'] = 1
        state.L['lanes'] = [lane for lane in state.L['lanes'] if lane['model'] == self.work][:1]
        state.L['lanes'][0]['up'] = True

    def cache(self, name, tier='memory', tokens=(1, 2)):
        path = (self.ram if tier == 'memory' else self.disk)/(name+'.bin')
        path.write_bytes(self.data)
        state.L['snapshots'][name] = {'model': self.work, 'owner': 'user', 'kind': 'checkpoint',
            'tier': tier, 'tokens': len(tokens), 'digest': snapshots.digest(list(tokens)),
            'bytes': len(self.data), 'last_run': 0}
        return path

    def save(self, cfg, model, lane, name):
        (self.ram/(name+'.bin')).write_bytes(self.data)
        return {'bytes': len(self.data)}

    def connection(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        self.addCleanup(connection.close)
        return connection

    def test_blocked_disk_unlink_keeps_api_and_generation_running_and_bytes_charged(self):
        path = self.cache('retired', 'disk')
        with state.LOCK:
            snapshots.drop('retired')
        entered, release = threading.Event(), threading.Event()
        delete = state.BACKEND.delete_snapshot_file
        def delayed(cfg, entry):
            entered.set(); release.wait(5)
            return delete(cfg, entry)
        worker = threading.Thread(target=cleanup.drain, args=('disk',), daemon=True)
        connection = self.connection()
        with patch.object(state.BACKEND, 'delete_snapshot_file', side_effect=delayed):
            try:
                worker.start(); self.assertTrue(entered.wait(2))
                with state.LOCK, patch.dict(state.CONFIG['memory'], disk_snapshots_gb=len(self.data)/memory.GB):
                    self.assertEqual(cleanup.occupied('disk'), len(self.data)/memory.GB)
                    self.assertFalse(snapshots.disk_room(1/memory.GB, 'incoming'))
                connection.request('GET', '/api/ledger')
                self.assertEqual(connection.getresponse().status, 200)
                lanes.HELD[0] = [1, 2]; state.L['lanes'][0]['resident'] = 'user'
                thought = lanes.begin('fixture', 'user', 'user', self.work, {'tokens': [1, 2], 'reader': {}}, {}, 4)
                stream = lanes.RUNS[thought]['queue']
                def think(cfg, model, lane, tokens, held, count, sampling, on_tokens):
                    on_tokens([3]); state.STOPPING.set()
                    return {'tokens': [3], 'held': [1, 2, 3], 'done': True, 'generation_seconds': .1}
                with patch.object(state.BACKEND, 'think', side_effect=think):
                    lanes.worker(0)
                self.assertEqual(stream.get(timeout=1), [3])
                self.assertEqual(stream.get(timeout=1), {'end': 'done'})
                self.assertTrue(path.exists())
                self.assertTrue(worker.is_alive())
            finally:
                release.set(); worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(path.exists())
        self.assertEqual(cleanup.occupied('disk'), 0)

    def test_replacement_waits_for_actual_ram_release_outside_lock(self):
        old = self.cache('old')
        entered, release = threading.Event(), threading.Event()
        delete = state.BACKEND.delete_snapshot_file
        result = []
        def delayed(cfg, entry):
            entered.set(); release.wait(5)
            return delete(cfg, entry)
        worker = threading.Thread(target=lambda: result.append(snapshots.keep(0, [1, 2, 3], 'user', 'checkpoint')), daemon=True)
        connection = self.connection()
        with patch.dict(state.CONFIG['memory'], snapshots_gb=.01), \
             patch.object(state.BACKEND, 'delete_snapshot_file', side_effect=delayed), \
             patch.object(state.BACKEND, 'save', side_effect=self.save) as save:
            try:
                worker.start(); self.assertTrue(entered.wait(2))
                save.assert_not_called()
                with state.LOCK:
                    self.assertFalse(snapshots.room(.01))
                self.assertTrue(old.exists())
                connection.request('GET', '/api/ledger')
                response = connection.getresponse(); self.assertEqual(response.status, 200); response.read()
            finally:
                release.set(); worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])
        self.assertFalse(old.exists())
        self.assertEqual(len(state.L['snapshots']), 1)

    def test_native_restore_pins_a_retired_file_until_import_completes(self):
        path = self.cache('pinned')
        def restore(*args):
            with state.LOCK:
                snapshots.drop('pinned')
            cleanup.drain('memory')
            self.assertTrue(path.exists())
            self.assertGreater(cleanup.occupied('memory'), 0)
            return True
        with patch.object(state.BACKEND, 'restore', side_effect=restore):
            self.assertEqual(lanes.switch(0, [1, 2, 3], 'user'), 'pinned')
        self.assertEqual(lanes.HELD[0], [1, 2])
        cleanup.drain('memory')
        self.assertFalse(path.exists())

    def test_unspill_can_restore_ram_while_its_old_disk_copy_is_being_deleted(self):
        path = self.cache('both', 'disk')
        with cleanup.pin('both') as pinned:
            self.assertTrue(pinned)
            self.assertTrue(snapshots.bring_back('both'))
        self.assertEqual((self.ram/'both.bin').read_bytes(), self.data)
        self.assertTrue(path.exists())
        entered, release = threading.Event(), threading.Event()
        delete = state.BACKEND.delete_snapshot_file
        def delayed(cfg, entry):
            entered.set(); release.wait(5); return delete(cfg, entry)
        worker = threading.Thread(target=cleanup.drain, args=('disk',), daemon=True)
        with patch.object(state.BACKEND, 'delete_snapshot_file', side_effect=delayed):
            try:
                worker.start(); self.assertTrue(entered.wait(2))
                with patch.object(state.BACKEND, 'restore', return_value=True):
                    self.assertEqual(lanes.switch(0, [1, 2, 3], 'user'), 'both')
                with state.LOCK, patch.object(state.BACKEND, 'spill') as spill:
                    self.assertEqual(snapshots.evict('both'), 0)
                    self.assertEqual(state.L['snapshots']['both']['tier'], 'memory')
                    spill.assert_not_called()
            finally:
                release.set(); worker.join(5)
        self.assertFalse(worker.is_alive())

    def test_queued_file_identity_survives_restart_and_cannot_be_reused(self):
        old = self.cache('old', 'disk')
        with state.LOCK:
            snapshots.drop('old')
        previous = json.loads(json.dumps(state.L))
        state.L.clear(); state.L.update(state.fresh(previous))
        self.assertEqual(cleanup.occupied('disk'), len(self.data)/memory.GB)
        with patch.object(snapshots.secrets, 'token_hex', side_effect=['old', 'fresh']), \
             patch.object(state.BACKEND, 'save', side_effect=self.save):
            self.assertTrue(snapshots.keep(0, [1, 2], 'user', 'checkpoint'))
        self.assertIn('fresh', state.L['snapshots'])
        cleanup.drain('disk')
        self.assertFalse(old.exists())
        self.assertTrue((self.ram/'fresh.bin').exists())

    def test_release_does_not_double_credit_measured_ram_or_unpaid_save_reservations(self):
        self.cache('old')
        with state.LOCK:
            snapshots.drop('old')
            state.L['memory']['headroom_gb'] = 10  # guard already sees the eventual release
            snapshots.RESERVED['unpaid'] = 3
        cleanup.drain('memory')
        self.assertEqual(state.L['memory']['headroom_gb'], 7)
        self.assertFalse(snapshots.make_room(8))

    def test_failed_unlink_stays_charged_and_healthy_retry_clears_error(self):
        path = self.cache('old', 'disk')
        with state.LOCK:
            snapshots.drop('old')
        with patch.object(state.BACKEND, 'delete_snapshot_file', side_effect=PermissionError('busy cache')):
            cleanup.drain('disk'); cleanup.drain('disk')
        self.assertTrue(path.exists())
        self.assertEqual(cleanup.occupied('disk'), len(self.data)/memory.GB)
        self.assertEqual(state.L['snapshot_cleanup_error'], 'busy cache')
        self.assertEqual(sum(e['event'] == 'snapshot file cleanup failed' for e in state.L['history']), 1)
        cleanup.drain('disk')
        self.assertFalse(path.exists())
        self.assertNotIn('snapshot_cleanup_error', state.L)

    def test_inventory_preserves_unpublished_save_and_independent_store_errors(self):
        def saved(cfg, model, index, name):
            result = self.save(cfg, model, index, name)
            cleanup.discover()
            self.assertFalse(cleanup.pending(name))
            return result
        with patch.object(state.BACKEND, 'save', side_effect=saved):
            self.assertTrue(snapshots.keep(0, [1, 2], 'user', 'checkpoint'))
        def inventory(cfg, tier):
            if tier == 'disk':
                raise PermissionError('disk inventory')
            return []
        with patch.object(state.BACKEND, 'snapshot_files', side_effect=inventory):
            cleanup.discover('disk'); cleanup.discover('memory')
        self.assertFalse(cleanup.ready('disk'))
        self.assertEqual(state.L['snapshot_cleanup_error'], 'disk inventory')
        cleanup.discover('disk')
        self.assertTrue(cleanup.ready('disk'))

    def test_malformed_retained_cleanup_cannot_name_an_arbitrary_file(self):
        good = {'backend': 'gufo', 'tier': 'disk', 'name': 'safe', 'bytes': 1}
        for changes in ({'name': '../escape'}, {'backend': 'other'}, {'tier': 'other'}, {'bytes': -1}, {'bytes': True}):
            entry = {**good, **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config.validate_ledger({'snapshot_garbage': {'gufo:disk:safe': entry}})
