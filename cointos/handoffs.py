"""One recoverable manager operation: publish the scoped plan and hand its work to children."""
from __future__ import annotations

from copy import deepcopy

from cointos import artifacts, contracts, git, lifecycle, queues, replacement, tasks
from cointos.config import ROOT
from cointos.state import ACTIVE, L, LOCK, STOPPING, log, save


def preview(task, items):
    """Validate a complete child graph without exposing partial queue records. Caller holds LOCK."""
    project = tasks.project_named(task['place'])
    original = L['queue']
    L['queue'] = deepcopy(original)
    created = []
    try:
        for item in items:
            if not isinstance(item, dict) or item.get('summary') is None or not isinstance(item.get('dependencies'), list):
                raise ValueError('every handoff child needs summary and dependencies')
            name = queues.add(project, item.get('kind', 'queued'), item.get('name', ''), item.get('brief', ''),
                              item.get('stage'), item.get('reasoning_effort'), item.get('budget'),
                              dependency_ids=item['dependencies'], summary=item['summary'],
                              reliances=item.get('relies_on'))
            key = f"{project['name']}:{name}"
            if key in created:
                raise ValueError('handoff children need distinct names')
            record = queues.records()[key]
            if record.get('proposed_by') not in (None, task['id']):
                raise ValueError('handoff child already belongs to another proposer')
            record['proposed_by'] = task['id']
            artifacts.carry_owner(record, task)
            created.append(key)
        problems = queues.frontier_problems(project['name'], owner=task['id'])
        if problems:
            raise ValueError('queued work cannot continue:\n' + '\n'.join(problems))
        return {key: deepcopy(L['queue'][key]) for key in created}
    finally:
        L['queue'] = original


def current(task, intent=None):
    """Recheck ownership, explicit holds and assignment epoch before publication. Caller holds LOCK."""
    if STOPPING.is_set():
        raise ValueError('daemon draining; retry handoff after replacement')
    if L['tasks'].get(task['id']) is not task:
        raise ValueError('planning ownership changed; inspect the current assignment')
    if not lifecycle.owns(task, intent['run'] if intent else task['agent']):
        raise ValueError('planning assignment is no longer owned by this run')
    record = queues.records().get(task.get('record'))
    if task.get('admission_hold') or (record and record.get('held_by')):
        raise ValueError('planning assignment is held; preserve its files until the hold is released')
    if intent and (task.get('record_version') != intent['version']
                   or (record and record['version'] != intent['version'])):
        raise ValueError('planning assignment changed; inspect its current scope before handing off')
    if intent and (not git.clean(task['worktree']) or git.head(task['worktree']) != intent['commit']):
        raise ValueError('planning files changed during handoff; retry to capture the current files')


def graph(task, intent):
    """Check the pinned records against current authority without changing it. Caller holds LOCK."""
    original = L['queue']
    for key, before in intent['before'].items():
        if original.get(key) != before:
            raise ValueError('a handoff child changed during publication; inspect current work and retry')
    L['queue'] = {**original, **deepcopy(intent['records'])}
    try:
        problems = queues.frontier_problems(task['place'], owner=task['id'])
        if problems:
            raise ValueError('handoff prerequisites changed:\n' + '\n'.join(problems))
    finally:
        L['queue'] = original


def settle(task, intent):
    """Publication has accepted this exact plan; finish from its durable verified intent alone."""
    original = L['queue']
    for key, record in intent['records'].items():
        if original.get(key) not in (intent['before'][key], record):
            raise ValueError('published handoff conflicts with newer child authority; preserve both for reconciliation')
    L['queue'] = {**original, **deepcopy(intent['records'])}
    try:
        receipt = lifecycle._receive(task, intent['run'], 'complete', intent['summary'],
                                     {**deepcopy(intent['evidence']), 'commit': intent['commit'],
                                      'handoff': deepcopy(intent['items'])})
    except BaseException:
        L['queue'] = original
        raise
    return {'ok': True, 'children': list(intent['records']), 'receipt': receipt}


