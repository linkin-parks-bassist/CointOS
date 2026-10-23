"""Fatal startup routes to an independent repairer, preserving durable authority."""
import builtins
import contextlib
import copy
import fcntl
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace


class Boot(unittest.TestCase):
    def test_success_calls_start_once_without_converting_its_return(self):
        from cointos import boot
        start = Mock(return_value='normal return')
        boot.run(start)
        start.assert_called_once_with()

    def test_startup_exception_prints_the_cause_and_exits_with_fatal_startup_status(self):
        from cointos import boot
        diagnostic = io.StringIO()
        with contextlib.redirect_stderr(diagnostic), self.assertRaises(SystemExit) as failed:
            boot.run(Mock(side_effect=ValueError('malformed durable ledger')))
        self.assertEqual(failed.exception.code, 2)
        self.assertIn('ValueError: malformed durable ledger', diagnostic.getvalue())
        self.assertIn('Traceback', diagnostic.getvalue())

    def test_explicit_exit_and_keyboard_interrupt_keep_their_original_meaning(self):
        from cointos import boot
        for exception in (KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(exception=type(exception).__name__), self.assertRaises(type(exception)) as ended:
                boot.run(Mock(side_effect=exception))
            self.assertIs(ended.exception, exception)

    def test_import_failure_is_inside_the_fatal_startup_boundary(self):
        from cointos import boot
        original = builtins.__import__

        def importing(name, globals=None, locals=None, fromlist=(), level=0):
            if name.endswith('daemon') or (name == 'cointos' and 'daemon' in fromlist):
                raise ImportError('fixture daemon dependency is unavailable')
            return original(name, globals, locals, fromlist, level)

        diagnostic = io.StringIO()
        with patch.object(builtins, '__import__', side_effect=importing), \
                contextlib.redirect_stderr(diagnostic), self.assertRaises(SystemExit) as failed:
            boot.main()
        self.assertEqual(failed.exception.code, 2)
        self.assertIn('fixture daemon dependency is unavailable', diagnostic.getvalue())

    def test_unit_routes_fatal_python_startup_to_one_independent_repair_service(self):
        root = Path(__file__).resolve().parents[1]
        daemon = (root / 'systemd/cointosd.service').read_text()
        self.assertIn('ExecStart=/usr/bin/python3 -m cointos.boot', daemon)
        self.assertIn('OnFailure=cointos-repair.service', daemon)
        self.assertIn('RestartPreventExitStatus=2', daemon)
        self.assertIn('Restart=on-failure', daemon, 'signal death retains ordinary native restart')
        repair = (root / 'systemd/cointos-repair.service').read_text()
        self.assertIn('cointos.repair', repair)
        self.assertIn('StartLimitIntervalSec=0', repair, 'transient launcher failures must not strand retained recovery')
        self.assertIn('RestartSec=@SERVICE_RESTART_SECONDS@', repair, 'native retries use the configured pause')
        self.assertNotIn('RuntimeMaxSec', repair, 'repair completion is evidence, not a new kill timeout')

    def test_repair_module_import_survives_broken_runtime_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            broken = directory / 'config.json'
            broken.write_bytes(b'{"unfinished":')
            environment = {**os.environ, 'COINTOS_CONFIG': str(broken),
                           'COINTOS_PROJECTS': str(broken), 'COINTOS_STATE': str(directory / 'state'),
                           'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, '-c', 'from cointos import repair; print("READY")'],
                                    capture_output=True, text=True, env=environment, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'READY')
            self.assertEqual(broken.read_bytes(), b'{"unfinished":')


class Repair(unittest.TestCase):
    def setUp(self):
        from cointos import config, repair, state
        self.config, self.repair = config, repair
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / 'state').mkdir()
        (self.root / 'config').mkdir()
        settings = copy.deepcopy(state.CONFIG)
        settings.update(projects=[], trees=[], snapshots=str(self.root / 'cache'), disk_snapshots=str(self.root / 'disk'))
        (self.root / 'config/cointos.json').write_text(json.dumps(settings))
        self.projects = {'projects': [{'name': 'kept', 'path': '/example/kept'}]}
        (self.root / 'config/projects.json').write_text(json.dumps(self.projects))
        self.ledger = {'tasks': {'kept:task': {'status': 'running', 'agent': 'old-format', 'session': 'kept-session',
                                              'receipt': None, 'acceptance': None, 'admission_hold': 'user hold'}},
                       'agents': {'old-format': {'task': 'kept:task'}},
                       'queue': {'kept:item': {'version': 7, 'held_by': 'user'}},
                       'checks': [{'name': 'fixture runtime', 'ok': True}]}
        (self.root / 'state/cointos.json').write_text(json.dumps(self.ledger))
        self.registry = {'coin': 'fixture-coin-key', 'agents': {'old-format': 'fixture-agent-key'}}
        (self.root / 'state/keys.json').write_text(json.dumps(self.registry))
        self.api = copy.deepcopy(self.ledger)
        self.daemon_active = True
        self.cli_ok = True
        self.cli_stderr = 'ModuleNotFoundError: fixture CLI adapter dependency is unavailable'
        self.enterContext(patch.object(repair.shutil, 'which', return_value='/fixture/codex'))

        def native(command, **options):
            if command[:4] == [sys.executable, '-m', 'cointos.cli', 'check']:
                self.assertEqual(options['cwd'], self.root)
                self.assertEqual(options['env']['COINTOS_STATE'], str(self.root / 'state'))
                self.assertEqual(options['env']['COINTOS_CONFIG'], str(self.root / 'config/cointos.json'))
                if not self.cli_ok:
                    raise subprocess.CalledProcessError(1, command, output='fixture runtime check failed',
                                                        stderr=self.cli_stderr)
                return subprocess.CompletedProcess(command, 0, 'checks passed', '')
            self.assertEqual(command[0], 'systemctl', 'all native calls must match declared fixture boundaries')
            if 'list-units' in command:
                output = ('cointos-agent-old-format.service loaded active running fixture\n'
                          'cointos-agent-unrelated.service loaded active running fixture\n')
            else:
                active = self.daemon_active if command[3] == 'cointosd.service' else True
                output = 'ActiveState=' + ('active' if active else 'failed') + '\nMainPID=' + (str(os.getpid()) if active else '0') + '\nInvocationID=fixture-invocation\nLoadState=loaded\n'
            return subprocess.CompletedProcess(command, 0, output, '')

        self.enterContext(patch.object(repair.subprocess, 'run', side_effect=native))
        self.enterContext(patch.object(repair.urllib.request, 'urlopen', side_effect=lambda *args, **kwargs:
                                     io.BytesIO(json.dumps(self.api).encode())))
        self.restore_startup()

    def restore_startup(self, previous=None):
        """Produce real restoration evidence; only post-restoration consumers are adapters."""
        from cointos import daemon, keys, state, startup
        original = copy.deepcopy(self.ledger if previous is None else previous)
        entries = self.config.read_owned_json(self.root / 'config/projects.json')['projects']
        with patch.dict(state.L, {}, clear=True), patch.dict(state.STARTUP, {}, clear=True), \
                patch.dict(state.CONFIG, projects=entries), \
                patch.dict(keys.OWNERS, {}, clear=True), patch.object(keys, 'KEYS', self.root / 'state/keys.json'), \
                patch.object(daemon.lifecycle, 'recover_landings'), patch.object(daemon.runs, 'adopt'), \
                patch.object(daemon.snapshots, 'recover_transfers'), patch.object(daemon.snapshots, 'forget_orphans'), \
                patch.object(daemon.snapshots, 'forget_untracked'), patch.object(daemon, 'log'), \
                patch.object(daemon, 'save'), patch.object(daemon.queues, 'publish'):
            daemon.restore(original)
            self.api = copy.deepcopy(state.L)
            self.api['checks'] = copy.deepcopy(self.ledger['checks'])
            self.api['startup'] = copy.deepcopy(state.STARTUP)
            self.api['gateway_coin'] = startup.coin_digest(keys.OWNERS)

    def incident_directory(self):
        current = json.loads((self.root / 'state/repairs/current.json').read_text())
        return self.root / 'state/repairs' / current['directory']

    def manual_directory(self):
        directory = self.root / 'state/repairs' / ('f' * 32)
        directory.mkdir(parents=True)
        return directory

    def test_actual_inspect_and_check_preserve_ownership_without_disclosing_gateway_keys(self):
        before = self.repair.inspect(self.root, 'cointosd.service')
        self.assertEqual(self.repair.check(self.root, 'cointosd.service', before), [])
        self.assertEqual(set(before['units']), {'cointos-agent-old-format.service'})
        self.assertNotIn('fixture-coin-key', json.dumps(before))
        self.assertNotIn('fixture-agent-key', json.dumps(before))
        damaged = copy.deepcopy(self.ledger)
        damaged['tasks']['kept:task']['session'] = 'replaced-session'
        self.restore_startup(damaged)
        self.assertTrue(any('authority' in failure for failure in self.repair.check(self.root, 'cointosd.service', before)))

    def test_check_cannot_claim_repair_after_clearing_an_explicit_queue_hold(self):
        before = self.repair.inspect(self.root, 'cointosd.service')
        damaged = copy.deepcopy(self.ledger)
        damaged['queue']['kept:item']['held_by'] = None
        self.restore_startup(damaged)
        self.assertTrue(self.repair.check(self.root, 'cointosd.service', before), 'user queue hold must survive repair')

    def test_check_cannot_claim_repair_after_withdrawing_or_replacing_project_enrollment(self):
        before = self.repair.inspect(self.root, 'cointosd.service')
        for entries in ([], [{'name': 'kept', 'path': '/example/replaced'}]):
            with self.subTest(entries=entries):
                (self.root / 'config/projects.json').write_text(json.dumps({'projects': entries}))
                self.assertTrue(self.repair.check(self.root, 'cointosd.service', before),
                                'enrollment cannot disappear or move to make startup pass')

    def test_main_checks_the_fake_executor_handback_before_recording_completion(self):
        self.daemon_active = False
        proposed = {'outcome': 'complete', 'summary': 'Corrected startup cause', 'evidence': ['Cause repaired in fixture']}

        def repair_cause(directory, prompt):
            self.assertIn('Current refusal', prompt)
            self.assertNotIn('fixture-agent-key', prompt)
            self.daemon_active = True
            return proposed

        with patch.object(self.repair, 'execute', side_effect=repair_cause) as executor:
            self.repair.main(self.root, 'cointosd.service')
            executor.assert_called_once()
        directory = self.incident_directory()
        checked = json.loads((directory / 'checked.json').read_text())
        self.assertEqual(checked['outcome'], 'complete')
        self.assertEqual(checked['checks'], [])
        self.assertEqual(json.loads((directory / 'proposed.json').read_text()), proposed)
        self.assertEqual(json.loads((self.root / 'state/keys.json').read_text()), self.registry)
        self.assertEqual(json.loads((self.root / 'state/cointos.json').read_text()), self.ledger)

    def test_complete_proposal_without_restored_runtime_is_refused_and_blocked_is_concrete(self):
        self.daemon_active = False
        proposed = {'outcome': 'complete', 'summary': 'Proposed repair', 'evidence': ['Claim without restored service']}
        with patch.object(self.repair, 'execute', return_value=proposed), self.assertRaises(ValueError):
            self.repair.main(self.root, 'cointosd.service')
        directory = self.incident_directory()
        self.assertFalse((directory / 'checked.json').exists())
        proposed['outcome'] = 'blocked'
        with patch.object(self.repair, 'execute', return_value=proposed):
            self.repair.main(self.root, 'cointosd.service')
        checked = json.loads((directory / 'checked.json').read_text())
        self.assertEqual(checked['outcome'], 'blocked')
        self.assertIn('daemon service is not active', checked['checks'])

    def test_busy_native_owner_waits_then_checks_fresh_authority(self):
        import threading
        started = threading.Event()
        inspected = threading.Event()
        failures = []
        def inspect(*args):
            inspected.set()
            return {'unit': 'cointosd.service'}
        def run():
            started.set()
            try:
                self.repair.main(self.root, 'cointosd.service')
            except BaseException as error:
                failures.append(error)
        with patch.object(self.repair, 'inspect', side_effect=inspect), \
                patch.object(self.repair, 'check', return_value=[]), \
                patch.object(self.repair, 'execute') as execute:
            with self.repair.ownership(self.root) as acquired:
                self.assertTrue(acquired)
                thread = threading.Thread(target=run)
                thread.start()
                self.assertTrue(started.wait(2))
                self.assertFalse(inspected.wait(.1))
                execute.assert_not_called()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            execute.assert_not_called()
        self.assertEqual(failures, [])
        self.assertTrue(inspected.is_set())
        self.assertEqual(json.loads((self.incident_directory() / 'checked.json').read_text())['outcome'], 'complete')

    def test_interrupted_executor_resumes_its_real_recorded_thread_instead_of_starting_over(self):
        directory = self.manual_directory()
        commands = []
        proposal = {'outcome': 'complete', 'summary': 'Cause repaired', 'evidence': ['Verified fixture']}

        def executor(command, **options):
            commands.append(command)
            failed = len(commands) == 1
            def communicate(prompt):
                options['stdout'].write(json.dumps({'type': 'thread.started', 'thread_id': 'retained-thread'}) + '\n')
                options['stdout'].flush()
                if not failed:
                    Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(proposal))
            return SimpleNamespace(communicate=communicate, returncode=1 if failed else 0)

        with patch.object(self.repair.subprocess, 'Popen', side_effect=executor):
            with self.assertRaises(subprocess.CalledProcessError):
                self.repair.execute(directory, 'Diagnose fixture')
            self.assertEqual(self.repair.execute(directory, 'Continue fixture'), proposal)
        self.assertEqual(commands[1][commands[1].index('exec'):commands[1].index('exec') + 3],
                         ['exec', 'resume', 'retained-thread'])
        self.assertEqual(commands[1][:3], ['/fixture/codex', '--cd', str(self.root)])
        self.assertIn('model_provider="openai"', commands[1])
        self.assertIn('--output-schema', commands[1])
        self.assertIn('--output-schema', commands[0])
        self.assertIn('--skip-git-repo-check', commands[0])
        self.assertIn('--skip-git-repo-check', commands[1])
        self.assertNotIn('--model', commands[0], 'independent CLI uses its own configured provider')

    def test_main_resumes_an_incomplete_incident_with_its_existing_baseline_and_thread(self):
        self.daemon_active = False
        commands = []
        proposal = {'outcome': 'complete', 'summary': 'Startup restored', 'evidence': ['Native and API fixture checks passed']}
        original_inspect = self.repair.inspect

        def executor(command, **options):
            commands.append(command)
            failed = len(commands) == 1
            def communicate(prompt):
                options['stdout'].write(json.dumps({'type': 'thread.started', 'thread_id': 'incident-thread'}) + '\n')
                options['stdout'].flush()
                if not failed:
                    self.daemon_active = True
                    Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(proposal))
            return SimpleNamespace(communicate=communicate, returncode=1 if failed else 0)

        with patch.object(self.repair, 'inspect', wraps=original_inspect) as inspect, \
                patch.object(self.repair.subprocess, 'Popen', side_effect=executor):
            with self.assertRaises(subprocess.CalledProcessError):
                self.repair.main(self.root, 'cointosd.service')
            directory = self.incident_directory()
            before_bytes = (directory / 'before.json').read_bytes()
            self.assertFalse((directory / 'checked.json').exists())
            self.repair.main(self.root, 'cointosd.service')
            inspect.assert_called_once()
        self.assertEqual(self.incident_directory(), directory)
        self.assertEqual((directory / 'before.json').read_bytes(), before_bytes)
        self.assertEqual(commands[1][commands[1].index('exec'):commands[1].index('exec') + 3],
                         ['exec', 'resume', 'incident-thread'])
        self.assertEqual(json.loads((directory / 'checked.json').read_text())['outcome'], 'complete')

    def assert_new_incident_after_terminal(self, outcome):
        self.daemon_active = False
        proposal = {'outcome': outcome, 'summary': 'Prior incident settled', 'evidence': ['Preserved fixture authority']}
        def first_execution(directory, prompt):
            self.daemon_active = outcome == 'complete'
            return proposal
        with patch.object(self.repair, 'execute', side_effect=first_execution):
            self.repair.main(self.root, 'cointosd.service')
        old_directory = self.incident_directory()
        old_baseline = (old_directory / 'before.json').read_bytes()
        self.assertEqual(json.loads((old_directory / 'checked.json').read_text())['outcome'], outcome)
        # A subsequent startup incident owns the now-current durable authority.
        self.ledger['tasks']['kept:task']['session'] = 'later-session'
        self.ledger['queue']['kept:item']['version'] = 8
        (self.root / 'state/cointos.json').write_text(json.dumps(self.ledger))
        self.restore_startup()
        self.daemon_active = False
        with patch.object(self.repair, 'execute', return_value={'outcome': 'blocked', 'summary': 'New obstruction',
                                                               'evidence': ['Current startup remains refused']}) as execute:
            self.repair.main(self.root, 'cointosd.service')
            execute.assert_called_once()
        current = self.incident_directory()
        self.assertNotEqual(current, old_directory)
        before = json.loads((current / 'before.json').read_text())
        self.assertEqual(before['tasks']['kept:task']['session'], 'later-session')
        self.assertEqual(before['queue']['kept:item']['version'], 8)
        self.assertEqual((old_directory / 'before.json').read_bytes(), old_baseline)

    def test_new_startup_after_complete_handback_gets_a_new_incident_baseline(self):
        self.assert_new_incident_after_terminal('complete')

    def test_new_startup_after_blocked_handback_gets_a_new_incident_baseline(self):
        self.assert_new_incident_after_terminal('blocked')

    def test_native_cli_check_failure_refuses_handback_even_when_api_and_unit_pass(self):
        before = self.repair.inspect(self.root, 'cointosd.service')
        self.cli_ok = False
        failures = self.repair.check(self.root, 'cointosd.service', before)
        self.assertTrue(any('repair check unavailable' in failure for failure in failures))
        self.assertEqual(len(failures), 1, 'native and authority gates otherwise pass')
        self.assertIn(self.cli_stderr, failures[0])
        self.assertIn('stdout:\nfixture runtime check failed', failures[0])

    def test_failed_cli_check_keeps_bounded_diagnostic_tail(self):
        before = self.repair.inspect(self.root, 'cointosd.service')
        self.cli_ok = False
        self.cli_stderr = 'omitted-start\n' + 'x' * 3000 + '\nValueError: exact fixture startup cause'
        failures = self.repair.check(self.root, 'cointosd.service', before)
        self.assertEqual(len(failures), 1)
        self.assertIn('ValueError: exact fixture startup cause', failures[0])
        self.assertNotIn('omitted-start', failures[0])
        diagnostic = failures[0].split('stderr:\n', 1)[1].split('\nstdout:', 1)[0]
        self.assertEqual(len(diagnostic), 2000)

    def test_malformed_terminal_handback_never_becomes_completion(self):
        directory = self.manual_directory()
        for payload in (None, {'outcome': 'complete', 'summary': 'Claim', 'evidence': []}):
            with self.subTest(payload=payload):
                def executor(command, **options):
                    def communicate(prompt):
                        options['stdout'].write(json.dumps({'type': 'thread.started', 'thread_id': 'retained-thread'}) + '\n')
                        Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(payload))
                    return SimpleNamespace(communicate=communicate, returncode=0)
                with patch.object(self.repair.subprocess, 'Popen', side_effect=executor), self.assertRaises(ValueError):
                    self.repair.execute(directory, 'Diagnose fixture')
                self.assertFalse((directory / 'checked.json').exists())
                self.assertIn('retained-thread', (directory / 'events.jsonl').read_text())

    def test_malformed_executor_events_cannot_destroy_the_retained_resume_identity(self):
        directory = self.manual_directory()
        events = [{'type': 'thread.started', 'thread_id': 'retained-thread'}, None, [],
                  {'type': 'thread.started', 'thread_id': None}, {'type': 'thread.started', 'thread_id': 7}]
        (directory / 'events.jsonl').write_text('\n'.join(json.dumps(event) for event in events) + '\n')
        proposal = {'outcome': 'blocked', 'summary': 'Needs concrete recovery evidence', 'evidence': ['Preserved damaged file']}
        commands = []
        def executor(command, **options):
            commands.append(command)
            return SimpleNamespace(returncode=0, communicate=lambda prompt:
                Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(proposal)))
        with patch.object(self.repair.subprocess, 'Popen', side_effect=executor):
            self.assertEqual(self.repair.execute(directory, 'Continue fixture'), proposal)
        self.assertEqual(commands[0][commands[0].index('exec'):commands[0].index('exec') + 3],
                         ['exec', 'resume', 'retained-thread'])


