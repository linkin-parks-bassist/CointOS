import fcntl
from pathlib import Path
import runpy
import tempfile
import threading
import unittest
from unittest import mock

from cointos import config, repair, replacement


class RepairInstallationOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'runtime'
        self.root.mkdir()
        (self.root / '.runtime-install').write_text('existing-source\n')
        self.install = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/install'),
                                     run_name='installation_ownership_test')['install']
        self.environment = self.install.__globals__
        self.environment['target'] = self.root
        (self.root / 'config').mkdir()
        config.write_json(self.root / 'config/cointos.json', config.load())

    def test_existing_repair_refuses_installation_before_contact_or_copy(self):
        with repair.ownership(self.root) as acquired:
            self.assertTrue(acquired)
            with mock.patch('urllib.request.urlopen') as contact, \
                    mock.patch.object(self.environment['subprocess'], 'run') as native, \
                    mock.patch.dict(self.environment, install_owned=mock.Mock()) as environment:
                with self.assertRaisesRegex(SystemExit, 'independent repair owns'):
                    self.install(live=True)
                environment['install_owned'].assert_not_called()
            contact.assert_not_called()
            native.assert_not_called()
        self.assertEqual((self.root / '.runtime-install').read_text(), 'existing-source\n')

    def test_installer_owns_entire_effectful_boundary_and_releases_on_failure(self):
        def effects(*args):
            with repair.ownership(self.root) as acquired:
                self.assertFalse(acquired)
            raise OSError('fixture copy failure')
        with mock.patch.dict(self.environment, install_owned=effects):
            with self.assertRaisesRegex(OSError, 'fixture copy failure'):
                self.install(live=True)
        with repair.ownership(self.root) as acquired:
            self.assertTrue(acquired, 'failure-path atexit restore can activate repair after release')

    def test_actual_failure_callback_starts_daemon_after_ownership_release(self):
        import io
        from types import SimpleNamespace
        callbacks = []
        native_commands = []
        def native(*args, **options):
            native_commands.append(args[0])
            if args[0][-2:] == ['stop', 'cointosd.service']:
                with replacement.lease(self.root, shared=True) as acquired:
                    self.assertFalse(acquired, 'replacement excludes new request admission before stopping')
            if args[0][-2:] == ['start', 'cointosd.service']:
                with repair.ownership(self.root) as acquired:
                    self.assertTrue(acquired)
                with replacement.lease(self.root, shared=True) as acquired:
                    self.assertTrue(acquired, 'failure restoration follows replacement lease release')
            return SimpleNamespace(stdout='')
        with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(b'{}')), \
                mock.patch.object(self.environment['subprocess'], 'run', side_effect=native), \
                mock.patch.object(self.environment['atexit'], 'register', side_effect=callbacks.append), \
                mock.patch.dict(self.environment, daemon_changed=lambda: True,
                                copy_runtime=mock.Mock(side_effect=OSError('copy failed'))):
            with self.assertRaisesRegex(OSError, 'copy failed'):
                self.install(live=True)
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
        self.assertEqual(native_commands[-1], ['systemctl', '--user', 'start', 'cointosd.service'])

    def test_first_install_failure_leaves_marked_resumable_lock_namespace(self):
        import shutil
        shutil.rmtree(self.root)
        with mock.patch.dict(self.environment, install_owned=mock.Mock(side_effect=OSError('contact failed'))):
            with self.assertRaisesRegex(OSError, 'contact failed'):
                self.install()
        self.assertEqual((self.root / '.runtime-install').read_text(), str(self.environment['source']) + '\n')
        with repair.ownership(self.root) as acquired:
            self.assertTrue(acquired)

    def test_completed_installation_retires_stale_repair_without_claiming_restoration(self):
        directory = self.root / 'state/repairs' / ('a' * 32)
        directory.mkdir(parents=True)
        config.write_json(directory.parent / 'current.json', {'directory': directory.name})
        (directory / 'before.json').write_text('retained original authority')
        (directory / 'events.jsonl').write_text('retained native evidence')
        with repair.ownership(self.root) as acquired:
            self.assertTrue(acquired)
            repair.supersede_installation(self.root)
            checked = (directory / 'checked.json').read_bytes()
            repair.supersede_installation(self.root)
        self.assertEqual((directory / 'checked.json').read_bytes(), checked)
        self.assertEqual(config.read_owned_json(directory / 'checked.json')['outcome'], 'blocked')
        self.assertEqual(config.read_owned_json(directory / 'checked.json')['superseded_by'], 'installation')
        self.assertEqual((directory / 'before.json').read_text(), 'retained original authority')
        self.assertEqual((directory / 'events.jsonl').read_text(), 'retained native evidence')

    def test_native_waiter_reads_only_after_installation_releases_ownership(self):
        started = threading.Event()
        checked = threading.Event()
        errors = []
        def inspect(root, unit):
            self.assertEqual((root / 'installed-version').read_text(), 'complete')
            checked.set()
            return {'unit': unit}
        def native_repair():
            started.set()
            try:
                repair.main(self.root, 'fixture.service')
            except BaseException as error:
                errors.append(error)
        with mock.patch.object(repair, 'inspect', side_effect=inspect), \
                mock.patch.object(repair, 'check', return_value=[]):
            with repair.ownership(self.root) as acquired:
                self.assertTrue(acquired)
                (self.root / 'installed-version').write_text('half-copy')
                thread = threading.Thread(target=native_repair)
                thread.start()
                self.assertTrue(started.wait(2))
                self.assertFalse(checked.wait(.1))
                (self.root / 'installed-version').write_text('complete')
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(checked.is_set())
        incident = config.read_owned_json(self.root / 'state/repairs/current.json')['directory']
        self.assertEqual(config.read_owned_json(self.root / 'state/repairs' / incident / 'checked.json')['outcome'], 'complete')

    def test_special_lock_files_are_refused_without_blocking_or_following(self):
        import os
        directory = self.root / 'state/repairs'
        directory.mkdir(parents=True)
        lock = directory / 'owner.lock'
        target = self.root / 'preserved'
        target.write_text('preserved')
        lock.symlink_to(target)
        with self.assertRaises(OSError), repair.ownership(self.root):
            pass
        self.assertEqual(target.read_text(), 'preserved')
        lock.unlink()
        os.mkfifo(lock)
        with self.assertRaisesRegex(ValueError, 'not a regular file'), repair.ownership(self.root):
            pass


if __name__ == '__main__':
    unittest.main()
