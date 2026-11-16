"""Who can advance wanted work now.

The queue is the work identity; worker runs, reviews and recovery are attempts to
advance it. One controller owns recovery of an unchanged assignment, independently
of which execution task reported the failure. Product work remains under review.
These queries derive ownership from authority rather than storing another queue.
"""
from __future__ import annotations

from cointos import packets, queues, schema
from cointos.state import CONFIG, L


def inspect(task_id: str, ledger: dict, history: bool = False) -> dict:
    """Current work authority, with old execution narratives available explicitly.

    This pure projection is shared by launch prompts and CLI/MCP inspection. A
    recovery task's stored brief may describe an obsolete intermediate task.
    Only the live queue and typed correction relations describe what binds now.
    """
    task = ledger['tasks'].get(task_id)
    source = ledger['tasks'].get((task or {}).get('worker')) or task
    key = ((source or {}).get('repair_origin') or {}).get('task') or (source or {}).get('record') or task_id
    original = ledger['tasks'].get(key)
    owned = ledger['queue'].get(key) or ledger['queue'].get((original or {}).get('record'))
    if task is None and owned is None:
        raise ValueError(f'unknown task {task_id!r}; use cointos jobs for current IDs')

    def execution(value, compact=False):
        if value is None or history:
            return value
        result = {k: v for k, v in value.items()
                  if k not in ('recovery_context', 'system_context', 'tool_context', 'system_context_v2', 'tool_context_v2')}
        if owned or value.get('repair_origin'):
            result.pop('brief', None)
        receipt = result.get('receipt') or {}
        if result.get('result') and not receipt:
            # start/revise clears the receipt but retains the old account for
            # history. It must not read as this run's checked completion.
            result.pop('result')
            result['historical_fields'] = ['result']
        account = receipt.get('summary')
        if isinstance(account, str):
            if result.get('result') == account:
                result.pop('result')
            prefix = str(receipt.get('disposition')) + ': '
            note = result.get('note')
            if isinstance(note, str) and note.startswith(prefix) and account.startswith(note[len(prefix):]):
                result.pop('note')
        for field in ('note', 'review', 'recovery_note'):
            if (compact or value.get('repair_origin')) and isinstance(result.get(field), str) and len(result[field]) > 1000:
                result[field] = result[field][:1000] + '\n[Historical detail: task --history ' + value['id'] + ']'
        return result

    binding = []
    for name in (owned or {}).get('depends', []):
        packet = ledger['queue'].get(f"{owned['project']}:{name}")
        if not packet or packet.get('stage') != 'test-contract' or not (packet.get('done') or {}).get('commit'):
            continue
        seen = set()
        while packet.get('corrected_by') and packet['corrected_by'] not in seen:
            seen.add(packet['corrected_by'])
            replacement = ledger['queue'].get(packet['corrected_by'])
            if not replacement or not (replacement.get('done') or {}).get('commit'):
                break
            packet = replacement
        packet_key = queues.key(packet)
        binding.append({'packet': packet_key, 'commit': packet['done']['commit'],
                        'pending_corrections': [queues.key(r) for r in ledger['queue'].values()
                            if (r.get('correction') or {}).get('packet') == packet_key
                            and not r.get('done') and not r.get('replaced_by')]})
    queue_view = dict(owned) if owned else None
    result = {'task': execution(task), 'queue': queue_view, 'binding_tests': binding}
    inputs = [*(task or {}).get('carried_work', []), *(owned or {}).get('carried_work', [])]
    if inputs:
        result['preserved_inputs'] = [{'task': key, 'role': (ledger['tasks'].get(key) or {}).get('role')}
                                      for key in dict.fromkeys(reference['task'] for reference in inputs)]
    if task:
        import time
        result['usage'] = usage(task, ledger, time.time())
    failure = (source or {}).get('composition_failure') or ((source or {}).get('submission_failure') or {}).get('composition')
    if failure:
        result['composition_failure'] = failure
    if task and task.get('repair_origin'):
        origin_failure = (original or {}).get('composition_failure') or ((original or {}).get('submission_failure') or {}).get('composition')
        if origin_failure:
            result['composition_failure'] = origin_failure
        result['recovery_origin'] = dict(task['repair_origin'])
        result['origin_task'] = execution(original, compact=True)
        result['recovery_instruction'] = (
            'Recover the current queue assignment shown here. Binding tests change only after independent '
            'acceptance of a typed correct-tests replacement. An ordinary test packet or revised brief does '
            'not replace them. Pending corrections above are actual typed owners, not claims in prose. '
            'Cancel obsolete queued work by its queue ID, not its derived recovery task ID.')
    if result.get('composition_failure'):
        failure = result['composition_failure']
        result['composition_failure'] = {**failure, 'test_tasks': [entry['packet'] for entry in binding
            if entry['commit'] == failure.get('failed_packet')]}
    if not history:
        accounts = [(value or {}).get('receipt') or {} for value in
                    (result['task'], result.get('origin_task'))]
        if queue_view and queue_view.get('blocker'):
            if any(queue_view['blocker'] == receipt.get('summary') for receipt in accounts):
                queue_view.pop('blocker')
            elif len(queue_view['blocker']) > 1000:
                queue_view['blocker'] = queue_view['blocker'][:1000] + '\n[Full evidence: task --history ' + task_id + ']'
        result['historical_evidence'] = f'cointos task {task_id} --history'
    return result


