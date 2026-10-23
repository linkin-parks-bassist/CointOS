"""Durable completion follow-ups for work dispatched from a user conversation."""
import hashlib
import time
from cointos import config, privatejson, wakeups


def _validate(data):
    if not isinstance(data, dict) or set(data) != {'version', 'items'} or data['version'] != 1 or not isinstance(data['items'], dict):
        raise ValueError('invalid completion follow-ups')
    for key, item in data['items'].items():
        if (not isinstance(item, dict) or set(item) != {'user', 'chat', 'task', 'description', 'created_at'}
                or type(item['user']) is not int or item['user'] <= 0
                or type(item['chat']) is not int or not item['chat']
                or not isinstance(item['task'], str) or not item['task']
                or not isinstance(item['description'], str)
                or key != identity(item['user'], item['task'])
                or type(item['created_at']) not in (int, float)):
            raise ValueError('invalid completion follow-up')
    return data


def identity(user, task):
    return hashlib.sha256(f'{user}:{task}'.encode()).hexdigest()


def _registry(directory):
    return privatejson.registry(directory, lambda fd: privatejson.read(
        fd, 'followups.json', _validate, config._fields, {'version': 1, 'items': {}}))


def retain(directory, user, chat, task, description):
    with _registry(directory) as (fd, data):
        data['items'].setdefault(identity(user, task), {'user': user, 'chat': chat, 'task': task,
            'description': description, 'created_at': time.time()})
        privatejson.write(fd, 'followups.json', data, _validate)


def observe(directory, wakes, ledger, allowed):
    """Successful task settlement queues model verification; failures remain local."""
    with _registry(directory) as (fd, data):
        for key, item in list(data['items'].items()):
            if item['user'] not in allowed:
                continue
            task = ledger.get('tasks', {}).get(item['task'])
            if not task or task.get('status') != 'done':
                continue
            message = ('Report completion of requested work. The user asked for: ' + item['description']
                + '\nTask: ' + item['task'] + '\nFollow-up: ' + key
                + '\nRead the current task receipt and verify the deliverables exist before replying. '
                  'Send a short substantive update saying what is finished and where the result is. '
                  'A significant usable deliverable merits a milestone message even if other work remains. '
                  'Internal planning or a successful test alone is not a user-facing milestone. '
                  'If this task handed off children, continue tracking the unfinished deliverables with '
                  'task-state wakes; do not claim the whole request is complete. '
                  'Keep routine mistakes and recovery chatter local. Check history to avoid duplicate announcements.')
            if not any(r['message'] == message for r in wakeups.list(wakes, item['user'])):
                wakeups.create(wakes, item['user'], item['chat'], message,
                               {'kind': 'deadline', 'after_seconds': 0})
            del data['items'][key]
            privatejson.write(fd, 'followups.json', data, _validate)
