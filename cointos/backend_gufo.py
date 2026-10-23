"""Externally scheduled Gufo runner, through the private gufo-control socket."""
from __future__ import annotations

import json
import hashlib
import math
import os
import selectors
import shutil
import socket
import subprocess
from pathlib import Path

from . import backend_chat, backend_llama

Lost = backend_llama.Lost


def _options(config: dict, model: str) -> dict:
    return config['models'][model]['gufo']


def _identity(options: dict) -> str:
    identity = options['sha256'] + ':1f97092333af10f29887b098d9cb8a041610004a:'
    if draft := options.get('dflash'):
        identity += f"dflash:{draft['sha256']}:{draft.get('max_draft_tokens', 7)}:{draft.get('policy', 'adaptive')}:"
    return identity


def _call(config: dict, model: str, op: str, *, timeout=None, **body):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout or config['timeouts']['server_seconds'])
        connection.connect(str(Path(_options(config, model)['socket']).expanduser()))
        connection.sendall(json.dumps({'op': op, **body}).encode() + b'\n')
        with connection.makefile('rb') as response:
            line = response.readline()
    if not line:
        raise RuntimeError('Gufo control connection ended without a response')
    result = json.loads(line)
    if 'error' in result:
        if result['error'].startswith('lost:'):
            raise Lost(result['error'])
        raise RuntimeError(result['error'])
    if 'result' not in result:
        if op == 'shutdown' and result.get('ok') is True:
            return None
        raise RuntimeError('Gufo control response is incomplete')
    return result['result']


def models(config: dict) -> dict[str, dict]:
    found = {}
    for model, shape in config['models'].items():
        try:
            info = _call(config, model, 'info', timeout=config['timeouts']['snapshot_seconds'])
            options = _options(config, model)
            identity = _identity(options)
            if (info.get('protocol') != 1 or info.get('context') != shape['ctx_size'] // shape['lanes']
                    or info.get('lanes') != shape['lanes'] or info.get('speculative') is not bool(options.get('dflash'))
                    or not info.get('identity', '').startswith(identity)):
                found[model] = {'problems': ['Gufo native shape/identity mismatch']}
            else:
                found[model] = {'lanes': shape['lanes']}
        except (OSError, ValueError, RuntimeError) as error:
            found[model] = {'problems': [str(error)]}
    return found


def _storage(config: dict) -> dict:
    return {**config, **{key: str(Path(config[key]).expanduser() / 'gufo')
                       for key in ('snapshots', 'disk_snapshots')}}


def budget(config: dict) -> None:
    # Gufo is charged through physical host pressure; it has no Lemonade cgroup.
    return None


