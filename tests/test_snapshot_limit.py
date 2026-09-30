import copy
import unittest
from unittest.mock import patch
from cointos import snapshots, state


class SnapshotLimit(unittest.TestCase):
    def setUp(self):
        old = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(old)))
        state.L.clear(); state.L.update(state.fresh({}))
        self.enterContext(patch.dict(state.CONFIG['memory'], snapshots_gb=10))
        self.enterContext(patch.dict(snapshots.RESERVED, {}, clear=True))
        self.thread = self.enterContext(patch.object(snapshots.threading, 'Thread'))
        self.disk_room_original = snapshots.disk_room
        self.enterContext(patch.object(snapshots, 'disk_room', return_value=True))
        self.forget = self.enterContext(patch.object(snapshots.BACKEND, 'forget'))

    def add(self, name, size, owner='shared', tier='memory', last=0):
        state.L['snapshots'][name] = {'bytes': size * 10**9, 'tier': tier,
                                      'owner': owner, 'last_run': last}

    def test_review_spills_before_running_and_does_not_credit_pending_bytes(self):
        state.L['tasks']['active'] = {'status': 'running'}
        state.L['tasks']['review'] = {'status': 'review'}
        self.add('active', 6, 'active', last=0)
        self.add('review', 5, 'review', last=100)
        self.assertFalse(snapshots.room(0))
        self.assertEqual(state.L['snapshots']['review']['tier'], 'moving')
        self.assertEqual(state.L['snapshots']['active']['tier'], 'memory')
        self.assertFalse(snapshots.room(0))
        self.assertEqual(self.thread.call_count, 1, 'Do not start duplicate spills')
        state.L['snapshots']['review']['tier'] = 'disk'
        self.assertTrue(snapshots.room(0))

    def test_inflight_save_and_restore_allocations_cannot_overcommit(self):
        self.add('resident', 5)
        snapshots.RESERVED['saving'] = 4
        self.assertFalse(snapshots.room(2))
        self.assertEqual(state.L['snapshots']['resident']['tier'], 'moving')

    def test_disk_is_not_charged_and_oversized_allocation_declined(self):
        self.add('disk', 90, tier='disk')
        self.assertTrue(snapshots.room(10))
        self.assertFalse(snapshots.room(11))
        self.assertFalse(self.thread.called)

    def test_full_disk_forgets_cache_instead_of_exceeding_ram_limit(self):
        self.add('old', 9)
        with patch.object(snapshots, 'disk_room', return_value=False):
            self.assertTrue(snapshots.room(3))
        self.forget.assert_called_once()
        self.assertNotIn('old', state.L['snapshots'])

    def test_pressure_spill_does_not_grant_allocation_until_memory_is_measured_free(self):
        self.add('old', 9)
        state.L['memory']['headroom_gb'] = 1
        self.assertFalse(snapshots.make_room(4))
        self.assertEqual(state.L['memory']['headroom_gb'], 1)
        self.assertEqual(state.L['snapshots']['old']['tier'], 'moving')
        state.L['snapshots']['old']['tier'] = 'disk'
        state.L['memory']['headroom_gb'] = 10
        self.assertTrue(snapshots.make_room(4))
        self.assertEqual(state.L['memory']['headroom_gb'], 6)

    def test_disk_capacity_counts_transfers_but_never_deletes_them(self):
        self.add('moving', 9, tier='moving')
        self.add('old', 1, tier='disk')
        with patch.dict(state.CONFIG['memory'], disk_snapshots_gb=10), \
             patch.object(snapshots, 'disk_room', wraps=snapshots.disk_room.__wrapped__ if hasattr(snapshots.disk_room, '__wrapped__') else self.disk_room_original):
            self.assertFalse(snapshots.disk_room(2, 'incoming'))
        self.assertIn('moving', state.L['snapshots'])

    def test_owner_retirement_during_spill_cleans_the_completed_file(self):
        self.add('retired', 2, tier='moving')
        with patch.object(snapshots.BACKEND, 'spill', side_effect=lambda *args: state.L['snapshots'].pop('retired')):
            snapshots.spill('retired')
        self.forget.assert_called_once_with(state.CONFIG, 'retired')
