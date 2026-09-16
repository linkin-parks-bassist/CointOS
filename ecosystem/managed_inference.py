"""Automatic native inference acquisition; credentials never leave the owner."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from ecosystem import cli, inference_capacity, models, workload_control
from ecosystem import inference_proxy as proxy


class InferenceWaiting(RuntimeError):
    """A retained request needs resource/cleanup recovery, rather than rejection."""


def _operator(root):
    path = Path(root) / 'state/operator-sessions.json'
    if not path.exists():
        return None
    stat = Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')', 1)[1].split()
    identity = {'pid': os.getpid(), 'process_start_ticks': int(stat[19])}
    for session in json.loads(path.read_text()).get('sessions', {}).values():
        if session.get('state') == 'active' and session.get('process') == identity:
            return session
    return None


def _caller_identity():
    stat = Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': os.getpid(), 'process_start_ticks': int(stat[19])}


def _kernel_start_ticks(pid):
    """Read the kernel start ticks; returns (status, ticks).

    status is 'ok' (ticks read), 'absent' (/proc entry gone), or 'unreadable'
    (inaccessible or malformed). Only 'absent' proves the original process is
    gone; 'unreadable' must stay unverified.
    """
    try:
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return 'ok', int(stat[19])
    except FileNotFoundError:
        return 'absent', None
    except (KeyError, ValueError, IndexError, OSError):
        return 'unreadable', None


def _owner_liveness(record):
    """Kernel proof of the recorded caller: 'live', 'dead', or 'unverified'.

    A live match requires the same pid and the same kernel start ticks, so a
    reused pid never passes as the original caller. Only proven absence of the
    original process, or a pid held by a process with different start ticks,
    establishes death.
    """
    pid = record.get('owner_pid')
    ticks = record.get('owner_start_ticks')
    if type(pid) is not int or pid <= 0 or type(ticks) is not int or ticks < 0:
        return 'unverified'
    status, observed = _kernel_start_ticks(pid)
    if status == 'absent':
        return 'dead'
    if status == 'unreadable':
        return 'unverified'
    return 'live' if observed == ticks else 'dead'


def _process_ended(pid, ticks):
    """True only with kernel proof that the recorded process is gone."""
    if type(pid) is not int or pid <= 0 or type(ticks) is not int or ticks < 0:
        return None
    status, observed = _kernel_start_ticks(pid)
    if status == 'unreadable':
        return None
    if status == 'absent':
        return True
    return observed != ticks


def _process_group_absent(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return None
    return False


def _retain(record_path, record, next_check, reason):
    record.update(state='reconciliation_required', reason=reason,
                  reconciliation={'next_check': next_check})
    cli.atomic_json(record_path, record)


def _capacity_lease_for_worker(root, worker_lease_id):
    path = root / 'state/inference-capacity.json'
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    for lease in state.get('leases', {}).values():
        if lease.get('request', {}).get('worker_lease_id') == worker_lease_id:
            return lease
    return None


def _worker_lease(root, lease_id):
    state = json.loads((root / 'state/workload-control.json').read_text())
    return state.get('leases', {}).get(lease_id)


def _credential_for_lease(root, lease_id):
    path = root / 'state/inference-proxy.json'
    if not path.exists():
        return None
    return json.loads(path.read_text()).get('credentials', {}).get(lease_id)


def _worker_request(identifier, route, request, authority, owner, operator, clock):
    result = {
        'workload_class': 'front' if authority == 'coin' else 'work',
        'model_id': route['model_id'], 'context_tokens': route['context_tokens_per_sequence'],
        'max_output_tokens': request['max_output_tokens'], 'deadline_monotonic': clock() + 86400,
        'owner_identity': owner, 'job_id': identifier, 'agent_generation': 1,
        'caller_handle': 'native-inference', 'request_id': identifier + ':worker',
        'stop_method': 'process_group', 'role': 'coin' if authority == 'coin' else 'worker',
        'authority_profile': authority, 'execution_profile': None,
        **{key: request[key] for key in ('requirements', 'prompt_tokens', 'tool_tokens', 'handoff_tokens')},
    }
    if operator:
        result['operator_session_id'] = operator['session_id']
    return result


def _finish(root, worker, gate, lease, clock, issued=False):
    from ecosystem import executor
    outcome = executor.gated_child_cleanup(gate)
    if outcome.get('state') != 'reaped' or outcome.get('process_group_alive') is not False:
        raise InferenceWaiting('owned inference process cleanup is pending')
    if lease and lease.get('state') not in {'deferred', 'released'}:
        if issued:
            evidence = proxy.completed_run_termination(root, lease['lease_id'], clock)
            if evidence is None:
                raise InferenceWaiting('backend termination is pending; request and allocation retained')
            proxy.revoke_proxy_credential(root, lease['lease_id'], evidence, clock)
        else:
            inference_capacity.withdraw_unissued_sequence(root, lease['lease_id'], clock)
    executor._observe_stopped_worker(
        root, worker, gate, outcome, {'state': 'run_finished', 'returncode': outcome['returncode']},
        clock, workload_control.release_worker, workload_control.observe_workers)


def _close_unissued_worker(root, record_path, record, lease, clock):
    """Close a worker lease whose attempt could never call the backend."""
    if lease.get('state') == 'quiescent':
        record.update(state='cancelled', reason='caller_terminated',
                      reconciliation={'next_check': 'none'})
        cli.atomic_json(record_path, record)
        return
    process = lease.get('process')
    if process is None:
        # Only reached with explicit spawn_intent=False, proving no Popen was
        # initiated. A missing legacy marker is retained by _reconcile_record;
        # gate non-execution alone would not prove that no child was spawned.
        observation = {'lease_id': lease['lease_id'], 'never_spawned': True,
                       'backend_request_active': False, 'inference_lease_active': False}
    else:
        if (_process_ended(process['pid'], process['process_start_ticks']) is not True
                or _process_group_absent(process['pid']) is not True):
            raise InferenceWaiting('owned child absence is not yet proven')
        observation = {
            'lease_id': lease['lease_id'], 'pid': process['pid'],
            'process_start_ticks': process['process_start_ticks'],
            'process_group_alive': False, 'backend_request_active': False,
            'inference_lease_active': False,
        }
    if lease.get('state') != 'release_requested':
        workload_control.release_worker(
            root, lease['lease_id'], {'state': 'run_terminated', 'returncode': None}, clock)
    workload_control.observe_workers(root, [observation], clock)
    record.update(state='cancelled', reason='caller_terminated',
                  reconciliation={'next_check': 'none'})
    cli.atomic_json(record_path, record)


def _reconcile_issued(root, record_path, record, clock):
    """Close an issued attempt only through the proxy end/revoke contracts.

    Caller or child exit is never treated as backend release; occupancy stays
    held until the proxy verifies the sequence end.
    """
    lease_id = record['inference_lease_id']
    if _process_ended(record.get('child_pid'), record.get('child_start_ticks')) is not True:
        _retain(record_path, record, 'verify_backend_termination',
                'caller_terminated; owned child still running')
        return
    evidence = proxy.completed_run_termination(root, lease_id, clock)
    if evidence is None:
        _retain(record_path, record, 'verify_backend_termination',
                'caller_terminated; backend termination unverified')
        return
    proxy.revoke_proxy_credential(root, lease_id, evidence, clock)
    lease = _worker_lease(root, record['worker_lease_id'])
    if lease is not None and lease.get('state') != 'quiescent':
        if lease.get('process') is None:
            raise InferenceWaiting('worker process identity is missing')
        _close_unissued_worker(root, record_path, record, lease, clock)
    record.update(state='completed',
                  reason='caller_terminated; backend termination verified on reconciliation')
    cli.atomic_json(record_path, record)


def _reconcile_record(root, record_path, record, clock):
    liveness = _owner_liveness(record)
    if liveness == 'live':
        return 'live'
    if liveness == 'unverified':
        if record.get('state') != 'reconciliation_required':
            _retain(record_path, record, 'verify_caller_identity',
                    'caller identity cannot be proven dead (pid reuse is possible)')
        return 'retained'
    state = record.get('state')
    if state in {'waiting', 'suspended'} or (
            state == 'reconciliation_required' and record.get('worker_lease_id') is None):
        record.update(state='cancelled', reason='caller_terminated',
                      reconciliation={'next_check': 'none'})
        cli.atomic_json(record_path, record)
        return 'cancelled'
    if record.get('worker_lease_id') is None:
        _retain(record_path, record, 'verify_worker_lease',
                'caller_terminated; worker lease is missing')
        return 'retained'
    capacity_lease = _capacity_lease_for_worker(root, record['worker_lease_id'])
    issued = (capacity_lease is not None
              and _credential_for_lease(root, capacity_lease['lease_id']) is not None)
    if not issued:
        # Unissued attempt: the gated child could never call the backend. Close
        # the worker lease only once its birth is proven: either a registered
        # child whose absence is verified, or a durably recorded absence of any
        # spawn intent. A spawn intent without an observed birth is ambiguous
        # (the gated child may exist) and must be retained, never attested as
        # never_spawned.
        worker_lease = _worker_lease(root, record['worker_lease_id'])
        if worker_lease is None:
            _retain(record_path, record, 'verify_worker_lease',
                    'caller_terminated; worker lease is missing')
            return 'retained'
        process = worker_lease.get('process')
        if process is not None:
            if (_process_ended(process['pid'], process['process_start_ticks']) is not True
                    or _process_group_absent(process['pid']) is not True):
                _retain(record_path, record, 'verify_owned_child_absence',
                        'caller_terminated; owned child absence is not yet proven')
                return 'retained'
        elif record.get('spawn_intent') is not False:
            # No registered child. never_spawned is proven only by an explicit
            # spawn_intent=False marker. A recorded True (spawn initiated, birth
            # unobserved) or a missing marker (legacy) is ambiguous and must be
            # retained, never attested as never_spawned.
            _retain(record_path, record, 'verify_worker_birth',
                    'caller_terminated; child birth is not proven absent')
            return 'retained'
        if capacity_lease is not None and capacity_lease.get('state') != 'released':
            inference_capacity.withdraw_unissued_sequence(root, capacity_lease['lease_id'], clock)
        _close_unissued_worker(root, record_path, record, worker_lease, clock)
        return 'recovered'
    record['inference_lease_id'] = capacity_lease['lease_id']
    _reconcile_issued(root, record_path, record, clock)
    return 'recovered' if record.get('state') == 'completed' else 'retained'


def reconcile_dead_callers(root, clock=time.monotonic) -> dict:
    """Reconcile durable native records after their callers have died.

    Live callers (pid + kernel start ticks) are never touched. Dead callers
    release only unissued allocations, and issued attempts stay occupied until
    the proxy verifies backend termination. No inference is re-run: recovery
    never repeats a request merely because a process ended.
    """
    root = Path(root)
    directory = root / 'state' / 'inference-runs'
    results = {'live': 0, 'recovered': 0, 'retained': 0, 'cancelled': 0,
               'ignored': 0, 'pending': []}
    if not directory.is_dir():
        return results
    for path in sorted(directory.glob('native-*.json')):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if type(record) is not dict or record.get('id') != path.stem:
            continue
        if record.get('state') not in {'waiting', 'starting', 'acquiring', 'running',
                                       'suspended', 'reconciliation_required'}:
            results['ignored'] += 1
            continue
        try:
            outcome = _reconcile_record(root, path, record, clock)
        except InferenceWaiting as pending:
            results['pending'].append({'id': record.get('id'), 'reason': str(pending)})
            continue
        except ValueError:
            _retain(path, record, 'verify_record_shape',
                    'durable record failed reconciliation validation')
            outcome = 'retained'
        results[outcome] = results.get(outcome, 0) + 1
    return results


def request(model: str, messages: list[dict], max_tokens: int, timeout: float = 180,
            temperature: float = .35, tools=None, response_format=None, *,
            root: Path | None = None, control: bool = False,
            refresh=None, clock=time.monotonic, sleeper=time.sleep, cancelled=None) -> dict:
    """Wait/retry for a loaded model, acquire/run/close automatically.

    Timeout bounds inference only, not time waiting for higher-priority resources.
    Control priority is selected by the trusted Telegram caller, never message JSON.
    """
    root = Path(root) if root is not None else cli.ROOT
    if not isinstance(model, str) or not model or type(messages) is not list:
        raise ValueError('invalid native inference request')
    if type(max_tokens) is not int or max_tokens <= 0:
        raise ValueError('invalid native output allowance')
    if (timeout is not None
            and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0)):
        raise ValueError('invalid native inference timeout')
    refresh = refresh or (lambda: models.snapshot(root))
    identifier = 'native-' + uuid.uuid4().hex
    record_path = root / 'state/inference-runs' / (identifier + '.json')
    operator = _operator(root)
    caller = _caller_identity()
    values = inference_capacity.scheduling_snapshot(root)
    authority = values['authority_profiles']['coin'] if control else 'ordinary'
    owner = operator['request']['owner_identity'] if operator else identifier
    # Routing gets the actual request allowance rather than worker policy defaults.
    routing = {
        'requirements': {'required_capabilities': ['tool-calling'] if tools else [],
                         'minimum_context_tokens': 0},
        'prompt_tokens': max(1, len(json.dumps(messages).encode()) // 2),
        'tool_tokens': max(1, len(json.dumps(tools or []).encode()) // 2),
        'max_output_tokens': max_tokens, 'handoff_tokens': 0,
    }
    record = {'id': identifier, 'state': 'waiting', 'model': model, 'messages': messages,
              'owner_pid': caller['pid'], 'owner_start_ticks': caller['process_start_ticks'],
              'owner_identity': owner, 'attempts': 0}
    cli.atomic_json(record_path, record)
    from ecosystem import executor
    while True:
        if cancelled and cancelled():
            record['state'] = 'cancelled'; cli.atomic_json(record_path, record)
            raise InterruptedError('native inference cancelled while waiting')
        try:
            inventory = refresh()
            policy = json.loads((root / 'config/resource-policy.json').read_text())
            route = next((item for item in models.safe_routes(inventory, policy, routing)
                          if item.get('model_id') == model), None)
        except (OSError, ValueError, RuntimeError) as error:
            record.update(state='waiting', reason=f'capacity refresh: {error}')
            cli.atomic_json(record_path, record); sleeper(.1); continue
        if not route or route.get('state') != 'admitted':
            record.update(state='waiting', reason=(route or {}).get('exclusion_reasons', ['model_not_loaded']))
            cli.atomic_json(record_path, record); sleeper(.1); continue
        if not route.get('loaded'):
            decision = {**route, 'action': 'load', 'model': model,
                        'context_tokens': route['context_tokens_per_sequence'],
                        'reason': 'managed inference requires unloaded model', 'valid': True}
            try:
                models.realize(decision, inventory)
            except (OSError, ValueError, RuntimeError) as error:
                record.update(state='waiting', reason=f'model realization: {error}')
                cli.atomic_json(record_path, record); sleeper(.1); continue
            record.update(state='waiting', reason='model realization completed; refreshing inventory')
            cli.atomic_json(record_path, record); sleeper(.1); continue
        record['attempts'] += 1
        for stale in ('worker_lease_id', 'child_pid', 'child_start_ticks',
                      'inference_lease_id', 'spawn_intent'):
            record.pop(stale, None)
        attempt = identifier + ':' + str(record['attempts'])
        worker_request = _worker_request(attempt, route, routing, authority, owner, operator, clock)
        # Use configured authority identities, rather than assuming the value is literally coin.
        worker_request['workload_class'] = 'front' if control else 'work'
        worker_request['role'] = 'coin' if control else 'worker'
        worker = workload_control.acquire_worker(root, worker_request, clock)
        if worker.get('state') == 'deferred':
            record.update(state='waiting', reason=worker.get('reasons', []))
            cli.atomic_json(record_path, record); sleeper(.1); continue
        # spawn_intent=False is recorded with the starting state so a reader can
        # distinguish "no spawn was initiated" (False) from "a spawn was
        # initiated" (True, set just before the Popen) from a legacy record with
        # no marker at all (proves nothing and must be retained).
        record.update(state='starting', worker_lease_id=worker['lease_id'], spawn_intent=False)
        cli.atomic_json(record_path, record)
        fd = None
        gate = None
        launch_attempted = False
        env = dict(os.environ)
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
        lease = None
        issued = False
        with tempfile.TemporaryFile() as output:
            try:
                fd = os.memfd_create('native-inference', 0)
                record['spawn_intent'] = True
                cli.atomic_json(record_path, record)
                launch_attempted = True
                gate = executor.gated_child_launch(
                    fd, [sys.executable, '-m', 'ecosystem.managed_inference', '--child', str(fd)],
                    env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL)
                workload_control.register_process(root, worker['lease_id'], gate['pid'], gate['start_ticks'], clock)
                record.update(state='acquiring', child_pid=gate['pid'], child_start_ticks=gate['start_ticks'],
                              worker_lease_id=worker['lease_id'])
                cli.atomic_json(record_path, record)
            except BaseException as error:
                if gate is not None:
                    # gated_child_launch returned a live gated child; _finish
                    # reaps it and reconciles the worker lease through the
                    # executor's own observation contract.
                    _finish(root, worker, gate, None, clock)
                    record.update(state='failed', reason=str(error))
                    cli.atomic_json(record_path, record)
                    raise error
                launch_failure = getattr(error, 'launch_failure', None)
                cleanup = launch_failure.get('cleanup') if launch_failure else None
                tagged = launch_failure is not None
                # Nonbirth is proven only when no launch was attempted, or when
                # the executor explicitly attests spawned=False. A missing
                # launch_failure after an attempt proves nothing.
                nonbirth_proven = (not launch_attempted) or (
                    tagged and launch_failure.get('spawned') is False)
                reaped = (cleanup is not None and cleanup.get('state') == 'reaped'
                          and cleanup.get('process_group_alive') is False)
                # config_fd ownership is unambiguous only when no launch was
                # attempted. After an attempt the executor may or may not have
                # closed it (for example os.pipe can fail before its try block),
                # so it must not be closed here: that risks EBADF or closing a
                # reused descriptor.
                if not launch_attempted and fd is not None:
                    os.close(fd)
                workload_control.release_worker(root, worker['lease_id'],
                    {'state': 'failed', 'returncode': 1}, clock)
                if nonbirth_proven:
                    workload_control.observe_workers(root,
                        [{'lease_id': worker['lease_id'], 'never_spawned': True}], clock)
                    record.update(state='failed', reason=str(error))
                    cli.atomic_json(record_path, record)
                elif reaped:
                    workload_control.observe_workers(root, [{'lease_id': worker['lease_id'],
                        'reaped_spawn': {'pid': launch_failure.get('pid'),
                            'process_start_ticks': cleanup.get('start_ticks'),
                            'returncode': cleanup.get('returncode'),
                            'process_group_alive': False}}], clock)
                    record.update(state='failed', reason=str(error))
                    cli.atomic_json(record_path, record)
                else:
                    # Ambiguous: a launch was attempted but neither nonbirth nor a
                    # proven reap is established (untagged failure, or spawned but
                    # reaped state unknown). Do not attest a stop; retain the
                    # record for reconciliation.
                    _retain(record_path, record, 'verify_worker_birth',
                            'launch_failed; child termination is not proven')
                raise error
            sequence_request = {
                'request_id': attempt + ':sequence', 'worker_lease_id': worker['lease_id'],
                'worker_request_id': worker_request['request_id'], 'owner_identity': owner,
                'workload_class': worker_request['workload_class'],
                'proxy_identity': policy['inference_capacity']['front_proxy_identity' if control else 'work_proxy_identity'],
                'route': route, 'role': worker_request['role'], 'execution_profile': None,
                'authority_profile': authority, 'preemption_method': 'process_group',
            }
            try:
                lease = inference_capacity.reserve_sequence(root, sequence_request, inventory, clock)
                while lease.get('state') in {'waiting_for_preemption', 'ready_for_revalidation'}:
                    record.update(state='waiting', inference_lease_id=lease['lease_id'])
                    cli.atomic_json(record_path, record)
                    if cancelled and cancelled():
                        raise InterruptedError('native inference cancelled during acquisition')
                    sleeper(.1)
                    inventory = refresh()
                    previous = lease
                    lease = inference_capacity.reserve_sequence(root, sequence_request, inventory, clock)
                    if lease.get('state') == 'deferred':
                        lease['pending_acquisition'] = previous
                if lease.get('state') == 'deferred':
                    _finish(root, worker, gate, lease.get('pending_acquisition'), clock)
                    record.update(state='waiting', reason=lease.get('reasons', []))
                    cli.atomic_json(record_path, record); sleeper(.1); continue
                semantic = {'lease': lease, 'messages': messages, 'timeout': timeout,
                            'temperature': temperature}
                if tools is not None:
                    semantic.update(tools=tools, tool_choice='auto')
                if response_format is not None:
                    semantic['response_format'] = response_format
                def deliver(secret):
                    payload = json.dumps({'root': str(root), 'request': semantic, 'credential': secret.hex()}).encode()
                    offset = 0
                    while offset < len(payload):
                        offset += os.write(fd, payload[offset:])
                    os.lseek(fd, 0, os.SEEK_SET)
                proxy.issue_proxy_credential(root, lease, deliver, clock)
                issued = True
                record.update(state='running', inference_lease_id=lease['lease_id'])
                cli.atomic_json(record_path, record)
                executor.gated_child_release(gate)
                preempted = False
                started = clock()
                while gate['process'].poll() is None:
                    state = json.loads((root / 'state/inference-capacity.json').read_text())
                    preempted = state['leases'][lease['lease_id']]['state'] == 'preemption_requested'
                    if preempted or (cancelled and cancelled()) or (
                            timeout is not None and clock() - started > timeout + 5):
                        proxy.cancel(root, lease['lease_id'], clock)
                        break
                    sleeper(.05)
                while True:
                    try:
                        _finish(root, worker, gate, lease, clock, issued)
                        break
                    except InferenceWaiting as pending:
                        record.update(state='waiting', reason=str(pending))
                        cli.atomic_json(record_path, record); sleeper(.1)
                if cancelled and cancelled():
                    record['state'] = 'cancelled'; cli.atomic_json(record_path, record)
                    raise InterruptedError('native inference cancelled')
                if preempted:
                    record.update(state='suspended', reason='higher_priority_inference')
                    cli.atomic_json(record_path, record); sleeper(.1); continue
                output.seek(0)
                result = json.load(output)
                if 'error' in result:
                    raise RuntimeError(result['error'])
                record.update(state='completed'); cli.atomic_json(record_path, record)
                return result['assistant']
            except BaseException as error:
                # Never turn an unknown upstream termination into available GPU capacity.
                try:
                    _finish(root, worker, gate, lease, clock, issued)
                except Exception as cleanup_error:
                    record.update(state='reconciliation_required', reason=str(cleanup_error))
                    cli.atomic_json(record_path, record)
                    raise InferenceWaiting(str(cleanup_error)) from error
                record.update(state='waiting' if isinstance(error, InferenceWaiting) else 'failed', reason=str(error))
                cli.atomic_json(record_path, record)
                raise


def _child(fd):
    from ecosystem.inference import request as admitted_request
    with os.fdopen(fd) as stream:
        payload = json.load(stream)
    semantic = payload['request']
    semantic['credential'] = bytes.fromhex(payload['credential'])
    try:
        result = {'assistant': admitted_request(semantic, Path(payload['root']), time.monotonic)}
    except Exception as error:
        result = {'error': f'{type(error).__name__}: {error}'}
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--child':
        raise SystemExit('internal native inference worker only')
    _child(int(sys.argv[2]))
