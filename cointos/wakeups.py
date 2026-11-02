"""Durable, owner-bound Coin wakes; delivery is replayable until acknowledgement.

The Coin service owns this registry. Observations never execute a caller's command.
Process identities survive polling, not reboot; task/unit conditions use their declared
logical identities. A pending event is not a claim on model or Telegram side effects.

Deadline, process-exit, unit-state and task-state wakes are one-shot. Schedule and *-change wakes
repeat until cancelled: each keeps a cursor (the next instant or the last observed state), fires
on a new occurrence and re-arms when acknowledged. One pending event per wake means occurrences
during downtime or a running turn collapse into one, never a burst.

A wake with `agent` starts that stationed agent when it fires instead of a model turn.
"""
from __future__ import annotations

import builtins
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid
from zoneinfo import ZoneInfo

from cointos import cron, schema, privatejson


UNIT_STATES = frozenset(('active', 'reloading', 'inactive', 'failed', 'activating', 'deactivating', 'maintenance', 'refreshing'))
TASK_STATES = frozenset(schema.ACTIVE + schema.SETTLED)
RECURRING = frozenset(('schedule', 'unit-change', 'task-change', 'path-change'))
AGENT_FIELDS = frozenset(('name', 'brief', 'project', 'station', 'abilities', 'reasoning_effort', 'budget'))


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


def local_zone() -> str:
    """The workstation's named timezone, which a schedule needs to follow daylight saving."""
    target = Path('/etc/localtime').resolve().as_posix()
    if 'zoneinfo/' not in target:
        raise ValueError('the workstation has no named timezone; give one explicitly')
    return target.split('zoneinfo/', 1)[1]


def path_state(path: str) -> str | None:
    """A file's identity, or a directory's direct entries; nested changes are not seen."""
    try:
        target = Path(path)
        if not target.is_dir():
            found = target.stat()
            return f'{found.st_mtime_ns}:{found.st_size}'
        digest = hashlib.sha256()
        for entry in sorted(target.iterdir()):
            found = entry.lstat()
            digest.update(f'{entry.name}:{found.st_mtime_ns}:{found.st_size}\0'.encode())
        return digest.hexdigest()
    except FileNotFoundError:
        return None


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


