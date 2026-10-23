"""Durable authority is absent only when absent, never when damaged or unsafe to read."""
import copy
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cointos import config, daemon, keys, state
from tests import support


class AuthorityStorage(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        # A refusal regression must remain harmless even before the reader fix:
        # old startup paths can otherwise reach cache cleanup before failing.
        self.enterContext(patch.dict(state.CONFIG, snapshots=str(self.root / 'memory-snapshots'),
                                     disk_snapshots=str(self.root / 'disk-snapshots'), projects=[], trees=[]))
        self.enterContext(patch.object(state.journal, 'STATE', self.root))
        self.enterContext(patch.object(state.journal, 'write'))
        self.enterContext(patch.object(daemon, 'save'))
        self.enterContext(patch.object(daemon.keys, 'load'))
        self.enterContext(patch.object(daemon.runs, 'adopt'))
        self.enterContext(patch.object(daemon.lifecycle, 'recover_landings'))
        self.enterContext(patch.object(daemon.gateway, 'serve', side_effect=AssertionError('unexpected gateway startup')))
        self.enterContext(patch.object(daemon.lanes, 'start', side_effect=AssertionError('unexpected lane startup')))
        self.enterContext(patch.object(daemon, 'shutdown'))
        self.enterContext(patch.object(state.configuration, 'LEDGER', self.root / 'fixture-ledger.json'))
        self.enterContext(patch.object(keys, 'KEYS', self.root / 'fixture-keys.json'))
        for cleanup in ('recover_transfers', 'forget_orphans', 'forget_untracked'):
            self.enterContext(patch.object(daemon.snapshots, cleanup))
        self.enterContext(patch.object(daemon.queues, 'publish'))
        self.enterContext(patch.object(daemon, 'tick', side_effect=AssertionError('startup must refuse before ticks')))
        self.path = self.root / 'authority.json'
        self.operational = self.root / 'config.json'
        self.operational.write_text(json.dumps({'trees': [], 'legacy_setting': 'preserved'}))
        self.child_config = self.root / 'child-config.json'
        self.child_config.write_text(json.dumps(state.CONFIG))
        self.child_projects = self.root / 'child-projects.json'
        self.child_projects.write_text('{"projects":[]}')
        self.child_env = {**os.environ, 'COINTOS_STATE': str(self.root / 'child-state'),
                          'COINTOS_CONFIG': str(self.child_config), 'COINTOS_PROJECTS': str(self.child_projects),
                          'PYTHONDONTWRITEBYTECODE': '1'}

    def deny_read(self, target):
        original = os.open

        def opened(path, *args, **kwargs):
            if Path(path) == target:
                raise PermissionError('fixture authority read denied')
            return original(path, *args, **kwargs)
        return patch.object(config.os, 'open', side_effect=opened)

    def test_reader_preserves_plain_json_and_only_absence_uses_default(self):
        default = {'initial': []}
        self.assertEqual(config.read_owned_json(self.path, default), default)
        for value in ({'legacy': {'nested': [1, False, None]}}, [], False, None):
            with self.subTest(value=value):
                raw = json.dumps(value).encode()
                self.path.write_bytes(raw)
                self.assertEqual(config.read_owned_json(self.path, default), value)
                self.assertEqual(self.path.read_bytes(), raw)

    def test_reader_refuses_malformed_or_duplicate_json_without_rewriting(self):
        for raw in (b'{"unfinished":', b'{"owner":"first","owner":"second"}',
                    b'{"nested":{"owner":1,"owner":2}}'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    config.read_owned_json(self.path, {'fresh': True})
                self.assertEqual(self.path.read_bytes(), raw)

    def test_reader_refuses_read_denial_without_using_default(self):
        raw = b'{"owned":"preserved"}'
        self.path.write_bytes(raw)
        with self.deny_read(self.path), self.assertRaises(PermissionError):
            config.read_owned_json(self.path, {})
        self.assertEqual(self.path.read_bytes(), raw)

    def test_coin_requires_its_recorded_key_without_anonymous_fallback(self):
        from cointos import coin
        with patch.object(coin, 'KEYS', self.path):
            with self.assertRaises(ValueError):
                coin.coin_key()
            for raw in (b'{}', b'{"agents":{}}', b'null', b'{"coin":"same","agents":{"run":"same"}}'):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    coin.coin_key()
                self.assertEqual(self.path.read_bytes(), raw)
            self.path.write_text('{"coin":"fixture-coin-key","agents":{}}')
            self.assertEqual(coin.coin_key(), 'fixture-coin-key')

    def test_registry_missing_allows_initialization_but_valid_plain_entries_stay_compatible(self):
        loaded = config.load(self.operational, self.path)
        self.assertEqual(loaded['projects'], [])
        self.assertEqual(loaded['legacy_setting'], 'preserved')
        entries = [{'name': 'Legacy', 'path': '/example/not-required-to-exist', 'custom': 'kept'}]
        raw = json.dumps({'projects': entries}).encode()
        self.path.write_bytes(raw)
        self.assertEqual(config.load(self.operational, self.path)['projects'], entries)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_registry_corruption_and_read_denial_never_become_empty_enrollment(self):
        malformed = [b'{"projects":', b'null', b'false', b'[]', b'{}', b'{"projects":{}}',
                     b'{"projects":[null]}', b'{"projects":[{"name":17,"path":"/example"}]}',
                     b'{"projects":[{"name":"project","path":false}]}']
        for raw in malformed:
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    config.load(self.operational, self.path)
                self.assertEqual(self.path.read_bytes(), raw)
        raw = b'{"projects":[{"name":"project","path":"/example"}]}'
        self.path.write_bytes(raw)
        with self.deny_read(self.path), self.assertRaises(PermissionError):
            config.load(self.operational, self.path)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_operational_config_requires_an_object_without_touching_registry(self):
        self.path.write_bytes(b'{"projects":[]}')
        for raw in (b'null', b'false', b'[]'):
            with self.subTest(raw=raw):
                self.operational.write_bytes(raw)
                with self.assertRaises(ValueError):
                    config.load(self.operational, self.path)
                self.assertEqual(self.operational.read_bytes(), raw)
                self.assertEqual(self.path.read_bytes(), b'{"projects":[]}')

    def test_invalid_ledger_refuses_startup_before_mutation_adoption_or_save(self):
        malformed = [b'{"tasks":', b'null', b'false', b'[]',
                     b'{"tasks":[]}', b'{"agents":[]}', b'{"queue":[]}', b'{"snapshots":[]}',
                     b'{"history":{}}', b'{"messages":{}}', b'{"tasks":{"task":null}}',
                     b'{"agents":{"run":17}}', b'{"queue":{"record":[]}}', b'{"snapshots":{"snapshot":false}}']
        for raw in malformed:
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                before = copy.deepcopy(state.L)
                with patch.object(daemon, 'LEDGER', self.path), patch.object(daemon.faulthandler, 'register'), \
                        patch.object(daemon.keys, 'load') as load_keys, patch.object(daemon.runs, 'adopt') as adopt, \
                        patch.object(daemon.lifecycle, 'recover_landings') as recover, \
                        patch.object(daemon, 'save') as save, patch.object(daemon.gateway, 'serve',
                            side_effect=AssertionError('invalid authority reached gateway startup')) as serve, \
                        patch.object(daemon.lanes, 'start') as lanes:
                    with self.assertRaises(ValueError):
                        daemon.main()
                    for effect in (load_keys, adopt, recover, save, serve, lanes):
                        effect.assert_not_called()
                self.assertEqual(state.L, before)
                self.assertEqual(self.path.read_bytes(), raw)

    def test_ledger_read_denial_refuses_startup_without_side_effects(self):
        raw = b'{"tasks":{},"agents":{},"queue":{},"snapshots":{}}'
        self.path.write_bytes(raw)
        before = copy.deepcopy(state.L)
        with patch.object(daemon, 'LEDGER', self.path), patch.object(daemon.faulthandler, 'register'), \
                self.deny_read(self.path), patch.object(daemon, 'restore') as restore, \
                patch.object(daemon.gateway, 'serve') as serve:
            with self.assertRaises(PermissionError):
                daemon.main()
            restore.assert_not_called()
            serve.assert_not_called()
        self.assertEqual(state.L, before)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_absent_ledger_reaches_initialization_with_an_empty_object(self):
        class Initialized(Exception):
            pass
        with patch.object(daemon, 'LEDGER', self.path), patch.object(daemon.faulthandler, 'register'), \
                patch.object(daemon, 'restore', side_effect=Initialized) as restore:
            with self.assertRaises(Initialized):
                daemon.main()
            restore.assert_called_once_with({})
        self.assertFalse(self.path.exists())

    def test_fresh_validates_all_retained_containers_before_touching_task_entries(self):
        previous = {'tasks': {'old': {'status': 'done', 'validating': True}}, 'history': {}}
        before = copy.deepcopy(previous)
        with self.assertRaises(ValueError):
            state.fresh(previous)
        self.assertEqual(previous, before, 'validation must precede removal of stale task flags')
        compatible = {'tasks': {}, 'agents': {}, 'queue': {}, 'snapshots': {}, 'history': [], 'legacy_field': True}
        self.assertEqual(state.fresh(compatible)['tasks'], {})

    def installer_fixture(self):
        source, target = self.root / 'source', self.root / 'runtime'
        for root in (source, target):
            (root / 'config').mkdir(parents=True, exist_ok=True)
        (target / 'state').mkdir(exist_ok=True)
        (target / '.runtime-install').touch()
        (source / 'config/cointos.json').write_text(json.dumps(state.CONFIG))
        (source / 'config/projects.json').write_text('{"projects":[]}')
        (target / 'state/cointos.json').write_text('{}')
        (target / 'state/keys.json').write_text('{"coin":"fixture-coin","agents":{}}')
        (target / 'config/projects.json').write_text('{"projects":[]}')
        return source, target

    def test_installer_authority_preflight_refuses_before_any_stop_copy_or_control(self):
        source, target = self.installer_fixture()
        installer = Path(__file__).resolve().parents[1] / 'scripts/install'
        program = '''import pathlib,runpy,sys
from unittest.mock import Mock,patch
ns=runpy.run_path(sys.argv[1],run_name="authority_fixture"); scope=ns["install"].__globals__
effects={name:Mock(side_effect=AssertionError("unexpected effect: "+name)) for name in ("run","copy_runtime","api","write_runtime_knowledge")}
with patch.dict(scope,{**effects,"source":pathlib.Path(sys.argv[2]),"target":pathlib.Path(sys.argv[3]),"units":pathlib.Path(sys.argv[3])/"units"}), patch.object(scope["urllib"].request,"urlopen",side_effect=AssertionError("unexpected network control")):
 try: scope["install"]()
 except (OSError,ValueError): pass
 else: raise AssertionError("damaged authority was accepted")
 for effect in effects.values(): effect.assert_not_called()
print("REFUSED BEFORE EFFECTS")
'''
        for relative in ('state/cointos.json', 'state/keys.json', 'config/projects.json'):
            path = target / relative
            original = path.read_bytes()
            for form in ('malformed', 'fifo'):
                with self.subTest(file=relative, form=form):
                    path.unlink()
                    if form == 'fifo':
                        os.mkfifo(path)
                    else:
                        path.write_bytes(b'{"unfinished":')
                    try:
                        result = subprocess.run([sys.executable, '-c', program, str(installer), str(source), str(target)],
                                                capture_output=True, text=True, timeout=3, env=self.child_env)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), 'REFUSED BEFORE EFFECTS')
                        if form == 'malformed':
                            self.assertEqual(path.read_bytes(), b'{"unfinished":')
                    finally:
                        path.unlink()
                        path.write_bytes(original)

    def test_installer_preflight_retains_supported_legacy_enrollment_list(self):
        source, target = self.installer_fixture()
        entries = [{'name': 'legacy', 'path': '/example/legacy'}]
        registry = target / 'config/projects.json'
        raw = json.dumps(entries).encode()
        registry.write_bytes(raw)
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/install'), run_name='authority_fixture')
        scope = namespace['install'].__globals__
        class PreflightPassed(Exception):
            pass
        with patch.dict(scope, source=source, target=target, units=self.root / 'units'), \
                patch.dict(scope, {name: unittest.mock.Mock(side_effect=AssertionError('unexpected effect'))
                                   for name in ('run', 'copy_runtime', 'api', 'write_runtime_knowledge')}), \
                patch.object(scope['urllib'].request, 'urlopen', side_effect=PreflightPassed):
            with self.assertRaises(PreflightPassed):
                namespace['install']()
            for name in ('run', 'copy_runtime', 'api', 'write_runtime_knowledge'):
                scope[name].assert_not_called()
        self.assertEqual(registry.read_bytes(), raw)

    def test_upgrader_distinguishes_null_from_absence_and_preserves_valid_legacy_data(self):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/upgrade-ledger'), run_name='authority_fixture')
        scope = namespace['main'].__globals__
        path = self.root / 'migration/state/cointos.json'
        path.parent.mkdir(parents=True)
        with patch.dict(scope, upgrade=unittest.mock.Mock(side_effect=AssertionError('unexpected migration'))):
            namespace['main'](path)
            scope['upgrade'].assert_not_called()
            self.assertFalse(path.exists())
            path.write_bytes(b'null')
            with self.assertRaises(ValueError):
                namespace['main'](path)
            scope['upgrade'].assert_not_called()
            self.assertEqual(path.read_bytes(), b'null')
        registry = path.parent.parent / 'config/projects.json'
        registry.parent.mkdir()
        entries = [{'name': 'legacy', 'path': '/example/legacy'}]
        registry.write_text(json.dumps(entries))
        previous = {'tasks': {}, 'queue': {}, 'snapshots': {}, 'legacy_field': {'kept': True}}
        path.write_text(json.dumps(previous))
        with patch.dict(scope, git=unittest.mock.Mock(side_effect=AssertionError('unexpected Git mutation'))):
            namespace['main'](path)
            scope['git'].assert_not_called()
        self.assertEqual(json.loads(path.read_text()), {**previous, 'frontier_version': 1})
        self.assertEqual(json.loads(registry.read_text()), entries)

    def test_special_authority_files_refuse_without_blocking_or_initializing(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        dangling = self.root / 'dangling'
        dangling.symlink_to(self.root / 'absent-target')
        ordinary = self.root / 'regular'
        ordinary.write_bytes(b'{"agents":{}}')
        symlink = self.root / 'symlink'
        symlink.symlink_to(ordinary)
        directory = self.root / 'directory'
        directory.mkdir()
        program = '''import pathlib,sys
from cointos import config,keys,daemon
path=pathlib.Path(sys.argv[1]); reader=sys.argv[2]
def unexpected(*args): raise AssertionError("unsafe authority reached restore")
try:
 if reader=="keys":
  keys.KEYS=path; keys.stored()
 elif reader=="ledger":
  daemon.LEDGER=path; daemon.restore=unexpected; daemon.main()
 else: config.read_owned_json(path,{})
except (OSError,ValueError):
 print("REFUSED")
else: raise AssertionError("unsafe authority treated as valid or absent")
'''
        for path in (fifo, dangling, symlink, directory):
            for reader in ('owned', 'keys', 'ledger'):
                with self.subTest(path=path.name, reader=reader):
                    result = subprocess.run([sys.executable, '-c', program, str(path), reader],
                                            capture_output=True, text=True, timeout=3, env=self.child_env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), 'REFUSED')
                    self.assertTrue(path.exists() or path.is_symlink())
        self.assertEqual(ordinary.read_bytes(), b'{"agents":{}}')
        self.assertFalse((self.root / 'absent-target').exists())


if __name__ == '__main__':
    unittest.main()
