import copy
import unittest
from unittest.mock import patch

from cointos import lanes, state


class ResidentSwitch(unittest.TestCase):
    def setUp(self):
        saved = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(saved)))
        state.L.clear()
        state.L.update(state.fresh({}))
        self.model = state.CONFIG['work_model']
        state.L['lanes'] = [{'model': self.model, 'index': 0, 'up': True, 'resident': 'b'}]
        self.enterContext(patch.object(lanes.BACKEND, 'resident_states', return_value=True))
        for table in (lanes.HELD, lanes.RESIDENT):
            previous = dict(table)
            self.addCleanup(lambda table=table, previous=previous: (table.clear(), table.update(previous)))
            table.clear()

    def test_hot_switch_selects_exact_resident_without_snapshot_calls(self):
        lanes.HELD[0] = [9, 8, 7]
        with patch.object(lanes.BACKEND, 'select', return_value=[1, 2, 3]) as select, \
             patch.object(lanes.snapshots, 'keep') as keep, \
             patch.object(lanes.BACKEND, 'restore') as restore:
            lanes.switch(0, [1, 2, 3, 4], 'a')
        select.assert_called_once_with(state.CONFIG, self.model, 0, 'a')
        keep.assert_not_called()
        restore.assert_not_called()
        self.assertEqual(lanes.HELD[0], [1, 2, 3])
        self.assertEqual(lanes.RESIDENT[self.model, 'a'], [1, 2, 3])
        self.assertEqual(state.L['history'][-1]['mode'], 'resident')

    def test_new_history_never_saves_outgoing_resident(self):
        lanes.HELD[0] = [9, 8, 7]
        with patch.object(lanes.BACKEND, 'select', return_value=[]), \
             patch.object(lanes.BACKEND, 'resident_bytes', return_value=0), \
             patch.object(lanes.memory, 'headroom_gb', return_value=20), \
             patch.object(lanes.snapshots, 'keep') as keep:
            lanes.switch(0, [1, 2, 3], 'a')
        keep.assert_not_called()
        self.assertEqual(lanes.HELD[0], [])

    def test_partial_read_needs_no_serialized_fairness_checkpoint(self):
        state.L['thoughts']['a'] = {'model': self.model}
        with patch.object(lanes.snapshots, 'keep') as keep:
            lanes.checkpoint_read(0, 'a', [1, 2])
        keep.assert_not_called()

    def test_model_loss_invalidates_resident_metadata(self):
        lanes.RESIDENT[self.model, 'a'] = [1, 2]
        lanes.RESIDENT['other', 'a'] = [3]
        state.L['lanes'][0]['holder'] = None
        with patch.object(lanes, 'schedule'):
            lanes.lanes_down(self.model)
        self.assertNotIn((self.model, 'a'), lanes.RESIDENT)
        self.assertIn(('other', 'a'), lanes.RESIDENT)