def usage(task: dict, ledger: dict, at: float) -> dict:
    agent = next((a for a in ledger['agents'].values() if a['task'] == task['id']), {})
    if not agent and task.get('last_run_usage'):
        return {**task['last_run_usage'], 'scope': 'last completed run'}
    gpu = agent.get('gpu_seconds', 0)
    if agent.get('gpu_since'):
        gpu += max(0, at - agent['gpu_since'])
    return {'scope': 'current run', 'available': bool(agent), 'gpu_seconds': gpu,
            'generated_tokens': agent.get('generation_tokens', agent.get('generated', 0))}


def implementation_view(view: dict) -> dict:
    """An implementer needs its behaviour and checkout, not acceptance machinery."""
    task = view.get('task') or {}
    queue = view.get('queue') or {}
    fields = ('id', 'role', 'stage', 'status', 'worktree', 'work_remaining')
    shown = {k: task[k] for k in fields if k in task}
    brief = queue.get('brief', task.get('brief', ''))
    # These headers are queue metadata, not behavioural requirements.
    shown['brief'] = '\n'.join(line for line in brief.splitlines()
                               if not line.lower().startswith(('depends on:', 'relies on:', 'workflow stage:')))
    return {'task': shown}


def agent_view(view: dict, reader: dict) -> dict:
    """Keep assignment/recovery evidence while forgetting private repository representations."""
    if reader.get('role') == 'worker' and reader.get('stage') != 'test-contract':
        view = implementation_view(view)
    # Other assignments are inspected through source/diagnostic controls, not
    # by navigating their private execution directories.
    view = dict(view)
    for field in ('task', 'origin_task'):
        task = view.get(field)
        if isinstance(task, dict):
            view[field] = {k: v for k, v in task.items() if k != 'retired'
                           and (k != 'worktree' or task.get('id') == reader.get('id'))}
    return file_view(view)


