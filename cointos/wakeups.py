"""Durable, owner-bound one-shot Coin wakes; delivery is replayable until acknowledgement.

The Coin service owns this registry. Observations never execute a caller's command.
Process identities survive polling, not reboot; task/unit conditions use their declared
logical identities. A pending event is not a claim on model or Telegram side effects.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid

from cointos import schema, privatejson


UNIT_STATES = frozenset(('active', 'reloading', 'inactive', 'failed', 'activating', 'deactivating', 'maintenance', 'refreshing'))
TASK_STATES = frozenset(schema.ACTIVE + schema.SETTLED)


def clock() -> float:
    return time.time()


def boot_id() -> str:
    return (Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def process(pid: int) -> dict | None:
    """Read the native identity/state, including zombies; disappearance is not an exit code."""
    try:
        text = (Path('/proc') / str(pid) / 'stat').read_text()
    except FileNotFoundError:
        return None
    try:
        fields = text.rsplit(')', 1)[1].split()
        return {'state': fields[0], 'start_ticks': int(fields[19])}
    except (IndexError, ValueError) as error:
        raise ValueError('native process identity is incomplete') from error


def unit_state(unit: str) -> dict:
    from cointos import client
    result = subprocess.run(['systemctl', '--user', 'show', unit, '--property=LoadState', '--property=ActiveState'],
                            capture_output=True, text=True, check=False,
                            timeout=client.CONFIG['timeouts']['api_seconds'])
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if (set(fields) != {'LoadState', 'ActiveState'} or not all(fields.values())
            or fields['ActiveState'] not in UNIT_STATES):
        raise ValueError('native unit observation is incomplete')
    # A confirmed missing logical unit is evidence; a query failure is not.
    if result.returncode and not (result.returncode == 1 and fields['LoadState'] == 'not-found'):
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    return fields


def task_records() -> dict:
    from cointos import client
    try:
        ledger = client.ledger()
    except client.Unreachable as error:
        raise OSError('task authority is temporarily unavailable') from error
    if not isinstance(ledger, dict) or not isinstance(ledger.get('tasks'), dict):
        raise ValueError('task authority is unavailable')
    return ledger['tasks']


def _number(value) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _identity(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or (value <= 0 if name == 'user' else value == 0):
        raise ValueError(f'{name} must be a Telegram integer identity')
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('wake id must be its opaque UUID')
    return value


def _at(value):
    if not isinstance(value, str):
        raise ValueError('deadline at must be a timezone-aware ISO timestamp')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError('timezone is required')
        timestamp = instant.timestamp()
        if not math.isfinite(timestamp):
            raise ValueError('timestamp must be finite')
    except (ValueError, OverflowError) as error:
        raise ValueError('deadline at must be a timezone-aware ISO timestamp') from error
    return instant.astimezone(timezone.utc).isoformat(), timestamp


def _unit(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:@\\-]+', value)
            or value.startswith('-') or not value.endswith(('.service', '.socket', '.target', '.timer', '.path',
                                                           '.slice', '.scope', '.mount', '.automount', '.swap', '.device'))):
        raise ValueError('unit must be one logical user-unit name, not a command or option')


def _task(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError('task must be its logical task id')


def _condition(condition: dict, now: float) -> dict:
    """Normalize user input and capture authoritative identity at registration."""
    if not isinstance(condition, dict):
        raise ValueError('one condition object is required')
    kind = condition.get('kind')
    if kind == 'deadline':
        if set(condition) == {'kind', 'after_seconds'}:
            delay = condition['after_seconds']
            if not _number(delay) or delay < 0 or not math.isfinite(now + delay):
                raise ValueError('after_seconds must be finite and nonnegative')
            try:
                at = datetime.fromtimestamp(now + delay, timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError) as error:
                raise ValueError('deadline is outside the supported timestamp range') from error
        elif set(condition) == {'kind', 'at'}:
            at, _ = _at(condition['at'])
        else:
            raise ValueError('deadline requires exactly one of after_seconds or at')
        return {'kind': kind, 'at': at}
    if kind == 'process-exit' and set(condition) == {'kind', 'pid'}:
        pid = condition['pid']
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError('pid must be a positive integer')
        boot = boot_id()
        if not isinstance(boot, str) or not boot.strip():
            raise ValueError('boot identity is unavailable')
        native = process(pid)
        if native is None:
            raise ValueError('process is absent; its original identity cannot be captured')
        if boot != boot_id():
            raise OSError('boot changed while registering process identity')
        captured = {'kind': kind, 'pid': pid, 'boot_id': boot, 'start_ticks': native['start_ticks']}
    elif kind == 'unit-state' and set(condition) == {'kind', 'unit', 'state'}:
        _unit(condition['unit'])
        if not isinstance(condition['state'], str) or condition['state'] not in UNIT_STATES:
            raise ValueError('unknown unit ActiveState')
        if unit_state(condition['unit'])['LoadState'] != 'loaded':
            raise ValueError('unit must be loaded when the wake is registered')
        captured = dict(condition)
    elif kind == 'task-state' and set(condition) == {'kind', 'task', 'state'}:
        _task(condition['task'])
        if not isinstance(condition['state'], str) or condition['state'] not in TASK_STATES:
            raise ValueError('unknown task status')
        task = task_records().get(condition['task'])
        if not isinstance(task, dict) or not _number(task.get('created_at')):
            raise ValueError('task is absent or lacks its durable creation identity')
        captured = {**condition, 'created_at': task['created_at']}
    else:
        raise ValueError('unsupported condition or unexpected fields')
    _stored_condition(captured)
    return captured


def _stored_condition(condition):
    if not isinstance(condition, dict):
        raise ValueError('invalid stored condition')
    kind = condition.get('kind')
    if kind == 'deadline' and set(condition) == {'kind', 'at'}:
        canonical, _ = _at(condition['at'])
        if canonical != condition['at']:
            raise ValueError('stored deadline is not canonical UTC')
    elif kind == 'process-exit' and set(condition) == {'kind', 'pid', 'boot_id', 'start_ticks'}:
        if (not isinstance(condition['pid'], int) or isinstance(condition['pid'], bool) or condition['pid'] <= 0
                or not isinstance(condition['boot_id'], str) or not condition['boot_id'].strip()
                or not isinstance(condition['start_ticks'], int) or isinstance(condition['start_ticks'], bool)
                or condition['start_ticks'] < 0):
            raise ValueError('invalid stored process identity')
    elif kind == 'unit-state' and set(condition) == {'kind', 'unit', 'state'}:
        _unit(condition['unit'])
        if not isinstance(condition['state'], str) or condition['state'] not in UNIT_STATES:
            raise ValueError('invalid stored unit state')
    elif kind == 'task-state' and set(condition) == {'kind', 'task', 'state', 'created_at'}:
        _task(condition['task'])
        if (not isinstance(condition['state'], str) or condition['state'] not in TASK_STATES
                or not _number(condition['created_at'])):
            raise ValueError('invalid stored task identity')
    else:
        raise ValueError('invalid stored condition fields')


def _validate(data):
    if (not isinstance(data, dict) or set(data) != {'version', 'wakeups'} or data['version'] != 1
            or not isinstance(data['version'], int) or isinstance(data['version'], bool) or not isinstance(data['wakeups'], dict)):
        raise ValueError('invalid wake registry')
    required = {'id', 'user', 'chat', 'message', 'condition', 'created_at'}
    outcomes = {'deadline': {'due'}, 'process-exit': {'exited', 'interrupted'},
                'unit-state': {'matched', 'unavailable'}, 'task-state': {'matched', 'unavailable', 'replaced', 'cancelled'}}
    for ident, record in data['wakeups'].items():
        _id(ident)
        if not isinstance(record, dict) or set(record) not in (required, required | {'event'}) or record['id'] != ident:
            raise ValueError('invalid wake record')
        _identity(record['user'], 'user')
        _identity(record['chat'], 'chat')
        if not isinstance(record['message'], str) or not record['message'].strip() or not _number(record['created_at']):
            raise ValueError('invalid wake message or registration time')
        _stored_condition(record['condition'])
        if 'event' in record:
            event = record['event']
            if (not isinstance(event, dict) or set(event) != {'at', 'outcome', 'result', 'detail'}
                    or not _number(event['at']) or not isinstance(event['outcome'], str)
                    or event['outcome'] not in outcomes[record['condition']['kind']]
                    or event['result'] != ('observed' if event['outcome'] in ('due', 'matched') else 'unknown')
                    or not isinstance(event['detail'], str) or not event['detail'].strip()):
                raise ValueError('invalid pending wake event')
    return data


def _fields(pairs):
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError('duplicate wake registry fields')
    return data


def _private(fd, directory=False):
    return privatejson.private(fd, directory)


def _read(directory):
    return privatejson.read(directory, 'wakeups.json', _validate, _fields, {'version': 1, 'wakeups': {}})


def _write(directory, data):
    return privatejson.write(directory, 'wakeups.json', data, _validate)


def _sync(directory):
    return privatejson.sync(directory, 'wakeups.json')


@contextmanager
def _registry(directory):
    with privatejson.registry(directory, _read) as value:
        yield value


def create(directory, user, chat, message, condition):
    _identity(user, 'user')
    _identity(chat, 'chat')
    if not isinstance(message, str) or not message.strip():
        raise ValueError('wake message must be nonempty')
    with _registry(directory) as (descriptor, data):
        now = clock()
        captured = _condition(condition, now)
        ident = uuid.uuid4().hex
        while ident in data['wakeups']:
            ident = uuid.uuid4().hex
        record = {'id': ident, 'user': user, 'chat': chat, 'message': message,
                  'condition': captured, 'created_at': now}
        data['wakeups'][ident] = record
        _write(descriptor, data)
        return copy.deepcopy(record)


def list(directory, user):
    _identity(user, 'user')
    with _registry(directory) as (_, data):
        return copy.deepcopy(sorted((record for record in data['wakeups'].values() if record['user'] == user),
                                    key=lambda record: (record['created_at'], record['id'])))


def _remove(directory, user, ident, acknowledge):
    _identity(user, 'user')
    _id(ident)
    with _registry(directory) as (descriptor, data):
        record = data['wakeups'].get(ident)
        if record is not None:
            if record['user'] != user:
                raise ValueError('wake belongs to another user')
            if acknowledge and 'event' not in record:
                raise ValueError('wake has not triggered; cancel it instead')
            del data['wakeups'][ident]
        # An idempotent retry also makes absence durable before acknowledging it.
        _write(descriptor, data)
        return record is not None


def cancel(directory, user, id):
    return _remove(directory, user, id, False)


def ack(directory, user, id):
    return _remove(directory, user, id, True)


def pending(directory, id):
    _id(id)
    with _registry(directory) as (_, data):
        record = data['wakeups'].get(id)
        return record is not None and 'event' in record


def _event(outcome, detail, now):
    return {'at': now, 'outcome': outcome, 'result': 'observed' if outcome in ('due', 'matched') else 'unknown', 'detail': detail}


def _observe(condition, now, cache):
    kind = condition['kind']
    if kind == 'deadline':
        if now >= _at(condition['at'])[1]:
            return _event('due', 'The registered deadline elapsed.', now)
    elif kind == 'process-exit':
        if 'boot' not in cache:
            cache['boot'] = boot_id()
        boot = cache['boot']
        if not isinstance(boot, str) or not boot.strip():
            raise ValueError('boot identity is unavailable')
        if boot != condition['boot_id']:
            return _event('interrupted', 'The system rebooted; the original process result is unknown.', now)
        key = ('pid', condition['pid'])
        if key not in cache:
            cache[key] = process(condition['pid'])
        native = cache[key]
        if native is None:
            return _event('exited', 'The original process disappeared; its exit result is unknown.', now)
        if native['start_ticks'] != condition['start_ticks']:
            return _event('exited', 'The original process is gone and its PID was reused; its exit result is unknown.', now)
        if native['state'] in ('Z', 'X', 'x'):
            return _event('exited', 'The registered process has exited; its exit result is unknown.', now)
    elif kind == 'unit-state':
        key = ('unit', condition['unit'])
        if key not in cache:
            cache[key] = unit_state(condition['unit'])
        observed = cache[key]
        if observed['LoadState'] != 'loaded':
            return _event('unavailable', 'The registered logical unit is no longer loaded; its result is unknown.', now)
        if observed['ActiveState'] == condition['state']:
            return _event('matched', 'The logical unit reached ' + condition['state'] + '.', now)
    else:
        if 'tasks' not in cache:
            cache['tasks'] = task_records()
        task = cache['tasks'].get(condition['task'])
        if task is None:
            return _event('unavailable', 'The registered task disappeared; completion is not inferred.', now)
        if not isinstance(task, dict) or not _number(task.get('created_at')):
            raise ValueError('task observation lacks durable identity')
        if task['created_at'] != condition['created_at']:
            return _event('replaced', "The task's creation timestamp changed under the same ID; its original outcome is unknown.", now)
        if task.get('cancelled'):
            return _event('cancelled', 'The task was cancelled; completion is not inferred.', now)
        if task.get('status') == condition['state']:
            return _event('matched', 'The same task reached ' + condition['state'] + '.', now)
    return None


def ready(directory):
    """Persist new triggers, then replay every unacknowledged event at least once."""
    with _registry(directory) as (descriptor, data):
        changed, cache, now = False, {}, clock()
        for record in data['wakeups'].values():
            if 'event' in record:
                continue
            try:
                event = _observe(record['condition'], now, cache)
            except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                # One temporarily unavailable observer must not block other due wakes.
                continue
            if event is not None:
                record['event'] = event
                changed = True
        if changed:
            _write(descriptor, data)
        elif any('event' in record for record in data['wakeups'].values()):
            _sync(descriptor)
        return copy.deepcopy(sorted((record for record in data['wakeups'].values() if 'event' in record),
                                    key=lambda record: (record['event']['at'], record['id'])))
