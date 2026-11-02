"""Admission across process launch, native initialization and disposable caches."""
import unittest
from unittest.mock import patch

from cointos import capacity, daemon, lanes, snapshots, spawner, state
from tests import support


class Capacity(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.model = state.CONFIG['work_model']
        state.L['lanes'] = [lane for lane in state.L['lanes'] if lane['model'] == self.model][:1]
        self.enterContext(patch.dict(lanes.RESIDENT, {}, clear=True))
        self.enterContext(patch.object(state.journal, 'write'))
        self.enterContext(patch.object(capacity.BACKEND, 'resident_states', return_value=True))
        state.L['models'][self.model].update(up=True, resident_state_bytes=11_000_000_000)
        state.L['memory'] = {'headroom_gb': 50, 'available_gb': 74, 'psi': 0}
        state.L['user_last_thought'] = 0

    def agent(self, owner, ident=None):
        state.L['agents'][ident or owner] = {'task': owner, 'class': 'background'}

    def test_burst_admission_holds_native_state_and_binary_process_caps(self):
        tasks = iter({'id': str(i)} for i in range(4))
        with patch.object(spawner, 'next_task', side_effect=lambda: next(tasks, None)), \
             patch.object(spawner.runs, 'start', side_effect=lambda t: self.agent(t['id'])), \
             patch.object(spawner.lanes, 'blocked', return_value=False):
            spawner.spawn()
        self.assertEqual(len(state.L['agents']), 2)
        self.assertAlmostEqual(capacity.process_gb(), 8 * 2**30 / 1e9)
        # Pending launches do not consume physical memory yet, but cannot be
        # spent a second time by cache saves or the next spawner tick.
        self.assertEqual(state.L['memory']['headroom_gb'], 50)
        self.assertFalse(snapshots.make_room(12))
        self.assertGreater(capacity.headroom_gb(), 0)

    def test_initialization_spends_own_native_claim_only(self):
        self.agent('a'); self.agent('b')
        pending = capacity.pending_gb()
        self.assertAlmostEqual(pending - capacity.pending_gb('a'), 11)
        # Once allocated, native bytes are measured physically; process growth
        # stays protected even while both clients are between model calls.
        lanes.RESIDENT[self.model, 'a'] = [1, 2]
        state.L['memory']['headroom_gb'] -= 11
        self.assertAlmostEqual(capacity.headroom_gb(), 50 - pending)
        self.assertEqual(capacity.pending_gb('a'), capacity.pending_gb())

    def test_fresh_measurements_cannot_readmit_a_burst_or_spend_process_growth(self):
        self.agent('a'); self.agent('b')
        for owner in ('a', 'b'):
            lanes.RESIDENT[self.model, owner] = [1, 2]
        # Native states have materialized; a new measurement no longer sees
        # their launch-time debit. It must still honor the process commitments.
        state.L['memory']['headroom_gb'] = 28
        with patch.object(spawner, 'next_task', return_value={'id': 'third'}), \
             patch.object(spawner.runs, 'start') as start, \
             patch.object(spawner.lanes, 'blocked', return_value=False):
            for _ in range(10):
                spawner.spawn()
        start.assert_not_called()
        self.assertFalse(snapshots.make_room(12))
        self.assertTrue(snapshots.make_room(10))
        # Even if both processes then grow by their entire caps, the admitted
        # cache plus execution cannot cross the workstation reserve.
        remaining = state.L['memory']['headroom_gb'] - 2 * capacity.process_gb()
        self.assertGreater(remaining, 0)

    def test_caches_leave_room_for_admitted_processes(self):
        self.agent('a')
        lanes.RESIDENT[self.model, 'a'] = [1]
        state.L['memory']['headroom_gb'] = 10
        self.assertFalse(snapshots.make_room(2))
        self.assertTrue(snapshots.make_room(1))
        self.assertEqual(state.L['memory']['headroom_gb'], 9)
        state.L['agents'].clear()
        self.assertTrue(snapshots.make_room(2))

    def test_unknown_native_claim_refuses_admission(self):
        state.L['models'][self.model].pop('resident_state_bytes')
        self.assertEqual(capacity.agent_gb('new'), float('inf'))
        self.assertFalse(snapshots.make_room(capacity.agent_gb('new'), claim=False))

    def test_first_native_checkpoint_has_a_nonzero_admission_estimate(self):
        state.L['memory']['headroom_gb'] = 5
        with patch.object(snapshots.BACKEND, 'save') as save:
            self.assertFalse(snapshots.keep(0, [1, 2], 'coin/user', 'checkpoint'))
        save.assert_not_called()

    def test_native_checkpoint_reserves_device_capture_as_well_as_ram_file(self):
        state.L['snapshots']['sample'] = {'model': self.model, 'tokens': 2, 'bytes': 2e9,
            'tier': 'disk', 'owner': 'shared', 'last_run': 1, 'digest': 'other'}
        state.L['memory']['headroom_gb'] = 12  # file fits; file + device clone does not
        with patch.object(snapshots.BACKEND, 'save') as save:
            self.assertFalse(snapshots.keep(0, [1, 2], 'coin/user', 'checkpoint'))
        save.assert_not_called()

    def test_waiting_conversation_cache_is_not_blocked_by_process_caps(self):
        for owner in ('a', 'b', 'c'):
            self.agent(owner)
            lanes.RESIDENT[self.model, owner] = [1]
        state.L['snapshots']['sample'] = {'model': self.model, 'tokens': 2, 'bytes': 1e9,
            'tier': 'disk', 'owner': 'shared', 'last_run': 1, 'digest': 'other'}
        state.L['memory']['headroom_gb'] = 24.4  # below three process caps
        with patch.object(snapshots.BACKEND, 'save', return_value={'bytes': 1e9}) as save, \
             patch.dict(snapshots.RESERVED, {}, clear=True), patch.object(snapshots, 'log') as log:
            self.assertFalse(snapshots.keep(0, [1, 2], 'a', 'checkpoint'))
            save.assert_not_called()
            self.assertEqual(log.call_args.args[0], 'snapshot refused')
            self.assertTrue(snapshots.keep(0, [1, 2], 'coin/user', 'checkpoint'))
            self.assertEqual(save.call_count, 1)
            # Capture and file are debited from physical headroom, not the caps.
            self.assertEqual(state.L['memory']['headroom_gb'], 12.4)

    def test_waiting_conversation_cache_still_respects_the_physical_reserve(self):
        self.agent('a')
        lanes.RESIDENT[self.model, 'a'] = [1]
        state.L['memory']['headroom_gb'] = 5  # the capture alone would enter the reserve
        with patch.object(snapshots.BACKEND, 'save') as save:
            self.assertFalse(snapshots.keep(0, [1, 2], 'coin/user', 'checkpoint'))
        save.assert_not_called()

    def test_waiting_conversation_state_is_not_starved_by_process_caps(self):
        for owner in ('a', 'b', 'c'):
            self.agent(owner)
            lanes.RESIDENT[self.model, owner] = [1]
        position = next(iter(state.L['lanes'])) if isinstance(state.L['lanes'], dict) else 0
        state.CONFIG['timeouts']['server_seconds'], saved = 0, state.CONFIG['timeouts']['server_seconds']
        self.addCleanup(state.CONFIG['timeouts'].__setitem__, 'server_seconds', saved)
        # Physical room for one state, but less than it after three process caps.
        measured = {'available_gb': state.CONFIG['memory']['reserve_gb'] + 34.4, 'psi': 0}
        with patch.object(lanes.memory, 'measure', return_value=measured), \
             patch.object(lanes.memory, 'headroom_gb', return_value=34.4), \
             patch.object(lanes.BACKEND, 'budget', return_value=None), \
             patch.object(lanes.BACKEND, 'select', return_value=[]), \
             patch.object(lanes.BACKEND, 'can_continue', return_value=False), \
             patch.object(lanes.BACKEND, 'resident_bytes', return_value=11_350_000_000), \
             patch.object(lanes.snapshot_cleanup, 'drain'), patch.object(lanes, 'log'):
            lanes.switch(position, [1, 2], 'coin/user')
            with self.assertRaises(MemoryError):
                lanes.switch(position, [1, 2], 'new-task')

    def test_pending_save_survives_a_fresh_physical_measurement(self):
        self.enterContext(patch.dict(snapshots.RESERVED, {'capture': 13}, clear=True))
        state.L['memory']['headroom_gb'] = 15
        self.assertFalse(snapshots.make_room(3))
        self.assertEqual(capacity.pending_gb(), 13)

    def test_retirement_distinguishes_run_from_conversation_lifetime(self):
        for owner in ('review', 'waiting', 'tools', 'reading'):
            state.L['tasks'][owner] = {'status': 'review' if owner == 'review' else 'waiting'}
            lanes.RESIDENT[self.model, owner] = [1, 2]
        self.agent('tools')
        state.L['thoughts']['step'] = {'owner': 'reading'}
        with patch.object(lanes.BACKEND, 'release_residents') as release:
            lanes.retire_residents(self.model, ['review', 'waiting', 'tools', 'reading', 'coin/user'])
        release.assert_called_once_with(state.CONFIG, self.model, ['review', 'waiting'])
        self.assertIn('review', state.L['tasks'])
        self.assertNotIn((self.model, 'review'), lanes.RESIDENT)
        self.assertIn((self.model, 'tools'), lanes.RESIDENT)

    def test_guard_uses_physical_headroom_rather_than_unspent_reservations(self):
        self.agent('a')
        state.L['memory']['headroom_gb'] = 5
        measured = {'available_gb': state.CONFIG['memory']['reserve_gb'] + 5, 'psi': 0}
        with patch.object(daemon.memory, 'measure', return_value=measured), \
             patch.object(daemon.BACKEND, 'budget', return_value=None), \
             patch.object(daemon.lifecycle, 'stop') as stop:
            daemon.guard()
        stop.assert_not_called()
        self.assertFalse(state.L['guard']['blocked'])
