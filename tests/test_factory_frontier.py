"""The factory advances work through one owner and atomic handoffs."""
import copy
import json
import unittest
from unittest.mock import patch

from cointos import api, frontier, lifecycle, packets, prompts, queues, schema, spawner, state, tasks
from tests import support


class Frontier(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        state.L['paused'] = False
        self.project = support.project(self, support.repository(self))
        self.enterContext(patch.object(spawner, 'periodic', return_value=[]))
        self.enterContext(patch.object(spawner, 'tree_work', return_value=[]))

    def test_worker_failure_has_one_capable_owner_and_no_manager_operator_cascade(self):
        worker = support.queued(self.project, 'build')
        lifecycle.fail(worker, 'The independent test contradicts the contract')
        repair = spawner.next_task()
        self.assertEqual(repair['role'], 'operator')
        self.assertEqual(repair['repair_origin'], {'task': worker['id'], 'version': 1})
        self.assertEqual(repair['abilities'], list(schema.ABILITIES))
        for source in (worker, queues.records()[worker['record']]):
            self.assertEqual(tasks.request_repair(source), (repair, False))
        self.assertEqual(len(state.L['tasks']), 2)
        lifecycle.fail(repair, 'No justified continuation found')
        self.assertIsNone(spawner.next_task(), 'exhaustion cannot fund a recursive controller')
        saved = copy.deepcopy(state.L)
        state.L.clear()
        state.L.update(state.fresh(saved))
        self.assertIsNone(spawner.next_task(), 'restart cannot refill recovery')
        self.assertFalse(frontier.view('p')[0]['owner'])

    def test_recovery_is_serial_per_project_without_blocking_unrelated_workers(self):
        first = support.queued(self.project, 'first')
        second = support.queued(self.project, 'second')
        lifecycle.fail(first, 'first blockage')
        lifecycle.fail(second, 'second blockage')
        controller = spawner.next_task()
        support.running(controller, 'repair-1', worktree=False)
        useful = support.queued(self.project, 'independent')
        self.assertEqual(spawner.next_task()['id'], useful['id'])
        self.assertEqual(sum(t.get('repair_origin') is not None for t in state.L['tasks'].values()), 2)

    def test_recovery_inspection_uses_live_binding_and_only_typed_corrections(self):
        queues.add(self.project, 'queued', 'tests', 'Pin the behavior', 'test-contract', reliances=['code'])
        original = queues.records()['p:tests']
        original['done'] = {'commit': 'original-accepted-commit', 'via': 'tests'}
        worker = support.queued(self.project, 'build', 'Depends on: tests\nImplement the behavior')
        lifecycle.fail(worker, 'An assertion contradicts the governing contract')
        repair = spawner.next_task()
        queues.add(self.project, 'queued', 'unrelated', 'Claims to replace tests in prose', 'test-contract', reliances=['code'])
        before = copy.deepcopy(state.L)
        shown = frontier.inspect(repair['id'], state.L)
        self.assertEqual(shown['binding_tests'], [{'packet': 'p:tests', 'commit': 'original-accepted-commit',
                                                 'pending_corrections': []}])
        self.assertEqual(state.L, before, 'inspection never changes authority')
        correction = packets.propose(self.project, 'tests', 'corrected', 'Correct the witness',
                                     by=repair['id'], summary='Correct the contract witness',
                                     reliances=['code'], reason='The witness contradicts the contract')
        self.assertEqual(frontier.inspect(worker['id'], state.L)['binding_tests'][0]['pending_corrections'],
                         ['p:corrected'])
        correction['done'] = {'commit': 'corrected-accepted-commit', 'via': 'tests'}
        packets.activate(correction)
        self.assertEqual(frontier.inspect(repair['id'], state.L)['binding_tests'],
                         [{'packet': 'p:corrected', 'commit': 'corrected-accepted-commit', 'pending_corrections': []}])

    def test_recovery_launch_does_not_replay_nested_obsolete_assignment_narratives(self):
        worker = support.queued(self.project, 'build', 'Implement the CURRENT requirement')
        worker['recovery_context'] = 'OLD NESTED EXECUTION ' * 1000
        lifecycle.fail(worker, 'Exact current refusal')
        repair = spawner.next_task()
        repair.update(brief='OBSOLETE DECOMPOSITION INSTRUCTIONS',
                      recovery_context='OLD CONTROLLER TRANSCRIPT', recovery_note='Earlier migration')
        launch = prompts.launch_text(repair, self.project)
        self.assertIn('CURRENT requirement', launch)
        self.assertIn('Exact current refusal', launch)
        self.assertNotIn('OLD NESTED', launch)
        self.assertNotIn('OBSOLETE DECOMPOSITION', launch)
        self.assertNotIn('OLD CONTROLLER', launch)
        historical = frontier.inspect(repair['id'], state.L, history=True)
        self.assertEqual(historical['task']['brief'], repair['brief'])
        self.assertEqual(historical['origin_task']['recovery_context'], worker['recovery_context'])

    def test_construction_launches_follow_reviewed_contract_authority(self):
        queues.add(self.project, 'queued', 'tests', 'Pin the behavior', 'test-contract', reliances=['code'])
        original = queues.records()['p:tests']
        original['done'] = {'commit': 'original-accepted-commit', 'via': 'tests'}
        worker = support.queued(self.project, 'build', 'Depends on: tests\nImplement the behavior')
        manager = support.queued(self.project, 'audit', 'Depends on: tests\nResolve the mismatch', kind='command')
        reviewer = tasks.create('integrate', self.project, 'review-build', worker['brief'], [2],
                                item=worker['item'], worker=worker['id'])
        queues.add(self.project, 'queued', 'ordinary', 'A replacement claimed in prose',
                   'test-contract', reliances=['code'])
        queues.records()['p:ordinary']['done'] = {'commit': 'unrelated-accepted-commit', 'via': 'tests'}
        for task in (worker, manager, reviewer):
            launch = prompts.launch_text(task, self.project)
            self.assertIn('original-accepted-commit', launch)
            self.assertNotIn('unrelated-accepted-commit', launch)

        correction = packets.propose(self.project, 'tests', 'corrected', 'Correct the witness',
                                     by=manager['id'], summary='Correct the contract witness',
                                     reliances=['code'], reason='The witness contradicts the contract')
        author = tasks.create('item', self.project, 'corrected', correction['brief'], [4],
                              item=correction['item'], record_version=correction['version'])
        correction_review = tasks.create('integrate', self.project, 'review-correction', author['brief'], [2],
                                         item=author['item'], worker=author['id'])
        for task in (author, correction_review):
            launch = prompts.launch_text(task, self.project)
            self.assertIn('"correction": {', launch)
            self.assertIn('original-accepted-commit', launch)
            self.assertIn('another packet does not complete this correction', launch)

        correction['done'] = {'commit': 'corrected-accepted-commit', 'via': 'tests'}
        lifecycle.activate_correction(correction, correction_review['id'])
        for task in (worker, manager, reviewer):
            launch = prompts.launch_text(task, self.project)
            self.assertIn('corrected-accepted-commit', launch)
            self.assertNotIn('unrelated-accepted-commit', launch)

    def test_current_task_view_keeps_one_assignment_and_checked_account(self):
        worker = support.queued(self.project, 'build', 'CURRENT ASSIGNMENT')
        account = 'CURRENT CHECKED ACCOUNT ' * 100
        worker.update(status='failed', result=account, note='blocked: ' + account[:500],
                      receipt={'disposition': 'blocked', 'summary': account, 'evidence': {'commit': 'preserved'}})
        queues.records()[worker['record']]['blocker'] = account
        before = copy.deepcopy(state.L)
        shown = frontier.inspect(worker['id'], state.L)
        rendered = json.dumps(shown)
        self.assertEqual(rendered.count('CURRENT ASSIGNMENT'), 1)
        self.assertEqual(rendered.count('CURRENT CHECKED ACCOUNT'), 100)
        self.assertEqual(shown['task']['receipt'], worker['receipt'])
        self.assertEqual(frontier.inspect(worker['id'], state.L, history=True)['task'], worker)
        self.assertEqual(state.L, before)

    def test_restarted_assignment_keeps_prior_completion_only_in_explicit_history(self):
        worker = support.queued(self.project, 'build', 'CURRENT ASSIGNMENT')
        worker['result'] = 'OLD COMPLETION: already committed and verified'
        lifecycle.fail(worker, 'Needs a corrected witness')
        lifecycle.revise(worker['record'], 'user', 'Correct the remaining defect',
                         'CURRENT REVISED ASSIGNMENT')
        support.running(worker, 'resumed-worker', worktree=False)
        before = copy.deepcopy(state.L)
        shown = frontier.inspect(worker['id'], state.L)
        self.assertNotIn('result', shown['task'])
        self.assertEqual(shown['task']['historical_fields'], ['result'])
        self.assertIn('--history', shown['historical_evidence'])
        self.assertIn('CURRENT REVISED ASSIGNMENT', json.dumps(shown))
        self.assertNotIn('OLD COMPLETION', prompts.launch_text(worker, self.project))
        self.assertEqual(frontier.inspect(worker['id'], state.L, history=True)['task'], worker)
        self.assertEqual(state.L, before)

    def test_agent_cancelling_derived_recovery_gets_the_actual_queue_target(self):
        worker = support.queued(self.project, 'build')
        lifecycle.fail(worker, 'Blocked')
        repair = spawner.next_task()
        support.running(repair, 'repair-1', worktree=False)
        caller = support.caller(repair, 'repair-1')
        with self.assertRaisesRegex(ValueError, 'originating queue ID: p:build'):
            api.dispatch('cancel', {'caller': caller, 'items': [repair['id']], 'reason': 'Obsolete work'})
        self.assertIn('p:build', state.L['queue'])
        api.dispatch('cancel', {'caller': caller, 'items': ['p:build'], 'reason': 'Obsolete work'})
        self.assertNotIn('p:build', state.L['queue'])

    def test_human_hold_stops_recovery_without_losing_session_or_artifacts(self):
        worker = support.queued(self.project, 'build')
        lifecycle.fail(worker, 'scope mismatch')
        repair = spawner.next_task()
        support.running(repair, 'repair-1', worktree=False)
        repair['session'] = 'preserved-session'
        lifecycle.hold(worker['id'], 'user')
        self.assertEqual((repair['status'], repair['session']), ('waiting', 'preserved-session'))
        self.assertFalse(spawner.runnable(repair, {}))

    def test_child_depending_on_failed_origin_cannot_hide_ownerless_blockage(self):
        worker = support.queued(self.project, 'build')
        child = queues.add(self.project, 'queued', 'continuation', 'Continue', dependency_ids=['build'])
        queues.records()['p:' + child]['proposed_by'] = worker['id']
        lifecycle.fail(worker, 'cannot implement current contract')
        self.assertFalse(frontier.handoff_pending(worker))
        repair = spawner.next_task()
        lifecycle.fail(repair, 'needs a product decision')
        projected = next(row for row in frontier.view('p') if row['item'] == worker['id'])
        self.assertIsNone(projected['owner'])
        self.assertEqual(projected['continuations'], [])

    def test_exhausted_controller_children_remain_the_assignments_continuation(self):
        manager = support.queued(self.project, 'plan', 'Plan the next boundary', kind='command')
        lifecycle.fail(manager, 'planning budget exhausted')
        repair = spawner.next_task()
        child = support.queued(self.project, 'tests', 'Pin the boundary', stage='test-contract',
                               reliances=['code'])
        record = queues.records()[child['record']]
        record['proposed_by'] = repair['id']
        lifecycle.fail(repair, 'controller budget exhausted after queueing useful work')
        for source in (manager, queues.records()[manager['record']]):
            self.assertEqual(frontier.handoffs(source), [record])
        row = next(r for r in frontier.view('p') if r['item'] == manager['id'])
        self.assertEqual(row['continuations'], [child['id']])
        self.assertEqual((manager['status'], repair['status']), ('failed', 'failed'))
        self.assertIsNone(manager['receipt'])
        self.assertIsNone(repair['receipt'])
        record['depends'] = ['plan']
        self.assertEqual(frontier.handoffs(manager), [], 'a backedge cannot hide the blockage')
        record['depends'] = []
        record['held_by'] = 'user'
        self.assertEqual(frontier.handoffs(manager), [], 'held work cannot be a continuation')
        record['held_by'] = None
        queues.records()[manager['record']]['version'] += 1
        self.assertEqual(frontier.handoffs(queues.records()[manager['record']]), [],
                         'old controller children do not authorize a new assignment')

    def manager(self):
        task = support.queued(self.project, 'plan', 'Plan the next boundary', kind='command')
        support.running(task, 'manager-1', worktree=False)
        task['branch'] = None
        return task

    def test_atomic_handoff_supports_forward_dependencies_and_lost_reply_replay(self):
        manager = self.manager()
        request = {'caller': support.caller(manager, 'manager-1'), 'summary': 'Next boundary dispatched', 'items': [
            {'name': 'code', 'brief': 'Implement the interface', 'summary': 'Implement the next interface',
             'dependencies': ['base']},
            {'name': 'base', 'brief': 'Declare the interface', 'summary': 'Declare the next interface',
             'dependencies': [], 'stage': 'skeleton'}]}
        result = api.dispatch('handoff', request)
        self.assertEqual(manager['status'], 'done')
        self.assertEqual(result['children'], ['p:code', 'p:base'])
        self.assertEqual(api.dispatch('handoff', request)['receipt'], result['receipt'])
        request['items'][0]['brief'] = 'A different assignment'
        with self.assertRaisesRegex(ValueError, 'different handoff'):
            api.dispatch('handoff', request)
        self.assertEqual(spawner.next_task()['id'], 'p:base')

    def test_invalid_atomic_handoff_leaves_no_partial_queue_or_completion(self):
        manager = self.manager()
        before = copy.deepcopy(state.L['queue'])
        with self.assertRaisesRegex(ValueError, 'cannot continue'):
            api.dispatch('handoff', {'caller': support.caller(manager, 'manager-1'),
                'summary': 'Dispatch', 'items': [
                    {'name': 'good', 'brief': 'Build', 'summary': 'Build one slice', 'dependencies': []},
                    {'name': 'bad', 'brief': 'Build', 'summary': 'Build another slice', 'dependencies': ['absent']}]})
        self.assertEqual(state.L['queue'], before)
        self.assertEqual(manager['status'], 'running')
        self.assertIsNone(manager['receipt'])
