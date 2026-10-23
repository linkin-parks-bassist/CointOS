"""Durable self-wakes bind declared identities and replay until a durable acknowledgement."""
import copy
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from cointos import wakeups


class Wakes(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = self.root / 'wakes'
        self.store.mkdir(mode=0o700)
        self.now = 1000.0
        self.enterContext(patch.object(wakeups, 'clock', side_effect=lambda: self.now))

    def deadline(self, user=1, **condition):
        return wakeups.create(self.store, user, -123, 'Recheck the useful work', {'kind': 'deadline', **condition})

    def raw(self):
        return (self.store / 'wakeups.json').read_bytes()

    def test_deadline_due_during_downtime_replays_the_same_event_until_ack(self):
        record = self.deadline(after_seconds=30)
        self.assertEqual(wakeups.ready(self.store), [])
        self.now += 200
        event = wakeups.ready(self.store)[0]
        self.assertEqual(event['id'], record['id'])
        self.assertEqual(event['event']['outcome'], 'due')
        self.now += 100
        self.assertEqual(wakeups.ready(Path(str(self.store))), [event])
        self.assertTrue(wakeups.pending(self.store, record['id']))
        self.assertTrue(wakeups.ack(self.store, 1, record['id']))
        self.assertFalse(wakeups.ack(self.store, 1, record['id']))
        self.assertEqual(wakeups.ready(self.store), [])
        self.assertEqual(wakeups.list(self.store, 1), [])

    def test_aware_deadline_normalizes_timezone_without_accepting_ambiguous_input(self):
        record = self.deadline(at='1970-01-01T01:20:00+01:00')
        self.assertEqual(record['condition']['at'], '1970-01-01T00:20:00+00:00')
        self.now = 1200
        self.assertEqual(wakeups.ready(self.store)[0]['id'], record['id'])
        before = self.raw()
        for condition in ({'at': '1970-01-01T00:20:00'}, {'after_seconds': -1},
                          {'after_seconds': True}, {'after_seconds': float('inf')},
                          {'after_seconds': 1, 'at': '1970-01-01T00:20:00Z'}):
            with self.subTest(condition=condition), self.assertRaises(ValueError):
                self.deadline(**condition)
            self.assertEqual(self.raw(), before)

    def test_process_wake_handles_disappearance_pid_reuse_zombie_and_reboot_truthfully(self):
        for transition, native, boot, outcome in (
                ('gone', None, 'boot-original', 'exited'),
                ('pid reused', {'state': 'S', 'start_ticks': 999}, 'boot-original', 'exited'),
                ('zombie', {'state': 'Z', 'start_ticks': 42}, 'boot-original', 'exited'),
                ('reboot', {'state': 'S', 'start_ticks': 42}, 'boot-new', 'interrupted')):
            with self.subTest(transition=transition):
                directory = self.root / transition.replace(' ', '-')
                with patch.object(wakeups, 'boot_id', return_value='boot-original'), \
                        patch.object(wakeups, 'process', return_value={'state': 'S', 'start_ticks': 42}):
                    record = wakeups.create(directory, 1, 123, 'Recheck process', {'kind': 'process-exit', 'pid': 99})
                    self.assertEqual(wakeups.ready(directory), [])
                with patch.object(wakeups, 'boot_id', return_value=boot), patch.object(wakeups, 'process', return_value=native) as observed:
                    event = wakeups.ready(directory)[0]
                    self.assertEqual(event['event']['outcome'], outcome)
                    self.assertEqual(event['event']['result'], 'unknown')
                    if transition == 'reboot':
                        observed.assert_not_called()
                self.assertEqual(event['condition']['start_ticks'], record['condition']['start_ticks'])

    def test_real_owned_process_exit_needs_no_watcher_process_to_survive(self):
        command = [sys.executable, '-c', 'import sys; print("READY",flush=True); sys.stdin.read()']
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([child.stdout], [], [], 3)[0])
            self.assertEqual(child.stdout.readline().strip(), 'READY')
            record = wakeups.create(self.store, 1, 123, 'Owned child exited', {'kind': 'process-exit', 'pid': child.pid})
            self.assertEqual(wakeups.ready(self.store), [])
            child.communicate('release', timeout=3)
            event = wakeups.ready(self.store)[0]
            self.assertEqual(event['id'], record['id'])
            self.assertEqual(event['event']['outcome'], 'exited')
            self.assertEqual(event['event']['result'], 'unknown')
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=3)

    def test_logical_unit_state_survives_reboot_and_requires_loaded_registration(self):
        native = {'LoadState': 'loaded', 'ActiveState': 'active'}
        with patch.object(wakeups, 'unit_state', side_effect=lambda unit: dict(native)):
            record = wakeups.create(self.store, 1, 123, 'Service stopped',
                                    {'kind': 'unit-state', 'unit': 'owned.service', 'state': 'inactive'})
            self.assertEqual(wakeups.ready(self.store), [])
            native['ActiveState'] = 'inactive'
            with patch.object(wakeups, 'boot_id', side_effect=AssertionError('logical unit must not bind boot')):
                self.assertEqual(wakeups.ready(self.store)[0]['id'], record['id'])
            before = self.raw()
            native['LoadState'] = 'not-found'
            with self.assertRaises(ValueError):
                wakeups.create(self.store, 1, 123, 'Unknown unit', {'kind': 'unit-state', 'unit': 'missing.service', 'state': 'active'})
            self.assertEqual(self.raw(), before)

    def test_unit_observation_is_one_exact_read_only_command_not_a_shell_watcher(self):
        from cointos import client
        result = subprocess.CompletedProcess([], 0, 'LoadState=loaded\nActiveState=inactive\n', '')
        with patch.object(wakeups.subprocess, 'run', return_value=result) as native:
            self.assertEqual(wakeups.unit_state('owned@fixture.service'), {'LoadState': 'loaded', 'ActiveState': 'inactive'})
        native.assert_called_once_with(['systemctl', '--user', 'show', 'owned@fixture.service',
                                       '--property=LoadState', '--property=ActiveState'],
                                      capture_output=True, text=True, check=False,
                                      timeout=client.CONFIG['timeouts']['api_seconds'])
        for name in ('--all', 'owned.service; touch elsewhere', '/tmp/file.service'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                wakeups.create(self.store, 1, 123, 'Invalid unit', {'kind': 'unit-state', 'unit': name, 'state': 'active'})

    def test_confirmed_missing_unit_is_uncertain_but_failed_queries_cannot_fake_a_trigger(self):
        with patch.object(wakeups, 'unit_state', return_value={'LoadState': 'loaded', 'ActiveState': 'active'}):
            record = wakeups.create(self.store, 1, 123, 'Service state',
                                    {'kind': 'unit-state', 'unit': 'owned.service', 'state': 'inactive'})
        failure = subprocess.CompletedProcess([], 1, '', 'Failed to connect to user bus')
        with patch.object(wakeups.subprocess, 'run', return_value=failure):
            self.assertEqual(wakeups.ready(self.store), [])
        confirmed = subprocess.CompletedProcess([], 1, 'LoadState=not-found\nActiveState=inactive\n', '')
        with patch.object(wakeups.subprocess, 'run', return_value=confirmed):
            event = wakeups.ready(self.store)[0]
        self.assertEqual(event['id'], record['id'])
        self.assertEqual((event['event']['outcome'], event['event']['result']), ('unavailable', 'unknown'))

    def test_task_wake_binds_creation_and_reports_replacement_disappearance_or_cancel(self):
        original = {'created_at': 7.5, 'status': 'running'}
        for label, current, outcome in (
                ('finished', {'created_at': 7.5, 'status': 'done'}, 'matched'),
                ('reused', {'created_at': 9.5, 'status': 'done'}, 'replaced'),
                ('gone', None, 'unavailable'),
                ('cancelled', {'created_at': 7.5, 'status': 'failed', 'cancelled': True}, 'cancelled')):
            with self.subTest(label=label):
                directory = self.root / label
                with patch.object(wakeups, 'task_records', return_value={'p:item': original}):
                    record = wakeups.create(directory, 1, 123, 'Recheck task', {'kind': 'task-state', 'task': 'p:item', 'state': 'done'})
                    self.assertEqual(wakeups.ready(directory), [])
                records = {} if current is None else {'p:item': current}
                with patch.object(wakeups, 'task_records', return_value=records):
                    event = wakeups.ready(directory)[0]
                self.assertEqual(event['id'], record['id'])
                self.assertEqual(event['event']['outcome'], outcome)
                self.assertEqual(event['event']['result'], 'observed' if outcome == 'matched' else 'unknown')

    def test_one_unavailable_observer_does_not_block_other_due_wakes(self):
        with patch.object(wakeups, 'task_records', return_value={'p:item': {'created_at': 1, 'status': 'running'}}):
            task = wakeups.create(self.store, 1, 123, 'Task done', {'kind': 'task-state', 'task': 'p:item', 'state': 'done'})
        due = self.deadline(after_seconds=0)
        with patch.object(wakeups, 'task_records', side_effect=OSError('daemon unavailable')):
            events = wakeups.ready(self.store)
        self.assertEqual([event['id'] for event in events], [due['id']])
        self.assertFalse(wakeups.pending(self.store, task['id']))

    def test_hung_owned_native_unit_query_times_out_without_starving_timer_or_cancel(self):
        with patch.object(wakeups, 'unit_state', return_value={'LoadState': 'loaded', 'ActiveState': 'active'}):
            unit = wakeups.create(self.store, 1, 123, 'Recheck unit',
                                 {'kind': 'unit-state', 'unit': 'owned-fixture.service', 'state': 'inactive'})
        due = self.deadline(after_seconds=0)
        binaries = self.root / 'bin'
        binaries.mkdir()
        gate, marker = self.root / 'native-gate', self.root / 'native-pid'
        os.mkfifo(gate, 0o600)
        native = binaries / 'systemctl'
        native.write_text('#!/usr/bin/python3\nimport os\nfrom pathlib import Path\n'
                          'Path(os.environ["WAKE_FIXTURE_PID"]).write_text(str(os.getpid()))\n'
                          'with open(os.environ["WAKE_FIXTURE_GATE"], "rb") as gate: gate.read()\n')
        native.chmod(0o700)
        environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'],
                           WAKE_FIXTURE_PID=str(marker), WAKE_FIXTURE_GATE=str(gate),
                           COINTOS_STATE=str(self.root / 'child-state'))
        program = ('from cointos import client,wakeups;import json,sys\n'
                   'client.CONFIG["timeouts"]["api_seconds"]=0.1\n'
                   'events=wakeups.ready(sys.argv[1])\n'
                   'cancelled=wakeups.cancel(sys.argv[1],1,sys.argv[2])\n'
                   'print(json.dumps({"events":events,"cancelled":cancelled}))\n')
        try:
            # The outer bound belongs only to this regression harness. The
            # production query uses the pre-existing configured API deadline.
            result = subprocess.run([sys.executable, '-c', program, str(self.store), unit['id']],
                                    env=environment, capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(result.stdout)
            self.assertEqual([event['id'] for event in evidence['events']], [due['id']])
            self.assertTrue(evidence['cancelled'], 'timed-out observation released registry ownership')
            self.assertTrue(marker.exists(), 'actual fake native process reached its blocking query')
            self.assertFalse(Path('/proc', marker.read_text()).exists(), 'timed-out native query was reaped')
            self.assertTrue(wakeups.pending(self.store, due['id']))
        finally:
            # If the query bound regresses, the harness kills its own observer;
            # reclaim its exact fake query too instead of leaving a FIFO waiter.
            if marker.exists():
                pid = int(marker.read_text())
                try:
                    command = Path('/proc', str(pid), 'cmdline').read_bytes()
                except FileNotFoundError:
                    pass
                else:
                    if str(native).encode() in command.split(b'\0'):
                        os.kill(pid, 9)

    def test_ownership_and_cancel_before_queued_consumption_preserve_other_users(self):
        mine = self.deadline(after_seconds=0)
        theirs = self.deadline(user=2, after_seconds=0)
        queued = wakeups.ready(self.store)
        before = self.raw()
        for operation in (wakeups.cancel, wakeups.ack):
            with self.assertRaises(ValueError):
                operation(self.store, 2, mine['id'])
            self.assertEqual(self.raw(), before)
        self.assertEqual([record['id'] for record in wakeups.list(self.store, 1)], [mine['id']])
        self.assertTrue(wakeups.cancel(self.store, 1, mine['id']))
        self.assertFalse(wakeups.pending(self.store, mine['id']), 'queued cancellation must suppress later consumption')
        self.assertTrue(wakeups.pending(self.store, theirs['id']))
        self.assertEqual(len(queued), 2, 'delivery already queued is not an exactly-once claim')

    def test_file_fsync_replace_directory_fsync_precede_trigger_and_ack_return(self):
        record = self.deadline(after_seconds=0)
        actual_sync, actual_replace = os.fsync, os.replace
        order = []
        def sync(fd):
            order.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
            return actual_sync(fd)
        def replace(*args, **kwargs):
            order.append('replace')
            return actual_replace(*args, **kwargs)
        with patch.object(wakeups.os, 'fsync', side_effect=sync), patch.object(wakeups.os, 'replace', side_effect=replace):
            event = wakeups.ready(self.store)[0]
            self.assertEqual(order[-3:], ['file', 'replace', 'directory'])
            self.assertTrue(all(item == 'directory' for item in order[:-3]))
            order.clear()
            self.assertTrue(wakeups.ack(self.store, 1, event['id']))
            self.assertEqual(order[-3:], ['file', 'replace', 'directory'])
            self.assertTrue(all(item == 'directory' for item in order[:-3]))
            self.assertFalse(wakeups.pending(self.store, record['id']))
        self.assertEqual(stat.S_IMODE(self.store.stat().st_mode), 0o700)
        for path in self.store.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_failed_commit_before_replace_preserves_scheduled_bytes_and_retry_progress(self):
        record = self.deadline(after_seconds=0)
        before = self.raw()
        actual_sync = os.fsync
        def fail_file(fd):
            if stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError('fixture failed file fsync')
            return actual_sync(fd)
        with patch.object(wakeups.os, 'fsync', side_effect=fail_file):
            with self.assertRaises(OSError):
                wakeups.ready(self.store)
        self.assertEqual(self.raw(), before)
        self.assertFalse(wakeups.pending(self.store, record['id']))
        self.assertEqual(wakeups.ready(self.store)[0]['id'], record['id'])
        self.assertFalse(any(path.name.endswith('.tmp') for path in self.store.iterdir()))

    def test_visible_event_after_failed_directory_fsync_is_resynced_before_replay(self):
        record = self.deadline(after_seconds=0)
        actual = os.fsync
        def failed_directory(fd):
            if os.fstat(fd).st_ino == self.store.stat().st_ino and stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('fixture directory fsync failed')
            return actual(fd)
        with patch.object(wakeups.os, 'fsync', side_effect=failed_directory), self.assertRaises(OSError):
            wakeups.ready(self.store)
        stored = json.loads(self.raw())['wakeups'][record['id']]
        self.now += 10
        order = []
        def synced(fd):
            order.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
            return actual(fd)
        with patch.object(wakeups.os, 'fsync', side_effect=synced):
            self.assertEqual(wakeups.ready(self.store), [stored])
        self.assertEqual(order[-2:], ['file', 'directory'])
        self.assertTrue(all(item == 'directory' for item in order[:-2]))

    def test_failed_ack_after_replace_can_retry_absence_durably(self):
        record = self.deadline(after_seconds=0)
        wakeups.ready(self.store)
        actual = os.fsync
        def failed_directory(fd):
            if os.fstat(fd).st_ino == self.store.stat().st_ino and stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('fixture ack directory fsync failed')
            return actual(fd)
        with patch.object(wakeups.os, 'fsync', side_effect=failed_directory), self.assertRaises(OSError):
            wakeups.ack(self.store, 1, record['id'])
        with patch.object(wakeups.os, 'fsync', wraps=actual) as sync:
            self.assertFalse(wakeups.ack(self.store, 1, record['id']))
            self.assertEqual(sync.call_count, len(self.store.absolute().parents) + 2)
        self.assertEqual(wakeups.ready(self.store), [])

    def test_full_registry_shape_duplicate_fields_and_nonfinite_values_refuse_untouched(self):
        record = self.deadline(after_seconds=100)
        valid = json.loads(self.raw())
        corrupt = [b'{"version":1,"version":1,"wakeups":{}}', b'null', b'{"version":true,"wakeups":{}}',
                   b'{"version":1,"wakeups":[],"claim":"running"}', b'{"version":1,"wakeups":{},"extra":NaN}']
        for mutation in ('foreign-id', 'unknown-kind', 'forged-event'):
            changed = copy.deepcopy(valid)
            item = changed['wakeups'][record['id']]
            if mutation == 'foreign-id':
                item['id'] = 'f' * 32
            elif mutation == 'unknown-kind':
                item['condition']['kind'] = 'shell-command'
            else:
                item['event'] = {'at': 1000, 'outcome': 'completed', 'result': 'observed', 'detail': 'false claim'}
            corrupt.append(json.dumps(changed).encode())
        for raw in corrupt:
            with self.subTest(raw=raw):
                (self.store / 'wakeups.json').write_bytes(raw)
                with self.assertRaises(ValueError):
                    wakeups.ready(self.store)
                self.assertEqual(self.raw(), raw)

    def test_special_registry_and_lock_files_refuse_promptly_in_owned_subprocess(self):
        program = 'from cointos import wakeups; import sys\ntry: wakeups.ready(sys.argv[1])\nexcept (OSError,ValueError): print("REFUSED")\nelse: raise AssertionError("unsafe storage accepted")'
        for artifact in ('wakeups.json', 'owner.lock'):
            for form in ('fifo', 'symlink'):
                with self.subTest(artifact=artifact, form=form):
                    directory = self.root / (artifact.replace('.', '-') + form)
                    directory.mkdir(mode=0o700)
                    path = directory / artifact
                    if form == 'fifo':
                        os.mkfifo(path, 0o600)
                    else:
                        path.symlink_to(directory / 'missing-target')
                    result = subprocess.run([sys.executable, '-c', program, str(directory)],
                                            capture_output=True, text=True, timeout=3)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), 'REFUSED')
                    self.assertTrue(path.is_symlink() or stat.S_ISFIFO(path.stat().st_mode))
                    self.assertFalse((directory / 'missing-target').exists())

    def test_concurrent_threads_do_not_lose_distinct_durable_definitions(self):
        barrier = threading.Barrier(3)
        records, failures = [], []
        def register(user):
            try:
                barrier.wait(timeout=3)
                for _ in range(3):
                    records.append(self.deadline(user=user, after_seconds=0))
            except BaseException as error:
                failures.append(error)
        threads = [threading.Thread(target=register, args=(user,)) for user in (1, 2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=3)
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len({record['id'] for record in wakeups.ready(self.store)}), 6)
        self.assertEqual(len(wakeups.list(self.store, 1)), 3)
        self.assertEqual(len(wakeups.list(self.store, 2)), 3)

    def test_new_nested_store_directories_are_private_and_parent_links_are_synced(self):
        directory = self.root / 'new-parent/deeper/wakes'
        actual = os.fsync
        synced = []
        def sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                synced.append(Path(os.readlink('/proc/self/fd/' + str(fd))))
            return actual(fd)
        with patch.object(wakeups.os, 'fsync', side_effect=sync):
            wakeups.create(directory, 1, 123, 'After reboot', {'kind': 'deadline', 'after_seconds': 1})
        for path in (directory, directory.parent, directory.parent.parent):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertIn(path.parent, synced)
        self.assertIn(directory, synced)

    def test_failed_new_ancestor_link_is_synced_on_retry_before_registration_returns(self):
        directory = self.root / 'interrupted-parent/deeper/wakes'
        actual = os.fsync
        order = []
        def failed_ancestor(fd):
            path = Path(os.readlink('/proc/self/fd/' + str(fd)))
            if path == self.root:
                raise OSError('fixture could not persist newly created ancestor')
            return actual(fd)
        with patch.object(wakeups.os, 'fsync', side_effect=failed_ancestor), self.assertRaises(OSError):
            wakeups.create(directory, 1, 123, 'After reboot', {'kind': 'deadline', 'after_seconds': 0})
        self.assertTrue(directory.exists(), 'failed sync left visible directory links')
        self.assertFalse((directory / 'wakeups.json').exists())
        def synced(fd):
            order.append(Path(os.readlink('/proc/self/fd/' + str(fd))))
            return actual(fd)
        with patch.object(wakeups.os, 'fsync', side_effect=synced):
            record = wakeups.create(directory, 1, 123, 'After reboot', {'kind': 'deadline', 'after_seconds': 0})
        for enclosing in (self.root, directory.parent.parent, directory.parent):
            self.assertIn(enclosing, order, 'retry must persist every potentially interrupted link')
            self.assertLess(order.index(enclosing), order.index(directory))
        self.assertEqual(wakeups.ready(directory)[0]['id'], record['id'])

    def test_separate_coin_processes_serialize_without_losing_each_others_records(self):
        program = ('from cointos import wakeups; import sys\n'
                   'print("READY",flush=True); sys.stdin.read()\n'
                   'for _ in range(3): wakeups.create(sys.argv[1],int(sys.argv[2]),123,"Owned wake",'
                   '{"kind":"deadline","after_seconds":0})\n')
        children = [subprocess.Popen([sys.executable, '-c', program, str(self.store), str(user)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for user in (1, 2)]
        try:
            for child in children:
                self.assertTrue(select.select([child.stdout], [], [], 3)[0])
                self.assertEqual(child.stdout.readline().strip(), 'READY')
            for child in children:
                child.stdin.close()
                child.stdin = None
            for child in children:
                output, error = child.communicate(timeout=3)
                self.assertEqual(child.returncode, 0, error)
            records = wakeups.list(self.store, 1) + wakeups.list(self.store, 2)
            self.assertEqual(len({record['id'] for record in records}), 6)
            self.now = max(record['created_at'] for record in records) + 1
            self.assertEqual(len(wakeups.ready(self.store)), 6)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=3)

    def test_cancelled_trigger_is_absent_on_reload_and_scheduled_ack_cannot_fake_delivery(self):
        scheduled = self.deadline(after_seconds=10)
        before = self.raw()
        with self.assertRaises(ValueError):
            wakeups.ack(self.store, 1, scheduled['id'])
        self.assertEqual(self.raw(), before)
        due = self.deadline(after_seconds=0)
        wakeups.ready(self.store)
        wakeups.cancel(self.store, 1, due['id'])
        self.assertFalse(wakeups.pending(Path(str(self.store)), due['id']))
        self.assertEqual(wakeups.ready(self.store), [])
        self.assertEqual([record['id'] for record in wakeups.list(self.store, 1)], [scheduled['id']])


if __name__ == '__main__':
    unittest.main()