def launch(config: dict, model: str) -> None:
    options, shape = _options(config, model), config['models'][model]
    path = Path(options['socket']).expanduser()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_uid != os.getuid() or path.parent.stat().st_mode & 0o077:
        raise RuntimeError('Gufo socket directory must be owned by this user and mode 0700')
    storage = _storage(config)
    snapshots = Path(storage['snapshots'])
    snapshots.mkdir(mode=0o700, parents=True, exist_ok=True)
    if snapshots.stat().st_uid != os.getuid() or snapshots.stat().st_mode & 0o077:
        raise RuntimeError('Gufo snapshots require a private directory owned by this user')
    # A live instance is adopted only when its exact configured shape is already ready.
    try:
        _call(config, model, 'info')
    except (FileNotFoundError, ConnectionRefusedError):
        pass
    else:
        problems = models({**config, 'models': {model: shape}})[model].get('problems')
        if problems:
            raise RuntimeError('; '.join(problems))
        return
    command = [str(Path(options['executable']).expanduser()),
            str(Path(options['model_path']).expanduser()), str(path), str(shape['ctx_size'] // shape['lanes']),
            str(shape['lanes']), storage['snapshots'], options['sha256']]
    if draft := options.get('dflash'):
        command += [str(Path(draft['model_path']).expanduser()), draft['sha256'],
                    str(draft.get('max_draft_tokens', 7)), draft.get('policy', 'adaptive')]
    # A native model outlives a compatible daemon replacement, like Lemonade's
    # model servers. A new session alone does not escape the daemon's cgroup:
    # systemd would SIGKILL it after the daemon exits, disrupting HIP teardown.
    unit = 'cointos-gufo-' + hashlib.sha256(str(path).encode()).hexdigest()[:12]
    command = ['systemd-run', '--user', '--scope', '--quiet', '--collect',
               '--unit=' + unit, *command]
    with (path.parent / 'control.log').open('ab', buffering=0) as log:
        process = subprocess.Popen(command,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, start_new_session=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(config['timeouts']['model_launch_seconds']):
                raise TimeoutError('Gufo model launch timed out')
            if process.stdout.readline() != b'ready\n':
                raise RuntimeError(f'Gufo failed to start; see {path.parent / "control.log"}')
        problems = models({**config, 'models': {model: shape}})[model].get('problems')
        if problems:
            raise RuntimeError('; '.join(problems))
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        process.stdout.close()


def kill(config: dict, model: str) -> None:
    try:
        info = _call(config, model, 'info', timeout=config['timeouts']['model_kill_seconds'])
        descriptor = os.pidfd_open(info['pid'])
    except (FileNotFoundError, ConnectionRefusedError, ProcessLookupError):
        return
    try:
        _call(config, model, 'shutdown', timeout=config['timeouts']['model_kill_seconds'])
        with selectors.DefaultSelector() as selector:
            selector.register(descriptor, selectors.EVENT_READ)
            if not selector.select(config['timeouts']['model_kill_seconds']):
                raise TimeoutError('Gufo did not release its model after shutdown')
    finally:
        os.close(descriptor)


def render(config: dict, model: str, conversation: dict) -> dict:
    result = _call(config, model, 'render', timeout=config['timeouts']['render_seconds'],
                   **backend_chat.prepare(conversation))
    def tokenize(value):
        return _call(config, model, 'tokenize', text=value)['tokens']
    return {'tokens': result['tokens'],
            'reader': backend_chat.reader(conversation, result['prompt'], tokenize)}


def can_continue(config: dict, model: str, held: list[int] | None, tokens: list[int]) -> bool:
    """Gufo retains next-token state after consuming the complete published vector."""
    return bool(held) and len(held) <= len(tokens) and tokens[:len(held)] == held


def prefill(config: dict, model: str, lane: int, tokens: list[int], held: int) -> None:
    result = _call(config, model, 'prefill', lane=lane, tokens=tokens, held=held,
                   max_input_tokens=config['scheduler']['read_chunk_tokens'])
    if result.get('held') != len(tokens):
        raise RuntimeError('Gufo prefill retained an unknown prefix')


def think(config: dict, model: str, lane: int, tokens: list[int], held: int, max_new: int,
          sampling: dict, on_tokens) -> dict:
    sampling = {**_options(config, model).get('sampling', {}), **sampling}
    event = _call(config, model, 'think', lane=lane, tokens=tokens, held=held, max_new=max_new,
                  sampling=sampling,
                  max_input_tokens=config['scheduler']['read_chunk_tokens'])
    new = event.get('tokens')
    if (not isinstance(new, list) or any(type(token) is not int or not 0 <= token <= 0xffffffff for token in new)
            or len(new) > max_new or event.get('held') != len(tokens) + len(new)
            or type(event.get('done')) is not bool or (not new and not event['done'])
            or type(event.get('generation_seconds')) not in (int, float)
            or not math.isfinite(event['generation_seconds']) or event['generation_seconds'] < 0):
        raise RuntimeError('Gufo returned an incomplete token step')
    if new:
        on_tokens(new)
    seconds = event['generation_seconds']
    return {**event, 'held': tokens + new, 'sampling': sampling,
            'rate': len(new) / seconds if seconds and len(new) >= 16 else None}


def text(config: dict, model: str, tokens: list[int]) -> str:
    return _call(config, model, 'text', tokens=tokens)['content'] if tokens else ''


def read(config: dict, model: str, reader: dict, tokens: list[int], final: bool) -> dict:
    return backend_chat.read(reader, text(config, model, tokens), final)


def save(config: dict, model: str, lane: int, name: str) -> dict:
    return _call(config, model, 'save', timeout=config['timeouts']['snapshot_seconds'], lane=lane,
                 name=backend_llama._snapshot(name).removesuffix('.bin'))


def restore(config: dict, model: str, lane: int, name: str) -> bool:
    try:
        return bool(_call(config, model, 'restore', timeout=config['timeouts']['snapshot_seconds'], lane=lane,
                          name=backend_llama._snapshot(name).removesuffix('.bin')).get('tokens'))
    except (OSError, ValueError, RuntimeError):
        return False


def spill(config: dict, name: str) -> None:
    backend_llama.spill(_storage(config), name)


def unspill(config: dict, name: str) -> None:
    copy_back(config, name)
    (Path(_storage(config)['disk_snapshots']) / backend_llama._snapshot(name)).unlink()


def copy_back(config: dict, name: str) -> None:
    storage = _storage(config)
    source = Path(storage['disk_snapshots']) / backend_llama._snapshot(name)
    target = Path(storage['snapshots']) / source.name
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o600)


def cache_kind(config: dict, model: str | None) -> str:
    return 'gufo'


def snapshot_files(config: dict, tier: str | None = None) -> list[dict]:
    return [{**entry, 'backend': 'gufo'} for entry in backend_llama.snapshot_files(_storage(config), tier)]


def delete_snapshot_file(config: dict, entry: dict) -> int:
    return backend_llama.delete_snapshot_file(_storage(config), entry)


def forget(config: dict, name: str) -> None:
    backend_llama.forget(_storage(config), name)


def recover_transfer(config: dict, name: str, expected_bytes: int) -> str | None:
    return backend_llama.recover_transfer(_storage(config), name, expected_bytes)


def forget_untracked(config: dict, memory_names: set[str], disk_names: set[str]) -> list[str]:
    return backend_llama.forget_untracked(_storage(config), memory_names, disk_names)
