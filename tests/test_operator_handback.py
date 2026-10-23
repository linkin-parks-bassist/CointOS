"""Operator repair authority and checked handbacks through production API/MCP."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import api, cli, client, lifecycle, mcp, opencode, queues, spawner, state, tasks
from tests import support


class OperatorHandback(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self, {'paused': False})
        support.quiet(self)
        self.project = support.project(self, support.repository(self, 'owner'))
        self.other = {**self.project, 'name': 'q', 'path': str(support.repository(self, 'foreign'))}
        state.CONFIG['projects'].append(self.other)
        support.accepted_plan(self.project['path'])
        support.accepted_plan(self.other['path'])
        self.enterContext(patch.object(cli, 'call', self.direct))
        self.enterContext(patch.object(mcp, 'call', self.direct))
        self.enterContext(patch.object(cli, 'ledger', lambda: state.L))
        self.enterContext(patch.object(mcp, 'ledger', lambda: state.L))

    def direct(self, action, body=None, **kwargs):
        caller = client.caller()
        return api.dispatch(action, {**(body or {}), **({'caller': caller} if caller else {})})

    def operator(self, abilities=('standard', 'control'), project='p', name='fix'):
        result = api.dispatch('run-agent', {'name': name, 'brief': 'Diagnose and repair the obstruction',
                                           'project': project, 'abilities': list(abilities)})
        return support.running(state.L['tasks'][result['task']], name + '-run')

    def call(self, by, action, **body):
        return api.dispatch(action, {**body, 'caller': support.caller(by, by['agent'])})

    def tool(self, task, name, arguments):
        with patch.dict(os.environ, COINTOS_TASK_ID=task['id'], COINTOS_AGENT=task['agent']):
            return mcp.invoke(name, arguments, 'operator')

    def blocked(self, name='origin'):
        source = support.running(support.queued(self.project, name, 'Plan the product', kind='command'), name + '-run')
        self.call(source, 'finish', outcome='blocked', detail='The owning contract contradicts the assignment')
        lifecycle.release(name + '-run', 'fixture completion delivered')
        return source

    def repair(self, source, start=True):
        task, created = tasks.request_repair(source)
        self.assertTrue(created)
        return support.running(task, 'repair-run') if start else task

    def test_control_operator_repairs_own_project_through_mcp(self):
        operator = self.operator()
        output, failed = self.tool(operator, 'queue', {'project': 'p', 'name': 'work', 'kind': 'command',
                                                      'brief': 'Investigate the verified problem',
                                                      'summary': 'Investigate the problem', 'dependencies': []})
        self.assertFalse(failed, output)
        for name, args in (
            ('hold', {'item': 'p:work'}),
            ('revise', {'item': 'p:work', 'brief': 'A corrected plan', 'reason': 'Verified the false premise',
                        'summary': 'Correct the plan', 'dependencies': []}),
            ('budget', {'task': 'p:work', 'generation_tokens': 1234}),
            ('cancel', {'items': ['p:work'], 'reason': 'The corrected plan makes this obsolete'}),
        ):
            with self.subTest(tool=name):
                output, failed = self.tool(operator, name, args)
                self.assertFalse(failed, output)
        self.assertNotIn('p:work', state.L['queue'])
        source = self.blocked()
        self.call(operator, 'queue', project='p', name='replacement', kind='command', brief='Corrective stage')
        output, failed = self.tool(operator, 'supersede', {'task': source['id'], 'replacements': ['replacement'],
                                                          'reason': 'Verified replacement fixes the mismatch'})
        self.assertFalse(failed, output)
        self.assertEqual(state.L['queue'][source['record']]['replaced_by'], ['replacement'])
        self.assertIsNone(source.get('acceptance'))

    def test_standard_and_foreign_operators_cannot_repair_owner_queue(self):
        source = self.blocked()
        support.queued(self.project, 'replacement', 'Corrective stage', kind='command')
        actions = (
            ('queue', {'project': 'p', 'name': 'new', 'kind': 'command', 'brief': 'New'}),
            ('hold', {'item': source['id']}),
            ('revise', {'item': source['id'], 'brief': 'New', 'reason': 'Changed'}),
            ('cancel', {'items': [source['id']], 'reason': 'Changed'}),
            ('supersede', {'task': source['id'], 'replacements': ['replacement'], 'reason': 'Changed'}),
            ('budget', {'task': 'p:replacement', 'budget': {'generation_tokens': 1234}}),
        )
        for operator in (self.operator(('standard',), name='standard'), self.operator(project='q', name='foreign')):
            for action, body in actions:
                with self.subTest(operator=operator['title'], action=action):
                    before = copy.deepcopy(state.L['queue'])
                    with self.assertRaises(ValueError):
                        self.call(operator, action, **body)
                    self.assertEqual(state.L['queue'], before)

    def test_system_operator_can_queue_diagnostic_handoff_without_file_scope_widening(self):
        operator = self.operator(project=None)
        self.call(operator, 'queue', project='q', name='diagnose', kind='command', brief='Check the verified obstruction')
        self.assertEqual(state.L['queue']['q:diagnose']['proposed_by'], operator['id'])
        self.assertEqual(operator['place'], 'system')
        self.assertIsNone(operator['branch'])
        with patch.object(opencode, 'GLOBAL_CONFIG', Path(self.project['path']).parent / 'absent.json'):
            broad = opencode.settings(state.CONFIG, 'fixture-key', operator, [])['permission']
            ordinary = opencode.settings(state.CONFIG, 'fixture-key', {**operator, 'abilities': ['standard']}, [])['permission']
        for permission in ('read', 'edit', 'external_directory'):
            self.assertEqual(broad[permission], ordinary[permission])
        self.assertEqual(broad['bash']['systemctl --user *'], 'allow')

    def test_terminal_blocked_source_does_not_prove_unverified_repair_complete(self):
        source = self.blocked()
        operator = self.repair(source)
        self.assertEqual(source['status'], 'done')
        self.assertEqual(source['receipt']['disposition'], 'blocked')
        with self.assertRaisesRegex(ValueError, 'checked handback'):
            self.call(operator, 'finish', outcome='complete', detail='I have not changed anything')
        self.assertEqual(operator['status'], 'running')
        self.assertIsNone(operator['receipt'])

    def test_valid_origin_revision_is_checked_handback(self):
        source = self.blocked()
        operator = self.repair(source)
        self.call(operator, 'revise', item=source['id'], brief='Use the corrected contract', reason='Verified the contradiction')
        result = self.call(operator, 'finish', outcome='complete', detail='Corrected the false assignment; its manager can resume')
        self.assertEqual(result['receipt']['evidence']['repaired_record'], source['record'])
        self.assertEqual(result['receipt']['evidence']['record_version'], state.L['queue'][source['record']]['version'])
        continuation = spawner.next_task()
        self.assertEqual(continuation['id'], source['id'])
        self.assertEqual(continuation['status'], 'waiting')
        self.assertEqual(continuation['brief'], 'Use the corrected contract')
        self.assertIsNone(source.get('acceptance'))

    def test_changed_origin_cannot_complete_with_unknown_or_cyclic_prerequisite(self):
        for name, dependency in (('unknown', 'nonexistent'), ('cycle', 'cycle')):
            with self.subTest(problem=name):
                queues.add(self.project, 'command', name, f'Original\nDepends on: {dependency}')
                record = state.L['queue']['p:' + name]
                operator = self.repair(record, start=False)
                support.running(operator, 'repair-' + name)
                self.call(operator, 'revise', item=queues.key(record),
                          brief=f'Reworded but still blocked\nDepends on: {dependency}', reason='Only changed wording')
                with self.assertRaisesRegex(ValueError, 'handback|dependenc|prerequisite'):
                    self.call(operator, 'finish', outcome='complete', detail='The impossible prerequisite remains')
                self.assertIsNone(operator['receipt'])

    def test_changed_origin_can_wait_on_known_corrective_work(self):
        queues.add(self.project, 'command', 'origin', 'Original\nDepends on: nonexistent')
        record = state.L['queue']['p:origin']
        operator = self.repair(record)
        self.call(operator, 'queue', project='p', name='corrective', kind='command', brief='Correct the verified prerequisite')
        self.call(operator, 'revise', item='p:origin', brief='Corrected\nDepends on: corrective', reason='Established real corrective work')
        self.assertEqual(queues.readiness(queues.live('p'), queues.landed('p'))['origin'], 'waiting')
        result = self.call(operator, 'finish', outcome='complete', detail='Origin now waits on runnable corrective work')
        self.assertEqual(result['receipt']['evidence']['repaired_record'], 'p:origin')
        self.assertIsNone(record['done'] if 'done' in record else None)

    def test_changed_origin_cannot_hide_unknown_prerequisite_behind_known_child(self):
        queues.add(self.project, 'command', 'origin', 'Original\nDepends on: nonexistent')
        operator = self.repair(state.L['queue']['p:origin'])
        self.call(operator, 'queue', project='p', name='corrective', kind='command',
                  brief='Corrective work\nDepends on: nonexistent')
        self.call(operator, 'revise', item='p:origin', brief='Use corrective work\nDepends on: corrective',
                  reason='Moved the same missing prerequisite into a child')
        readiness = queues.readiness(queues.live('p'), queues.landed('p'))
        self.assertEqual(readiness['origin'], 'waiting')
        self.assertTrue(readiness['corrective'].startswith('depends on unknown '))
        with self.assertRaisesRegex(ValueError, 'handback|dependenc|prerequisite'):
            self.call(operator, 'finish', outcome='complete', detail='The original impossible prerequisite remains reachable')
        self.assertIsNone(operator['receipt'])

    def test_replacement_cannot_hide_unknown_prerequisite_behind_known_child(self):
        source = self.blocked()
        operator = self.repair(source)
        self.call(operator, 'queue', project='p', name='inner', kind='command',
                  brief='Corrective work\nDepends on: nonexistent')
        self.call(operator, 'queue', project='p', name='replacement', kind='command',
                  brief='Replacement plan\nDepends on: inner')
        self.call(operator, 'supersede', task=source['id'], replacements=['replacement'],
                  reason='Established a replacement that still has an impossible prerequisite')
        with self.assertRaisesRegex(ValueError, 'handback|dependenc|prerequisite'):
            self.call(operator, 'finish', outcome='complete', detail='The replacement cannot reach a runnable frontier')
        self.assertIsNone(operator['receipt'])

    def test_changed_origin_cannot_hide_a_cycle_inside_known_corrective_work(self):
        queues.add(self.project, 'command', 'origin', 'Original\nDepends on: nonexistent')
        operator = self.repair(state.L['queue']['p:origin'])
        self.call(operator, 'queue', project='p', name='corrective', kind='command',
                  brief='Corrective work\nDepends on: corrective')
        self.call(operator, 'revise', item='p:origin', brief='Use corrective work\nDepends on: corrective',
                  reason='Moved the blocker into a cyclic child')
        readiness = queues.readiness(queues.live('p'), queues.landed('p'))
        self.assertEqual(readiness['origin'], 'waiting')
        self.assertIn('cycle', readiness['corrective'])
        with self.assertRaisesRegex(ValueError, 'handback|dependenc|prerequisite|cycle'):
            self.call(operator, 'finish', outcome='complete', detail='The known corrective child cannot run')
        self.assertIsNone(operator['receipt'])

    def test_valid_corrective_chain_is_not_rejected_for_unrelated_invalid_record(self):
        queues.add(self.project, 'command', 'origin', 'Original\nDepends on: nonexistent')
        operator = self.repair(state.L['queue']['p:origin'])
        queues.add(self.project, 'command', 'unrelated', 'Separate work\nDepends on: missing-elsewhere')
        self.call(operator, 'queue', project='p', name='inner', kind='command', brief='Correct the verified prerequisite')
        self.call(operator, 'queue', project='p', name='corrective', kind='command',
                  brief='Apply the correction\nDepends on: inner')
        self.call(operator, 'revise', item='p:origin', brief='Use corrective work\nDepends on: corrective',
                  reason='Established a runnable corrective chain')
        result = self.call(operator, 'finish', outcome='complete', detail='Runnable correction is established')
        self.assertEqual(result['receipt']['evidence']['repaired_record'], 'p:origin')

    def test_infrastructure_handback_requires_successful_origin_reentry(self):
        source = support.queued(self.project, 'origin', 'Plan', kind='command')
        source.update(admission_hold='repeated infrastructure launch failure', launch_failures=3)
        operator = self.repair(source)
        self.call(operator, 'resume-task', task=source['id'])
        with self.assertRaisesRegex(ValueError, 'checked handback'):
            self.call(operator, 'finish', outcome='complete', detail='Only removed the infrastructure hold')
        support.running(source, 'reentered-run')
        lifecycle.engaged('reentered-run')
        result = self.call(operator, 'finish', outcome='complete', detail='Origin reached the model through the repaired launch path')
        self.assertEqual(result['receipt']['evidence']['source_status'], 'running')
        self.assertEqual(source['launch_failures'], 0)

    def test_explicit_origin_hold_blocks_operator_controls_and_child_handoffs(self):
        source = self.blocked()
        operator = self.repair(source)
        self.call(operator, 'queue', project='p', name='replacement', kind='command', brief='Corrective stage')
        api.dispatch('hold', {'item': source['id']})
        actions = (
            ('revise', {'item': source['id'], 'brief': 'New', 'reason': 'Changed'}),
            ('cancel', {'items': [source['id']], 'reason': 'Changed'}),
            ('supersede', {'task': source['id'], 'replacements': ['replacement'], 'reason': 'Changed'}),
            ('unhold', {'item': source['id']}),
            ('queue', {'project': 'p', 'name': 'bypass', 'kind': 'command', 'brief': 'Bypass the hold'}),
        )
        for action, body in actions:
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    self.call(operator, action, **body)
                self.assertEqual(state.L['queue'][source['record']]['held_by'], 'user')
        source.update(status='waiting', admission_hold='paused by the user')
        with self.assertRaises(ValueError):
            self.call(operator, 'resume-task', task=source['id'])
        self.assertEqual(source['admission_hold'], 'paused by the user')

    def test_manual_control_operator_cannot_remove_a_targets_user_hold(self):
        source = self.blocked()
        operator = self.operator()
        self.call(operator, 'queue', project='p', name='replacement', kind='command', brief='Corrective stage')
        api.dispatch('hold', {'item': source['id']})
        for action, body in (
            ('unhold', {'item': source['id']}),
            ('revise', {'item': source['id'], 'brief': 'New', 'reason': 'Changed'}),
            ('supersede', {'task': source['id'], 'replacements': ['replacement'], 'reason': 'Changed'}),
            ('cancel', {'items': [source['id']], 'reason': 'Changed'}),
        ):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    self.call(operator, action, **body)
                self.assertEqual(state.L['queue'][source['record']]['held_by'], 'user')

    def test_manager_can_correct_assignment_without_releasing_user_hold(self):
        source = self.blocked()
        manager = support.running(support.queued(self.project, 'manager', 'Repair the brief', kind='command'), 'manager-run')
        api.dispatch('hold', {'item': source['id']})
        self.call(manager, 'revise', item=source['id'], brief='Corrected manager assignment', reason='Verified correction')
        self.assertEqual(state.L['queue'][source['record']]['brief'], 'Corrected manager assignment')
        self.assertEqual(state.L['queue'][source['record']]['held_by'], 'user')

    def test_system_repair_handoff_requires_a_runnable_provenance_linked_command(self):
        source = support.running(tasks.create('steward', tasks.SYSTEM, 'diagnose', 'Inspect the failed infrastructure', [6]),
                                 'source-run', worktree=False)
        self.call(source, 'finish', outcome='blocked', detail='A project contract needs independent diagnosis')
        lifecycle.release('source-run', 'fixture completion delivered')
        operator = self.repair(source)
        with self.assertRaisesRegex(ValueError, 'checked handback'):
            self.call(operator, 'finish', outcome='complete', detail='I have not established any continuation')
        self.call(operator, 'queue', project='q', name='diagnose', kind='command',
                  brief='Diagnose the original obstruction\nDepends on: nonexistent')
        with self.assertRaisesRegex(ValueError, 'checked handback'):
            self.call(operator, 'finish', outcome='complete', detail='The proposed handoff cannot run')
        self.call(operator, 'revise', item='q:diagnose', brief='Diagnose the original obstruction against its contract',
                  reason='Removed the impossible prerequisite')
        result = self.call(operator, 'finish', outcome='complete', detail='The diagnostic manager can now run')
        self.assertEqual(result['receipt']['evidence']['continuation'], 'q:diagnose')
        self.assertEqual(state.L['queue']['q:diagnose']['proposed_by'], operator['id'])
        self.assertIsNone(operator['branch'])

    def test_standard_and_foreign_resume_refused_and_human_hold_release_works(self):
        source = support.queued(self.project, 'origin', 'Plan', kind='command')
        source['admission_hold'] = 'repeated infrastructure launch failure'
        for operator in (self.operator(('standard',), name='standard'), self.operator(project='q', name='foreign')):
            with self.assertRaises(ValueError):
                self.call(operator, 'resume-task', task=source['id'])
        source['admission_hold'] = 'paused by the user'
        api.dispatch('resume-task', {'task': source['id']})
        self.assertNotIn('admission_hold', source)

    def test_terminal_repair_dedup_survives_history_clear(self):
        source = self.blocked()
        operator = self.repair(source)
        self.call(operator, 'finish', outcome='blocked', detail='Verified external decision needed')
        lifecycle.release('repair-run', 'fixture completion delivered')
        api.dispatch('clear-task-history', {})
        known, created = tasks.request_repair(source)
        self.assertFalse(created)
        self.assertIs(known, operator)
        self.assertIn(source['id'], state.L['tasks'])
        self.assertIn(operator['id'], state.L['tasks'])

    def test_nonqueue_blocked_terminal_repair_dedup_survives_history_clear(self):
        source = support.running(tasks.create('steward', tasks.SYSTEM, 'diagnose', 'Inspect failed infrastructure', [6]),
                                 'source-run', worktree=False)
        self.call(source, 'finish', outcome='blocked', detail='Verified external dependency remains')
        lifecycle.release('source-run', 'fixture completion delivered')
        operator = self.repair(source)
        self.call(operator, 'finish', outcome='blocked', detail='External dependency still requires a decision')
        lifecycle.release('repair-run', 'fixture completion delivered')
        api.dispatch('clear-task-history', {})
        self.assertIn(source['id'], state.L['tasks'])
        known, created = tasks.request_repair(state.L['tasks'][source['id']])
        self.assertFalse(created)
        self.assertIs(known, operator)

    def test_obsolete_never_started_repair_cancelled_without_fake_receipt(self):
        source = self.blocked()
        operator = self.repair(source, start=False)
        api.dispatch('revise', {'item': source['id'], 'brief': 'Corrected', 'reason': 'User fixed the contract'})
        lifecycle.reconcile()
        self.assertEqual(operator['status'], 'failed')
        self.assertTrue(operator.get('cancelled'))
        self.assertEqual(operator['runs'], 0)
        self.assertIsNone(operator['receipt'])

    def test_started_repair_can_resume_and_report_handback_after_restart(self):
        source = self.blocked()
        operator = self.repair(source)
        self.call(operator, 'revise', item=source['id'], brief='Corrected', reason='Verified contract correction')
        previous = json.loads(json.dumps(state.L))
        state.L.clear()
        state.L.update(state.fresh(previous))
        operator = state.L['tasks'][operator['id']]
        lifecycle.orphaned(operator)
        self.assertTrue(spawner.runnable(operator, {}))
        support.running(operator, 'repair-run-2')
        result = self.call(operator, 'finish', outcome='complete', detail='The corrected origin remains runnable')
        self.assertEqual(result['receipt']['run'], 'repair-run-2')
        self.assertEqual(result['receipt']['evidence']['repaired_record'], source['record'])