def file_view(view):
    """Public file/task evidence without daemon-private storage identities."""
    private = {'branch', 'base_commit', 'commit', 'worker_commit', 'main', 'main_branch',
               'candidate', 'tree', 'prepared_review', 'landing', 'handoff_intent', 'preserved_artifact',
               'preserved_run', 'carried_work', 'material_snapshots', 'session_store', 'system_context', 'tool_context',
               'system_context_v2', 'tool_context_v2'}

    def preparation(evidence):
        from cointos.contracts import CompositionError
        return CompositionError('', paths=evidence.get('paths')).public

    def public(value):
        if isinstance(value, dict):
            if isinstance(value.get('push'), dict):
                delivery = value['push']
                shown = {'status': delivery.get('status')}
                if delivery.get('status') == 'failed':
                    shown['error'] = 'External delivery failed; accepted work remains recorded. CointOS retains diagnostics for the operator.'
                value = {**value, 'push': shown}
            receipt = value.get('receipt')
            receipt = receipt if isinstance(receipt, dict) else {}
            evidence = receipt.get('evidence')
            evidence = evidence if isinstance(evidence, dict) else {}
            account = f"{value.get('item')} accepted at {evidence.get('commit')}"
            if (receipt.get('disposition') == 'complete' and evidence.get('via') == 'landing'
                    and receipt.get('summary') == account):
                shown = f"{value['item']} accepted"
                value = {**value, 'receipt': {**receipt, 'summary': shown}}
                if value.get('note') == 'complete: ' + account:
                    value['note'] = 'complete: ' + shown
                if value.get('result') == account:
                    value['result'] = shown
            failure = value.get('composition_failure') or (value.get('submission_failure') or {}).get('composition')
            if failure:
                value = dict(value)
                if 'note' in value:
                    value['note'] = preparation(failure)
                if isinstance(value.get('queue'), dict) and value['queue'].get('blocker'):
                    value['queue'] = {**value['queue'], 'blocker': preparation(failure)}
                if (value.get('receipt') or {}).get('disposition') == 'blocked':
                    value['receipt'] = {**value['receipt'], 'summary': preparation(failure)}
            if value.get('category') == 'composition' and value.get('composition'):
                value = {**value, 'error': preparation(value['composition'])}
            return {('workspace' if k == 'worktree' else k): public(v)
                    if k not in ('composition_failure', 'composition') else {
                        'paths': v.get('paths', []), 'test_tasks': v.get('test_tasks', [])}
                    for k, v in value.items() if k not in private
                    and k not in ('failed_packet', 'packets')
                    and not (k == 'tests' and isinstance(v, list) and all(
                        isinstance(item, str) and len(item) == 40 and all(c in '0123456789abcdef' for c in item)
                        for item in v))}
        if isinstance(value, list):
            return [public(v) for v in value]
        return value

    return public(view)


def record(source: dict) -> dict | None:
    if 'project' in source:
        return source
    if source.get('worker'):
        source = L['tasks'].get(source['worker']) or source
    return queues.records().get(source.get('record'))


def origin(source: dict) -> dict:
    if (source.get('kind') == 'integrate' and source['status'] == 'failed'
            and source.get('runs', 0) > 0 and not source.get('receipt')):
        return {'task': source['id'], 'version': source.get('record_version')}
    owned = record(source)
    version = source['version'] if 'project' in source else source.get('record_version')
    if version is None and owned:
        version = owned['version']
    return {'task': queues.key(owned) if owned else source['id'],
            'version': version}


def controller(source: dict) -> dict | None:
    identity = origin(source)
    owners = [t for t in L['tasks'].values() if t.get('repair_origin') == identity]
    return min(owners, key=lambda t: (t['status'] not in schema.PENDING, t['created_at']), default=None)


def obsolete(task: dict) -> bool:
    identity = task.get('repair_origin')
    if not identity:
        return False
    owned = queues.records().get(identity['task'])
    return bool(owned and owned['version'] != identity['version']
                and owned.get('revised_by') != task['id'])


def children(source: dict) -> list[dict]:
    """Work proposed by an assignment or its current canonical recovery owner."""
    owned = record(source)
    task = queues.current(source) if 'project' in source else source
    repair = controller(source)
    owners = {owner['id'] for owner in (task, repair) if owner}
    found = [r for r in queues.records().values()
             if r.get('proposed_by') in owners
             and r.get('revised_by') in (None, r.get('proposed_by'))
             and not r.get('done') and not r.get('replaced_by') and not r.get('held_by')]
    for candidate in packets.continuations(owned) if owned else []:
        if candidate not in found:
            found.append(candidate)
    return found


def handoffs(source: dict) -> list[dict]:
    """Children whose dependency closure can actually advance the origin."""
    result = []
    for child in children(source):
        readiness = queues.readiness(queues.live(child['project']), queues.landed(child['project']))
        pending, seen, valid = [child], set(), True
        while pending:
            node = pending.pop()
            key = queues.key(node)
            if key in seen or node.get('done'):
                continue
            seen.add(key)
            status = queues.state(node)
            if (key == origin(source)['task'] or node.get('held_by')
                    or readiness.get(node['item']) not in ('ready', 'waiting')
                    or (status['status'] == 'blocked' and not status['recoverable'])):
                valid = False
                break
            pending.extend(queues.records()[f"{node['project']}:{name}"] for name in node['depends']
                           if f"{node['project']}:{name}" in queues.records())
        if valid:
            result.append(child)
    return result


