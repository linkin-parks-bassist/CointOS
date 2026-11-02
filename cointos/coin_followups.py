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


def context(directory, user, chat):
    """The conversation's dispatched owners, independent of rolling history."""
    with _registry(directory) as (_, data):
        return [dict(item) for item in data['items'].values()
                if item['user'] == user and item['chat'] == chat]


def settled(task_id, ledger):
    """Follow declared factory ownership without asking Coin to supervise the queue."""
    tasks, records = ledger.get('tasks', {}), ledger.get('queue', {})
    pending, seen = [task_id], set()
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        task, record = tasks.get(key), records.get(key)
        replacements = (record or {}).get('replaced_by') or []
        if replacements:
            pending.extend(f"{record['project']}:{name}" for name in replacements)
        elif record is not None:
            if not record.get('done'):
                return False
        elif not task or task.get('status') != 'done':
            return False
        owners = {key}
        owners.update(t['id'] for t in tasks.values()
                      if t.get('record') == key or t.get('worker') == key
                      or (t.get('repair_origin') or {}).get('task') == key)
        pending.extend(k for k, r in records.items() if r.get('proposed_by') in owners)
        # A declared handoff missing from the projection is unknown, never completion.
        for child in ((task or {}).get('receipt') or {}).get('evidence', {}).get('handoff', []):
            name = child.get('name')
            if name:
                place = (record or {}).get('project') or (task or {}).get('place')
                pending.append(f'{place}:{name}')
    return True


def observe(directory, wakes, ledger, allowed):
    """Successful task settlement queues model verification; failures remain local."""
    with _registry(directory) as (fd, data):
        for key, item in list(data['items'].items()):
            if item['user'] not in allowed:
                continue
            if not settled(item['task'], ledger):
                continue
            message = ('Report completion of requested work. This is a verification trigger, not proof of completion. The user asked for: ' + item['description']
                + '\nTask: ' + item['task'] + '\nFollow-up: ' + key
                + '\nRead the current task receipt and verify the deliverables exist before replying. '
                  'Read exact returned evidence paths; delegate implementation/diff and behaviour verification. A plan-only commit, '
                  'green unrelated suite or completed controller does not establish the requested implementation. '
                  'Use report_result for a short substantive update saying what is finished and where it is. '
                  'A significant usable deliverable merits a milestone message even if other work remains. '
                  'Internal planning or a successful test alone is not a user-facing milestone. '
                  'The service observes declared handoffs; factory managers and Operators own product supervision. '
                  'Do not inspect the whole queue, schedule continuation checks or choose the next product task. '
                  'Use only the exact returned result/evidence paths; delegate detailed verification if needed. '
                  'Keep routine mistakes and recovery chatter local. Check reported-results context and archive '
                  'before reporting; reuse the same location/milestone for the same user deliverable across task IDs. '
                  'A repeated verification or cleared internal blocker merits no new announcement. Finish silently '
                  'when there is no new verified user deliverable.')
            if not any(r['message'] == message for r in wakeups.list(wakes, item['user'])):
                wakeups.create(wakes, item['user'], item['chat'], message,
                               {'kind': 'deadline', 'after_seconds': 0})
            del data['items'][key]
            privatejson.write(fd, 'followups.json', data, _validate)
