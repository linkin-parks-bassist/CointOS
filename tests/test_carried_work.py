"""Generic decomposition and recovery carry material through authority, not workflow prose."""
import copy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from cointos import api, artifacts, config, contracts, frontier, git, lifecycle, opencode, queues, runs, state, tasks
from tests import support


class CarriedWork(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.enterContext(patch.object(opencode, 'active', return_value=False))
        self.repo = support.repository(self)
        (self.repo / 'code.c').write_text('original\n')
        support.accepted_plan(self.repo)
        self.project = support.project(self, self.repo)
        support.queued(self.project, 'contract', 'Prerequisite', stage='skeleton')
        queues.finish(queues.records()['p:contract'], commit=git.head(self.repo), via='landing')
        self.source = support.running(support.queued(self.project, 'origin', 'Complete A and B.',
                                                    dependency_ids=['contract']), 'old-author')
        self.tree = Path(self.source['worktree'])
        (self.tree / 'code.c').write_text('valuable unfinished work\n')
        (self.tree / 'new.c').write_text('new authored material\n')
        lifecycle.stop('old-author', 'stopped work', requeue=False)

    def launch(self, name):
        record = queues.records()['p:' + name]
        child = queues.current(record) or tasks.create('item', self.project, name, record['brief'], [4],
                                                      item=name, record_version=record['version'])
        support.running(child, name, worktree=False)
        with patch.object(opencode, 'launch', return_value=None):
            runs.launch(name, child, 'fixture-key')
        self.assertEqual((Path(child['worktree']) / 'code.c').read_text(), 'valuable unfinished work\n')
        self.assertEqual((Path(child['worktree']) / 'new.c').read_text(), 'new authored material\n')
        self.assertFalse((Path(child['worktree']) / '.git').exists())
        return child

    def test_manual_split_manager_handoff_prepares_children_and_survives_lost_source(self):
        result = api.dispatch('split', {'task': self.source['id'], 'reason': 'Too many obligations'})
        record = queues.records()[result['task']]
        self.assertNotIn(self.source['branch'], record['brief'])
        self.assertNotIn(str(self.tree), record['brief'])
        self.assertNotIn('Complete A and B.', record['brief'], 'one current requirement source, not a copied dossier')
        self.assertFalse(lifecycle.retire(self.source), 'unresolved carried material must survive retirement')
        manager = support.running(tasks.create('breakdown', self.project, record['item'], record['brief'], [3],
                                               item=record['item'], record_version=record['version']), 'manager')
        body = {'caller': support.caller(manager, 'manager'), 'summary': 'Publish the next two small obligations', 'items': [
            {'name': 'first', 'summary': 'Complete A', 'brief': 'Complete A.', 'dependencies': []},
            {'name': 'second', 'summary': 'Complete B', 'brief': 'Complete B.', 'dependencies': []}]}
        api.dispatch('handoff', body)
        for name in ('first', 'second'):
            self.assertEqual(queues.records()['p:' + name]['depends'], ['contract'])
            self.assertEqual(queues.records()['p:' + name]['carried_work'][0]['task'], 'p:origin')
        self.launch('first')
        self.assertEqual((self.tree / 'code.c').read_text(), 'valuable unfinished work\n')
        state.L.update(state.fresh(config.validate_ledger(copy.deepcopy(state.L))))
        shutil.rmtree(self.tree)
        with patch.object(artifacts, 'preserved', side_effect=AssertionError('original recaptured after persistence')):
            self.launch('second')

    def test_first_responder_replacement_carries_existing_work_and_prerequisites(self):
        repair = tasks.request_repair(self.source)[0]
        support.running(repair, 'repair')
        child = support.queued(self.project, 'next', 'Complete the remaining behavior.')
        api.dispatch('replace', {'caller': support.caller(repair, 'repair'), 'children': ['next']})
        self.assertIn('contract', queues.records()[child['id']]['depends'])
        self.assertEqual(queues.records()[child['id']]['carried_work'][0]['run'], 'old-author')
        child = self.launch('next')
        public = frontier.agent_view(frontier.inspect(child['id'], state.L), child)
        self.assertNotIn('carried_work', str(public))
        self.assertNotIn('material_snapshots', str(public))

    def test_source_author_change_cannot_silently_substitute_new_work(self):
        repair = tasks.request_repair(self.source)[0]
        support.running(repair, 'repair')
        api.dispatch('queue', {'caller': support.caller(repair, 'repair'), 'project': 'p', 'kind': 'queued',
                               'name': 'next', 'summary': 'Continue the remaining behavior', 'brief': 'Complete A.'})
        self.source['preserved_run'] = 'different-author'
        with self.assertRaisesRegex(ValueError, 'author changed'):
            artifacts.materials({'record': 'p:next', 'kind': 'item', 'place': 'p', 'branch': 'work/next',
                                'stage': 'implementation'}, self.project)
        self.assertFalse(self.source.get('material_snapshots'))

    def test_preserved_baseline_does_not_demand_fake_edits_for_already_accepted_material(self):
        repair = tasks.request_repair(self.source)[0]
        support.running(repair, 'repair')
        api.dispatch('queue', {'caller': support.caller(repair, 'repair'), 'project': 'p', 'kind': 'queued',
                               'name': 'next', 'summary': 'Verify the remaining behavior', 'brief': 'Verify A.'})
        material = artifacts.materials({'record': 'p:next', 'kind': 'item', 'place': 'p', 'branch': 'work/next',
                                        'stage': 'implementation'}, self.project)
        git.run(self.repo, 'merge', '-q', '--ff-only', material[0]['commit'])
        child = self.launch('next')
        self.assertEqual(child['base_commit'], self.source['base_commit'])
        self.assertTrue(git.clean(child['worktree']))
        contracts.worker_artifact(self.repo, child, git.head(child['worktree']))

    def test_carried_material_never_crosses_work_stages(self):
        target = {'kind': 'queued', 'item': 'tests', 'stage': 'test-contract', 'depends': [], 'brief': 'Write tests.'}
        artifacts.carry(target, self.source)
        self.assertNotIn('carried_work', target)

    def test_carried_material_never_crosses_project_boundaries(self):
        target = {'project': 'other', 'kind': 'queued', 'item': 'code', 'stage': 'implementation',
                  'depends': [], 'brief': 'Other project behavior.'}
        artifacts.carry(target, self.source)
        self.assertNotIn('carried_work', target)
        self.assertFalse(target['depends'])

    def test_accepted_replacement_is_not_revised_or_given_old_material(self):
        target = support.queued(self.project, 'accepted', 'Already accepted behavior.')
        record = queues.records()[target['record']]
        queues.finish(record, commit=git.head(self.repo), via='landing')
        before = copy.deepcopy(record)
        lifecycle.replace(queues.records()[self.source['record']], ['accepted'], 'user', 'Existing work covers the obligation')
        self.assertEqual(record, before)

    def test_active_child_is_revised_before_new_material_can_reach_it(self):
        child = support.running(support.queued(self.project, 'next', 'Finish the remaining behavior.'), 'child-old')
        version = child['record_version']
        lifecycle.replace(queues.records()[self.source['record']], ['next'], 'user', 'Preserve the remaining work')
        self.assertEqual(child['status'], 'waiting')
        self.assertGreater(child['record_version'], version)
        self.assertNotIn('child-old', state.L['agents'])
        self.assertFalse(child.get('session'))

    def test_reusing_origin_cannot_inherit_itself_or_claim_a_restart(self):
        repair = tasks.request_repair(self.source)[0]
        support.running(repair, 'repair')
        record = queues.records()[self.source['record']]
        record.update(queues.contents(record['kind'], record['brief'], record['stage'], project='p',
                                     summary='Complete the remaining scoped behavior', dependency_ids=record['depends']))
        self.source['brief'] = record['brief']
        before = copy.deepcopy(state.L)
        result = api.dispatch('run-agent', {'caller': support.caller(repair, 'repair'), 'role': 'worker',
                              'project': 'P', 'name': record['item'], 'brief': record['brief'],
                              'stage': record['stage'], 'summary': record['summary'],
                              'dependencies': record['depends'], 'abilities': ['standard']})
        self.assertFalse(result['created'])
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('no run restarted', result['message'])
        for field in ('tasks', 'queue', 'agents'):
            self.assertEqual(state.L[field], before[field])
        self.assertEqual((self.tree / 'code.c').read_text(), 'valuable unfinished work\n')
        self.assertNotIn('carried_work', record)

    def test_queue_retry_cannot_attach_new_inputs_to_an_existing_assignment(self):
        repair = tasks.request_repair(self.source)[0]
        support.running(repair, 'repair')
        child = support.running(support.queued(self.project, 'next', 'Complete A.', summary='Complete A'), 'child')
        before = copy.deepcopy(queues.records()['p:next'])
        with self.assertRaisesRegex(ValueError, 'checked replacement'):
            api.dispatch('queue', {'caller': support.caller(repair, 'repair'), 'project': 'p',
                                  'name': 'next', 'brief': 'Complete A.', 'summary': 'Complete A'})
        self.assertEqual(queues.records()['p:next'], before)
        self.assertEqual(child['status'], 'running')

    def test_generic_queue_refuses_stale_workspace_directions_without_partial_children(self):
        repair = tasks.request_repair(self.source)[0]
        support.running(repair, 'repair')
        with self.assertRaisesRegex(ValueError, 'relative file paths'):
            api.dispatch('queue', {'caller': support.caller(repair, 'repair'), 'project': 'p', 'name': 'next',
                                  'summary': 'Continue the remaining behavior', 'brief': 'Work only in ' + str(self.tree)})
        self.assertNotIn('p:next', queues.records())

    def test_manager_child_scope_is_checked_without_inherited_material(self):
        manager = support.running(support.queued(self.project, 'plan', 'Plan tests.', kind='command'), 'manager')
        child = {'project': 'p', 'name': 'witness', 'stage': 'test-contract',
                 'brief': 'Add the witness in ' + manager['worktree'],
                 'summary': 'Add a discriminating witness', 'dependencies': [], 'relies_on': ['code.c']}
        caller = support.caller(manager, 'manager')
        for action, fields in [('queue', {}), ('run-agent', {'role': 'worker'}),
                               ('run-agent', {'role': 'operator', 'stage': None,
                                              'dependencies': None, 'relies_on': None})]:
            with self.subTest(action=action, fields=fields):
                before = copy.deepcopy(state.L)
                with self.assertRaisesRegex(ValueError, 'relative file paths'):
                    api.dispatch(action, {**child, **fields, 'caller': caller})
                self.assertEqual(state.L, before)
        before = copy.deepcopy(state.L)
        checked = api.dispatch('check-work', {**child, 'caller': caller})
        self.assertFalse(checked['ok'])
        self.assertIn('relative file paths', checked['problems'][0])
        self.assertEqual(state.L, before)
        with self.assertRaisesRegex(ValueError, 'relative file paths'):
            api.dispatch('handoff', {'caller': caller, 'summary': 'Hand off the witness', 'items': [child]})
        self.assertEqual(state.L, before)
        child['brief'] = 'Add the witness in tests/fsm_test.c.'
        result = api.dispatch('run-agent', {**child, 'role': 'worker', 'caller': caller})
        self.assertEqual(result['task'], 'p:witness')
        self.assertEqual(queues.records()['p:witness']['stage'], 'test-contract')
        self.assertNotIn('carried_work', queues.records()['p:witness'])

    def test_malformed_material_cache_refuses_loading(self):
        self.source['material_snapshots'] = {'f' * 64: {'commit': 'not-an-artifact', 'base': 'f' * 40}}
        with self.assertRaisesRegex(ValueError, 'preserved material cache'):
            config.validate_ledger(state.L)

    def test_malformed_carried_authority_refuses_loading(self):
        record = queues.records()['p:origin']
        record['carried_work'] = [{'task': 'foreign:origin', 'version': 1, 'stage': 'implementation', 'run': 'old'}]
        with self.assertRaisesRegex(ValueError, 'carried work reference'):
            config.validate_ledger(state.L)

    def test_finished_history_cleanup_keeps_unresolved_material_authority(self):
        repair = tasks.request_repair(self.source)[0]
        support.running(repair, 'repair')
        api.dispatch('queue', {'caller': support.caller(repair, 'repair'), 'project': 'p', 'name': 'next',
                              'summary': 'Continue the remaining behavior', 'brief': 'Complete A.'})
        api.dispatch('replace', {'caller': support.caller(repair, 'repair'), 'children': ['next']})
        lifecycle.release('repair', 'receipt delivered')
        api.dispatch('clear-task-history', {})
        self.assertIn(self.source['id'], state.L['tasks'])
        self.assertIn(self.source['record'], queues.records())
        self.launch('next')

    def test_forgetting_a_source_cannot_orphan_its_unfinished_children(self):
        api.dispatch('split', {'task': self.source['id'], 'reason': 'Decompose the remaining work'})
        state.L['paused'] = True
        with self.assertRaisesRegex(ValueError, 'unfinished work still needs'):
            api.dispatch('forget-task', {'task': self.source['id']})
        self.assertIn(self.source['id'], state.L['tasks'])
