"""Installer boundary: executable assets deploy; live data and overrides survive."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('install_cointos', str(ROOT / 'scripts/install-cointos'))
spec = importlib.util.spec_from_loader(loader.name, loader)
installer = importlib.util.module_from_spec(spec)
loader.exec_module(installer)


def test_installed_commands_work_without_checkout():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        source, prefix = base / 'source', base / 'runtime'
        source.mkdir()
        for name in installer.PAYLOAD:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, source / name, ignore=shutil.ignore_patterns('__pycache__'))
            else:
                shutil.copy2(src, source / name)
        installer.install(source, prefix)
        shutil.rmtree(source)
        env = dict(os.environ, COINTOS_RUNTIME_ROOT=str(prefix))
        env.pop('PYTHONPATH', None)
        for command in ([str(prefix / 'scripts/ecosystem'), '--help'],
                        [str(prefix / 'scripts/cointos-opencode'), '--help'],
                        ['python3', '-c', 'from ecosystem import cli; from survival import guardian; '
                         'print(cli.ROOT)']):
            result = subprocess.run(command, cwd=prefix if command[0] == 'python3' else base,
                                    env=env, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
        assert str(prefix) in result.stdout
        assert not (prefix / '.git').exists()
        assert (prefix / '.knowledge/where/am/i.md').exists()
        assert not (prefix / 'tests').exists()


def test_upgrade_preserves_state_and_local_configuration():
    with tempfile.TemporaryDirectory() as temporary:
        prefix = Path(temporary) / 'runtime'
        state = prefix / 'state/jobs/task.json'
        state.parent.mkdir(parents=True)
        state.write_text('{"state":"running"}')
        logs = prefix / 'logs/run.jsonl'
        logs.parent.mkdir()
        logs.write_text('original evidence\n')
        installer.install(ROOT, prefix)
        config = prefix / 'config/opencode-capacity.json'
        config.write_text('{"local":true}')
        custom = prefix / 'config/custom.cfg'
        custom.write_text('custom override')
        obsolete = prefix / 'ecosystem/obsolete.py'
        obsolete.write_text('stale executable')
        leaf = prefix / '.knowledge/where/am/i.md'
        leaf.write_text(leaf.read_text() + '\nInstalled-only addition.\n')
        added = prefix / '.knowledge/what/is/runtime/discovery.md'
        added.parent.mkdir(parents=True)
        added.write_text('New runtime knowledge.\n')
        installer.install(ROOT, prefix)
        assert state.read_text() == '{"state":"running"}'
        assert logs.read_text() == 'original evidence\n'
        assert config.read_text() == '{"local":true}'
        assert custom.read_text() == 'custom override'
        assert 'Installed-only addition.' in leaf.read_text()
        assert added.read_text() == 'New runtime knowledge.\n'
        assert config.with_name(config.name + '.dist').exists()
        assert not obsolete.exists()
        assert (prefix / '.cointos-previous/ecosystem/obsolete.py').exists()
        metadata = json.loads((prefix / installer.MANIFEST).read_text())
        assert metadata['source']['revision']
        assert 'config/opencode-capacity.json' in metadata['preserved_config']
        text = (prefix / 'roles/worker.md').read_text()
        assert str(prefix / 'scripts/tell-david') in text
        assert str(prefix / 'scripts/ecosystem') in (prefix / 'services/systemd/agent-ecosystem.service').read_text()


def test_failed_replacement_restores_previous_payload():
    with tempfile.TemporaryDirectory() as temporary:
        prefix = Path(temporary) / 'runtime'
        installer.install(ROOT, prefix)
        (prefix / 'ecosystem/sentinel').write_text('previous version')
        manifest = (prefix / installer.MANIFEST).read_bytes()
        rename = Path.rename
        def fail_once(path, destination):
            if path.name == 'roles' and path.parent.name.startswith('.cointos-stage-'):
                raise OSError('simulated replacement failure')
            return rename(path, destination)
        with patch.object(Path, 'rename', fail_once):
            try:
                installer.install(ROOT, prefix)
            except OSError:
                pass
            else:
                raise AssertionError('expected replacement failure')
        assert (prefix / 'ecosystem/sentinel').read_text() == 'previous version'
        assert (prefix / installer.MANIFEST).read_bytes() == manifest
        assert (prefix / 'roles/worker.md').exists()


def test_dry_run_and_bad_destination_do_not_write_payload():
    with tempfile.TemporaryDirectory() as temporary:
        prefix = Path(temporary) / 'runtime'
        installer.install(ROOT, prefix, dry_run=True)
        assert not prefix.exists()
        with patch.object(installer, 'PAYLOAD', ('missing-required-payload',)):
            try:
                installer.install(ROOT, prefix)
            except ValueError:
                pass
            else:
                raise AssertionError('missing source must fail')
        assert not prefix.exists()
        prefix.mkdir()
        (prefix / 'config').symlink_to(ROOT / 'config', target_is_directory=True)
        try:
            installer.install(ROOT, prefix)
        except ValueError:
            pass
        else:
            raise AssertionError('symlink destination must fail')


def test_conflicting_knowledge_stops_upgrade_before_replacement():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        source, prefix = base / 'source', base / 'runtime'
        source.mkdir()
        for name in installer.PAYLOAD:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, source / name, ignore=shutil.ignore_patterns('__pycache__'))
            else:
                shutil.copy2(src, source / name)
        installer.install(source, prefix)
        relative = '.knowledge/what/is/cointos.md'
        (prefix / relative).write_text('Runtime edit.\n')
        (source / relative).write_text('Independent source edit.\n')
        original = (prefix / installer.MANIFEST).read_bytes()
        try:
            installer.install(source, prefix)
        except ValueError as exc:
            assert 'conflicting' in str(exc)
        else:
            raise AssertionError('divergent edits must stop upgrade')
        assert (prefix / relative).read_text() == 'Runtime edit.\n'
        assert (prefix / installer.MANIFEST).read_bytes() == original
        runtime_leaf = '---\nstatus: unverified\nsource: runtime review\nupdated_at: today\n---\nReconciled answer.\n'
        source_leaf = '---\nstatus: unverified\nsource: source evidence\nupdated_at: yesterday\n---\nReconciled answer.\n'
        (prefix / relative).write_text(runtime_leaf)
        (source / relative).write_text(source_leaf)
        installer.install(source, prefix)
        assert (prefix / relative).read_text() == runtime_leaf
        (source / relative).write_text(source_leaf.replace('status: unverified', 'status: falsified'))
        try:
            installer.install(source, prefix)
        except ValueError as exc:
            assert 'conflicting' in str(exc)
        else:
            raise AssertionError('status divergence must still stop upgrade')


def test_noninteractive_install_grants_only_its_knowledge_root():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        prefix = base / 'runtime'
        registry = base / 'roots.json'
        other = base / 'unrelated/.knowledge'
        other.mkdir(parents=True)
        kt = shutil.which('kt')
        assert kt, 'standalone KT is required for the installation boundary test'
        env = dict(os.environ, KT_CONFIG=str(registry))
        subprocess.run([kt, 'register', 'unrelated', str(other)], env=env, check=True,
                       capture_output=True)
        command = [str(ROOT / 'scripts/install-cointos'), '--prefix', str(prefix)]
        for _ in range(2):
            result = subprocess.run(command, cwd=base, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=20)
            assert result.returncode == 0, result.stderr + result.stdout
        saved = json.loads(registry.read_text())
        assert saved['roots']['cointos']['access'] == 'allow'
        assert saved['roots']['unrelated']['access'] == 'ask'
        assert not saved.get('dangerously_skip_permissions')
        result = subprocess.run([kt, 'open', 'cointos:what/is/cointos.md'],
                                cwd=base, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_installed_commands_work_without_checkout,
        test_upgrade_preserves_state_and_local_configuration,
        test_failed_replacement_restores_previous_payload,
        test_dry_run_and_bad_destination_do_not_write_payload,
        test_conflicting_knowledge_stops_upgrade_before_replacement,
        test_noninteractive_install_grants_only_its_knowledge_root,
    ))
