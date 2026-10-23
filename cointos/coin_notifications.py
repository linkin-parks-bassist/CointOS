"""Durable delivery of questions and ownerless work; diagnostics stay on the dashboard.

Recovery belongs to the daemon's canonical controller. Coin observes its frontier,
never creates another recovery chain, and durably queues explanations without needing a model.
Telegram acceptance is delivery evidence, not proof that the user has read it.
"""
import hashlib
import math
import os

from cointos import config, privatejson

FILE = 'notifications.json'


def _validate(data):
    if (not isinstance(data, dict) or set(data) != {'version', 'after', 'pending'}
            or data['version'] != 1 or not isinstance(data['pending'], dict)
            or not isinstance(data['after'], (int, float)) or not math.isfinite(data['after'])):
        raise ValueError('invalid progress notification authority')
    for key, item in data['pending'].items():
        if (not isinstance(key, str) or not isinstance(item, dict)
                or set(item) != {'kind', 'text', 'since', 'delivered', 'source'}
                or item['kind'] not in ('message', 'blocked') or not isinstance(item['text'], str)
                or not isinstance(item['since'], (int, float)) or not math.isfinite(item['since'])
                or not isinstance(item['delivered'], dict)
                or (item['source'] is not None and (not isinstance(item['source'], dict)
                    or set(item['source']) != {'from', 'at'}))
                or any(not user.isdecimal() or not (isinstance(receipt, int) and receipt > 0
                           or isinstance(receipt, str) and len(receipt) == 32
                           and all(c in "0123456789abcdef" for c in receipt))
                       for user, receipt in item['delivered'].items())):
            raise ValueError('invalid progress notification')
    return data


def _read(fd):
    return privatejson.read(fd, FILE, _validate, config._fields, None)


def context(directory, user):
    """Delivered work evidence remains available to interpret an answer outside chat history."""
    # Atomic replacement gives readers a coherent snapshot. Do not wait on the
    # observer's writer lease while it is retrying a network send.
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return []
    try:
        privatejson.private(fd, directory=True)
        data = _read(fd)
        return [{('message_id' if isinstance(item['delivered'][str(user)], int) else 'explanation_id'):
                 item['delivered'][str(user)], 'evidence': item['text']}
                for item in (data or {}).get('pending', {}).values() if str(user) in item['delivered']]
    finally:
        os.close(fd)


def identity(value):
    return hashlib.sha256(value.encode()).hexdigest()


def recovery_owns_message(message, ledger):
    """Do not escalate an assignment while its recovery or continuation can act."""
    sender = message['from']
    task = ledger.get('tasks', {}).get(sender, {})
    origin = (task.get('repair_origin') or {}).get('task')
    item = task.get('item')
    assignment = f"{task.get('place')}:{item}" if item else None
    return any(row['item'] in {sender, origin, assignment}
               and (row.get('owner') or row.get('continuations'))
               for row in ledger.get('work_frontier', []))


def observe(data, ledger, now):
    """Add current actionable evidence; never replay old dashboard history on enrollment."""
    pending = data['pending']
    for message in ledger.get('messages', []):
        if message.get('to') == 'user' and (not message.get('read', True) or message['at'] > data['after']):
            key = 'message:' + identity(str(message['at']) + ':' + message['from'] + ':' + message['text'])
            if recovery_owns_message(message, ledger):
                pending.pop(key, None)
                continue
            pending.setdefault(key, {'kind': 'message', 'text': message['text'], 'since': now, 'delivered': {},
                                    'source': {'from': message['from'], 'at': message['at']}})
    data['after'] = max([data['after']] + [m['at'] for m in ledger.get('messages', [])])
    active = set()
    for row in ledger.get('work_frontier', []) if not ledger.get('paused') else []:
        if (row['status'] != 'blocked' or row.get('held_by') or row.get('admission_hold')
                or row.get('owner') or row.get('continuations')):
            continue
        record = ledger.get('queue', {}).get(row['item'], {})
        controller = ledger.get('tasks', {}).get(row.get('recovery'), {})
        # Prefer the controller's checked account over an older worker diagnosis.
        reason = ((controller.get('receipt') or {}).get('summary')
                  or controller.get('result') or row.get('blocker') or 'Recovery ended without a runnable continuation.')
        key = 'blocked:' + identity(row['item'] + ':' + str(record.get('version')) + ':' + reason)
        active.add(key)
        pending.setdefault(key, {'kind': 'blocked', 'since': now, 'delivered': {}, 'source': None,
            'text': ('CointOS needs attention: ' + row['item'] + '\n\n' + reason
                     + '\n\nAutomatic recovery has no runnable next step. The preserved work is not lost.')})
    for key, item in list(pending.items()):
        if item['kind'] == 'blocked' and key not in active:
            del pending[key]


def deliver(directory, ledger, users, send, now, delay, acknowledge):
    """Retain evidence until each recipient has transport acceptance or a durable explanation.

One failed recipient/event does not starve another. Retrying after an ambiguous
network result or a crash between send and fsync can duplicate a notification.
"""
    errors = []
    with privatejson.registry(directory, _read) as (fd, data):
        if data is None:
            data = {'version': 1, 'after': now, 'pending': {}}
        observe(data, ledger, now)
        privatejson.write(fd, FILE, data, _validate)
        for key, item in list(data['pending'].items()):
            if item['kind'] == 'blocked' and now - item['since'] < delay:
                continue
            for user in sorted(users):
                if str(user) in item['delivered']:
                    continue
                try:
                    receipt = send(user, item['text'])
                except (OSError, RuntimeError) as error:
                    errors.append(str(error))
                    continue
                item['delivered'][str(user)] = (receipt['explanation_id'] if 'explanation_id' in receipt
                                                   else receipt['message_id'])
                privatejson.write(fd, FILE, data, _validate)
            if item['kind'] == 'message' and users and all(str(user) in item['delivered'] for user in users):
                acknowledge(item['source'])
                del data['pending'][key]
                privatejson.write(fd, FILE, data, _validate)
    return errors
