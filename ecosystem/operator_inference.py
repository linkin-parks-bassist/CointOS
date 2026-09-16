"""Managed local OpenCode runs: acquire automatically, retain and resume on priority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from ecosystem import cli, executor, inference_capacity, models, operator_session


def _argument(command, option, default=None):
    return command[command.index(option) + 1] if option in command else default


def _controller_process_alive(record):
    controller = record.get('controller_process')
    if not isinstance(controller, dict):
        return False
    pid = controller.get('pid')
    start_ticks = controller.get('start_ticks')
    pgid = controller.get('pgid')
    if type(pid) is not int or type(start_ticks) is not int or type(pgid) is not int:
        return False
    try:
        identity = executor.process_identity(pid)
    except (OSError, ValueError):
        return False
    return identity['start_ticks'] == start_ticks and identity['pgid'] == pgid


def recover_abandoned_controllers(root):
    """Restart resource-free operator work whose exact controller has died."""
    root = Path(root)
    recovered = []
    for path in (root / 'state/operator-runs').glob('*.json'):
        try:
            job = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if (job.get('kind') != 'operator-session'
                or job.get('state') not in {'ready', 'runner_starting', 'recovery_starting'}
                or _controller_process_alive(job)):
            continue
        # Once any execution resource was acquired, normal evidence-bound
        # cleanup owns recovery.  This path is only the no-resource prefix.
        if any(job.get(field) for field in (
                'executor_pid', 'worker_lease_id', 'inference_lease_id')):
            continue
        request = job.get('operator_request')
        command = job.get('original_command')
        session = job.get('opencode_session')
        required_request = ('session_id', 'owner_identity', 'tool', 'request_id')
        if (type(request) is not dict
                or any(type(request.get(field)) is not str or not request[field]
                       for field in required_request)
                or type(command) is not list
                or not command or any(type(item) is not str for item in command)):
            continue
        command = list(command)
        if session:
            if '--session' in command:
                command[command.index('--session') + 1] = session
            else:
                command += ['--session', session]
        arguments = [
            sys.executable, '-m', 'ecosystem.operator_session', 'run',
            '--session-id', request['session_id'], '--owner', request['owner_identity'],
            '--tool', request['tool'], '--request-id', request['request_id'],
            '--root', str(root),
        ]
        if request.get('model_id'):
            arguments += ['--model', request['model_id']]
        arguments += ['--', *command]
        logs = root / 'logs/operator-recovery'
        logs.mkdir(parents=True, exist_ok=True)
        stream = (logs / f"{job['id']}.log").open('ab', buffering=0)
        environment = dict(os.environ)
        environment['COINTOS_RUNTIME_ROOT'] = str(root)
        gate = None
        try:
            gate = executor.gated_child_launch(
                None, arguments, environment, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT)
            controller = {field: gate[field]
                          for field in ('pid', 'start_ticks', 'pgid')}
            job.update(state='recovery_starting',
                       controller_process=controller,
                       recovery_attempts=int(job.get('recovery_attempts', 0)) + 1,
                       updated_at=cli.now())
            cli.atomic_json(path, job)
            executor.gated_child_release(gate)
        except BaseException:
            if gate is not None:
                executor.gated_child_cleanup(gate)
            raise
        finally:
            stream.close()
        recovered.append(job['id'])
    return recovered


def run(root, request, command, *, clock=time.monotonic, refresh=None, sleeper=time.sleep):
    root = Path(root)
    refresh = refresh or (lambda: models.snapshot(root))
    identifier = 'operator-' + request['session_id']
    path = root / 'state/operator-runs' / (identifier + '.json')
    model = request.get('model_id') or _argument(command, '--model')
    if model and model.startswith('Lemonade/'):
        model = model.split('/', 1)[1]
    preferred_model = model
    directory = _argument(command, '--dir', str(Path.cwd()))
    title = _argument(command, '--title', identifier)
    base = list(command)
    if '--dir' not in base:
        base += ['--dir', directory]
    if '--title' not in base:
        base += ['--title', title]
    requirements = {'required_capabilities': ['tool-calling'], 'minimum_context_tokens': 0}
    if model:
        requirements['preferred_model_ids'] = [model]
    routing = {'requirements': requirements,
               'prompt_tokens': max(4096, len(' '.join(command).encode()) // 2),
               'tool_tokens': 8192, 'max_output_tokens': 32000, 'handoff_tokens': 0}
    job = {'id': identifier, 'kind': 'operator-session', 'state': 'ready',
           'workload_class': 'work', 'role': None, 'authority_profile': 'ordinary',
           'operator_session_id': request['session_id'], 'owner_identity': request['owner_identity'],
           'caller_handle': 'operator:local', 'agent_generation': 1,
            'remaining_budget': {'task_seconds': 86400}, 'original_command': base,
            'opencode_session': _argument(base, '--session'),
            'controller_process': executor.process_identity(os.getpid()),
            'operator_request': dict(request), **routing}
    cli.atomic_json(path, job)
    while True:
        try:
            inventory = refresh()
            policy = json.loads((root / 'config/resource-policy.json').read_text())
            failed_models = set(job.get('failed_model_ids', []))
            routes = [item for item in models.safe_routes(inventory, policy, routing)
                      if item.get('loaded') and item.get('model_id') not in failed_models]
            preferred = next((item for item in routes
                              if item.get('state') == 'admitted'
                              and item.get('model_id') == preferred_model), None)
            route = preferred or models.choose_route(routes, routing)
        except (OSError, ValueError, RuntimeError) as error:
            job.update(state='ready', waiting_reason=f'capacity refresh: {error}')
            cli.atomic_json(path, job); sleeper(.1); continue
        if route.get('state') != 'admitted':
            job.update(state='ready', waiting_reason=route.get('exclusion_reasons', ['model_not_loaded']))
            cli.atomic_json(path, job); sleeper(.1); continue
        model = route['model_id']
        run_command = list(base)
        if '--model' not in run_command:
            run_command += ['--model', 'Lemonade/' + model]
        else:
            run_command[run_command.index('--model') + 1] = 'Lemonade/' + model
        if job.get('suspended_once'):
            # Retain options, replace only the original positional user message.
            arguments = run_command[2:]
            kept = []
            options_with_values = {'--model', '--dir', '--title', '--format', '--agent', '--file', '--port', '--variant', '--session', '-m', '-f', '-s'}
            i = 0
            while i < len(arguments):
                value = arguments[i]
                if value in {'--session', '-s'}:
                    i += 2; continue
                if value.startswith('-'):
                    kept.append(value)
                    if value in options_with_values and i + 1 < len(arguments):
                        kept.append(arguments[i + 1]); i += 1
                i += 1
            run_command = run_command[:2] + kept + ['--session', job['opencode_session'],
                'Continue the original task after resource suspension. Check completed work and resume without duplicating it.']
        view = root / 'state/worker-views' / (identifier + '-' + str(time.time_ns()) + '.json')
        view.parent.mkdir(parents=True, exist_ok=True)
        wrapped = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/opencode_observable.py'),
                   '--view-record', str(view), '--', *run_command]
        context = executor.launch_runner_round(job, path, route, inventory, wrapped,
                                               refresh_inventory=refresh, clock=clock, sleeper=sleeper,
                                               stdin=None, stdout=None, stderr=None)
        if context['state'] == 'deferred':
            sleeper(.1); continue
        if context['state'] != 'running':
            raise RuntimeError('user allocation requires cleanup recovery; request retained')
        gate = context['launch']
        suspended = False
        interrupted = None
        lease_id = context['inference_lease']['lease_id']

        def cleanup_owned():
            # Secondary failures must not strand the owned child; each step is
            # best-effort and unknown occupancy stays retained for reconciliation.
            for step in (lambda: cli.atomic_json(path, job),
                         lambda: executor.cancel_proxy(root, lease_id, clock),
                         lambda: executor.gated_child_cleanup(gate)):
                try:
                    step()
                except BaseException:
                    pass

        def interrupted_close(error):
            nonlocal interrupted
            if interrupted is None:
                interrupted = error
                job.update(interruption_reason=str(error), runner_phase='interrupted_close_intent')
            cleanup_owned()

        try:
            while gate['process'].poll() is None:
                if view.exists():
                    job['opencode_session'] = json.loads(view.read_text())['session_id']
                    cli.atomic_json(path, job)
                state = json.loads((root / 'state/inference-capacity.json').read_text())
                if state['leases'][lease_id]['state'] == 'preemption_requested':
                    if job.get('opencode_session'):
                        executor.cancel_proxy(root, lease_id, clock)
                        executor.gated_child_cleanup(gate)
                        suspended = True
                        break
                sleeper(.05)
        except BaseException as error:
            interrupted_close(error)
        # Resource cleanup is recoverable waiting, not a rejected user request.
        # Repeated interruptions while the reap or the verified backend end is
        # pending keep retrying closure instead of bypassing it or replacing
        # the first error; unknown occupancy stays retained for reconciliation.
        while True:
            try:
                outcome = executor.gated_child_wait(gate, 0)
                closed = executor.close_runner_round(job, path, context, outcome, clock=clock, root=root)
                if closed['state'] != 'reconciliation_required':
                    break
                if outcome.get('process_group_alive') is not False:
                    raise RuntimeError('user process cleanup is pending; session and allocation retained')
                sleeper(.1)
            except BaseException as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    interrupted_close(error)
                    continue
                cleanup_owned()
                reap_retry = isinstance(error, subprocess.TimeoutExpired) \
                    or str(error) == 'user process cleanup is pending; session and allocation retained'
                if reap_retry:
                    # Cleanup may have finished the reap; retry with a fresh outcome.
                    try:
                        outcome = executor.gated_child_wait(gate, 0)
                    except BaseException:
                        continue
                    if outcome.get('process_group_alive') is False:
                        continue
                if interrupted is None:
                    raise
                raise interrupted
        if interrupted is not None:
            try:
                job.update(state='interrupted', updated_at=cli.now())
                cli.atomic_json(path, job)
                operator_session.release_operator_session(root, request['session_id'],
                    {'state': 'interrupted', 'returncode': outcome['returncode']}, clock)
                operator_session.observe_operator_sessions(root, [{
                    'session_id': request['session_id'], 'pid': gate['pid'],
                    'process_start_ticks': gate['start_ticks'], 'process_group_alive': False}], clock)
            finally:
                raise interrupted
        if suspended:
            operator_session.suspend_operator_session(root, request['session_id'], job['opencode_session'], clock)
            job.update(state='ready', suspended_once=True, suspension_reason='higher_priority_inference')
            cli.atomic_json(path, job); sleeper(.1); continue
        if outcome['returncode'] != 0:
            failed = list(dict.fromkeys([*job.get('failed_model_ids', []), model]))
            alternatives = [item for item in routes
                            if item.get('state') == 'admitted'
                            and item.get('model_id') not in failed]
            if alternatives and job.get('opencode_session'):
                operator_session.suspend_operator_session(
                    root, request['session_id'], job['opencode_session'], clock)
                job.update(state='ready', failed_model_ids=failed,
                           suspended_once=True,
                           suspension_reason='model_run_failed_retry_alternative',
                           updated_at=cli.now())
                cli.atomic_json(path, job)
                sleeper(.1)
                continue
        operator_session.release_operator_session(root, request['session_id'],
            {'state': 'run_finished', 'returncode': outcome['returncode']}, clock)
        operator_session.observe_operator_sessions(root, [{
            'session_id': request['session_id'], 'pid': gate['pid'],
            'process_start_ticks': gate['start_ticks'], 'process_group_alive': False}], clock)
        return outcome['returncode']
