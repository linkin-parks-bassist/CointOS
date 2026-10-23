"""Repair handback must permit actual lifecycle progress after daemon recovery."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cointos import api, daemon, gateway, git, keys, lifecycle, opencode, projects, repair, state, tasks
from tests.pipeline_simulator import Simulation


class RepairProgress(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation()
        self.addCleanup(self.sim.close)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='cointos-repair-progress-')))
        (self.root / 'state').mkdir()
        (self.root / 'config').mkdir()
        product = self.root / 'fixture-product'
        product.mkdir()
        self.sim.project['path'] = str(product)
        settings = copy.deepcopy(state.CONFIG)
        settings.update(snapshots=str(self.root / 'cache'), disk_snapshots=str(self.root / 'disk'))
        self.enterContext(patch.dict(state.CONFIG, snapshots=settings['snapshots'], disk_snapshots=settings['disk_snapshots']))
        (self.root / 'config/cointos.json').write_text(json.dumps(settings))
        (self.root / 'config/projects.json').write_text(json.dumps({'projects': settings['projects']}))
        (self.root / 'state/keys.json').write_text(json.dumps({'coin': 'fixture-fixed-coin', 'agents': {}}))
        self.enterContext(patch.object(keys, 'KEYS', self.root / 'state/keys.json'))
        self.enterContext(patch.dict(keys.OWNERS, {}, clear=True))
        self.enterContext(patch.dict(keys.ISSUED, {}, clear=True))
        self.enterContext(patch.object(keys, 'ENDED', set()))
        self.enterContext(patch.dict(state.STARTUP, {}, clear=True))
        self.enterContext(patch.object(opencode, 'active', side_effect=lambda run:
                                     self.unit_overrides.get(run, {}).get('ActiveState', 'active')
                                     not in ('inactive', 'failed')))
        self.enterContext(patch.object(opencode, 'stop_group'))
        self.enterContext(patch.object(opencode, 'find_processes', side_effect=lambda:
                                     {run: [pid] for run, pid in self.unit_pids.items()
                                      if self.unit_overrides.get(run, {}).get('ActiveState', 'active')
                                      not in ('inactive', 'failed')}))
        for name in ('recover_transfers', 'forget_orphans', 'forget_untracked'):
            self.enterContext(patch.object(daemon.snapshots, name))
        self.unit_pids = {}
        self.unit_overrides = {}
        self.query_failures = set()
        self.producer_calls = 0
        self.enterContext(patch.object(repair.subprocess, 'run', side_effect=self.native))
        self.enterContext(patch.object(gateway.projects, 'about', return_value='fixture project'))
        self.enterContext(patch.object(repair.urllib.request, 'urlopen', side_effect=self.api_view))

    def api_view(self, url, **options):
        handler = object.__new__(gateway.Handler)
        handler.path = '/api/ledger'
        emitted = []
        handler.reply = lambda status, value: emitted.append((status, value))
        gateway.Handler.do_GET(handler)
        self.assertEqual(emitted[0][0], 200)
        return io.BytesIO(json.dumps(emitted[0][1]).encode())

    def native(self, command, **options):
        if command[:4] == [sys.executable, '-m', 'cointos.cli', 'check']:
            self.assertEqual(options['cwd'], self.root)
            self.assertEqual(options['env']['COINTOS_STATE'], str(self.root / 'state'))
            return subprocess.CompletedProcess(command, 0, 'fixture checks passed', '')
        self.assertEqual(command[0], 'systemctl')
        if 'list-units' in command:
            output = ''.join(f'cointos-agent-{run}.service loaded active running fixture\n' for run in self.unit_pids)
        else:
            self.assertEqual(command[:3], ['systemctl', '--user', 'show'])
            unit = command[3]
            run = unit.removeprefix('cointos-agent-').removesuffix('.service')
            if run in self.query_failures:
                raise subprocess.CalledProcessError(1, command, stderr='fixture bus query refused')
            pid = os.getpid() if unit == 'cointosd.service' else self.unit_pids[run]
            fields = {'ActiveState': 'active', 'MainPID': str(pid),
                      'InvocationID': 'fixture-' + run, 'LoadState': 'loaded'}
            fields.update(self.unit_overrides.get(run, {}))
            output = ''.join(f'{name}={value}\n' for name, value in fields.items() if value is not None)
        return subprocess.CompletedProcess(command, 0, output, '')

    def baseline(self):
        for agent in state.L['agents'].values():
            agent['place'] = state.L['tasks'][agent['task']]['place']
        state.L['checks'] = [{'name': 'fixture runtime', 'ok': True}]
        (self.root / 'state/cointos.json').write_text(json.dumps(state.L))
        self.unit_pids = {run: 501 + index for index, run in enumerate(state.L['agents'])}
        keys.KEYS.write_text(json.dumps({'coin': 'fixture-fixed-coin',
                                        'agents': {run: 'fixture-key-' + run for run in self.unit_pids}}))
        before = repair.inspect(self.root, 'cointosd.service')
        daemon.restore(copy.deepcopy(state.L))
        state.L['checks'] = [{'name': 'fixture runtime', 'ok': True}]
        self.producer_calls += 1
        self.sim.worker = state.L['tasks'][self.sim.worker['id']]
        if self.sim.integration:
            self.sim.integration = state.L['tasks'][self.sim.integration['id']]
        self.assertEqual(state.STARTUP['pid'], os.getpid())
        self.assertEqual(state.STARTUP['authority'], before['authority'])
        self.certified = copy.deepcopy(state.STARTUP)
        self.assertEqual(repair.check(self.root, 'cointosd.service', before), [])
        return before

    def checked_progress(self, before):
        (self.root / 'state/cointos.json').write_text(json.dumps(state.L))
        self.assertEqual(state.STARTUP, self.certified, 'runtime progress rewrote restoration evidence')
        self.assertEqual(self.producer_calls, 1, 'restoration was not certified by actual producer')
        return repair.check(self.root, 'cointosd.service', before)

    def test_actual_failed_worker_revision_can_progress_after_runtime_recovery(self):
        self.sim.reset('worker_blocked', 62901)
        worker = self.sim.worker
        worker['session'] = 'retained-prior-session'
        manager, _ = tasks.request_repair(worker)
        self.sim.start(manager, 'manager')
        commit = self.sim.refs[worker['branch']]
        before = self.baseline()
        worker = self.sim.worker
        api.dispatch('revise', {'caller': {'task': manager['id'], 'run': 'manager'}, 'item': worker['record'],
                                'reason': 'correct the independently verified brief',
                                'dependencies': state.L['queue'][worker['record']]['depends'],
                                'brief': 'Summary: Implement the clarified API using existing ownership and checked recovery evidence'})
        self.assertEqual(worker['status'], 'waiting')
        self.assertIsNone(worker['receipt'])
        self.assertIsNone(worker['session'])
        self.assertEqual(worker['record_version'], 2)
        self.assertEqual(self.sim.refs[worker['branch']], commit)
        self.assertEqual(self.checked_progress(before), [])

    def test_explicit_budget_retry_preserves_assignment_and_changes_session(self):
        self.sim.reset('none', 62902)
        task = self.sim.integration
        task['session'] = 'retained-prior-session'
        commit = self.sim.refs[task['branch']]
        before = self.baseline()
        task = self.sim.integration
        with patch.dict(state.CONFIG['recovery']['role_fresh_retries'], integrator=1):
            lifecycle.retry_fresh('integrator', 'generation budget exhausted', 'checked continuation evidence')
        self.assertEqual(task['status'], 'waiting')
        self.assertIsNone(task['session'])
        self.assertEqual(task['fresh_retries'], 1)
        self.assertEqual(task['recovery_context'], 'checked continuation evidence')
        self.assertEqual(self.sim.refs[task['branch']], commit)
        self.assertEqual(self.checked_progress(before), [])

    def test_producer_refuses_protected_authority_lost_during_restore(self):
        self.sim.reset('worker_blocked', 62904)
        self.sim.worker['admission_hold'] = 'paused by the user'
        state.L['queue'][self.sim.worker['record']]['held_by'] = 'user'
        before = self.baseline()
        original = daemon.fresh
        def lose_authority(previous):
            restored = original(previous)
            restored['tasks'][self.sim.worker['id']]['receipt'] = None
            restored['tasks'][self.sim.worker['id']].pop('admission_hold')
            restored['queue'][self.sim.worker['record']]['held_by'] = None
            return restored
        with patch.object(daemon, 'fresh', side_effect=lose_authority):
            with self.assertRaisesRegex(ValueError, 'startup did not retain authority'):
                daemon.restore(copy.deepcopy(state.L))
        self.assertEqual(state.STARTUP, {}, 'failed restore retained a reusable success certificate')
        self.assertTrue(any('retained authority' in item for item in repair.check(
            self.root, 'cointosd.service', before)))

    def test_guard_refuses_erasure_before_certification_even_with_healthy_api(self):
        self.sim.reset('worker_blocked', 62905)
        before = self.baseline()
        erased = copy.deepcopy(state.L)
        erased['tasks'].pop(self.sim.worker['id'])
        erased['queue'].pop(self.sim.worker['record'])
        daemon.restore(erased)
        state.L['checks'] = [{'name': 'fixture runtime', 'ok': True}]
        self.assertNotEqual(state.STARTUP['authority'], before['authority'])
        self.assertTrue(all(check['ok'] for check in state.L['checks']))
        self.assertTrue(any('retained authority' in item for item in repair.check(
            self.root, 'cointosd.service', before)), 'healthy API disguised original authority erasure')

    def test_actual_project_settings_and_disable_can_progress_after_restore(self):
        self.sim.reset('none', 62906)
        before = self.baseline()
        update = projects.update
        registry = self.root / 'config/projects.json'
        def update_owned(config, name, settings):
            return update(config, name, settings, path=registry)
        def git_metadata(repo, *args):
            self.assertEqual(Path(repo), self.root / 'fixture-product')
            self.assertIn(args, [('rev-parse', '--show-toplevel'), ('branch', '--show-current')])
            return subprocess.CompletedProcess(args, 0, str(repo) if args[0] == 'rev-parse' else 'main', '')
        with patch.object(projects, 'update', side_effect=update_owned), \
             patch.object(git, 'result', side_effect=git_metadata):
            for settings in ({'priority': 15}, {'enabled': False}):
                api.dispatch('project-set', {'project': 'sim', 'settings': settings})
                self.assertEqual(self.checked_progress(before), [])
        self.assertFalse(state.CONFIG['projects'][0]['enabled'])
        self.assertFalse(state.L['agents'], 'disable did not release its live assignment')

    def test_disk_enrollment_change_without_live_authority_is_refused(self):
        self.sim.reset('worker_blocked', 62907)
        before = self.baseline()
        registry = self.root / 'config/projects.json'
        data = json.loads(registry.read_text())
        data['projects'][0]['enabled'] = False
        registry.write_text(json.dumps(data))
        failures = self.checked_progress(before)
        self.assertTrue(any('current enrollment differs' in item for item in failures),
                        'disk-only project alteration masqueraded as authorized daemon progress')

    def certify_again(self):
        daemon.restore(copy.deepcopy(state.L))
        state.L['checks'] = [{'name': 'fixture runtime', 'ok': True}]

    def test_changed_surviving_pid_before_restore_is_refused(self):
        self.sim.reset('none', 62908)
        before = self.baseline()
        self.unit_pids['integrator'] += 10000
        self.certify_again()
        self.assertEqual(state.STARTUP['units']['cointos-agent-integrator.service']['pid'], '10501')
        self.assertTrue(any('surviving unit identity changed' in item for item in
                            repair.check(self.root, 'cointosd.service', before)))

    def test_changed_native_invocation_before_restore_is_refused(self):
        self.sim.reset('none', 62909)
        before = self.baseline()
        self.unit_overrides['integrator'] = {'InvocationID': 'replacement-invocation'}
        self.certify_again()
        self.assertTrue(any('surviving unit identity changed' in item for item in
                            repair.check(self.root, 'cointosd.service', before)))

    def test_confirmed_terminal_unit_at_birth_recovers_without_reopening_receipt(self):
        self.sim.reset('none', 62910)
        before = self.baseline()
        receipt = copy.deepcopy(self.sim.worker['receipt'])
        commit = self.sim.refs[self.sim.integration['branch']]
        self.unit_overrides['integrator'] = {'ActiveState': 'inactive', 'MainPID': '0'}
        self.certify_again()
        integration = state.L['tasks'][self.sim.integration['id']]
        worker = state.L['tasks'][self.sim.worker['id']]
        self.assertEqual(integration['status'], 'waiting')
        self.assertFalse(state.L['agents'])
        self.assertEqual(worker['status'], 'review')
        self.assertEqual(worker['receipt'], receipt)
        self.assertEqual(self.sim.refs[integration['branch']], commit)
        self.assertEqual(repair.check(self.root, 'cointosd.service', before), [])

    def test_unknown_or_missing_native_birth_evidence_is_refused(self):
        self.sim.reset('none', 62911)
        before = self.baseline()
        for fields in ({'ActiveState': 'unknown'}, {'LoadState': None}, {'LoadState': 'not-found'}):
            with self.subTest(fields=fields):
                self.unit_overrides['integrator'] = fields
                self.certify_again()
                self.assertTrue(any('native ownership unavailable' in item for item in
                                    repair.check(self.root, 'cointosd.service', before)))

    def test_refused_native_birth_query_cannot_reuse_previous_certificate(self):
        self.sim.reset('none', 62912)
        before = self.baseline()
        self.query_failures.add('integrator')
        with self.assertRaises(subprocess.CalledProcessError):
            daemon.restore(copy.deepcopy(state.L))
        self.assertEqual(state.STARTUP, {})
        self.assertTrue(any('retained authority' in item or 'native ownership unavailable' in item
                            for item in repair.check(self.root, 'cointosd.service', before)))

    def test_actual_terminal_history_cleanup_can_follow_verified_landing(self):
        self.sim.reset('none', 62903)
        from cointos import landing
        landing.land(self.sim.integration['id'], self.sim.candidate, 'integrator')
        with patch.object(opencode, 'watch', return_value={'finish': 'stop', 'code': 0}):
            from cointos import runs
            runs.follow('integrator', None, None)
        accepted = copy.deepcopy(self.sim.worker['acceptance'])
        self.assertEqual(accepted['commit'], self.sim.refs['main'])
        before = self.baseline()
        removed = api.dispatch('clear-task-history', {})
        self.assertEqual(removed['task_records'], 2)
        self.assertEqual(removed['queue_records'], 2)  # implementation and independent contract
        self.assertEqual(self.sim.refs['main'], accepted['commit'])
        self.assertEqual(self.checked_progress(before), [])
