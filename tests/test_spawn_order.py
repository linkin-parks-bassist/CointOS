import unittest
from unittest.mock import patch

from cointos import spawner, state
from tests import support


class SpawnOrder(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        for name in ('reorder', 'tree_work', 'periodic'):
            self.enterContext(patch.object(spawner, name, return_value=[] if name != 'reorder' else None))
        self.enterContext(patch.object(spawner, 'refresh', return_value=({}, {})))
        self.enterContext(patch.object(spawner, 'runnable', return_value=True))
        self.enterContext(patch.object(spawner, 'queued_work', return_value=[]))
        self.waiting = {'id': 'p:tests', 'status': 'waiting', 'rank': [4, 50, 0], 'created_at': 1}
        state.L['tasks']['p:tests'] = self.waiting

    def test_an_integration_goes_ahead_of_waiting_test_authoring(self):
        integration = {'id': 'p:integrate'}
        with patch.object(spawner, 'integrations', return_value=[([2, 50], lambda: integration)]):
            self.assertIs(spawner.next_task(), integration)

    def test_lower_ranked_new_work_waits_behind_a_waiting_task(self):
        made = []
        with patch.object(spawner, 'integrations', return_value=[([7], lambda: made.append(1))]):
            self.assertIs(spawner.next_task(), self.waiting)
        self.assertEqual(made, [], 'nothing is created that would not run')


if __name__ == '__main__':
    unittest.main()
