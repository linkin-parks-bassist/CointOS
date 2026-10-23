"""Canonical retained authority and evidence of its actual startup restoration."""
import copy
import hashlib
import json
import subprocess
from pathlib import Path

from cointos import config


def projects(entries):
    return {entry['name']: {**copy.deepcopy(entry), 'path': str(Path(entry['path']).expanduser())}
            for entry in config.project_entries(entries)}


def key_digests(registry):
    values = {**registry.get('agents', {}), **({'coin': registry['coin']} if 'coin' in registry else {})}
    return {name: hashlib.sha256(value.encode()).hexdigest() for name, value in values.items()}


def authority(ledger, enrollment, registry):
    """Snapshot before fresh() or any restoration consumer can mutate its input."""
    config.validate_ledger(ledger)
    tasks = copy.deepcopy(ledger.get('tasks', {}))
    for task in tasks.values():
        task.pop('validating', None)
    return {'tasks': tasks, 'queue': copy.deepcopy(ledger.get('queue', {})),
            'paused': ledger.get('paused', True), 'projects': projects(enrollment),
            'keys': key_digests(registry)}


def fingerprint(authority):
    return hashlib.sha256(json.dumps(authority, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def verify(expected, restored, enrollment, registry, *, bootstrap_coin=False):
    """Compare actual restored data, rather than certifying that inputs were read."""
    actual = authority(restored, enrollment, registry)
    if bootstrap_coin:
        actual['keys'].pop('coin', None)
    if fingerprint(actual) != fingerprint(expected):
        changed = ', '.join(field for field in expected
                            if fingerprint(actual.get(field)) != fingerprint(expected[field]))
        raise ValueError('startup did not retain authority: ' + changed)


def coin_digest(owners):
    """Current loaded Coin ownership, without exposing its gateway credential."""
    values = [key for key, owner in owners.items() if owner == ('coin', 'coin')]
    return hashlib.sha256(values[0].encode()).hexdigest() if len(values) == 1 else None


def unit_witness(registry):
    """Observe native run identity before adoption can retire or follow it."""
    found = {}
    for run in registry.get('agents', {}):
        unit = 'cointos-agent-' + run + '.service'
        result = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'ActiveState', '-p', 'MainPID',
                                 '-p', 'InvocationID', '-p', 'LoadState'], capture_output=True, text=True, check=True)
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        found[unit] = {'state': fields.get('ActiveState'), 'pid': fields.get('MainPID'),
                       'invocation': fields.get('InvocationID'), 'load_state': fields.get('LoadState')}
    return found
