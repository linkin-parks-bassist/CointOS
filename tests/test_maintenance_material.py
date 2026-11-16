"""Maintenance recovery receives scoped files rather than storage-recovery instructions."""
import copy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from cointos import api, artifacts, config, contracts, git, lifecycle, opencode, queues, runs, state, tasks
from tests import support


class MaintenanceMaterial(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.enterContext(patch.object(opencode, 'active', return_value=False))
        self.repo = support.repository(self)
        support.accepted_plan(self.repo)
        (self.repo / 'code.c').write_text('accepted behavior\n')
        (self.repo / 'config').mkdir()
        (self.repo / 'config/options').write_text('accepted option\n')
        support.commit(self.repo)
        self.project = support.project(self, self.repo, test_policy={
            'manifest': 'tests/contracts.json', 'protected': ['tests/**'], 'non_code': ['config/**']})

    def stop_and_repair(self, source):
        lifecycle.stop(source['agent'], 'retain unfinished maintenance', requeue=False)
        responder = tasks.request_repair(source)[0]
        support.running(responder, 'responder', worktree=False)
        return responder

    def dispatch(self, owner, role, name='continuation'):
        return api.dispatch('run-agent', {'caller': support.caller(owner, owner['agent']), 'role': role,
                                          'name': name, 'project': 'p', 'brief': 'Complete the remaining scoped concern.',
                                          'summary': 'Complete maintenance', 'dependencies': []})['task']

    def launch(self, child):
        support.running(child, child['id'], worktree=False)
        with patch.object(opencode, 'launch', return_value=None):
            runs.launch(child['id'], child, 'fixture')
        return Path(child['worktree'])

    def test_failed_manager_passes_unpublished_plan_to_a_manager_without_product_changes(self):
        support.queued(self.project, 'prerequisite', stage='skeleton')
        queues.finish(queues.records()['p:prerequisite'], commit=git.head(self.repo), via='landing')
        source = support.running(support.queued(self.project, 'planning', kind='command',
                                                dependency_ids=['prerequisite']), 'planner')
        plan = Path(source['worktree']) / '.knowledge/what/is/the/plan.md'
        plan.write_text('A preserved planning frontier.\n')
        owner = self.stop_and_repair(source)
        child_id = self.dispatch(owner, 'manager')
        record = queues.records()[child_id]
        self.assertEqual(record['depends'], ['prerequisite'])
        self.assertEqual(record['carried_work'][0]['task'], source['id'])
        self.assertFalse(lifecycle.retire(source))
        child = tasks.create('breakdown', self.project, record['item'], record['brief'], [5],
                             item=record['item'], record_version=record['version'])
        tree = self.launch(child)
        self.assertEqual((tree / '.knowledge/what/is/the/plan.md').read_text(), plan.read_text())
        self.assertEqual((tree / 'code.c').read_text(), 'accepted behavior\n')
        self.assertFalse((tree / '.git').exists())
        self.assertEqual(plan.read_text(), 'A preserved planning frontier.\n')

    def test_operator_recovery_keeps_noncode_files_and_authority_after_restart_and_source_removal(self):
        source = support.running(tasks.request_operator('original', 'Maintain options.', 'p', None, None, None), 'operator')
        (Path(source['worktree']) / 'config/options').write_text('unfinished option\n')
        owner = self.stop_and_repair(source)
        child = state.L['tasks'][self.dispatch(owner, 'operator')]
        self.assertEqual(child['carried_work'][0]['task'], source['id'])
        config.validate_ledger(copy.deepcopy(state.L))
        self.assertFalse(lifecycle.retire(source))
        # The new assignment must retain provenance independently of its former controller.
        state.L['tasks'].pop(owner['id'])
        state.L['agents'].pop('responder')
        api.dispatch('clear-task-history', {})
        self.assertIn(source['id'], state.L['tasks'])
        tree = self.launch(child)
        self.assertEqual((tree / 'config/options').read_text(), 'unfinished option\n')
        shutil.rmtree(source['worktree'])
        with patch.object(artifacts, 'preserved', side_effect=AssertionError('recaptured retired source')):
            self.assertTrue(artifacts.materials(child, self.project))
        with patch.dict(state.L, paused=True, agents={}):
            with self.assertRaisesRegex(ValueError, 'unfinished work still needs'):
                api.dispatch('forget-task', {'task': source['id']})

    def test_tree_maintenance_can_continue_in_a_different_knowledge_only_role(self):
        source = support.running(tasks.create('garden', self.project, 'garden', 'Verify selected answers.', [6]), 'gardener')
        (Path(source['worktree']) / '.knowledge/what/is/the/plan.md').write_text('Preserved answer.\n')
        owner = self.stop_and_repair(source)
        child = state.L['tasks'][self.dispatch(owner, 'tree-auditor')]
        tree = self.launch(child)
        self.assertEqual((tree / '.knowledge/what/is/the/plan.md').read_text(), 'Preserved answer.\n')
        self.assertEqual((tree / 'code.c').read_text(), 'accepted behavior\n')

    def test_operator_files_do_not_enter_a_planning_workspace(self):
        source = support.running(tasks.request_operator('original', 'Maintain options.', 'p', None, None, None), 'operator')
        (Path(source['worktree']) / 'config/options').write_text('unfinished option\n')
        owner = self.stop_and_repair(source)
        child_id = self.dispatch(owner, 'manager')
        record = queues.records()[child_id]
        child = tasks.create('breakdown', self.project, record['item'], record['brief'], [5],
                             item=record['item'], record_version=record['version'])
        tree = self.launch(child)
        self.assertEqual((tree / 'config/options').read_text(), 'accepted option\n')
        self.assertEqual((Path(source['worktree']) / 'config/options').read_text(), 'unfinished option\n')
        from cointos import frontier
        public = frontier.agent_view(frontier.inspect(child_id, state.L), child)
        self.assertEqual(public['preserved_inputs'], [{'task': source['id'], 'role': 'operator'}])
        next_owner = state.L['tasks'][self.dispatch(child, 'operator', 'scoped-continuation')]
        continued = self.launch(next_owner)
        self.assertEqual((continued / 'config/options').read_text(), 'unfinished option\n')
        self.assertEqual((tree / 'config/options').read_text(), 'accepted option\n')

    def test_snapshot_preserves_pending_editor_answers_but_publication_still_refuses_overlap(self):
        source = support.running(tasks.request_operator('original', 'Maintain answers.', 'p', None, None, None), 'operator')
        relative = '.knowledge/what/is/the/plan.md'
        (Path(source['worktree']) / relative).write_text('Unfinished maintained answer.\n')
        (self.repo / relative).write_text('Unpublished human editor answer.\n')
        owner = self.stop_and_repair(source)
        child = state.L['tasks'][self.dispatch(owner, 'operator')]
        tree = self.launch(child)
        self.assertEqual((tree / relative).read_text(), 'Unfinished maintained answer.\n')
        with self.assertRaisesRegex(ValueError, 'pending canonical'):
            contracts.maintenance_history(self.project, child, git.head(self.repo), include_worktree=True)
        self.assertEqual((self.repo / relative).read_text(), 'Unpublished human editor answer.\n')

    def test_held_recovery_cannot_import_files_or_leave_a_new_partial_assignment(self):
        source = support.running(tasks.request_operator('original', 'Maintain options.', 'p', None, None, None), 'operator')
        owner = self.stop_and_repair(source)
        source['admission_hold'] = 'held by user'
        before = set(state.L['tasks'])
        with self.assertRaisesRegex(ValueError, 'held or its recovery authority changed'):
            self.dispatch(owner, 'operator')
        self.assertEqual(set(state.L['tasks']), before)