def complete(body, *, allow_empty=False):
    from cointos import api
    with replacement.lease(ROOT, shared=True) as acquired:
        if not acquired:
            raise ValueError('runtime replacement in progress; retry planning handoff after replacement')
        with LOCK:
            task, run = api.caller(body)
            if not task or task['role'] != 'manager' or not task.get('branch'):
                raise ValueError('planning handoff requires the assigned manager')
            summary, items = body.get('summary'), body.get('items')
            if (not isinstance(summary, str) or not summary.strip() or not isinstance(items, list)
                    or (not items and not allow_empty)):
                raise ValueError('handoff needs a summary and nonempty child assignments')
            summary = summary.strip()
            receipt = task.get('receipt') or {}
            replay = receipt.get('run') == run and receipt.get('disposition') == 'complete'
            if replay:
                if receipt['summary'] != summary or receipt['evidence'].get('handoff') != items:
                    raise ValueError('this run already submitted a different handoff')
                result = {'ok': True, 'receipt': deepcopy(receipt)}
            else:
                api.running(body)
                current(task)
                if task.get('validating'):
                    raise ValueError('this planning handoff is already being prepared')
                preview(task, items)  # Invalid graphs must never publish a plan.
                where = deepcopy(tasks.place(task))
                version = task.get('record_version')
                candidate = deepcopy(task)
                task['validating'] = True
                ACTIVE['landings'] += 1
        if replay:
            save()
            queues.publish()
            return result
        try:
            commit = artifacts.maintenance(candidate, where)
            with git.repository_lock(where['path']):
                with LOCK:
                    api.running(body)
                    records = preview(task, items)
                    parent = git.head(where['path'], where['main_branch'])
                    if not git.contains(where['path'], parent, commit):
                        raise ValueError('accepted product changed; retry handoff to prepare the current plan')
                    intent = {'run': run, 'version': version, 'commit': commit, 'parent': parent,
                              'summary': summary, 'items': deepcopy(items), 'records': records,
                              'before': {key: deepcopy(L['queue'].get(key)) for key in records},
                              'evidence': lifecycle.repair_evidence(task) if task.get('repair_origin') else {}}
                    current(task, intent)
                    contracts.maintenance_history(where, task, parent)
                    unchanged = git.head(where['path'], commit + '^{tree}') == git.head(where['path'], parent + '^{tree}')
                    if unchanged:
                        # No product publication is needed. The graph and receipt are one
                        # ordinary ledger transaction; do not create artificial product versions.
                        task.pop('handoff_intent', None)
                        result = settle(task, {**intent, 'commit': parent})
                    else:
                        task['handoff_intent'] = intent
                if unchanged:
                    save()
                    queues.publish()
                    return result
                save()  # The exact graph and verified artifact precede repository mutation.
                with LOCK:
                    api.running(body)
                    current(task, intent)
                    graph(task, intent)
                    if task.get('handoff_intent') != intent:
                        raise ValueError('planning publication changed; retry the current handoff')
                    if git.head(where['path'], where['main_branch']) != parent:
                        raise ValueError('accepted product changed; retry handoff')
                    contracts.maintenance_history(where, task, parent)
                    git.publish(where['path'], where['main_branch'], commit, parent)
                    result = settle(task, intent)
                save()  # Acceptance and child authority are durable before acknowledgement.
            queues.publish()
            return result
        finally:
            with LOCK:
                task.pop('validating', None)
                ACTIVE['landings'] -= 1


def recover():
    """Settle verified, published planning intents before adoption or later controls. Caller holds LOCK."""
    count = 0
    for task in list(L['tasks'].values()):
        intent = task.get('handoff_intent')
        if not intent or task.get('receipt') or task['role'] != 'manager':
            continue
        record = queues.records().get(task.get('record'))
        if task.get('record_version') != intent['version'] or (record and
                (record['version'] != intent['version'] or record.get('done') or record.get('replaced_by'))):
            continue
        where = tasks.place(task)
        if not git.contains(where['path'], intent['commit'], where['main_branch']):
            continue
        settle(task, intent)
        log('planning handoff recovered', task=task['id'], children=list(intent['records']))
        count += 1
    return count
