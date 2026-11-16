import unittest
from unittest.mock import patch

from cointos import spawner, state, tasks
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


class UserOperatorAdmission(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.enterContext(patch.dict(state.CONFIG['spawner'], max_agents=1))
        self.enterContext(patch.object(spawner.models, 'changing', return_value=False))
        self.enterContext(patch.object(spawner.lanes, 'blocked', return_value=False))
        self.enterContext(patch.dict(state.L['models'], {state.CONFIG['work_model']: {'up': True}}))
        self.enterContext(patch.object(spawner, 'refresh', return_value=({}, {})))
        state.L['agents']['worker'] = {'task': 'p:existing', 'session': 'keep-session'}
        state.L['user_last_thought'] = state.now()
        self.operator = tasks.request_operator('user-job', 'Inspect requested evidence.', None, None, None, None)

    def test_user_operator_starts_at_capacity_during_coins_turn_without_stopping_worker(self):
        with patch.object(spawner.runs, 'start') as start, \
                patch.object(spawner.snapshots, 'make_room', return_value=True):
            spawner.spawn()
        start.assert_called_once_with(self.operator)
        self.assertEqual(state.L['agents']['worker']['session'], 'keep-session')
        spawner.lifecycle.opencode.stop.assert_not_called()

    def test_memory_holds_and_agent_created_helpers_do_not_bypass_admission(self):
        with patch.object(spawner.runs, 'start') as start, \
                patch.object(spawner.snapshots, 'make_room', return_value=False):
            spawner.spawn()
        start.assert_not_called()
        for field, value in (('admission_hold', 'user hold'), ('spawned_by', 'p:manager'),
                             ('replaced_by', ['p:replacement'])):
            self.operator[field] = value
            with self.subTest(field=field), patch.object(spawner.runs, 'start') as start, \
                    patch.object(spawner.snapshots, 'make_room', return_value=True):
                spawner.spawn()
            start.assert_not_called()
            self.operator.pop(field)


if __name__ == '__main__':
    unittest.main()
