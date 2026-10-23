import json
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock

from cointos import config, replacement


INSTALL = Path(__file__).resolve().parents[1] / "scripts/install"


class LiveInstallBoundaryTests(unittest.TestCase):
    def test_runtime_templates_refresh_without_removing_other_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            runtime = source / 'runtime'
            runtime.mkdir(parents=True)
            (runtime / 'where-am-i.md').write_text('orientation')
            (runtime / 'how-to-submit-work.md').write_text('focused guidance')
            target = root / 'target'
            (target / '.knowledge').mkdir(parents=True)
            retained = target / '.knowledge' / 'user-answer.md'
            retained.write_text('user-owned answer')
            environment = self.install.__globals__
            with mock.patch.dict(environment, source=source, target=target), \
                    mock.patch.object(environment['kt'], 'write') as write, \
                    mock.patch.object(environment['subprocess'], 'run') as native:
                environment['write_runtime_knowledge']()
            self.assertEqual(write.call_args_list, [
                mock.call(target, 'how to submit work', 'focused guidance'),
                mock.call(target, 'where am i', 'orientation')])
            native.assert_not_called()
            self.assertEqual(retained.read_text(), 'user-owned answer')

    def alias_ledger(self):
        return {'frontier_version': 1, 'agents': {}, 'paused': False, 'tasks': {}, 'queue': {'p:impl': {
            'project': 'p', 'item': 'impl', 'version': 4, 'kind': 'queued',
            'depends': ['p:base'], 'brief': 'Depends on: p:base\nRetain this request'}}}

    def test_recovery_schema_change_requires_full_install_before_contact_or_copy(self):
        self.write_installed_config(config.load())
        (self.target / 'state').mkdir()
        ledger = self.alias_ledger()
        ledger.pop('frontier_version')
        path = self.target / 'state/cointos.json'
        path.write_text(json.dumps(ledger))
        before = path.read_bytes()
        environment = self.install.__globals__
        with mock.patch('urllib.request.urlopen') as contact, \
                mock.patch.object(environment['subprocess'], 'run') as native, \
                mock.patch.dict(environment, copy_runtime=mock.Mock()):
            with self.assertRaisesRegex(SystemExit, 'recovery ownership changed'):
                self.install(live=True)
            environment['copy_runtime'].assert_not_called()
        contact.assert_not_called()
        native.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_alias_migration_requires_stopped_daemon_even_when_runtime_bytes_match(self):
        self.write_installed_config(config.load())
        ledger = self.alias_ledger()
        calls = []
        def native(command, **options):
            calls.append(command)
            return mock.Mock(stdout='')
        environment = self.install.__globals__
        with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(ledger).encode())), \
                mock.patch.object(environment['subprocess'], 'run', side_effect=native), \
                mock.patch.object(environment['atexit'], 'register'), \
                mock.patch.dict(environment, daemon_changed=lambda: False,
                                copy_runtime=mock.Mock(side_effect=OSError('fixture stop after ownership'))):
            with self.assertRaisesRegex(OSError, 'fixture stop'): self.install(live=True)
        self.assertIn(('systemctl', '--user', 'stop', 'cointosd.service'), calls)

    def test_canonical_live_graph_keeps_no_restart_fastpath(self):
        self.write_installed_config(config.load())
        ledger = self.alias_ledger()
        ledger['queue']['p:impl'].update(depends=['base'], brief='Depends on: base\nRetain this request')
        environment = self.install.__globals__
        with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(ledger).encode())), \
                mock.patch.object(environment['subprocess'], 'run', return_value=mock.Mock(stdout='')) as native, \
                mock.patch.dict(environment, daemon_changed=lambda: False, copy_runtime=mock.Mock(),
                                write_runtime_knowledge=mock.Mock()):
            self.install(live=True)
            environment['copy_runtime'].assert_called_once()
        self.assertFalse(any('stop' in call.args[0] for call in native.call_args_list))

    def test_bad_live_qualification_refuses_before_native_or_copy_effects(self):
        self.write_installed_config(config.load())
        ledger = self.alias_ledger()
        ledger['queue']['p:impl'].update(depends=['foreign:base'], brief='Depends on: foreign:base')
        environment = self.install.__globals__
        with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(ledger).encode())), \
                mock.patch.object(environment['subprocess'], 'run') as native, \
                mock.patch.dict(environment, copy_runtime=mock.Mock()):
            with self.assertRaises(ValueError): self.install(live=True)
            environment['copy_runtime'].assert_not_called()
        native.assert_not_called()

    def test_live_daemon_replacement_refuses_an_observed_validation(self):
        self.write_installed_config(config.load())
        ledger = self.alias_ledger()
        ledger['tasks']['packet'] = {'validating': True}
        environment = self.install.__globals__
        with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(ledger).encode())), \
                mock.patch.object(environment['subprocess'], 'run', return_value=mock.Mock(stdout='')) as native, \
                mock.patch.dict(environment, daemon_changed=lambda: True, copy_runtime=mock.Mock()):
            with self.assertRaisesRegex(SystemExit, 'during packet or landing validation'):
                self.install(live=True)
            environment['copy_runtime'].assert_not_called()
        self.assertFalse(any('stop' in call.args[0] for call in native.call_args_list))

    def test_live_non_daemon_update_can_preserve_an_active_validation(self):
        self.write_installed_config(config.load())
        ledger = self.alias_ledger()
        ledger['queue']['p:impl'].update(depends=['base'], brief='Depends on: base\nRetain this request')
        ledger['tasks']['packet'] = {'validating': True}
        environment = self.install.__globals__
        with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(ledger).encode())), \
                mock.patch.object(environment['subprocess'], 'run', return_value=mock.Mock(stdout='')) as native, \
                mock.patch.dict(environment, daemon_changed=lambda: False, copy_runtime=mock.Mock(),
                                write_runtime_knowledge=mock.Mock()):
            with replacement.lease(self.target, shared=True) as acquired:
                self.assertTrue(acquired)
                self.install(live=True)
            environment['copy_runtime'].assert_called_once()
        self.assertFalse(any('stop' in call.args[0] for call in native.call_args_list))

    def test_request_admitted_after_ledger_read_still_prevents_replacement(self):
        self.write_installed_config(config.load())
        ledger = self.alias_ledger()
        environment = self.install.__globals__
        # The observed ledger is quiet, but a validator acquired its lease before
        # installation could replace the daemon. No stop/copy may follow.
        with replacement.lease(self.target, shared=True), \
                mock.patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(ledger).encode())), \
                mock.patch.object(environment['subprocess'], 'run', return_value=mock.Mock(stdout='')) as native, \
                mock.patch.dict(environment, daemon_changed=lambda: True, copy_runtime=mock.Mock()):
            with self.assertRaisesRegex(SystemExit, 'receipt settlement is in progress'):
                self.install(live=True)
            environment['copy_runtime'].assert_not_called()
        self.assertFalse(any('stop' in call.args[0] for call in native.call_args_list))

    def test_bad_retained_qualification_refuses_before_contact_without_replacing_bytes(self):
        self.write_installed_config(config.load())
        (self.target / 'state').mkdir()
        ledger = self.alias_ledger()
        ledger['queue']['p:impl'].update(depends=['p:base:extra'], brief='Depends on: p:base:extra')
        path = self.target / 'state/cointos.json'
        path.write_text(json.dumps(ledger, indent=3) + '\n')
        before = path.read_bytes()
        environment = self.install.__globals__
        with mock.patch('urllib.request.urlopen') as contact, \
                mock.patch.object(environment['subprocess'], 'run') as native, \
                mock.patch.dict(environment, copy_runtime=mock.Mock()):
            with self.assertRaises(ValueError): self.install(live=True)
            environment['copy_runtime'].assert_not_called()
        contact.assert_not_called()
        native.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_secondary_metadata_refuses_before_copy_or_native_effects(self):
        self.write_installed_config(config.load())
        (self.target / 'state').mkdir()
        environment = self.install.__globals__
        for retained in (True, False):
            ledger = self.alias_ledger()
            ledger['queue']['p:impl']['brief'] += '\r\nDepends on: foreign:base\r\n'
            path = self.target / 'state/cointos.json'
            path.write_text(json.dumps(ledger if retained else {}))
            before = path.read_bytes()
            with self.subTest(retained=retained), \
                    mock.patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(ledger).encode())) as contact, \
                    mock.patch.object(environment['subprocess'], 'run') as native, \
                    mock.patch.dict(environment, copy_runtime=mock.Mock()):
                with self.assertRaises(ValueError): self.install(live=True)
                environment['copy_runtime'].assert_not_called()
                native.assert_not_called()
                if retained: contact.assert_not_called()
            self.assertEqual(path.read_bytes(), before)

    def setUp(self):
        self.script = runpy.run_path(str(INSTALL), run_name="cointos_install_test")
        self.install = self.script["install"]
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        target = Path(self.temporary.name) / ".CointOS"
        target.mkdir()
        (target / ".runtime-install").write_text("test\n")
        self.install.__globals__["target"] = target
        self.target = target

    def write_installed_config(self, value):
        path = self.target / "config/cointos.json"
        path.parent.mkdir()
        path.write_text(json.dumps(value))

    def test_process_identity_drift_is_rejected_before_daemon_contact(self):
        installed = config.load()
        installed["port"] += 1
        self.write_installed_config(installed)

        with mock.patch("urllib.request.urlopen") as contact, mock.patch.object(
                self.install.__globals__["subprocess"], "run") as systemd:
            with self.assertRaisesRegex(SystemExit, r"preserved-process configuration changed \(port\)"):
                self.install(live=True)

        contact.assert_not_called()
        systemd.assert_not_called()

    def test_missing_installed_config_is_rejected_before_daemon_contact(self):
        with mock.patch("urllib.request.urlopen") as contact, mock.patch.object(
                self.install.__globals__["subprocess"], "run") as systemd:
            with self.assertRaisesRegex(SystemExit, "installed runtime configuration is unavailable"):
                self.install(live=True)

        contact.assert_not_called()
        systemd.assert_not_called()

    def test_service_rendering_failure_precedes_contact_and_runtime_mutation(self):
        settings = config.load()
        settings.pop('service_restart_seconds')
        marker = self.target / 'existing-work'
        marker.write_text('preserve this runtime')
        with mock.patch.object(config, 'load', return_value=settings), \
                mock.patch('urllib.request.urlopen') as contact, \
                mock.patch.object(self.install.__globals__['subprocess'], 'run') as systemd, \
                mock.patch.dict(self.install.__globals__, copy_runtime=mock.Mock()) as environment:
            with self.assertRaisesRegex(KeyError, 'service_restart_seconds'):
                self.install(live=True)
            environment['copy_runtime'].assert_not_called()
        contact.assert_not_called()
        systemd.assert_not_called()
        self.assertEqual(marker.read_text(), 'preserve this runtime')

    def test_daemon_changes_are_detected_and_projects_ignored(self):
        changed = self.install.__globals__["daemon_changed"]
        source = self.install.__globals__["source"]
        for part in ("cointos", "config", "systemd"):
            import shutil
            shutil.copytree(source / part, self.target / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.target / "config/projects.json").write_text("[]")
        self.assertFalse(changed(), "an identical daemon with different enrollment needs no restart")
        (self.target / 'cointos/cli.py').write_text('# older client\n')
        self.assertFalse(changed(), 'the daemon does not import the client CLI')
        (self.target / "cointos/state.py").write_text("# older\n")
        self.assertTrue(changed())

    def test_live_client_refresh_is_atomic_and_does_not_interrupt_validation(self):
        import shutil
        environment = self.install.__globals__
        source = environment['source']
        for part in environment['DAEMON_PARTS']:
            shutil.copytree(source / part, self.target / part,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        client = self.target / 'cointos/cli.py'
        client.write_text('# previous client\n')
        ledger = self.alias_ledger()
        ledger['queue'].clear()
        ledger['tasks']['packet'] = {'validating': True}
        with replacement.lease(self.target, shared=True), \
                mock.patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(ledger).encode())), \
                mock.patch.object(environment['subprocess'], 'run', return_value=mock.Mock(stdout='')) as native, \
                mock.patch.dict(environment, copy_runtime=mock.Mock(), write_runtime_knowledge=mock.Mock()):
            self.install(live=True)
        self.assertEqual(client.read_bytes(), (source / 'cointos/cli.py').read_bytes())
        self.assertFalse(any('stop' in call.args[0] for call in native.call_args_list))

    def test_failed_client_publication_preserves_the_previous_module(self):
        environment = self.install.__globals__
        client = self.target / 'cointos/cli.py'
        client.parent.mkdir()
        client.write_text('# preserve imported client\n')
        with mock.patch.object(environment['os'], 'replace', side_effect=OSError('publication refused')):
            with self.assertRaisesRegex(OSError, 'publication refused'):
                environment['copy_client_files']()
        self.assertEqual(client.read_text(), '# preserve imported client\n')
        self.assertEqual(list(client.parent.iterdir()), [client])