def _zone(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('timezone must be a named zone such as Australia/Sydney')
    try:
        ZoneInfo(value)
    except (ValueError, OSError, KeyError) as error:
        raise ValueError(f'unknown timezone {value!r}') from error


def _instant(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _matching_tasks(condition: dict, tasks: dict) -> builtins.list:
    """Tasks in the watched state. A wake's own agents are excluded, or it would trigger itself."""
    return sorted(ident for ident, task in tasks.items()
                  if isinstance(task, dict) and task.get('status') == condition['state']
                  and not task.get('occurrence')
                  and condition['project'] in (None, task.get('place')))


def _cursor(condition: dict, now: float):
    """Where a repeating wake starts watching from: only later occurrences count."""
    kind = condition['kind']
    if kind == 'schedule':
        return _instant(cron.after(condition['cron'], condition['timezone'], now))
    if kind == 'unit-change':
        return unit_state(condition['unit'])['ActiveState']
    if kind == 'task-change':
        return _matching_tasks(condition, task_records())
    return path_state(condition['path'])


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
    if kind == 'schedule' and set(condition) <= {'kind', 'cron', 'timezone'} and 'cron' in condition:
        captured = {'kind': kind, 'cron': condition['cron'], 'timezone': condition.get('timezone') or local_zone()}
    elif kind == 'unit-change' and set(condition) == {'kind', 'unit', 'state'}:
        _unit(condition['unit'])
        if not isinstance(condition['state'], str) or condition['state'] not in UNIT_STATES:
            raise ValueError('unknown unit ActiveState')
        if unit_state(condition['unit'])['LoadState'] != 'loaded':
            raise ValueError('unit must be loaded when the wake is registered')
        captured = dict(condition)
    elif kind == 'task-change' and set(condition) <= {'kind', 'state', 'project'} and 'state' in condition:
        captured = {'kind': kind, 'state': condition['state'], 'project': condition.get('project')}
    elif kind == 'path-change' and set(condition) == {'kind', 'path'}:
        if not isinstance(condition['path'], str) or not condition['path'].strip():
            raise ValueError('path must be a file or directory path')
        path = Path(condition['path']).expanduser()
        if not path.is_absolute():
            raise ValueError('path must be absolute or start with ~')
        captured = {'kind': kind, 'path': str(path)}
    elif kind == 'process-exit' and set(condition) == {'kind', 'pid'}:
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
    elif kind == 'schedule' and set(condition) == {'kind', 'cron', 'timezone'}:
        cron.parse(condition['cron'])
        _zone(condition['timezone'])
    elif kind == 'unit-change' and set(condition) == {'kind', 'unit', 'state'}:
        _unit(condition['unit'])
        if not isinstance(condition['state'], str) or condition['state'] not in UNIT_STATES:
            raise ValueError('invalid stored unit state')
    elif kind == 'task-change' and set(condition) == {'kind', 'state', 'project'}:
        if not isinstance(condition['state'], str) or condition['state'] not in TASK_STATES:
            raise ValueError('unknown task status')
        if condition['project'] is not None and not isinstance(condition['project'], str):
            raise ValueError('project must be a project name')
    elif kind == 'path-change' and set(condition) == {'kind', 'path'}:
        if not isinstance(condition['path'], str) or not Path(condition['path']).is_absolute():
            raise ValueError('invalid stored path')
    else:
        raise ValueError('invalid stored condition fields')


def _agent(agent):
    if (not isinstance(agent, dict) or not {'name', 'brief'} <= set(agent) or set(agent) - AGENT_FIELDS
            or not isinstance(agent['name'], str) or not isinstance(agent['brief'], str) or not agent['brief'].strip()):
        raise ValueError('agent needs a name and brief, and only run_agent fields')


def _validate(data):
    if (not isinstance(data, dict) or set(data) != {'version', 'wakeups'} or data['version'] != 1
            or not isinstance(data['version'], int) or isinstance(data['version'], bool) or not isinstance(data['wakeups'], dict)):
        raise ValueError('invalid wake registry')
    required = {'id', 'user', 'chat', 'message', 'condition', 'created_at'}
    outcomes = {'deadline': {'due'}, 'process-exit': {'exited', 'interrupted'},
                'unit-state': {'matched', 'unavailable'}, 'task-state': {'matched', 'unavailable', 'replaced', 'cancelled'},
                'schedule': {'due'}, 'unit-change': {'matched'}, 'task-change': {'matched'}, 'path-change': {'matched'}}
    optional = {'event', 'agent', 'cursor', 'runs', 'last_run', 'paused'}
    for ident, record in data['wakeups'].items():
        _id(ident)
        if (not isinstance(record, dict) or not required <= set(record) or set(record) - required - optional
                or record['id'] != ident):
            raise ValueError('invalid wake record')
        _identity(record['user'], 'user')
        _identity(record['chat'], 'chat')
        if not isinstance(record['message'], str) or not record['message'].strip() or not _number(record['created_at']):
            raise ValueError('invalid wake message or registration time')
        _stored_condition(record['condition'])
        recurring = record['condition']['kind'] in RECURRING
        if recurring != ('cursor' in record) or recurring != ('runs' in record) or (('last_run' in record or 'paused' in record) and not recurring):
            raise ValueError('invalid repeating wake state')
        if 'agent' in record:
            _agent(record['agent'])
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


def _view(record):
    """A copy for callers, with a schedule's next run on its own wall clock."""
    view = copy.deepcopy(record)
    if record['condition']['kind'] == 'schedule' and not record.get('paused'):
        view['next_run'] = (datetime.fromisoformat(record['cursor'])
                            .astimezone(ZoneInfo(record['condition']['timezone'])).isoformat())
    return view


def create(directory, user, chat, message, condition, agent=None):
    _identity(user, 'user')
    _identity(chat, 'chat')
    if not isinstance(message, str) or not message.strip():
        raise ValueError('wake message must be nonempty')
    if agent is not None:
        _agent(agent)
    with _registry(directory) as (descriptor, data):
        now = clock()
        captured = _condition(condition, now)
        ident = uuid.uuid4().hex
        while ident in data['wakeups']:
            ident = uuid.uuid4().hex
        record = {'id': ident, 'user': user, 'chat': chat, 'message': message,
                  'condition': captured, 'created_at': now}
        if agent is not None:
            record['agent'] = copy.deepcopy(agent)
        if captured['kind'] in RECURRING:
            record.update(cursor=_cursor(captured, now), runs=0)
        data['wakeups'][ident] = record
        _write(descriptor, data)
        return _view(record)


def list(directory, user):
    _identity(user, 'user')
    with _registry(directory) as (_, data):
        return [_view(record) for record in sorted((record for record in data['wakeups'].values() if record['user'] == user),
                                                   key=lambda record: (record['created_at'], record['id']))]


def _remove(directory, user, ident, acknowledge, outcome=None):
    _identity(user, 'user')
    _id(ident)
    with _registry(directory) as (descriptor, data):
        record = data['wakeups'].get(ident)
        if record is not None:
            if record['user'] != user:
                raise ValueError('wake belongs to another user')
            recurring = acknowledge and record['condition']['kind'] in RECURRING
            if recurring and 'event' not in record:
                return False  # paused or already re-armed while its turn ran
            if acknowledge and 'event' not in record:
                raise ValueError('wake has not triggered; cancel it instead')
            if recurring:
                now = clock()
                event = record.pop('event')
                record['runs'] += 1
                record['last_run'] = {'at': now, 'detail': event['detail'], **(outcome or {})}
                if record['condition']['kind'] == 'schedule':
                    record['cursor'] = _cursor(record['condition'], now)
            else:
                del data['wakeups'][ident]
        # An idempotent retry also makes absence durable before acknowledging it.
        _write(descriptor, data)
        return record is not None


def cancel(directory, user, id):
    return _remove(directory, user, id, False)


def ack(directory, user, id, outcome=None):
    """Finish this occurrence: a one-shot wake ends; a repeating one re-arms."""
    return _remove(directory, user, id, True, outcome)


def pause(directory, user, id, paused):
    """Stop or restart a repeating wake, keeping it. Occurrences while paused do not count."""
    _identity(user, 'user')
    _id(id)
    with _registry(directory) as (descriptor, data):
        record = data['wakeups'].get(id)
        if record is None or record['user'] != user:
            raise ValueError('no such wake for this user')
        if record['condition']['kind'] not in RECURRING:
            raise ValueError('only a repeating wake can be paused; cancel a one-shot wake instead')
        record.pop('event', None)
        if paused:
            record['paused'] = True
        else:
            record.pop('paused', None)
            record['cursor'] = _cursor(record['condition'], clock())
        _write(descriptor, data)
        return _view(record)


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


def _observe_repeating(record, now, cache):
    """Advance a repeating wake's cursor; an event means this observation is a new occurrence."""
    condition, cursor = record['condition'], record['cursor']
    kind = condition['kind']
    if kind == 'schedule':
        if now < _at(cursor)[1]:
            return None
        local = datetime.fromisoformat(cursor).astimezone(ZoneInfo(condition['timezone']))
        return _event('due', f'Scheduled for {local.isoformat()}.', now)
    if kind == 'unit-change':
        key = ('unit', condition['unit'])
        if key not in cache:
            cache[key] = unit_state(condition['unit'])
        if cache[key]['LoadState'] != 'loaded':
            return None
        record['cursor'] = cache[key]['ActiveState']
        if record['cursor'] != cursor and record['cursor'] == condition['state']:
            return _event('matched', f"The unit changed from {cursor} to {condition['state']}.", now)
        return None
    if kind == 'task-change':
        if 'tasks' not in cache:
            cache['tasks'] = task_records()
        record['cursor'] = _matching_tasks(condition, cache['tasks'])
        new = sorted(set(record['cursor']) - set(cursor))
        if new:
            return _event('matched', f"Newly {condition['state']}: {', '.join(new)}.", now)
        return None
    record['cursor'] = path_state(condition['path'])
    if record['cursor'] != cursor:
        state = 'is gone' if record['cursor'] is None else 'changed'
        return _event('matched', f"{condition['path']} {state}.", now)
    return None


def ready(directory):
    """Persist new triggers, then replay every unacknowledged event at least once."""
    with _registry(directory) as (descriptor, data):
        changed, cache, now = False, {}, clock()
        for record in data['wakeups'].values():
            if 'event' in record or record.get('paused'):
                continue
            before = record.get('cursor')
            try:
                event = (_observe_repeating(record, now, cache) if record['condition']['kind'] in RECURRING
                         else _observe(record['condition'], now, cache))
            except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                # One temporarily unavailable observer must not block other due wakes.
                continue
            changed |= record.get('cursor') != before
            if event is not None:
                record['event'] = event
                changed = True
        if changed:
            _write(descriptor, data)
        elif any('event' in record for record in data['wakeups'].values()):
            _sync(descriptor)
        return copy.deepcopy(sorted((record for record in data['wakeups'].values() if 'event' in record),
                                    key=lambda record: (record['event']['at'], record['id'])))
