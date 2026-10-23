"""Run admission preserves ownership and historical artifacts before any native launch."""
import copy
import json
import os
import threading
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from cointos import keys, lifecycle, opencode, runs, state, tasks
from tests import support

NativeThread = threading.Thread


class Admission(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.enterContext(patch.dict(state.CONFIG, projects=[]))
        self.enterContext(patch.object(state.journal, 'write'))
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directories = self.root / 'agents'
        self.directories.mkdir()
        self.enterContext(patch.object(opencode, 'run_dir', side_effect=lambda agent: self.directories / agent))
        self.enterContext(patch.object(keys, 'KEYS', self.root / 'keys.json'))
        self.enterContext(patch.dict(keys.OWNERS, {}, clear=True))
        self.enterContext(patch.dict(keys.ISSUED, {}, clear=True))
        ended = set(keys.ENDED)
        keys.ENDED.clear()
        self.addCleanup(lambda: (keys.ENDED.clear(), keys.ENDED.update(ended)))
        self.task = tasks.create('steward', tasks.SYSTEM, 'inspect-admission', 'Inspect admission', [6])

    def snapshot(self):
        return copy.deepcopy((state.L, keys.OWNERS, keys.ISSUED, keys.ENDED))

    def test_start_owns_a_reentrant_lock_and_reserves_all_existing_run_identities(self):
        # A run released from the ledger, a durable ghost, and an existing directory
        # all remain unavailable identities, even without a currently active unit.
        state.L['agents']['steward-live'] = {'id': 'steward-live', 'task': 'other'}
        state.L['exiting']['steward-released'] = state.now()
        keys.adopt('steward-issued', 'background', 'issued-key')
        keys.KEYS.write_text(json.dumps({'agents': {'steward-durable': 'durable-key'}}))
        history = self.directories / 'steward-history'
        history.mkdir()
        (history / 'run.json').write_bytes(b'historical run bytes')
        nonces = iter(['live', 'released', 'issued', 'durable', 'history', 'fresh'])

        def issue(agent, klass):
            self.assertTrue(state.LOCK._is_owned(), 'start must hold its own ledger lock')
            return original_issue(agent, klass)

        original_issue = keys.issue
        with patch.object(runs.secrets, 'token_hex', side_effect=lambda *args: next(nonces)), \
                patch.object(keys, 'issue', side_effect=issue), patch.object(runs.threading, 'Thread') as thread:
            agent = runs.start(self.task)  # direct call must acquire LOCK
            self.assertEqual(agent, 'steward-fresh')
            self.assertEqual((history / 'run.json').read_bytes(), b'historical run bytes')
            self.assertTrue((self.directories / agent).is_dir())
            self.assertEqual(thread.call_count, 1)
            other = tasks.create('steward', tasks.SYSTEM, 'another-admission', 'Inspect again', [6])
            with state.LOCK, patch.object(runs.secrets, 'token_hex', return_value='reentrant'):
                runs.start(other)

    def test_invalid_task_or_run_alias_admission_has_no_effects(self):
        for condition in ('not-waiting', 'held', 'duplicate-task', 'active-alias', 'exiting-alias'):
            with self.subTest(condition=condition):
                self.task.update(status='waiting', admission_hold=None)
                state.L['agents'].clear()
                state.L['exiting'].clear()
                if condition == 'not-waiting':
                    self.task['status'] = 'done'
                elif condition == 'held':
                    self.task['admission_hold'] = 'user hold'
                elif condition == 'duplicate-task':
                    state.L['agents']['other-run'] = {'task': self.task['id']}
                elif condition == 'active-alias':
                    state.L['agents']['claimed-run'] = {'task': 'another-task'}
                else:
                    state.L['exiting']['claimed-run'] = state.now()
                before = self.snapshot()
                with state.LOCK, self.assertRaises(ValueError):
                    lifecycle.start(self.task, 'claimed-run')
                self.assertEqual(self.snapshot(), before)

    def test_key_persistence_failure_preserves_exact_ledger_and_key_ownership(self):
        before = self.snapshot()
        keys.KEYS.write_bytes(b'{"agents":{}}')
        with patch.object(keys, 'write_json', side_effect=OSError('key persistence failed')), \
                patch.object(runs.threading, 'Thread') as thread:
            with self.assertRaisesRegex(OSError, 'key persistence failed'):
                runs.start(self.task)
            thread.return_value.start.assert_called_once()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(keys.KEYS.read_bytes(), b'{"agents":{}}')

    def test_invalid_key_registry_never_replaces_historical_bytes_or_memory(self):
        corrupt = [b'{"coin":"prior-coin","agents":{"prior-run":"prior-key"}', b'[]',
                   b'{"coin":"prior-coin","agents":[]}',
                   b'{"coin":"prior-coin","agents":{"prior-run":17}}',
                   b'{"coin":17,"agents":{"prior-run":"prior-key"}}']
        keys.adopt('prior-run', 'background', 'prior-key')
        keys.OWNERS['prior-coin'] = ('coin', 'coin')
        for raw in corrupt:
            for action in ('load', 'recorded', 'issue', 'start'):
                with self.subTest(raw=raw, action=action):
                    keys.KEYS.write_bytes(raw)
                    before = self.snapshot()
                    with self.assertRaises((ValueError, TypeError)):
                        {'load': keys.load, 'recorded': keys.recorded, 'issue': lambda: keys.issue('new-run', 'background'),
                         'start': lambda: runs.start(self.task)}[action]()
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(keys.KEYS.read_bytes(), raw)

    def test_key_registry_read_denial_is_not_an_empty_registry(self):
        raw = b'{"coin":"prior-coin","agents":{"prior-run":"prior-key"}}'
        keys.KEYS.write_bytes(raw)
        keys.adopt('prior-run', 'background', 'prior-key')
        keys.OWNERS['prior-coin'] = ('coin', 'coin')
        opened = os.open

        def denied(path, *args, **kwargs):
            if path == keys.KEYS:
                raise PermissionError('fixture key registry read denied')
            return opened(path, *args, **kwargs)

        for action in ('load', 'recorded', 'issue', 'start'):
            with self.subTest(action=action):
                before = self.snapshot()
                with patch.object(os, 'open', denied), self.assertRaises(PermissionError):
                    {'load': keys.load, 'recorded': keys.recorded, 'issue': lambda: keys.issue('new-run', 'background'),
                         'start': lambda: runs.start(self.task)}[action]()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(keys.KEYS.read_bytes(), raw)

    def test_logging_failure_after_registration_cannot_orphan_its_started_follower(self):
        entered, finished = threading.Event(), threading.Event()
        threads = []

        def thread_factory(*, target, args, daemon):
            def controlled():
                entered.set()
                try:
                    target(*args)
                finally:
                    finished.set()
            native = NativeThread(target=controlled, daemon=daemon)
            threads.append(native)
            return native

        def failed_log(*args, **kwargs):
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.task['status'], 'running')
            self.assertIn(self.task['agent'], state.L['agents'])
            self.assertIn(self.task['agent'], keys.ISSUED)
            raise RuntimeError('fixture log failed after admission')

        with patch.object(runs.threading, 'Thread', side_effect=thread_factory), \
                patch.object(runs, 'log', side_effect=failed_log), patch.object(runs, 'launch') as launch, \
                patch.object(opencode, 'watch', side_effect=runs.Ended), patch.object(opencode, 'stop'):
            with self.assertRaisesRegex(RuntimeError, 'log failed after admission'):
                runs.start(self.task)
            self.assertTrue(finished.wait(2))
            for native in threads:
                native.join(2)
                self.assertFalse(native.is_alive())
            launch.assert_called_once()
            agent, current, key = launch.call_args.args
            self.assertTrue(lifecycle.owns(self.task, agent))
            self.assertEqual(current['agent'], agent)
            self.assertEqual(key, keys.ISSUED[agent])

    def test_issued_key_resamples_every_persisted_memory_and_ended_identity(self):
        keys.KEYS.write_text(json.dumps({'coin': 'coin-key', 'agents': {'ghost-run': 'ghost-key'}}))
        keys.OWNERS['owner-only-key'] = ('owner-only', 'background')
        keys.ISSUED['issued-only'] = 'issued-only-key'
        keys.ENDED.add('ended-key')
        candidates = iter(['coin-key', 'ghost-key', 'owner-only-key', 'issued-only-key', 'ended-key', 'fresh-key'])
        with patch.object(keys.secrets, 'token_urlsafe', side_effect=lambda *args: next(candidates)):
            issued = keys.issue('fresh-run', 'background')
        self.assertEqual(issued, 'fresh-key')
        self.assertEqual(keys.stored(), {'coin': 'coin-key', 'agents': {'ghost-run': 'ghost-key', 'fresh-run': 'fresh-key'}})
        self.assertEqual(keys.owner('fresh-key'), ('fresh-run', 'background'))
        self.assertEqual(keys.OWNERS['owner-only-key'], ('owner-only', 'background'))
        self.assertIn('ended-key', keys.ENDED)

    def test_new_coin_key_bootstraps_absence_without_aliasing_live_or_ended_identities(self):
        self.assertFalse(keys.KEYS.exists())
        keys.OWNERS['ghost-key'] = ('ghost-run', 'background')
        keys.OWNERS['owner-only-key'] = ('owner-only', 'background')
        keys.ISSUED['issued-only'] = 'issued-only-key'
        keys.ENDED.add('ended-key')
        candidates = iter(['ghost-key', 'owner-only-key', 'issued-only-key', 'ended-key', 'fresh-coin-key'])
        with patch.object(keys.secrets, 'token_urlsafe', side_effect=lambda *args: next(candidates)):
            keys.load()
        self.assertEqual(keys.stored(), {'coin': 'fresh-coin-key'})
        self.assertEqual(keys.owner('fresh-coin-key'), ('coin', 'coin'))
        self.assertEqual(keys.OWNERS['ghost-key'], ('ghost-run', 'background'))
        self.assertEqual(keys.ISSUED['issued-only'], 'issued-only-key')
        self.assertIn('ended-key', keys.ENDED)

    def test_existing_keyless_registry_cannot_initialize_fixed_coin_identity(self):
        for raw in (b'{}', b'{"agents":{}}', b'{"agents":{"ghost-run":"ghost-key"}}'):
            with self.subTest(raw=raw):
                keys.KEYS.write_bytes(raw)
                before = self.snapshot()
                with patch.object(keys.secrets, 'token_urlsafe') as allocate, \
                        patch.object(keys, 'write_json') as persist, \
                        self.assertRaisesRegex(ValueError, 'missing fixed Coin identity'):
                    keys.load()
                allocate.assert_not_called()
                persist.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(keys.KEYS.read_bytes(), raw)

    def test_issue_refuses_existing_actor_instead_of_rotating_its_identity(self):
        raw = b'{"coin":"coin-key","agents":{"ghost-run":"ghost-key"}}'
        keys.KEYS.write_bytes(raw)
        keys.adopt('live-run', 'background', 'live-key')
        for actor, klass in [('ghost-run', 'background'), ('live-run', 'background'), ('coin', 'coin'), ('fresh-as-coin', 'coin')]:
            with self.subTest(actor=actor):
                before = self.snapshot()
                with patch.object(keys, 'write_json') as persist, self.assertRaises(ValueError):
                    keys.issue(actor, klass)
                persist.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(keys.KEYS.read_bytes(), raw)

    def test_adoption_is_idempotent_only_for_the_same_actor_class_and_key(self):
        keys.adopt('live-run', 'background', 'live-key')
        keys.OWNERS['coin-key'] = ('coin', 'coin')
        keys.ENDED.add('ended-key')
        before = self.snapshot()
        keys.adopt('live-run', 'background', 'live-key')
        self.assertEqual(self.snapshot(), before)
        conflicting = [('other-run', 'background', 'live-key'), ('live-run', 'background', 'new-key'),
                       ('live-run', 'user', 'live-key'), ('new-run', 'background', 'ended-key'),
                       ('new-run', 'background', 'coin-key'), ('coin', 'background', 'unused-key'),
                       ('new-run', 'coin', 'unused-key'), ('coin', 'coin', 'unused-key')]
        for actor, klass, key in conflicting:
            with self.subTest(actor=actor, klass=klass, key=key):
                with self.assertRaises(ValueError):
                    keys.adopt(actor, klass, key)
                self.assertEqual(self.snapshot(), before)

    def test_duplicate_persisted_key_ownership_is_refused_without_rewriting_history(self):
        ambiguous = [b'{"coin":"shared-key","agents":{"run":"shared-key"}}',
                     b'{"coin":"coin-key","agents":{"one":"shared-key","two":"shared-key"}}',
                     b'{"coin":"first-coin","coin":"second-coin","agents":{}}',
                     b'{"coin":"coin-key","agents":{"first":"one-key"},"agents":{"second":"two-key"}}',
                     b'{"coin":"coin-key","agents":{"run":"old-key","run":"new-key"}}']
        for raw in ambiguous:
            with self.subTest(raw=raw):
                keys.KEYS.write_bytes(raw)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    keys.stored()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(keys.KEYS.read_bytes(), raw)

    def test_key_is_persisted_before_it_becomes_a_gateway_identity(self):
        original_write = keys.write_json
        published = []

        def persist(path, stored, **options):
            agent, key = next(iter(stored['agents'].items()))
            self.assertNotIn(agent, keys.ISSUED)
            self.assertNotIn(key, keys.OWNERS)
            original_write(path, stored, **options)
            published.append((agent, key))

        with patch.object(keys, 'write_json', side_effect=persist):
            key = keys.issue('durable-first', 'background')
        self.assertEqual(published, [('durable-first', key)])
        self.assertEqual(keys.recorded()['durable-first'], key)
        self.assertEqual(keys.owner(key), ('durable-first', 'background'))

    def test_thread_start_failure_occurs_before_key_persistence_or_registration(self):
        before = self.snapshot()
        with patch.object(runs.threading, 'Thread') as thread, patch.object(keys, 'issue') as issue:
            thread.return_value.start.side_effect = RuntimeError('cannot start follower')
            with self.assertRaisesRegex(RuntimeError, 'cannot start follower'):
                runs.start(self.task)
            issue.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(keys.KEYS.exists())

    def test_directory_or_recorded_key_read_failure_precedes_any_registration(self):
        for boundary in ('mkdir', 'recorded'):
            with self.subTest(boundary=boundary):
                before = self.snapshot()
                target = Path if boundary == 'mkdir' else keys
                method = 'mkdir' if boundary == 'mkdir' else 'recorded'
                with patch.object(target, method, side_effect=OSError('fixture admission filesystem failure')), \
                        patch.object(keys, 'issue') as issue, patch.object(runs.threading, 'Thread') as thread:
                    with self.assertRaisesRegex(OSError, 'admission filesystem failure'):
                        runs.start(self.task)
                    issue.assert_not_called()
                    thread.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def test_real_follower_waits_for_registration_and_failed_keys_never_launch_or_stop(self):
        for fail_keys in (False, True):
            with self.subTest(fail_keys=fail_keys):
                task = tasks.create('steward', tasks.SYSTEM, 'thread-' + str(fail_keys), 'Inspect follower', [6])
                entered = threading.Event()
                finished = threading.Event()
                threads = []
                original_issue = keys.issue

                def thread_factory(*, target, args, daemon):
                    def controlled():
                        entered.set()
                        try:
                            target(*args)
                        finally:
                            finished.set()
                    native = NativeThread(target=controlled, daemon=daemon)
                    threads.append(native)
                    return native

                def issue(agent, klass):
                    self.assertTrue(entered.wait(2), 'real follower must start before persistence')
                    launch.assert_not_called()
                    self.assertEqual(task['status'], 'waiting')
                    self.assertNotIn(agent, state.L['agents'])
                    if fail_keys:
                        raise OSError('fixture key write failed')
                    return original_issue(agent, klass)

                with patch.object(runs.threading, 'Thread', side_effect=thread_factory), \
                        patch.object(keys, 'issue', side_effect=issue), patch.object(runs, 'launch') as launch, \
                        patch.object(opencode, 'watch', side_effect=runs.Ended), patch.object(opencode, 'stop') as stop:
                    if fail_keys:
                        with self.assertRaises(OSError):
                            runs.start(task)
                    else:
                        runs.start(task)
                    self.assertTrue(finished.wait(2), 'follower must release after admission resolves')
                    for native in threads:
                        native.join(2)
                        self.assertFalse(native.is_alive())
                    if fail_keys:
                        launch.assert_not_called()
                        stop.assert_not_called()
                    else:
                        launch.assert_called_once()
                        agent, fresh, key = launch.call_args.args
                        self.assertEqual(fresh['agent'], agent)
                        self.assertEqual(key, keys.ISSUED[agent])
                        stop.assert_called_once_with(agent)

    def test_fresh_follow_uses_current_task_and_key_and_unregistered_follow_is_inert(self):
        support.running(self.task, 'fresh-run')
        keys.adopt('fresh-run', 'background', 'registered-key')
        stale = dict(self.task, brief='stale brief')
        self.task['brief'] = 'current corrected brief'
        with patch.object(runs, 'launch') as launch, patch.object(opencode, 'watch', side_effect=runs.Ended), \
                patch.object(opencode, 'stop') as stop:
            runs.follow('fresh-run', stale, 'stale-key')
            self.assertEqual(launch.call_args.args[1]['brief'], 'current corrected brief')
            self.assertEqual(launch.call_args.args[2], 'registered-key')
            launch.reset_mock()
            stop.reset_mock()
            runs.follow('unregistered-run', stale, 'unregistered-key')
            launch.assert_not_called()
            stop.assert_not_called()

    def test_adoption_orphans_a_legacy_displaced_task_without_changing_surviving_run(self):
        displaced = support.running(self.task, 'legacy-displaced')
        displaced['session'] = 'displaced-session'
        survivor = tasks.create('steward', tasks.SYSTEM, 'surviving-admission', 'Inspect survivor', [6])
        support.running(survivor, 'legacy-shared')
        survivor['session'] = state.L['agents']['legacy-shared']['session'] = 'surviving-session'
        key = keys.issue('legacy-shared', 'background')
        # Reconstruct the old collision rather than weakening today's admission guard.
        state.L['agents'].pop('legacy-displaced')
        displaced['agent'] = 'legacy-shared'
        previous = copy.deepcopy({'agents': state.L['agents']})
        before_runs = (displaced['runs'], survivor['runs'])
        state.L['agents'].clear()
        keys.OWNERS.clear()
        keys.ISSUED.clear()
        with state.LOCK, patch.object(opencode, 'active', return_value=True), \
                patch.object(opencode, 'find_processes', return_value={'legacy-shared': [123]}), \
                patch.object(opencode, 'stop_group') as stop, patch.object(runs.threading, 'Thread') as thread:
            runs.adopt(previous)
            stop.assert_not_called()
            thread.assert_called_once_with(target=runs.follow, args=('legacy-shared', None, None), daemon=True)
        self.assertEqual((displaced['status'], displaced['agent'], displaced['session']),
                         ('waiting', None, 'displaced-session'))
        self.assertEqual((survivor['status'], survivor['agent'], survivor['session']),
                         ('running', 'legacy-shared', 'surviving-session'))
        self.assertEqual(state.L['agents']['legacy-shared']['task'], survivor['id'])
        self.assertEqual(state.L['agents']['legacy-shared']['session'], 'surviving-session')
        self.assertEqual((displaced['runs'], survivor['runs']), before_runs)
        self.assertEqual(keys.recorded()['legacy-shared'], key)
        self.assertEqual(keys.owner(key), ('legacy-shared', 'background'))

    def test_adoption_follows_a_live_receipted_survivor_without_relaunching_it(self):
        support.running(self.task, 'receipted-survivor')
        self.task['session'] = state.L['agents']['receipted-survivor']['session'] = 'receipted-session'
        support.review_frontier(self.task)
        key = keys.issue('receipted-survivor', 'background')
        receipt = lifecycle.submit(self.task['id'], 'receipted-survivor', 'complete', 'Inspection complete',
                                   {'scout_result': {'kind': 'no_action',
                                                     'checked_projects': [p['name'] for p in tasks.enabled_projects()]}})
        previous = copy.deepcopy({'agents': state.L['agents']})
        state.L['agents'].clear()
        keys.OWNERS.clear()
        keys.ISSUED.clear()
        with state.LOCK, patch.object(opencode, 'active', return_value=True), \
                patch.object(opencode, 'find_processes', return_value={'receipted-survivor': [123]}), \
                patch.object(opencode, 'stop_group') as stop, patch.object(runs.threading, 'Thread') as thread:
            runs.adopt(previous)
            stop.assert_not_called()
            thread.assert_called_once_with(target=runs.follow, args=('receipted-survivor', None, None), daemon=True)
        self.assertEqual((self.task['status'], self.task['agent'], self.task['receipt']), ('done', None, receipt))
        self.assertEqual(state.L['agents']['receipted-survivor']['session'], 'receipted-session')
        self.assertEqual(keys.owner(key), ('receipted-survivor', 'background'))

    def test_direct_producer_never_overwrites_existing_config_or_run_metadata(self):
        self.task['worktree'] = str(self.root)
        for artifact in ('opencode.json', 'run.json'):
            with self.subTest(artifact=artifact):
                directory = self.directories / artifact.replace('.', '-')
                directory.mkdir()
                (directory / artifact).write_bytes(b'historical metadata bytes')
                with patch.object(opencode, 'run_dir', return_value=directory), \
                        patch.object(opencode, 'settings', return_value={}), patch.object(opencode.subprocess, 'run') as launch:
                    with self.assertRaises(FileExistsError):
                        opencode.launch(state.CONFIG, 'direct-run', self.task, 'key', 'Inspect', [])
                    launch.assert_not_called()
                self.assertEqual((directory / artifact).read_bytes(), b'historical metadata bytes')


if __name__ == '__main__':
    unittest.main()