class StartupAuthority(unittest.TestCase):
    def setUp(self):
        from cointos import config, daemon, keys, state
        self.config, self.daemon, self.keys, self.state = config, daemon, keys, state
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.keyfile = self.root / 'keys.json'
        self.keyfile.write_text(json.dumps({'coin': 'kept-coin', 'agents': {'worker': 'kept-worker-key'}}))
        self.enterContext(patch.object(keys, 'KEYS', self.keyfile))
        self.enterContext(patch.object(config, 'LEDGER', self.root / 'ledger.json'))
        self.enterContext(patch.dict(keys.OWNERS, {}, clear=True))
        self.enterContext(patch.dict(keys.ISSUED, {}, clear=True))
        self.enterContext(patch.dict(state.L, {}, clear=True))
        self.enterContext(patch.dict(state.STARTUP, {}, clear=True))
        self.enterContext(patch.dict(state.CONFIG, projects=[]))
        self.recover = self.enterContext(patch.object(daemon.lifecycle, 'recover_landings'))
        self.adopt = self.enterContext(patch.object(daemon.runs, 'adopt'))
        for name in ('recover_transfers', 'forget_orphans', 'forget_untracked'):
            self.enterContext(patch.object(daemon.snapshots, name))
        self.enterContext(patch.object(daemon, 'log'))
        self.enterContext(patch.object(daemon.queues, 'publish'))
        self.enterContext(patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
            [], 0, 'ActiveState=inactive\nMainPID=0\nInvocationID=original-invocation\nLoadState=loaded\n', '')))
        self.previous = {'paused': False, 'tasks': {'task': {'status': 'running', 'agent': 'worker',
                         'session': 'original-session', 'receipt': {'run': 'prior'},
                         'acceptance': {'commit': 'original'}, 'admission_hold': 'user',
                         'validating': 'old-process'}}, 'queue': {'item': {'version': 7, 'held_by': 'user'}}}

    def test_actual_startup_preserves_authority_before_consumers_and_certificate_is_not_durable(self):
        from cointos import startup
        expected = startup.fingerprint(startup.authority(self.previous, [], self.keys.stored()))
        self.daemon.restore(self.previous)
        self.assertEqual(self.state.STARTUP['pid'], os.getpid())
        self.assertEqual(self.state.STARTUP['authority'], expected)
        self.assertEqual(self.state.STARTUP['units']['cointos-agent-worker.service']['state'], 'inactive')
        durable = json.loads((self.root / 'ledger.json').read_text())
        self.assertNotIn('startup', durable)
        self.assertNotIn('validating', durable['tasks']['task'])
        self.assertNotIn('kept-worker-key', json.dumps(self.state.STARTUP))
        self.assertEqual(durable['tasks']['task']['session'], 'original-session')
        self.recover.assert_called_once()
        self.adopt.assert_called_once()

    def test_mutating_fresh_cannot_certify_lost_tasks_queue_holds_or_paused_state(self):
        original = self.daemon.fresh
        def damaged(previous):
            ledger = original(previous)
            ledger['tasks']['task']['session'] = 'replaced'
            ledger['queue']['item']['held_by'] = None
            ledger['paused'] = True
            return ledger
        with patch.object(self.daemon, 'fresh', side_effect=damaged), self.assertRaisesRegex(ValueError, 'startup did not retain authority'):
            self.daemon.restore(self.previous)
        self.assertEqual(self.state.STARTUP, {})
        self.recover.assert_not_called()
        self.adopt.assert_not_called()

    def test_load_that_changes_known_key_refuses_before_recovery(self):
        original = self.keys.load
        def damaged():
            self.keyfile.write_text(json.dumps({'coin': 'kept-coin', 'agents': {'worker': 'changed-key'}}))
            original()
        with patch.object(self.keys, 'load', side_effect=damaged), self.assertRaisesRegex(ValueError, 'keys'):
            self.daemon.restore(self.previous)
        self.assertEqual(self.state.STARTUP, {})
        self.recover.assert_not_called()
        self.adopt.assert_not_called()

    def test_actual_absence_bootstraps_coin_and_certifies_empty_known_keys(self):
        self.keyfile.unlink()
        self.daemon.restore({})
        self.assertIn('coin', self.keys.stored())
        self.assertEqual(self.keys.owner(self.keys.stored()['coin']), ('coin', 'coin'))
        self.assertEqual(self.state.STARTUP['pid'], os.getpid())

    def test_existing_keyless_registry_is_preserved_and_never_bootstrapped(self):
        for registry in ({}, {'agents': {'worker': 'kept-worker-key'}}):
            with self.subTest(registry=registry):
                encoded = json.dumps(registry).encode()
                self.keyfile.write_bytes(encoded)
                with self.assertRaisesRegex(ValueError, 'missing fixed Coin identity'):
                    self.daemon.restore({})
                self.assertEqual(self.keyfile.read_bytes(), encoded)
                self.assertEqual(self.state.STARTUP, {})
        self.recover.assert_not_called()
        self.adopt.assert_not_called()

    def test_failed_recovery_does_not_emit_successful_certificate(self):
        self.recover.side_effect = RuntimeError('recovery failed')
        with self.assertRaisesRegex(RuntimeError, 'recovery failed'):
            self.daemon.restore(self.previous)
        self.assertEqual(self.state.STARTUP, {})



if __name__ == '__main__':
    unittest.main()
