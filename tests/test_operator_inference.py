"""Real gated user admission/release, with an inert child in place of OpenCode."""
import json
import os
import signal
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ecosystem import cli, executor, operator_inference, operator_session
from ecosystem.opencode_capacity import launch_fingerprint
from tests.test_inference_capacity import write_root, inventory
from tests.test_executor import _capacity_producers


def _exercise_user_run(interrupt=False, pending_end=False, terminate=False):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); write_root(root)
        (root / 'config/executor-opencode.json').write_text(json.dumps({'provider': {'Lemonade': {
            'npm': '@ai-sdk/openai-compatible', 'options': {'baseURL': 'http://127.0.0.1:13305/v1'},
            'models': {'model-a': {'name': 'model-a'}}}}}))
        (root / 'config/model-policy.json').write_text(json.dumps({'inference_proxy': {
            'proxy_base': 'http://127.0.0.1:13306/v1'}}))
        observed = inventory(); observed['models'][0]['capabilities'].append('tool-calling')
        observed['models'][0].update(
            context=262144, loaded_context=262144,
            context_tokens_per_sequence=131072,
        )
        observed['resident_models'][0].update(
            backend_context_tokens=262144,
            context_tokens_per_sequence=131072,
        )
        observed['resource_envelope']['maximum_context_tokens'] = 262144
        launched = []
        monitors = []
        active_job = []
        interrupted_once = []
        def observation(model_id, clock):
            command = ['llama-server', '--ctx-size', '262144', '--parallel', '2']
            return {'selected_model_id': model_id, 'observed_model_id': model_id,
                    'backend_incarnation': {'backend_url': 'http://127.0.0.1:9000/v1', 'pid': 4242,
                                           'launch_command': command, 'launch_fingerprint': launch_fingerprint(command)},
                    'layout': {'context_mode': 'fixed', 'backend_context_tokens': 262144,
                               'parallel_sequences': 2, 'context_tokens_per_sequence': 131072,
                               'preallocated_context_tokens': 262144},
                    'observed_at': clock(), 'evidence': 'fixture', 'prompt_estimate_tokens': 0,
                    'backend_output_ceiling': None}
        producers = _capacity_producers(observation=observation,
                                        policy={'output_reserve_tokens': 32000, 'rollover_fraction': .75, 'max_age_seconds': 300})
        real_launch = executor.launch_runner_round
        def launch(job, path, route, current, command, **kwargs):
            launched.append(command)
            active_job[:] = [job]
            view = Path(command[command.index('--view-record') + 1])
            first = len(launched) == 1
            def inert(fd, _argv, env, **streams):
                code = 'import json,time; from pathlib import Path; '
                code += f'Path({str(view)!r}).write_text(json.dumps({{"session_id":"ses_retained"}})); '
                code += 'time.sleep(60)' if first else 'print("resumed")'
                return executor.gated_child_launch(fd, [__import__('sys').executable, '-c', code], env, **streams)
            result = real_launch(job, path, route, current, command,
                                 observe_capacity=producers[0], qualify_capability=producers[1],
                                 capacity_policy=producers[2], launch=inert, **kwargs)
            if first and result['state'] == 'running' and not interrupt:
                def preempt():
                    deadline = time.monotonic() + 5
                    while not view.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    state_path = root / 'state/inference-capacity.json'
                    state = json.loads(state_path.read_text())
                    lease = state['leases'][result['inference_lease']['lease_id']]
                    assert lease['priority'] == 850
                    lease['state'] = 'preemption_requested'
                    cli.atomic_json(state_path, state)
                monitor = threading.Thread(target=preempt, daemon=True); monitor.start(); monitors.append(monitor)
            return result
        request = {'session_id': 'user-test', 'owner_identity': 'operator:test', 'tool': 'opencode',
                   'model_id': 'model-a', 'request_id': 'user-request'}
        prior_term = signal.getsignal(signal.SIGTERM)
        original_run = operator_inference.run
        original_close = executor.close_runner_round
        end_checks = []
        def termination(*args, **kwargs):
            end_checks.append(True)
            if pending_end and len(end_checks) < 3:
                return None
            return executor.completed_run_termination(*args, **kwargs)
        def sleeper(seconds):
            if interrupt and active_job and active_job[0].get('opencode_session') and not interrupted_once:
                interrupted_once.append(True)
                if terminate:
                    os.kill(os.getpid(), signal.SIGTERM)
                else:
                    raise KeyboardInterrupt('operator interrupted')
            time.sleep(seconds)
        with patch.object(cli, 'ROOT', root), patch.object(operator_inference.models, 'snapshot', return_value=observed), \
                patch.object(operator_inference.executor, 'launch_runner_round', side_effect=launch), \
                patch.object(operator_inference, 'run', side_effect=lambda *args, **kwargs: original_run(*args, **kwargs, sleeper=sleeper)), \
                patch.object(executor, 'close_runner_round', side_effect=lambda *args, **kwargs: original_close(*args, **kwargs, termination=termination)):
            if interrupt:
                try:
                    operator_session.run_command(root, request, ['opencode', 'run', 'original task'])
                except KeyboardInterrupt:
                    pass
                else:
                    raise AssertionError('operator interruption was ignored')
            else:
                assert operator_session.run_command(root, request, ['opencode', 'run', 'original task']) == 0
        assert signal.getsignal(signal.SIGTERM) == prior_term
        for monitor in monitors:
            monitor.join(6)
        if interrupt:
            assert len(launched) == 1
            assert active_job[0]['state'] == 'interrupted'
            assert active_job[0]['opencode_session'] == 'ses_retained'
        else:
            assert len(launched) == 2
            resumed = launched[1]
            assert resumed[resumed.index('--session') + 1] == 'ses_retained'
            assert 'original task' not in resumed
        sessions = json.loads((root / 'state/operator-sessions.json').read_text())['sessions']
        assert sessions['user-test']['state'] == 'quiescent'
        assert all(item['state'] == 'released' for item in json.loads((root / 'state/inference-capacity.json').read_text())['leases'].values())
        if pending_end:
            assert len(end_checks) >= 3


def test_user_run_automatically_allocates_and_resumes_exact_session():
    _exercise_user_run()


def test_operator_interruption_closes_owned_allocation_and_preserves_session():
    _exercise_user_run(interrupt=True)


def test_sigterm_closes_operator_allocation_and_restores_handler():
    _exercise_user_run(interrupt=True, terminate=True)


def test_pending_backend_end_is_retried_before_user_resume():
    _exercise_user_run(pending_end=True)


def test_simple_user_launch_needs_no_manual_lease_parameters():
    with patch.object(operator_session, 'run_command', return_value=0) as run, \
            patch.object(operator_session.shutil, 'which', return_value='/usr/bin/opencode'):
        assert operator_session.main(['run', 'inspect the files']) == 0
    root, request, command = run.call_args.args
    assert root == Path.home() / '.CointOS'
    assert request['tool'] == 'opencode' and request['session_id'].startswith('user-')
    assert command == ['/usr/bin/opencode', 'run', 'inspect the files']


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(function) for name, function in globals().items()
                              if name.startswith('test_') and callable(function))
