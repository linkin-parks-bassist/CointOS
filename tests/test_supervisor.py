import unittest
import copy
import json
from pathlib import Path
from unittest.mock import patch

from cointos import api, artifacts, frontier, lifecycle, opencode, prompts, recovery, schema, spawner, state, tasks
from tests import support


class Supervisors(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.project = support.project(self, Path('/tmp/p'))
        self.enterContext(patch.dict(state.CONFIG['recovery'], supervise_every_tokens=5000))
        self.worker = support.running(support.queued(self.project, 'long', 'Summary: a long job for this test\nDo it.'), 'worker-1', worktree=False)
        self.agent = state.L['agents']['worker-1']
        self.enterContext(patch.object(lifecycle.opencode, 'stop'))
        self.enterContext(patch.object(artifacts, 'preserved', return_value={'commit': 'a' * 40, 'base': 'b' * 40}))

    def run_for(self, tokens):
        self.agent['generation_tokens'] = tokens

    def supervisors(self):
        return [t for t in state.L['tasks'].values() if t['kind'] == 'supervise']

    def test_a_long_run_gets_one_supervisor_per_threshold(self):
        self.run_for(4999)
        recovery.enforce()
        self.assertEqual(self.supervisors(), [])
        self.run_for(5000)
        recovery.enforce()
        recovery.enforce()
        found = self.supervisors()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['supervises'], self.worker['id'])
        self.assertEqual(found[0]['supervises_run'], 'worker-1')
        self.assertIn('cointos_log', found[0]['brief'])
        self.assertEqual(found[0]['budget']['generation_seconds'], state.CONFIG['recovery']['role_budgets']['supervisor']['generation_seconds'])

    def test_thirty_gpu_minutes_summons_a_progress_decision_without_stopping_work(self):
        self.run_for(4999)  # below the output threshold
        self.agent['generation_seconds'] = self.agent['gpu_seconds'] = 3000  # slow, prefill-heavy run
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 1)
        self.assertEqual(self.worker['status'], 'running')
        self.assertEqual(state.L['agents']['worker-1']['generation_tokens'], 4999)

    def test_elapsed_generation_time_is_not_a_kill_limit_and_usage_is_real(self):
        self.agent.update(generation_seconds=100000, gpu_seconds=1801, generation_tokens=100)
        recovery.enforce()
        self.assertEqual(self.worker['status'], 'running')
        supervisor = self.supervisors()[0]
        launch = prompts.launch_text(supervisor, tasks.SYSTEM)
        self.assertIn('30.0 GPU minutes', launch)
        self.assertIn('100 generated tokens', launch)
        view = frontier.inspect(self.worker['id'], state.L)
        self.assertEqual(view['usage']['gpu_seconds'], 1801)
        self.assertEqual(view['usage']['generated_tokens'], 100)
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 1)

    def test_a_supervisor_is_not_itself_supervised(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        state.L['agents']['supervisor-1']['generation_tokens'] = 400
        state.L['agents']['supervisor-1']['supervisions'] = 0
        with patch.dict(state.CONFIG['recovery'], supervise_every_tokens=100):
            recovery.supervise(supervisor, state.L['agents']['supervisor-1'], 400)
        self.assertEqual([t['supervises'] for t in self.supervisors()], [self.worker['id']])
        self.assertEqual(supervisor['role'], 'supervisor')

    def test_starting_supervision_does_not_message_its_subject(self):
        before = copy.deepcopy(state.L['messages'])
        self.run_for(5000)
        recovery.enforce()
        self.assertEqual(state.L['messages'], before)
        self.assertEqual(len(self.supervisors()), 1)

    def test_a_gardener_also_gets_a_check_if_it_generates_enough(self):
        self.worker['role'] = 'gardener'
        self.run_for(5000)
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 1)

    def test_a_supervisor_finishes_once_and_the_next_interval_checks_again(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        lifecycle.submit(supervisor['id'], 'supervisor-1', 'complete', 'No action: scoped edit and passing checks')
        self.assertEqual(supervisor['receipt']['disposition'], 'complete')
        supervisor['status'] = 'done'
        self.run_for(10000)
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 2, 'a second one double-checks at 10,000 generated tokens')

    def test_a_supervisor_that_stops_needs_no_first_responder(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        lifecycle.submit(supervisor['id'], 'supervisor-1', 'blocked', 'this run needs no supervising')
        self.assertIsNone(frontier.reason(supervisor))

    def test_an_implementer_cannot_write_or_run_a_probe(self):
        permission = opencode.settings(state.CONFIG, 'key', {'abilities': ['standard']}, ['tests/*'])['permission']
        self.assertEqual((permission['shell']['*probe*'], permission['edit']['*probe*']), ('deny', 'deny'))
        other = opencode.settings(state.CONFIG, 'key', {'abilities': ['standard']}, [])['permission']
        self.assertNotIn('*probe*', other['shell'])

    def test_a_revise_replaces_the_run_and_retires_the_supervisor(self):
        self.run_for(5000)
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

    def test_unchanged_revision_does_not_retire_supervisor_as_a_handoff(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        record = state.L['queue'][self.worker['record']]
        result = api.dispatch('revise', {'item': self.worker['id'], 'brief': record['brief'],
                              'reason': 'Retry unchanged work',
                              'caller': support.caller(supervisor, 'supervisor-1')})
        self.assertFalse(result['changed'])
        self.assertEqual(supervisor['status'], 'running')
        self.assertEqual(self.worker['status'], 'running')

    def test_a_supervisor_can_send_a_malformed_assignment_to_recovery(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        with patch.object(lifecycle.opencode, 'stop'):
            api.dispatch('recover', {'task': self.worker['id'], 'reason': 'the brief contradicts itself',
                                     'caller': support.caller(supervisor, 'supervisor-1')})
        self.assertEqual(self.worker['status'], 'failed')
        self.assertIn('contradicts itself', frontier.reason(self.worker))

    def test_a_supervisor_is_stood_down_when_its_run_ends(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = self.supervisors()[0]
        self.worker['status'] = 'done'
        state.L['agents'] = {k: a for k, a in state.L['agents'].items() if a['task'] != self.worker['id']}
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'failed', 'an unstarted one just goes')

    def test_a_supervisor_is_stood_down_when_its_subject_waits_in_review(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = self.supervisors()[0]
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'waiting', 'kept while the run is live')
        self.worker['status'] = 'review'
        state.L['agents'] = {k: a for k, a in state.L['agents'].items() if a['task'] != self.worker['id']}
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'failed', 'a reviewed subject has no run to watch')

    def test_a_running_supervisor_retires_when_its_run_ends_without_follow_up(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        before = copy.deepcopy(state.L['messages'])
        self.worker['status'] = 'done'
        state.L['agents'].pop('worker-1')
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'failed')
        self.assertNotIn('supervisor-1', state.L['agents'])
        self.assertEqual(state.L['messages'], before)
        self.assertIsNone(frontier.reason(supervisor), 'retirement creates no recovery owner')

    def test_supervision_does_not_transfer_to_a_new_run_of_the_same_task(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        lifecycle.kill('worker-1')
        lifecycle.resume_task(self.worker['id'])
        support.running(self.worker, 'worker-2', worktree=False)
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'failed')
        self.assertEqual(self.worker['agent'], 'worker-2')
        self.assertIn('worker-2', state.L['agents'])
        successor = tasks.request_supervisor(self.worker, 10000)
        self.assertNotEqual(successor['id'], supervisor['id'])
        self.assertEqual(successor['supervises_run'], 'worker-2')

    def test_old_notified_supervisor_cannot_adopt_a_resumed_subject(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        supervisor.pop('supervises_run')
        supervisor['standing_down'] = state.now()
        lifecycle.kill('worker-1')
        lifecycle.resume_task(self.worker['id'])
        support.running(self.worker, 'worker-2', worktree=False)
        successor = tasks.request_supervisor(self.worker, 10000)
        self.assertEqual(supervisor['status'], 'failed')
        self.assertNotEqual(successor['id'], supervisor['id'])
        self.assertIn('worker-2', state.L['agents'])

    def test_ordinary_supervision_requires_an_existing_run(self):
        lifecycle.kill('worker-1')
        before = set(state.L['tasks'])
        with self.assertRaisesRegex(ValueError, 'requires a live run'):
            tasks.request_supervisor(self.worker, 5000)
        self.assertEqual(set(state.L['tasks']), before)

    def test_an_explicitly_missing_watched_run_cannot_adopt_a_later_run(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        supervisor['supervises_run'] = None
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'failed')
        self.assertIn('worker-1', state.L['agents'])

    def test_a_supervisor_starts_past_a_full_house(self):
        self.run_for(5000)
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

    def test_supervision_has_no_separate_scheduling_tier(self):
        from cointos import runs
        self.assertEqual(runs.scheduling_class({'role': 'supervisor'}), 'background')
        self.assertEqual(runs.scheduling_class({'role': 'worker'}), 'background')

    def test_any_role_can_call_one_and_it_may_read_and_steer(self):
        steward = support.running(tasks.create('steward', tasks.SYSTEM, 'scout', 'Look.', [6]), 'steward-1', worktree=False)
        result = api.run_agent({'role': 'supervisor', 'name': 'look', 'brief': 'Look.', 'task': self.worker['id'],
                                'caller': support.caller(steward, 'steward-1')})
        task = state.L['tasks'][result['task']]
        self.assertEqual(task['role'], 'supervisor')
        self.assertTrue(opencode.confined_writes(task))
        self.assertIn('supervisor', schema.DISPATCH_PROPERTIES['role']['enum'])

    def test_redispatching_own_supervision_refuses_without_a_false_steer(self):
        supervisor = support.running(tasks.request_supervisor(self.worker, 5000),
                                     'supervisor-1', worktree=False)
        before = copy.deepcopy(state.L)
        with self.assertRaisesRegex(api.ApiError, 'cointos_send'):
            api.run_agent({'role': 'supervisor', 'name': 'steer-worker',
                           'brief': 'Stop rereading and write the test.',
                           'task': self.worker['id'],
                           'caller': support.caller(supervisor, 'supervisor-1')})
        self.assertEqual(state.L, before)

    def second(self):
        self.run_for(5000)
        recovery.enforce()
        supervisor = tasks.request_supervisor(self.worker, 10000, must_split=True)
        support.running(supervisor, 'second-1', worktree=False)
        return supervisor

    def halves(self):
        return [{'name': 'first-half', 'summary': 'First half', 'brief': 'Finish the first half.',
                 'dependencies': []},
                {'name': 'second-half', 'summary': 'Second half', 'brief': 'Finish the second half.',
                 'dependencies': ['first-half']}]

    def handoff(self, supervisor, items):
        return api.dispatch('handoff', {'caller': support.caller(supervisor, 'second-1'),
                             'summary': 'Split the remaining work evenly in two', 'items': items})

    def test_second_supervisor_stops_worker_and_cannot_be_talked_out_of_splitting(self):
        worktree = Path(self.worker['worktree'])
        worktree.mkdir(parents=True, exist_ok=True)
        draft = worktree / 'unfinished.c'
        draft.write_text('valuable unfinished work\n')
        supervisor = self.second()
        self.assertTrue(supervisor['must_split'])
        self.assertNotIn('worker-1', state.L['agents'])
        self.assertEqual(draft.read_text(), 'valuable unfinished work\n')
        self.assertEqual(self.worker['split_supervisor'], supervisor['id'])
        for action, body in [('finish', {'outcome': 'complete', 'detail': 'it is almost finished'}),
                             ('finish', {'outcome': 'blocked', 'detail': 'let a manager split it'}),
                             ('revise', {'item': self.worker['id'], 'reason': 'nearly done', 'brief': 'Finish it.'}),
                             ('split', {'task': self.worker['id'], 'reason': 'delegate the split'})]:
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'second supervisor'):
                api.dispatch(action, {**body, 'caller': support.caller(supervisor, 'second-1')})
        with self.assertRaisesRegex(ValueError, 'second supervisor'):
            lifecycle.submit(supervisor['id'], 'second-1', 'complete', 'nearly finished')
        lifecycle.reconcile()
        self.assertEqual(supervisor['status'], 'running', 'the stopped subject does not retire its splitter')

    def test_second_handoff_creates_exactly_two_fresh_jobs_and_repoints_dependents(self):
        dependent = support.queued(self.project, 'after', 'Summary: Later work\nDepends on: long')
        supervisor = self.second()
        response = self.handoff(supervisor, self.halves())
        self.assertEqual(response['receipt']['disposition'], 'complete')
        self.assertEqual(self.worker['replaced_by'], ['first-half', 'second-half'])
        self.assertEqual(state.L['queue'][dependent['record']]['depends'], ['first-half', 'second-half'])
        for key in response['children']:
            record = state.L['queue'][key]
            self.assertEqual(record['kind'], 'queued')
            self.assertNotIn(self.worker['worktree'], record['brief'])
            self.assertEqual(record['preserved_artifact'], {'commit': 'a' * 40, 'base': 'b' * 40})
            self.assertNotIn(key, state.L['tasks'], 'the scheduler starts a fresh child task')
        self.assertEqual(self.handoff(supervisor, self.halves())['receipt'], response['receipt'])
        with self.assertRaisesRegex(ValueError, 'second supervisor'):
            lifecycle.require_start(self.worker, 'worker-returning')

    def test_invalid_two_way_handoff_has_no_partial_queue_effects(self):
        supervisor = self.second()
        original = copy.deepcopy(state.L['queue'])
        cases = [self.halves()[:1], self.halves() + [self.halves()[0]],
                 [self.halves()[0], self.halves()[0]],
                 [{**self.halves()[0], 'kind': 'command'}, self.halves()[1]],
                 [{**self.halves()[0], 'stage': 'test-contract'}, self.halves()[1]],
                 [{**self.halves()[0], 'dependencies': ['second-half']}, self.halves()[1]],
                 [{**self.halves()[0], 'dependencies': ['missing']}, self.halves()[1]]]
        for items in cases:
            with self.subTest(items=items), self.assertRaises(ValueError):
                self.handoff(supervisor, items)
            self.assertEqual(state.L['queue'], original)
            self.assertIsNone(supervisor['receipt'])

    def test_job_supervision_survives_revision_and_ledger_reload(self):
        self.run_for(5000)
        recovery.enforce()
        lifecycle.revise(self.worker['record'], 'user', 'new instructions',
                         'Summary: Keep the same job\nFinish the remaining work.')
        restored = state.fresh(json.loads(json.dumps(state.L)))
        state.L.clear()
        state.L.update(restored)
        self.worker = state.L['tasks'][self.worker['id']]
        support.running(self.worker, 'worker-2', worktree=False)
        state.L['agents']['worker-2']['generation_tokens'] = 5000
        recovery.enforce()
        self.assertEqual(self.worker['supervision_tokens'], 10000)
        self.assertFalse(self.supervisors()[-1].get('must_split', False))
        self.assertIn('worker-2', state.L['agents'])

    def test_repeated_checks_do_not_duplicate_token_spend_or_supervisors(self):
        self.run_for(5000)
        for _ in range(4): recovery.enforce()
        self.assertEqual(self.worker['supervision_tokens'], 5000)
        self.assertEqual(len(self.supervisors()), 1)
        self.supervisors()[0]['status'] = 'done'
        self.run_for(10000)
        recovery.enforce()
        for _ in range(4): recovery.enforce()
        self.assertEqual(len(self.supervisors()), 2)

    def test_repeat_inspections_never_automatically_stop_or_split_the_worker(self):
        first = tasks.request_supervisor(self.worker, 5000)
        first['status'] = 'done'
        second = tasks.request_supervisor(self.worker, 10000)
        self.assertFalse(second.get('must_split', False))
        self.assertIn('worker-1', state.L['agents'])

    def test_halves_inherit_original_dependencies_without_retyping_them(self):
        support.queued(self.project, 'accepted-contract', 'Original prerequisite.')
        state.L['queue'][self.worker['record']]['depends'] = ['accepted-contract']
        supervisor = self.second()
        result = self.handoff(supervisor, self.halves())
        first, second = [state.L['queue'][key] for key in result['children']]
        self.assertEqual(first['depends'], ['accepted-contract'])
        self.assertEqual(second['depends'], ['accepted-contract', 'first-half'])

    def test_overdue_intervals_coalesce_and_next_absolute_boundary_checks_again(self):
        self.run_for(16000)
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 1)
        first = self.supervisors()[0]
        first['status'] = 'done'
        recovery.enforce()
        self.run_for(19999)
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 1)
        self.run_for(20000)
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 2)
        self.assertIn('worker-1', state.L['agents'])

    def test_pending_inspection_prevents_duplicates_without_losing_next_interval(self):
        self.run_for(5000)
        recovery.enforce()
        self.run_for(10000)
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 1)
        self.supervisors()[0]['status'] = 'done'
        recovery.enforce()
        self.assertEqual(len(self.supervisors()), 2)

    def test_40k_supervisor_stops_and_splits_implementer_even_with_a_pending_check(self):
        self.run_for(39999)
        recovery.enforce()
        self.assertIn('worker-1', state.L['agents'])
        self.assertFalse(self.supervisors()[-1].get('must_split', False))
        self.run_for(40000)
        recovery.enforce()
        splitter = self.supervisors()[-1]
        self.assertTrue(splitter['must_split'])
        self.assertNotIn('worker-1', state.L['agents'])
        self.assertEqual(self.worker['split_supervisor'], splitter['id'])
        self.assertIn('worker is stopped', splitter['brief'])

    def test_managers_and_integrators_never_force_split_at_40k(self):
        for role in ('manager', 'integrator'):
            with self.subTest(role=role):
                self.worker['role'] = role
                recovery.supervise(self.worker, self.agent, 40000)
                self.assertIn('worker-1', state.L['agents'])
                self.assertNotIn('split_supervisor', self.worker)
                self.assertFalse(self.supervisors()[-1].get('must_split', False))

    def test_supervisor_has_no_token_cap_in_prompt_or_enforcement(self):
        self.run_for(5000)
        recovery.enforce()
        task = support.running(self.supervisors()[0], 'supervisor-1', worktree=False)
        self.assertIsNone(task['budget']['generation_tokens'])
        from cointos import prompts
        self.assertNotIn('budget', prompts.launch_text(task, tasks.SYSTEM).lower())
        state.L['agents']['supervisor-1']['generation_tokens'] = 10**9
        recovery.enforce()
        self.assertIn('supervisor-1', state.L['agents'])