def handoff_pending(source: dict) -> bool:
    return bool(handoffs(source))


def reason(source: dict) -> str | None:
    """A current obstruction requiring a controller, never a historical run failure."""
    if L['paused'] or source.get('cancelled') or source.get('replaced_by'):
        return None
    owned = record(source)
    if 'project' not in source and source.get('record') and owned is None:
        return None
    place = source.get('project', source.get('place'))
    project = next((p for p in CONFIG['projects'] if p['name'] == place), None)
    if project and not project.get('enabled', True):
        return None
    if 'project' in source and project is None:
        return None
    if ('project' not in source and project is None and place != 'system'
            and schema.KINDS[source['kind']]['scope'] in ('project', 'either')):
        return None
    task = queues.current(source) if 'project' in source else source
    died = task and task['status'] == 'failed' and task.get('runs', 0) > 0 and not task.get('receipt')
    # An unreceipted death needs diagnosis regardless of role, including the
    # controller itself. A checked blocked receipt is a different outcome.
    if died and not (owned and (owned.get('done') or owned.get('replaced_by'))):
        return task.get('note') or 'run ended without a completion receipt'
    if owned:
        if owned.get('done') or owned.get('replaced_by') or owned.get('held_by'):
            return None
        if 'project' not in source and source.get('record_version') != owned['version']:
            return None
    if task is None:
        readiness = queues.readiness(queues.live(place), queues.landed(place)).get(source['item'], '')
        return readiness if readiness.startswith('depends on unknown ') or 'cycle' in readiness else None
    if task.get('repair_origin') or task['kind'] in ('operator', 'integrate', 'supervise'):
        return None
    if owned is None and any(t['kind'] == task['kind'] and t['place'] == place
                             and t['created_at'] > task['created_at'] for t in L['tasks'].values()):
        return None
    hold = task.get('admission_hold')
    if hold:
        return (task.get('note') or hold) if hold == 'repeated infrastructure launch failure' else None
    if task['status'] not in schema.SETTLED:
        return None
    receipt = task.get('receipt') or {}
    if task['status'] != 'failed' and receipt.get('disposition') != 'blocked':
        return None
    if handoff_pending(task):
        return None
    return receipt.get('summary') or task.get('note') or 'assignment ended without a checked handoff'


def runnable(task: dict) -> bool:
    """Recovery never competes with another recovery owner in the same project."""
    identity = task['repair_origin']
    source = queues.records().get(identity['task']) or L['tasks'].get(identity['task'])
    if source is None:
        return bool(task['runs'])  # a retained run can close a withdrawn assignment
    owned = record(source)
    original = queues.current(source) if 'project' in source else source
    if owned and owned.get('held_by') not in (None, task['id']):
        return False
    if original and original.get('admission_hold') not in (None, 'repeated infrastructure launch failure'):
        return False
    if not task['runs'] and (origin(source) != identity or reason(source) is None):
        return False
    return not any(other['id'] != task['id'] and other.get('repair_origin')
                   and other['place'] == task['place'] and other['status'] == 'running'
                   for other in L['tasks'].values())


def view(project: str | None = None) -> list[dict]:
    result = []
    for owned in queues.records().values():
        if project is not None and owned['project'] != project:
            continue
        if owned.get('done') or owned.get('replaced_by'):
            continue
        task, repair = queues.current(owned), controller(owned)
        result.append({'item': queues.key(owned), 'version': owned['version'],
                       'status': queues.status(owned), 'held_by': owned.get('held_by'),
                       'admission_hold': (task or {}).get('admission_hold'),
                       'owner': repair['id'] if repair and repair['status'] in schema.PENDING else
                                (task['id'] if task and task['status'] in schema.ACTIVE else None),
                       'recovery': repair['id'] if repair else None,
                       'continuations': [queues.key(r) for r in handoffs(owned)],
                       'blocker': queues.state(owned)['blocker']})
    return result
