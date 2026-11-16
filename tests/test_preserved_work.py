"""Split children inherit immutable authored files, never an instruction to recover Git state."""
import copy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from cointos import api, artifacts, config, frontier, git, lifecycle, opencode, prompts, queues, runs, state, tasks
from tests import support


class PreservedWork(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.enterContext(patch.object(opencode, 'active', return_value=False))
        self.repo = support.repository(self)
        (self.repo / 'old.c').write_text('original\n')
        (self.repo / 'gone.c').write_text('remove me\n')
        support.commit(self.repo)
        self.project = support.project(self, self.repo)
        self.worker = support.running(support.queued(self.project, 'whole'), 'original')
        self.tree = Path(self.worker['worktree'])
        (self.tree / 'old.c').write_text('staged\n')
        git.run(self.tree, 'add', 'old.c')
        (self.tree / 'old.c').write_text('latest unfinished\n')
        (self.tree / 'new.c').write_text('new unfinished\n')
        (self.tree / 'gone.c').unlink()
        self.splitter = tasks.request_supervisor(self.worker, 40000, must_split=True)
        support.running(self.splitter, 'splitter', worktree=False)
        self.body = {'caller': support.caller(self.splitter, 'splitter'),
                     'summary': 'Divide the remaining two obligations', 'items': [
                         {'name': 'first', 'summary': 'First obligation', 'brief': 'Finish behavior A.', 'dependencies': []},
                         {'name': 'second', 'summary': 'Second obligation', 'brief': 'Finish behavior B.', 'dependencies': ['first']}]}

    def handoff(self):
        return api.dispatch('handoff', self.body)

    def test_snapshot_and_child_launch_preserve_unstaged_staged_deleted_and_new_files(self):
        original = (git.head(self.tree), git.run(self.tree, 'diff', '--cached', '--binary'),
                    git.run(self.tree, 'diff', '--binary'))
        result = self.handoff()
        self.assertEqual(original, (git.head(self.tree), git.run(self.tree, 'diff', '--cached', '--binary'),
                                    git.run(self.tree, 'diff', '--binary')))
        children = []
        for name in ('first', 'second'):
            record = queues.records()['p:' + name]
            self.assertNotIn(str(self.tree), record['brief'])
            child = tasks.create('item', self.project, name, record['brief'], [4],
                                 item=name, record_version=record['version'])
            support.running(child, name, worktree=False)
            with patch.object(runs.opencode, 'launch', return_value=None):
                runs.launch(name, child, 'fixture-key')
            path = Path(child['worktree'])
            self.assertEqual((path / 'old.c').read_text(), 'latest unfinished\n')
            self.assertEqual((path / 'new.c').read_text(), 'new unfinished\n')
            self.assertFalse((path / 'gone.c').exists())
            self.assertFalse((path / '.git').exists())
            self.assertEqual(child['base_commit'], self.worker['base_commit'])
            shown = frontier.agent_view(frontier.inspect(child['id'], state.L), child)
            self.assertNotIn('preserved_artifact', str(shown))
            self.assertNotIn(record['preserved_artifact']['commit'], str(shown))
            children.append(path)
        (children[0] / 'new.c').write_text('first changes\n')
        self.assertEqual((children[1] / 'new.c').read_text(), 'new unfinished\n')
        self.assertEqual((self.tree / 'new.c').read_text(), 'new unfinished\n')
        shutil.rmtree(self.tree)
        with patch.object(artifacts, 'preserved', side_effect=AssertionError('replay recaptured old files')):
            self.assertEqual(self.handoff()['receipt'], result['receipt'])
        retained = config.validate_ledger(copy.deepcopy(state.L))
        self.assertEqual(retained['queue']['p:first']['preserved_artifact'],
                         retained['queue']['p:second']['preserved_artifact'])

    def test_held_or_changed_assignment_during_preparation_creates_no_children(self):
        preserve = artifacts.preserved
        def held(*args):
            result = preserve(*args)
            queues.records()[self.worker['record']]['held_by'] = 'user'
            return result
        with patch.object(artifacts, 'preserved', side_effect=held):
            with self.assertRaisesRegex(ValueError, 'assignment changed'):
                self.handoff()
        self.assertNotIn('p:first', queues.records())
        self.assertIsNone(self.splitter['receipt'])
        self.assertFalse(self.splitter.get('validating'))

    def test_running_old_author_must_end_before_capture(self):
        with patch.object(opencode, 'active', return_value=True):
            with self.assertRaisesRegex(ValueError, 'still stopping'):
                self.handoff()
        self.assertNotIn('p:first', queues.records())
        self.assertEqual((self.tree / 'old.c').read_text(), 'latest unfinished\n')

    def test_child_briefs_cannot_redirect_authors_into_the_old_workspace(self):
        for value in (str(self.tree), self.worker['branch']):
            with self.subTest(value=value):
                self.body['items'][0]['brief'] = 'Continue work only in ' + value
                with self.assertRaisesRegex(ValueError, 'own prepared files automatically'):
                    self.handoff()
                self.assertNotIn('p:first', queues.records())
                self.assertIsNone(self.splitter['receipt'])

    def test_source_drift_refuses_without_mutating_or_publishing_the_source(self):
        capture = artifacts.capture
        def changed(*args, **kwargs):
            result = capture(*args, **kwargs)
            (self.tree / 'new.c').write_text('newer author work\n')
            return result
        with patch.object(artifacts, 'capture', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed during preparation'):
                self.handoff()
        self.assertNotIn('p:first', queues.records())
        self.assertEqual((self.tree / 'new.c').read_text(), 'newer author work\n')

    def test_malformed_snapshot_identity_refuses_ledger_loading(self):
        self.handoff()
        malformed = copy.deepcopy(state.L)
        malformed['queue']['p:first']['preserved_artifact']['commit'] = 'arbitrary-path'
        with self.assertRaisesRegex(ValueError, 'preserved work artifact'):
            config.validate_ledger(malformed)

    def test_current_source_is_prepared_without_markers_and_prior_material_is_retained(self):
        (self.repo / 'old.c').write_text('current accepted behavior\n')
        support.commit(self.repo)
        (self.repo / 'editor-draft').write_text('preserve editor work\n')
        editor = git.run(self.repo, 'status', '--porcelain')
        remaining = artifacts.prepare_assignment(self.worker, self.project)
        self.assertEqual(remaining, ['old.c'])
        self.assertEqual((self.tree / 'old.c').read_text(), 'current accepted behavior\n')
        self.assertEqual((self.tree / 'new.c').read_text(), 'new unfinished\n')
        self.assertFalse((self.tree / 'gone.c').exists())
        self.assertTrue(git.clean(self.tree))
        self.assertEqual(git.show(self.tree, 'HEAD^1', 'old.c'), 'latest unfinished\n')
        self.assertEqual(git.run(self.repo, 'status', '--porcelain'), editor)
        self.worker.update(work_remaining=remaining, session='retained-session')
        launch = prompts.launch_text(self.worker, self.project)
        self.assertIn('Re-read cointos_task', launch)
        self.assertNotEqual(launch, 'Continue.')
        self.assertNotIn('merge', launch)

    def test_existing_unrelated_child_files_are_not_overwritten(self):
        self.handoff()
        record = queues.records()['p:first']
        child = tasks.create('item', self.project, 'first', record['brief'], [4],
                             item='first', record_version=record['version'])
        support.running(child, 'first')
        path = Path(child['worktree'])
        (path / 'unexpected').write_text('preserve me\n')
        with patch.object(runs.opencode, 'launch') as launch:
            with self.assertRaisesRegex(ValueError, 'do not contain the prepared work'):
                runs.launch('first', child, 'fixture-key')
        launch.assert_not_called()
        self.assertEqual((path / 'unexpected').read_text(), 'preserve me\n')

    def test_restart_can_launch_a_child_after_the_original_workspace_is_gone(self):
        self.handoff()
        retained = config.validate_ledger(copy.deepcopy(state.L))
        state.L.clear()
        state.L.update(state.fresh(retained))
        shutil.rmtree(self.tree)
        record = queues.records()['p:first']
        child = tasks.create('item', self.project, 'first', record['brief'], [4],
                             item='first', record_version=record['version'])
        support.running(child, 'first', worktree=False)
        with patch.object(runs.opencode, 'launch', return_value=None):
            runs.launch('first', child, 'fixture-key')
        self.assertEqual((Path(child['worktree']) / 'old.c').read_text(), 'latest unfinished\n')
