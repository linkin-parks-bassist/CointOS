import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, frontier, lifecycle, opencode, recovery, schema, spawner, state, tasks
from tests import support


class Supervisors(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.project = support.project(self, Path('/tmp/p'))
        self.enterContext(patch.dict(state.CONFIG['recovery'], supervise_every_seconds=1800))
        self.worker = support.running(support.queued(self.project, 'long', 'Summary: a long job for this test\nDo it.'), 'worker-1', worktree=False)
        self.agent = state.L['agents']['worker-1']

    def supervisors(self):
        return [t for t in state.L['tasks'].values() if t['kind'] == 'supervise']

    def test_a_long_run_gets_one_supervisor_per_threshold(self):
        self.agent['generation_seconds'] = 1799
        recovery.enforce()
        self.assertEqual(self.supervisors(), [])
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        recovery.enforce()
        found = self.supervisors()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['supervises'], self.worker['id'])
        self.assertIn('cointos transcript ' + self.worker['id'], found[0]['brief'])
        self.assertEqual(found[0]['budget']['generation_seconds'], state.CONFIG['recovery']['role_budgets']['supervisor']['generation_seconds'])

    def test_a_supervisor_is_not_itself_supervised(self):
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        state.L['agents']['supervisor-1']['generation_seconds'] = 400
        state.L['agents']['supervisor-1']['supervisions'] = 0
        with patch.dict(state.CONFIG['recovery'], supervise_every_seconds=100):
            recovery.enforce()
        self.assertEqual([t['supervises'] for t in self.supervisors()], [self.worker['id']])
        self.assertEqual(supervisor['role'], 'supervisor')

    def test_a_supervisor_cannot_complete_while_its_run_is_going(self):
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        with self.assertRaisesRegex(ValueError, 'you stay until it ends'):
            lifecycle.submit(supervisor['id'], 'supervisor-1', 'complete', 'looks fine')
        self.worker['status'] = 'done'
        lifecycle.submit(supervisor['id'], 'supervisor-1', 'complete', 'it finished')
        self.assertEqual(supervisor['receipt']['disposition'], 'complete')

    def test_a_supervisor_that_stops_needs_no_first_responder(self):
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        lifecycle.submit(supervisor['id'], 'supervisor-1', 'blocked', 'this run needs no supervising')
        self.assertIsNone(frontier.reason(supervisor))

    def test_an_implementer_cannot_write_or_run_a_probe(self):
        permission = opencode.settings(state.CONFIG, 'key', {'abilities': ['standard']}, ['tests/*'])['permission']
        self.assertEqual((permission['bash']['*probe*'], permission['edit']['*probe*']), ('deny', 'deny'))
        other = opencode.settings(state.CONFIG, 'key', {'abilities': ['standard']}, [])['permission']
        self.assertNotIn('*probe*', other['bash'])

    def test_a_revise_replaces_the_run_and_retires_the_supervisor(self):
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        with patch.object(lifecycle.opencode, 'stop'):
            api.dispatch('revise', {'item': self.worker['id'], 'brief': 'Summary: a long job for this test\nDo it.\nDone so far: half.',
                                    'reason': 'it was compacting', 'caller': support.caller(supervisor, 'supervisor-1')})
            lifecycle.reconcile()
        self.assertEqual(self.worker['status'], 'waiting')
        self.assertIsNone(self.worker['session'])
        self.assertNotIn('worker-1', state.L['agents'])
        self.assertEqual(supervisor['status'], 'failed')
        self.assertIn('its brief is the handoff', supervisor['note'])
        self.assertNotIn('supervisor-1', state.L['agents'])

    def test_a_supervisor_can_send_a_malformed_assignment_to_recovery(self):
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        with patch.object(lifecycle.opencode, 'stop'):
            api.dispatch('recover', {'task': self.worker['id'], 'reason': 'the brief contradicts itself',
                                     'caller': support.caller(supervisor, 'supervisor-1')})
        self.assertEqual(self.worker['status'], 'failed')
        self.assertIn('contradicts itself', frontier.reason(self.worker))

    def test_a_supervisor_is_stood_down_when_its_run_ends(self):
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        supervisor = self.supervisors()[0]
        self.worker['status'] = 'done'
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'failed', 'an unstarted one just goes')

    def test_a_running_supervisor_gets_a_short_wrap_up_when_its_run_ends(self):
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        self.worker['status'] = 'done'
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'running')
        self.assertEqual(state.L['messages'][-1]['to'], supervisor['id'])
        supervisor['standing_down'] -= state.CONFIG['recovery'].get('supervise_wrap_up_seconds', 120)
        with patch.object(lifecycle.opencode, 'stop'):
            lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'failed')

    def test_a_supervisor_starts_past_a_full_house(self):
        self.agent['generation_seconds'] = 1800
        recovery.enforce()
        supervisor = self.supervisors()[0]
        started = []
        with patch.dict(state.CONFIG['spawner'], max_agents=1), patch.object(spawner.runs, 'start', started.append), \
                patch.object(spawner.snapshots, 'make_room', return_value=True), patch.object(spawner.lanes, 'blocked', return_value=frozenset()), \
                patch.object(spawner.models, 'changing', return_value=False), patch.dict(state.L['models'], {state.CONFIG['work_model']: {'up': True}}), \
                patch.object(spawner, 'next_task', return_value=None):
            state.L['user_last_thought'] = 0
            spawner.spawn()
        self.assertEqual(started, [supervisor])

    def test_a_run_past_its_budget_gets_no_supervisor(self):
        self.agent['generation_seconds'] = 10 ** 6
        with patch.object(lifecycle, 'retry_fresh'):
            recovery.enforce()
        self.assertEqual(self.supervisors(), [])

    def test_a_supervisor_takes_the_lane_from_a_background_run(self):
        ranks = state.CONFIG['classes']
        self.assertLess(ranks.index('supervisor'), ranks.index('background'))
        self.assertLess(ranks.index('user'), ranks.index('supervisor'))

    def test_any_role_can_call_one_and_it_may_read_and_steer(self):
        steward = support.running(tasks.create('steward', tasks.SYSTEM, 'scout', 'Look.', [6]), 'steward-1', worktree=False)
        result = api.run_agent({'role': 'supervisor', 'name': 'look', 'brief': 'Look.', 'task': self.worker['id'],
                                'caller': support.caller(steward, 'steward-1')})
        task = state.L['tasks'][result['task']]
        self.assertEqual(task['role'], 'supervisor')
        self.assertFalse(opencode.confined_writes(task))
        self.assertIn('supervisor', schema.DISPATCH_PROPERTIES['role']['enum'])
