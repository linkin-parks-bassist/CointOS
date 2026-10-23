"""Independent boundary witnesses beyond the ordinary Operator handback matrix."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, git, lifecycle, queues, spawner, state, tasks
from tests import support
from tests import test_operator_handback as handback


class OperatorBoundaries(unittest.TestCase):
    # Reuse only the isolated API fixture and its constructors, not its tests.
    setUp = handback.OperatorHandback.setUp
    direct = handback.OperatorHandback.direct
    call = handback.OperatorHandback.call
    blocked = handback.OperatorHandback.blocked
    repair = handback.OperatorHandback.repair

    def test_project_operator_cannot_publish_product_or_tests_through_maintenance(self):
        self.project['test_policy'] = {'manifest': 'tests/contracts.json', 'protected': ['tests/**', 'Makefile'],
                                       'non_code': ['*.md', '.knowledge/**', 'tests/**', 'Makefile']}
        before = git.head(self.project['path'], 'main')
        for i, path in enumerate(('product.c', 'tests/witness.c', 'Makefile')):
            with self.subTest(path=path):
                operator, _ = tasks.request_repair(self.blocked('origin-' + str(i)))
                support.running(operator, 'repair-' + str(i))
                tree = Path(operator['worktree'])
                target = tree / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('diagnostic product or harness edit\n')
                candidate = support.commit(tree, 'diagnostic edits are not reviewed product work')
                with self.assertRaisesRegex(ValueError, 'independent review'):
                    self.call(operator, 'merge', commit=candidate)
                self.assertEqual(git.head(self.project['path'], 'main'), before)
                self.assertIsNone(operator['receipt'])
                self.assertEqual(git.head(tree), candidate, 'refusal preserves diagnostic artifacts')

    def test_project_operator_can_publish_declared_non_code_maintenance(self):
        self.project['test_policy'] = {'manifest': 'tests/contracts.json', 'protected': ['tests/**'],
                                       'non_code': ['*.md', '.knowledge/**']}
        operator = self.repair(self.blocked())
        tree = Path(operator['worktree'])
        (tree / 'diagnosis.md').write_text('Current verified maintenance guidance.\n')
        candidate = support.commit(tree, 'non-code maintenance')
        self.assertEqual(self.call(operator, 'merge', commit=candidate)['commit'], candidate)
        self.assertEqual(git.head(self.project['path'], 'main'), candidate)

    def test_maintenance_preflight_reports_uncommitted_product_and_protected_paths_without_mutation(self):
        self.project['test_policy'] = {'manifest': 'tests/contracts.json', 'protected': ['tests/**', 'Makefile'],
                                       'non_code': ['*.md', '.knowledge/**', 'tests/**', 'Makefile']}
        repo = Path(self.project['path'])
        for name in ('product.c', 'tests/witness.c', 'Makefile'):
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('baseline\n')
        support.commit(repo, 'existing product and protected harness')
        operator = self.repair(self.blocked())
        tree = Path(operator['worktree'])
        self.assertTrue(self.call(operator, 'check-work')['ok'])
        for mode in ('unstaged', 'staged', 'untracked'):
            names = ('new-product.c', 'tests/untracked.md', 'tests/extra/Makefile') if mode == 'untracked' else (
                'product.c', 'tests/witness.c', 'Makefile')
            for name in names:
                with self.subTest(mode=mode, path=name):
                    target = tree / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text('diagnostic change\n')
                    if mode == 'staged':
                        git.run(tree, 'add', name)
                    before = (git.head(tree), git.run(tree, 'status', '--porcelain'),
                              Path(git.run(tree, 'rev-parse', '--git-path', 'index')).read_bytes(),
                              git.run(tree, 'diff', '--cached'), target.read_bytes())
                    result = self.call(operator, 'check-work')
                    self.assertFalse(result['ok'])
                    self.assertIn(target.relative_to(tree).as_posix(), '\n'.join(result['problems']))
                    self.assertIn('independent review', '\n'.join(result['problems']))
                    self.assertEqual(before, (git.head(tree), git.run(tree, 'status', '--porcelain'),
                                     Path(git.run(tree, 'rev-parse', '--git-path', 'index')).read_bytes(),
                                     git.run(tree, 'diff', '--cached'), target.read_bytes()))
                    self.assertIsNone(operator['receipt'])
                    if mode == 'untracked':
                        target.unlink()
                    else:
                        git.run(tree, 'restore', '--staged', '--worktree', name)
        (tree / 'allowed.md').write_text('Allowed non-code maintenance.\n')
        self.assertTrue(self.call(operator, 'check-work')['ok'])

    def test_reverted_operator_product_edits_still_require_review(self):
        self.project['test_policy'] = {'manifest': 'tests/contracts.json', 'protected': ['tests/**'],
                                       'non_code': ['*.md', '.knowledge/**']}
        operator = self.repair(self.blocked())
        tree = Path(operator['worktree'])
        before = git.head(self.project['path'], 'main')
        target = tree / 'product.c'
        target.write_text('temporary diagnostic implementation\n')
        support.commit(tree, 'diagnostic product edit')
        target.unlink()
        candidate = support.commit(tree, 'revert diagnostic product edit')
        self.assertEqual(git.changed(tree, before, candidate), [])
        result = self.call(operator, 'check-work')
        self.assertFalse(result['ok'])
        self.assertIn('product.c', '\n'.join(result['problems']))
        with self.assertRaisesRegex(ValueError, 'independent review'):
            self.call(operator, 'merge', commit=candidate)
        self.assertEqual(git.head(self.project['path'], 'main'), before)

    def test_maintenance_cannot_publish_over_pending_canonical_knowledge(self):
        repo = Path(self.project['path'])
        name = '.knowledge/owned.md'
        original = '---\nstatus: green\nchecked_at: before\nexpires_every: 1d\n---\nAccepted answer.\n'
        canonical = repo / name
        canonical.write_text(original)
        support.commit(repo, 'accepted knowledge baseline')
        operator = self.repair(self.blocked())
        tree = Path(operator['worktree'])
        (tree / name).write_text(original.replace('Accepted answer.', 'Reviewed branch correction.'))
        candidate = support.commit(tree, 'bounded knowledge maintenance')
        main = git.head(repo, 'main')
        for mode in ('unstaged', 'staged-only', 'deleted', 'policy'):
            with self.subTest(mode=mode):
                if mode == 'deleted':
                    canonical.unlink()
                elif mode == 'policy':
                    canonical.write_text(original.replace('expires_every: 1d', 'expires_every: 2d'))
                else:
                    canonical.write_text(original.replace('Accepted answer.', 'Pending owner answer.'))
                    if mode == 'staged-only':
                        git.run(repo, 'add', name)
                        canonical.write_text(original)
                before = ((repo / '.git/index').read_bytes(), canonical.read_bytes() if canonical.exists() else None)
                checked = self.call(operator, 'check-work')
                self.assertFalse(checked['ok'])
                self.assertIn('pending canonical knowledge', '\n'.join(checked['problems']))
                with self.assertRaisesRegex(ValueError, 'pending canonical knowledge'):
                    self.call(operator, 'merge', commit=candidate)
                self.assertEqual(git.head(repo, 'main'), main)
                self.assertEqual(git.head(tree), candidate)
                self.assertEqual(before, ((repo / '.git/index').read_bytes(),
                    canonical.read_bytes() if canonical.exists() else None))
                self.assertIsNone(operator['receipt'])
                git.run(repo, 'restore', '--staged', '--worktree', name)
        canonical.write_text(original.replace('status: green', 'status: yellow').replace('checked_at: before', 'checked_at: after'))
        self.assertTrue(self.call(operator, 'check-work')['ok'])
        self.assertEqual(self.call(operator, 'merge', commit=candidate)['commit'], candidate)

    def test_new_maintenance_answer_preserves_an_untracked_canonical_owner(self):
        operator = self.repair(self.blocked())
        tree = Path(operator['worktree'])
        name = '.knowledge/new.md'
        (tree / name).write_text('Branch answer.\n')
        candidate = support.commit(tree, 'new knowledge answer')
        canonical = Path(self.project['path']) / name
        canonical.write_text('Pending owner answer.\n')
        main = git.head(self.project['path'], 'main')
        with self.assertRaisesRegex(ValueError, 'pending canonical knowledge'):
            self.call(operator, 'merge', commit=candidate)
        self.assertEqual(canonical.read_text(), 'Pending owner answer.\n')
        self.assertEqual(git.head(self.project['path'], 'main'), main)

    def test_existing_work_needs_explicit_origin_handoff_without_duplicate_queueing(self):
        source = self.blocked()
        operator = self.repair(source)
        existing = support.queued(self.project, 'existing', 'Preserved implementation')
        self.call(operator, 'revise', item=existing['record'], brief='Continue the preserved implementation',
                  summary='Continue the existing preserved implementation work',
                  reason='The existing item owns the next step')
        with self.assertRaises(ValueError) as refused:
            self.call(operator, 'finish', outcome='complete', detail='Another item was revised')
        self.assertIn(source['record'], str(refused.exception))
        self.assertIn('cointos_replace', str(refused.exception))
        before = set(state.L['queue'])
        result = self.call(operator, 'replace', children=[existing['item']])
        self.assertEqual(set(state.L['queue']), before)
        self.assertEqual(state.L['queue'][source['record']]['replaced_by'], [existing['item']])
        self.assertEqual(result['receipt']['evidence']['repaired_record'], source['record'])
        self.assertIsNone(source.get('acceptance'))
        self.assertIsNone(existing.get('acceptance'))

    def test_changed_origin_cannot_hand_back_to_an_exhausted_corrective_prerequisite(self):
        source = self.blocked()
        operator = self.repair(source)
        corrective = support.running(support.queued(self.project, 'corrective', 'Correct the verified obstruction',
                                                    kind='command'), 'corrective-run')
        self.call(corrective, 'finish', outcome='blocked', detail='The corrective prerequisite cannot continue')
        lifecycle.release('corrective-run', 'fixture completion delivered')
        failed_repair, _ = tasks.request_repair(corrective)
        lifecycle.fail(failed_repair, 'Recovery exhausted without a continuation')
        self.call(operator, 'revise', item=source['id'], brief='Use correction\nDepends on: corrective',
                  reason='Repointed the original to a corrective prerequisite')
        readiness = queues.readiness(queues.live('p'), queues.landed('p'))
        self.assertEqual(readiness['origin'], 'depends on a blocked item: corrective')
        with self.assertRaisesRegex(ValueError, 'handback|dependenc|prerequisite|blocked'):
            self.call(operator, 'finish', outcome='complete', detail='The correction is still blocked')
        self.assertIsNone(operator['receipt'])

    def test_running_repair_cannot_queue_more_work_after_user_withdraws_origin(self):
        source = self.blocked()
        operator = self.repair(source)
        api.dispatch('cancel', {'items': [source['id']], 'reason': 'User withdrew the requested work'})
        self.assertNotIn(source['record'], state.L['queue'])
        with self.assertRaisesRegex(ValueError, 'repair|scope|withdraw|owning|Operator'):
            self.call(operator, 'queue', project='p', name='resurrect', kind='command',
                      brief='Continue the withdrawn obstruction anyway')
        self.assertNotIn('p:resurrect', state.L['queue'])
        result = self.call(operator, 'finish', outcome='complete', detail='The user withdrew the origin; no work was resurrected')
        self.assertEqual(result['receipt']['evidence']['withdrawn_record'], source['record'])
        self.assertNotIn(source['record'], state.L['queue'])
        self.assertIsNone(source.get('acceptance'))

    def test_withdrawal_handback_still_requires_operator_changes_committed_and_landed(self):
        source = self.blocked()
        operator = self.repair(source)
        (Path(operator['worktree']) / 'repair-note.txt').write_text('Verified the abandoned obstruction.\n')
        api.dispatch('cancel', {'items': [source['id']], 'reason': 'User withdrew the work'})
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            self.call(operator, 'finish', outcome='complete', detail='Handing back the withdrawn assignment')
        commit = support.commit(operator['worktree'], 'checked repair note')
        with self.assertRaisesRegex(ValueError, 'land|merge'):
            self.call(operator, 'finish', outcome='complete', detail='Handing back the withdrawn assignment')
        git.publish(self.project['path'], 'main', commit, git.head(self.project['path'], 'main'))
        result = self.call(operator, 'finish', outcome='complete', detail='The retained repair note is committed and landed')
        self.assertEqual(result['receipt']['evidence']['commit'], commit)
        self.assertEqual(result['receipt']['evidence']['withdrawn_record'], source['record'])
        self.assertNotIn(source['record'], state.L['queue'])

    def test_replacement_child_itself_terminally_blocked_cannot_prove_handback(self):
        source = self.blocked()
        operator = self.repair(source)
        self.call(operator, 'queue', project='p', name='replacement', kind='command', brief='Corrective stage')
        self.call(operator, 'supersede', task=source['id'], replacements=['replacement'], reason='Use corrective stage')
        record = state.L['queue']['p:replacement']
        replacement = tasks.create('breakdown', self.project, 'replacement', record['brief'], [5],
                                   item='replacement', record_version=record['version'])
        support.running(replacement, 'replacement-run')
        self.call(replacement, 'finish', outcome='blocked', detail='This replacement cannot proceed')
        lifecycle.release('replacement-run', 'fixture completion delivered')
        failed_repair, _ = tasks.request_repair(replacement)
        lifecycle.fail(failed_repair, 'Recovery exhausted without a continuation')
        self.assertEqual(queues.readiness(queues.live('p'), queues.landed('p'))['replacement'], 'ready')
        self.assertEqual(queues.status(record), 'blocked')
        with self.assertRaisesRegex(ValueError, 'handback|dependenc|prerequisite|blocked'):
            self.call(operator, 'finish', outcome='complete', detail='Replacement exists but has no continuation')

    def test_recoverable_prerequisite_is_a_valid_pending_handback(self):
        source = self.blocked()
        operator = self.repair(source)
        corrective = support.queued(self.project, 'corrective', 'Implement the bounded correction')
        lifecycle.fail(corrective, 'Worker needs its recovery controller')
        self.assertTrue(queues.state(state.L['queue'][corrective['record']])['recoverable'])
        self.call(operator, 'revise', item=source['id'], brief='Use correction\nDepends on: corrective',
                  reason='Its recovery controller can continue the corrective prerequisite')
        self.assertEqual(queues.readiness(queues.live('p'), queues.landed('p'))['origin'], 'waiting')
        result = self.call(operator, 'finish', outcome='complete', detail='The corrective prerequisite has its recovery controller')
        self.assertEqual(result['receipt']['evidence']['repaired_record'], source['record'])
        self.assertNotIn('origin', queues.landed('p'))

    def test_active_corrective_worker_is_a_valid_pending_handback(self):
        source = self.blocked()
        operator = self.repair(source)
        corrective = support.running(support.queued(self.project, 'corrective', 'Implement the bounded correction'),
                                     'corrective-run')
        self.call(operator, 'revise', item=source['id'], brief='Use correction\nDepends on: corrective',
                  reason='The verified corrective worker is already active')
        result = self.call(operator, 'finish', outcome='complete', detail='The corrected origin waits on the active worker')
        self.assertEqual(result['receipt']['evidence']['repaired_record'], source['record'])
        self.assertEqual(corrective['status'], 'running')
        self.assertIsNone(corrective.get('acceptance'))
        self.assertNotIn('origin', queues.landed('p'))

    def maintenance(self, kind='steward', place=None, outcome='blocked', run='maintenance-run'):
        task = tasks.create(kind, place or tasks.SYSTEM, 'inspect', 'Inspect the original obstruction', [6])
        support.running(task, run)
        if kind == 'steward' and outcome == 'complete':
            support.review_frontier(task)
        self.call(task, 'finish', outcome=outcome, detail='Checked maintenance result: ' + outcome,
                  scout_result={'kind': 'no_action', 'checked_projects': ['p', 'q']})
        lifecycle.release(run, 'fixture completion delivered')
        return task

    def test_latest_successful_maintenance_supersedes_started_repair_origin(self):
        source = self.maintenance(run='old-run')
        operator = self.repair(source)
        latest = self.maintenance(outcome='complete', run='latest-run')
        result = self.call(operator, 'finish', outcome='complete', detail='The latest checked maintenance resolved the old episode')
        self.assertEqual(result['receipt']['evidence']['superseding_task'], latest['id'])
        self.assertEqual(result['receipt']['evidence']['receipt'], latest['receipt'])
        self.assertEqual(source['receipt']['disposition'], 'blocked')

    def test_newer_failed_maintenance_does_not_prove_old_repair_complete(self):
        source = self.maintenance(run='old-run')
        operator = self.repair(source)
        self.maintenance(run='latest-run')
        with self.assertRaisesRegex(ValueError, 'checked handback'):
            self.call(operator, 'finish', outcome='complete', detail='A newer attempt also remained blocked')

    def test_intermediate_success_cannot_hide_latest_blocked_maintenance(self):
        source = self.maintenance(run='old-run')
        operator = self.repair(source)
        self.maintenance(outcome='complete', run='intermediate-run')
        self.maintenance(run='latest-run')
        with self.assertRaisesRegex(ValueError, 'checked handback'):
            self.call(operator, 'finish', outcome='complete', detail='An older success cannot settle the current failure')

    def test_success_in_other_kind_or_place_does_not_supersede_origin(self):
        source = self.maintenance(run='old-run')
        operator = self.repair(source)
        self.maintenance(kind='test-audit', outcome='complete', run='different-kind-run')
        self.maintenance(place=self.other, outcome='complete', run='different-place-run')
        with self.assertRaisesRegex(ValueError, 'checked handback'):
            self.call(operator, 'finish', outcome='complete', detail='Unrelated maintenance passed')

    def test_interrupted_started_repair_can_resume_withdrawn_origin_handback(self):
        source = self.blocked()
        operator = self.repair(source)
        api.dispatch('cancel', {'items': [source['id']], 'reason': 'User withdrew the assignment'})
        previous = json.loads(json.dumps(state.L))
        state.L.clear()
        state.L.update(state.fresh(previous))
        operator = state.L['tasks'][operator['id']]
        lifecycle.orphaned(operator)
        self.assertTrue(spawner.runnable(operator, {}))
        support.running(operator, 'resumed-repair-run')
        result = self.call(operator, 'finish', outcome='complete', detail='The withdrawn origin remains withdrawn after replacement')
        self.assertEqual(result['receipt']['evidence']['withdrawn_record'], source['record'])
        self.assertNotIn(source['record'], state.L['queue'])

    def test_newer_garden_receipt_cannot_bypass_original_selected_leaf_health(self):
        source = tasks.create('garden', tasks.SYSTEM, 'garden', 'what/is/original.md', [6])
        support.running(source, 'old-garden-run')
        self.call(source, 'finish', outcome='blocked', detail='The originally selected leaf remains unresolved')
        lifecycle.release('old-garden-run', 'fixture completion delivered')
        operator = self.repair(source)
        newer = tasks.create('garden', tasks.SYSTEM, 'garden', 'what/is/different.md', [6])
        support.running(newer, 'new-garden-run')
        checked = {'brown': [], 'yellow': [], 'unresolved': []}
        with patch.object(lifecycle, 'garden_health', return_value=checked):
            self.call(newer, 'finish', outcome='complete', detail='Only the newer selected leaf was checked')
        lifecycle.release('new-garden-run', 'fixture completion delivered')
        unresolved = {'brown': ['what/is/original.md'], 'yellow': [], 'unresolved': ['what/is/original.md']}
        with patch.object(lifecycle, 'garden_health', return_value=unresolved) as health:
            with self.assertRaisesRegex(ValueError, 'checked handback'):
                self.call(operator, 'finish', outcome='complete', detail='A different garden completed')
            health.assert_called_once_with(source)
        self.assertIsNone(operator['receipt'])
        with patch.object(lifecycle, 'garden_health', return_value=checked) as health:
            result = self.call(operator, 'finish', outcome='complete', detail='The original selected leaf is now checked too')
            health.assert_called_once_with(source)
        self.assertEqual(result['receipt']['evidence']['unresolved'], [])
        self.assertNotIn('superseding_task', result['receipt']['evidence'])


if __name__ == '__main__':
    unittest.main()

