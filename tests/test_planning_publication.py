"""Planning publishes files and child authority together, including every lost-process boundary."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import api, config, daemon, git, handoffs, lifecycle, queues, state
from tests import support


class Crash(BaseException):
    pass


class Planning(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.repo = support.repository(self)
        support.accepted_plan(self.repo, 'Original approved scope.\n')
        self.project = support.project(self, self.repo)
        self.task = support.running(support.queued(self.project, 'plan', 'Plan the product', kind='command'), 'manager-1')
        self.tree = Path(self.task['worktree'])
        git.insulate(self.tree)
        self.plan = '.knowledge/what/is/the/plan.md'
        (self.tree / self.plan).write_text('The interface and implementation children own the remaining scope.\n')
        self.body = {'caller': support.caller(self.task, 'manager-1'), 'summary': 'Next boundary dispatched',
                     'items': [{'name': 'code', 'brief': 'Implement the interface', 'summary': 'Implement behavior',
                                'dependencies': ['interface']},
                               {'name': 'interface', 'brief': 'Declare the interface', 'summary': 'Declare interface',
                                'dependencies': [], 'stage': 'skeleton'}]}
        self.parent = git.head(self.repo, 'main')

    def act(self):
        return api.dispatch('handoff', self.body)

    def test_uncommitted_plan_and_forward_children_publish_without_git_from_the_manager(self):
        editor = self.repo / 'editor.txt'
        editor.write_text('Preserve this editor draft.\n')
        result = self.act()
        self.assertEqual(result['children'], ['p:code', 'p:interface'])
        self.assertEqual(self.task['status'], 'done')
        self.assertEqual(git.show(self.repo, 'main', self.plan), (self.tree / self.plan).read_text())
        self.assertEqual(editor.read_text(), 'Preserve this editor draft.\n')
        accepted = git.head(self.repo, 'main')
        self.assertEqual(self.act()['receipt'], result['receipt'])
        self.assertEqual(git.head(self.repo, 'main'), accepted)
        self.assertFalse((self.tree / '.git').exists())

    def test_invalid_graph_never_publishes_or_creates_partial_children(self):
        self.body['items'][0]['dependencies'] = ['missing']
        before = copy.deepcopy(state.L['queue'])
        with self.assertRaisesRegex(ValueError, 'cannot continue'):
            self.act()
        self.assertEqual(state.L['queue'], before)
        self.assertEqual(git.head(self.repo, 'main'), self.parent)
        self.assertEqual(git.head(self.tree), self.parent)
        self.assertNotIn('handoff_intent', self.task)
        self.assertIsNone(self.task['receipt'])

    def test_prepared_plan_already_covering_the_obligation_needs_no_token_edit(self):
        intended = (self.tree / self.plan).read_text()
        accepted = 'Implement behavior after declaring the interface; two child items own both obligations.\n'
        (self.repo / self.plan).write_text(accepted)
        current = support.commit(self.repo, 'Already-current approved plan')
        with self.assertRaisesRegex(ValueError, 'verify the original concern'):
            self.act()
        self.assertEqual((self.tree / self.plan).read_text(), accepted)
        result = self.act()  # Explicit handoff attests the prepared plan; no artificial file edit.
        self.assertEqual(result['children'], ['p:code', 'p:interface'])
        self.assertEqual(git.head(self.repo, 'main'), current)
        self.assertEqual((self.tree / self.plan).read_text(), accepted)
        self.assertEqual(git.show(self.tree, 'HEAD^1', self.plan), intended)

    def test_no_edit_handoff_saves_graph_and_receipt_without_artificial_product_versions(self):
        (self.tree / self.plan).write_text(git.show(self.repo, 'main', self.plan))
        observed = []
        save = handoffs.save
        def inspect():
            with state.LOCK:
                observed.append(lifecycle.recover_landings())
                self.assertEqual(self.task['status'], 'done')
                self.assertIn('p:code', state.L['queue'])
                self.assertNotIn('handoff_intent', self.task)
            save()
        with patch.object(handoffs, 'save', side_effect=inspect), patch.object(git, 'publish') as publish:
            self.act()
            publish.assert_not_called()
        self.assertEqual(observed, [0])
        self.assertEqual(git.head(self.repo, 'main'), self.parent)

    def crash_and_reload(self, phase):
        saved = []
        save, publish = handoffs.save, git.publish
        def persist():
            saved.append(copy.deepcopy(state.L))
            if phase == 'before-publication':
                raise Crash()
            if phase == 'before-settlement-save' and len(saved) == 2:
                saved.pop()  # The failed write cannot become recovered authority.
                raise Crash()
            save()
        def published(*args, **kwargs):
            result = publish(*args, **kwargs)
            if phase == 'after-publication':
                raise Crash()
            return result
        with patch.object(handoffs, 'save', side_effect=persist), patch.object(git, 'publish', side_effect=published):
            with self.assertRaises(Crash):
                self.act()
        self.assertEqual(state.ACTIVE['landings'], 0)
        self.saved_snapshot = copy.deepcopy(saved[-1])
        state.L.clear()
        state.L.update(state.fresh(saved[-1]))
        self.task = state.L['tasks'][self.task['id']]

    def check_recovery(self, phase):
        self.crash_and_reload(phase)
        self.assertNotIn('p:code', state.L['queue'])
        with state.LOCK:
            self.assertEqual(lifecycle.recover_landings(), 1)
            self.assertEqual(lifecycle.recover_landings(), 0)
        self.assertEqual(self.task['status'], 'done')
        self.assertEqual(self.task['receipt']['evidence']['handoff'], self.body['items'])
        self.assertEqual(state.L['queue']['p:code']['depends'], ['interface'])
        accepted = git.head(self.repo, 'main')
        self.assertEqual(self.act()['receipt'], self.task['receipt'])
        self.assertEqual(git.head(self.repo, 'main'), accepted)

    def test_crash_after_publication_recovers_before_adoption(self):
        self.check_recovery('after-publication')

    def test_crash_before_settlement_save_recovers_exact_children_and_receipt(self):
        self.check_recovery('before-settlement-save')

    def test_published_plan_recovers_without_the_old_workspace(self):
        self.crash_and_reload('after-publication')
        git.remove_worktree(self.repo, str(self.tree))
        with state.LOCK:
            self.assertEqual(lifecycle.recover_landings(), 1)
        self.assertEqual(self.task['status'], 'done')
        self.assertEqual(self.act()['receipt'], self.task['receipt'])

    def test_daemon_restores_published_graph_before_adopting_surviving_runs(self):
        self.crash_and_reload('after-publication')
        keyfile = self.repo.parent / 'keys.json'
        config.write_json(keyfile, {'coin': 'fixture-coin', 'agents': {'manager-1': 'fixture-manager'}})
        observed, saved = [], []
        def adopt(previous):
            observed.append(state.L['tasks'][self.task['id']]['status'])
            self.assertIn('p:code', state.L['queue'])
            self.assertEqual(saved[0]['tasks'][self.task['id']]['receipt']['disposition'], 'complete')
        with patch.object(daemon.keys, 'KEYS', keyfile), \
                patch.dict(daemon.keys.ISSUED, {}, clear=True), patch.dict(daemon.keys.OWNERS, {}, clear=True), \
                patch.object(daemon.startup, 'unit_witness', return_value={}), \
                patch.object(daemon.runs, 'adopt', side_effect=adopt), \
                patch.object(daemon.snapshots, 'recover_transfers'), \
                patch.object(daemon.snapshots, 'forget_orphans'), patch.object(daemon.snapshots, 'forget_untracked'), \
                patch.object(daemon, 'save', side_effect=lambda: saved.append(copy.deepcopy(state.L))):
            daemon.restore(self.saved_snapshot)
        self.assertEqual(observed, ['done'])

    def test_malformed_intent_refuses_before_any_authority_changes(self):
        self.crash_and_reload('before-publication')
        mutations = [lambda i: i.pop('records'), lambda i: i.update(commit='invalid'),
                     lambda i: i['before'].clear(), lambda i: i['records']['p:code'].update(project='foreign'),
                     lambda i: i.update(evidence=[])]
        for mutate in mutations:
            value = copy.deepcopy(state.L)
            mutate(value['tasks'][self.task['id']]['handoff_intent'])
            with self.assertRaises(ValueError):
                config.validate_ledger(value)
        self.assertEqual(git.head(self.repo, 'main'), self.parent)
        self.assertNotIn('p:code', state.L['queue'])

    def test_finish_captures_and_publishes_a_plan_without_an_extra_publish_step(self):
        body = {'caller': self.body['caller'], 'outcome': 'complete', 'detail': 'Planning concern is complete'}
        result = api.dispatch('finish', body)
        self.assertEqual(result['receipt']['evidence']['handoff'], [])
        self.assertEqual(git.show(self.repo, 'main', self.plan), (self.tree / self.plan).read_text())
        self.assertNotIn('p:code', state.L['queue'])
        self.assertEqual(api.dispatch('finish', body)['receipt'], result['receipt'])

    def test_unpublished_intent_does_not_create_children_and_can_retry(self):
        self.crash_and_reload('before-publication')
        self.assertEqual(git.head(self.repo, 'main'), self.parent)
        with state.LOCK:
            self.assertEqual(lifecycle.recover_landings(), 0)
        self.assertNotIn('p:code', state.L['queue'])
        self.act()
        self.assertEqual(self.task['status'], 'done')

    def test_user_hold_during_storage_revokes_publication(self):
        save = handoffs.save
        def held():
            with state.LOCK:
                state.L['queue'][self.task['record']]['held_by'] = 'user'
            save()
        with patch.object(handoffs, 'save', side_effect=held):
            with self.assertRaisesRegex(ValueError, 'held'):
                self.act()
        self.assertEqual(git.head(self.repo, 'main'), self.parent)
        self.assertNotIn('p:code', state.L['queue'])
        self.assertEqual(state.L['queue'][self.task['record']]['held_by'], 'user')
        self.assertIsNone(self.task['receipt'])

    def test_prerequisite_change_during_storage_revokes_publication(self):
        queues.add(self.project, 'queued', 'prerequisite', 'Build the prerequisite')
        self.body['items'][1]['dependencies'] = ['prerequisite']
        save = handoffs.save
        def changed():
            with state.LOCK:
                state.L['queue']['p:prerequisite']['depends'] = ['absent']
            save()
        with patch.object(handoffs, 'save', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'prerequisites changed'):
                self.act()
        self.assertEqual(git.head(self.repo, 'main'), self.parent)
        self.assertNotIn('p:code', state.L['queue'])
