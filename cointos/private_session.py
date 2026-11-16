"""Disposable local OpenCode sessions using CointOS scheduling without transcripts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import resource
import shutil
import secrets
import signal
import subprocess
import sys
import tempfile

from cointos.config import ROOT, api_url, load
from cointos import private_clients


def configured_settings() -> dict:
    """Read ordinary user configuration without its session store."""
    native = Path.home() / '.config/opencode2/opencode/opencode.json'
    legacy = Path.home() / '.config/opencode/opencode.json'
    path = native if native.is_file() else legacy
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def configured_cli() -> dict:
    for parent in (Path.home() / '.config/opencode2/opencode', Path.home() / '.config/opencode'):
        path = parent / 'cli.json'
        if path.is_file():
            return json.loads(path.read_text())
    return {}


def configured_mcp() -> dict:
    return configured_settings().get('mcp', {})


def private_mcp(directory: Path) -> dict:
    """Keep installed tool runtimes, but put browser output/profile in tmpfs."""
    settings = configured_mcp()
    for name, server in settings.get('servers', {}).items():
        if name != 'playwright' or not isinstance(server, dict):
            continue
        command = list(server.get('command', []))
        if '--user-data-dir' in command:
            index = command.index('--user-data-dir')
            command[index + 1] = str(directory / 'browser-profile')
        else:
            command += ['--user-data-dir', str(directory / 'browser-profile')]
        command += ['--output-dir', str(directory / 'browser-output')]
        server['command'] = ['env', 'PLAYWRIGHT_BROWSERS_PATH=' + os.environ.get(
            'PLAYWRIGHT_BROWSERS_PATH', str(Path.home() / '.cache/ms-playwright')), *command]
    return settings


def environment(directory: Path, config: dict, *, workdir: Path | None = None) -> dict:
    """Keep database in memory and ancillary stores in a private tmpfs directory."""
    for name in ('data', 'config', 'state', 'cache', 'tmp'):
        (directory / name).mkdir(mode=0o700)
    # V2 writes prompt-bearing diagnostic records even with --log-level none.
    # Give its actual log destination a sink before the server starts.
    log = directory / 'data/opencode/log'
    log.mkdir(parents=True, mode=0o700)
    (log / 'opencode.log').symlink_to('/dev/null')
    shape = config['models'][config['work_model']]
    ordinary = configured_settings()
    station = (workdir or Path.cwd()).resolve()
    settings = {**ordinary,
        'model': 'cointos/default', 'small_model': 'cointos/default',
        'providers': {'cointos': {
            'package': '@opencode/ai/providers/openai-compatible',
            'settings': {'baseURL': api_url(config) + '/v1/private',
                         'apiKey': secrets.token_urlsafe(32), 'timeout': False,
                         'headerTimeout': False, 'chunkTimeout': False},
            'models': {'default': {'name': 'CointOS private local', 'limit': {
                'context': shape['ctx_size'] // int(shape.get('slots') or shape['lanes']),
                'output': config['scheduler']['max_thought_tokens']}}}}},
        'plugins': [*ordinary.get('plugins', ordinary.get('plugin', [])),
                    str(ROOT / 'cointos/private_session_plugin')],
        'skills': ordinary.get('skills', []),
        'instructions': [*ordinary.get('instructions', []),
                         *[str(parent / 'AGENTS.md') for parent in (*reversed(station.parents), station)]],
        'mcp': private_mcp(directory), 'share': 'disabled', 'update': 'disable',
        'snapshots': False,
    }
    private_clients.register(directory, settings['providers']['cointos']['settings']['apiKey'])
    settings.pop('plugin', None)  # V2 uses plugins; avoid loading either list twice.
    path = directory / 'opencode.json'
    path.write_text(json.dumps(settings))
    path.chmod(0o600)
    cli = configured_cli()
    cli_path = directory / 'config/opencode/cli.json'
    cli_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path.write_text(json.dumps(cli))
    cli_path.chmod(0o600)
    models = directory / 'models.json'
    models.write_text('{}')
    env = {**os.environ, **{f'XDG_{n.upper()}_HOME': str(directory / n)
                           for n in ('data', 'config', 'state', 'cache')},
           'TMPDIR': str(directory / 'tmp'), 'OPENCODE_DB': ':memory:',
           'KT_HOOK_STATE_DIR': str(directory / 'state/knowledgetrees'),
           'OPENCODE_CONFIG': str(path), 'OPENCODE_MODELS_PATH': str(models),
           'OPENCODE_DISABLE_MODELS_FETCH': '1', 'OPENCODE_DISABLE_FREE_MODELS': '1',
           'OPENCODE_DISABLE_AUTOUPDATE': '1'}
    # Inherited inline config could reintroduce hosted providers or plugins.
    env.pop('OPENCODE_CONFIG_CONTENT', None)
    env['OPENCODE_CLI_CONFIG_CONTENT'] = json.dumps(cli)
    return env


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '--cleanup':
        # Only the launcher passes this pipe. EOF also arrives after SIGKILL,
        # allowing a separate process to remove transient stores after a crash.
        fd, pgid = int(args[1]), int(args[2])
        directory = Path(args[3])
        if directory.parent != Path('/dev/shm') or not directory.name.startswith('cointos-private-'):
            raise SystemExit('Invalid private cleanup directory')
        with os.fdopen(fd, 'rb') as pipe:
            finished = pipe.read()
        if finished != b'done':
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        shutil.rmtree(directory, ignore_errors=True)
        return 0
    if args == ['--help']:
        print('Usage: cointos-private [run MESSAGE | OpenCode TUI options]\n'
              'Local CointOS inference; in-memory session database; no session recovery.\n'
              'Tools can still write requested files. Live process memory and terminal scrollback remain visible.')
        return 0
    if any(a in ('--server', '--session', '-s', '--continue', '-c', '--model', '-m')
           or a.startswith(('--server=', '--session=', '--model=')) for a in args):
        raise SystemExit('Private sessions cannot attach, resume or select another model.')
    binary = Path.home() / '.local/lib/opencode/2.3.0/opencode'
    if not binary.is_file():
        raise SystemExit('The qualified OpenCode 2.3.0 executable is unavailable.')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # /dev/shm is tmpfs; do not silently fall back to persistent /tmp storage.
    with tempfile.TemporaryDirectory(prefix='cointos-private-', dir='/dev/shm') as temp:
        env = environment(Path(temp), load())
        command = [str(binary)]
        if args and args[0] == 'run':
            command += ['run', '--standalone', '--log-level', 'none', *args[1:]]
        else:
            command += ['--standalone', '--log-level', 'none', *args]
        process = subprocess.Popen(command, env=env, start_new_session=True)
        read_fd, cleanup_fd = os.pipe()
        try:
            janitor = subprocess.Popen([sys.executable, '-P', '-m', 'cointos.private_session',
                '--cleanup', str(read_fd), str(process.pid), temp], pass_fds=(read_fd,),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            os.close(cleanup_fd)
            raise
        finally:
            os.close(read_fd)
        previous = {}
        def stop(signum, _frame):
            try:
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                pass
        # The detached child does not receive the foreground terminal's resize
        # signals directly. Forward them along with lifecycle signals.
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGWINCH):
            previous[signum] = signal.signal(signum, stop)
        try:
            return process.wait()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            os.write(cleanup_fd, b'done')
            os.close(cleanup_fd)
            janitor.wait()
            for signum, handler in previous.items():
                signal.signal(signum, handler)


if __name__ == '__main__':
    raise SystemExit(main())
