"""Personal mode must not restart a retained factory through recovery."""
import unittest
from unittest.mock import patch

from cointos import api, recovery, spawner, state, tasks
from tests import support


class FactoryDisabled(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.enterContext(patch.dict(state.CONFIG, factory_enabled=False))

    def task(self, name, kind, place='system', **extra):
        task = dict(id=name, kind=kind, place=place, **extra)
        state.L['tasks'][name] = task
        return task

    def test_retained_factory_and_indirect_recovery_cannot_run(self):
        for kind in ('steward', 'test-audit', 'garden', 'tree-audit', 'item', 'breakdown', 'integrate'):
            with self.subTest(kind=kind):
                source = self.task('source', kind)
                repair = self.task('repair', 'first-response', repair_origin={'task': source['id']})
                supervisor = self.task('supervisor', 'supervise', supervises=repair['id'])
                for task in (source, repair, supervisor):
                    self.assertFalse(spawner.runnable(task, {}))
        self.assertFalse(spawner.allowed(self.task('product-op', 'operator', 'p')))
        missing = self.task('missing', 'first-response', repair_origin={'task': 'absent'})
        self.assertFalse(spawner.allowed(missing))
        cycle = self.task('cycle', 'supervise', supervises='cycle')
        self.assertFalse(spawner.allowed(cycle))

    def test_discovery_publication_and_tree_observation_stay_idle(self):
        with patch.object(spawner, 'managed_trees', side_effect=AssertionError('tree scan')), \
                patch.object(tasks, 'enabled_projects', side_effect=AssertionError('project scan')):
            self.assertEqual(spawner.periodic(), [])
            self.assertEqual(spawner.tree_work(), [])
            self.assertEqual(spawner.queued_work({}, {}), [])
            self.assertEqual(spawner.integrations(), [])
            spawner.refresh_trees()

    def test_requested_operator_admits_without_automatic_support(self):
        operator = tasks.request_operator('requested', 'Do the requested job.', None, None, None, None)
        self.assertTrue(spawner.runnable(operator, {}))
        repair = self.task('repair', 'first-response', repair_origin={'task': operator['id']})
        supervisor = self.task('supervisor', 'supervise', supervises=operator['id'])
        self.assertFalse(spawner.allowed(repair))
        self.assertFalse(spawner.allowed(supervisor))
        self.enterContext(patch.object(spawner.models, 'changing', return_value=False))
        self.enterContext(patch.object(spawner.lanes, 'blocked', return_value=False))
        self.enterContext(patch.dict(state.L['models'], {state.CONFIG['work_model']: {'up': True}}))
        state.L['user_last_thought'] = state.now()
        with patch.object(spawner, 'refresh', return_value=({}, {})), \
                patch.object(spawner.runs, 'start') as start, \
                patch.object(spawner.snapshots, 'make_room', return_value=True):
            spawner.spawn()
        start.assert_called_once_with(operator)

    def test_milestones_and_failures_do_not_create_agents(self):
        operator = tasks.request_operator('requested', 'Do the requested job.', None, None, None, None)
        with patch.object(tasks, 'request_supervisor', side_effect=AssertionError('automatic supervisor')), \
                patch.object(tasks, 'request_repair', side_effect=AssertionError('automatic recovery')):
            recovery.supervise(operator, {}, 100000)
            spawner.repair_work({'p': [{'project': 'p', 'item': 'failed'}]})

    def test_explicit_requests_and_timer_replays_are_admitted(self):
        operator = tasks.request_operator('requested', 'Do the requested job.', None, None, None, None)
        support.running(operator, 'operator-requested', worktree=False)
        result = api.run_role({'name': 'inspect', 'brief': 'Inspect requested work.', 'task': operator['id']}, 'supervisor')
        self.assertTrue(spawner.allowed(state.L['tasks'][result['task']]))
        body = {'name': 'scheduled', 'brief': 'Run the requested check.', 'occurrence': 'timer:one'}
        first = api.run_role(body, 'steward')
        task = state.L['tasks'][first['task']]
        self.assertTrue(spawner.allowed(task))
        task.pop('dispatch_requested')
        self.assertEqual(api.run_role(body, 'steward')['task'], task['id'])
        self.assertTrue(spawner.allowed(task))

    def test_suspended_failures_do_not_create_recovery(self):
        source = self.task('scout', 'steward')
        with patch.object(spawner.frontier, 'reason', side_effect=AssertionError('factory recovery')):
            spawner.repair_work({})
        self.assertEqual(state.L['tasks'], {'scout': source})

    def test_factory_can_be_reenabled_without_recreating_tasks(self):
        source = self.task('scout', 'steward')
        with patch.dict(state.CONFIG, factory_enabled=True):
            self.assertTrue(spawner.allowed(source))
        self.assertIs(state.L['tasks']['scout'], source)
