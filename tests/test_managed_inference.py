"""Actual native subprocess/client/proxy boundary, with inert backend responses."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ecosystem import cli, managed_inference, inference_proxy, telegram, control_agent
from tests.test_inference_capacity import write_root, inventory


def with_proxy(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_root(root)
            observed = inventory()
            observed['models'][0]['capabilities'].append('tool-calling')
            requests = []
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass
                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    requests.append(body)
                    def backend(context):
                        lease = context['lease']
                        while (root / 'delay-backend').exists():
                            time.sleep(.01)
                        return {'status': 200, 'choices': [{'message': {
                            'role': 'assistant', 'content': 'Checked.',
                            'tool_calls': [{'id': 'end', 'type': 'function', 'function': {
                                'name': 'finish_silently', 'arguments': '{}'}}],
                        }}], 'termination_observation': {
                            'terminated': True, 'binding': lease['expected_release_binding'],
                            'claim_id': context['claim_id'], 'request_id': 'fixture-request',
                            'observer_identity': 'observer:inference-backend',
                            'observer_generation': 1, 'observed_monotonic': time.monotonic(),
                            'clock_domain_id': 'host-monotonic:boot-one', 'evidence_id': 'fixture-end',
                        }}
                    result = inference_proxy.handle_proxy_request(root, {
                        'authorization': self.headers['Authorization'],
                        'lease_id': self.headers['X-Inference-Lease-Id'],
                        'owner_identity': self.headers['X-Inference-Owner-Identity'],
                        'request_id': 'fixture-request',
                    }, body, backend, time.monotonic)
                    encoded = json.dumps(result).encode()
                    self.send_response(result['status']); self.send_header('Content-Length', str(len(encoded)))
                    self.end_headers()
                    try:
                        self.wfile.write(encoded)
                    except BrokenPipeError:
                        pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            (root / 'config/model-policy.json').write_text(json.dumps({'inference_proxy': {
                'proxy_base': f'http://127.0.0.1:{server.server_port}/v1'}}))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with patch.object(cli, 'ROOT', root), patch.object(managed_inference.models, 'snapshot', return_value=observed):
                    function(root, observed, requests)
            finally:
                server.shutdown(); server.server_close(); thread.join()
    run.__name__ = function.__name__
    return run


def assert_closed(root):
    capacities = json.loads((root / 'state/inference-capacity.json').read_text())['leases']
    assert capacities and all(item['state'] == 'released' for item in capacities.values())
    credentials = json.loads((root / 'state/inference-proxy.json').read_text())['credentials']
    assert all(item['state'] == 'revoked' and not item['digest'] for item in credentials.values())
    workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
    assert all(item['state'] == 'quiescent' for key, item in workers.items() if key.startswith('worker-') and 'native-' in item['request']['request_id'])


@with_proxy
def test_native_request_acquires_and_releases_without_supplied_lease(root, _observed, requests):
    result = managed_inference.request('model-a', [{'role': 'user', 'content': 'check'}], 96, root=root)
    assert result['content'] == 'Checked.'
    assert requests[0]['max_tokens'] == 96
    assert requests[0]['context_tokens'] == 32768
    assert_closed(root)
    records = list((root / 'state/inference-runs').glob('*.json'))
    assert json.loads(records[0].read_text())['state'] == 'completed'
    assert 'credential' not in records[0].read_text()


@with_proxy
def test_default_telegram_fast_and_deep_use_real_acquisition(root, _observed, requests):
    _observed['models'][0].update(context=131072, loaded_context=131072)
    _observed['resource_envelope']['maximum_context_tokens'] = 131072
    with patch.object(telegram, 'active_chat_model', return_value='model-a'), patch.object(control_agent, 'active_chat_model', return_value='model-a'):
        assert telegram.generate_first_response([{'role': 'user', 'content': 'hello'}]) == 'Checked.'
        assert control_agent.respond('hello', [], 'checking', {}, lambda *_args: {}) == {'followup': None}
    assert [item['max_tokens'] for item in requests] == [96, 32000]
    assert_closed(root)
    capacities = json.loads((root / 'state/inference-capacity.json').read_text())['leases']
    assert all(item['priority'] >= 900 for item in capacities.values())


@with_proxy
def test_busy_resources_wait_then_run_instead_of_rejecting(root, observed, requests):
    refreshes = []
    def refresh():
        refreshes.append(1)
        if len(refreshes) < 3:
            return {**observed, 'fresh': False}
        return observed
    result = managed_inference.request('model-a', [{'role': 'user', 'content': 'check'}], 96,
                                       root=root, refresh=refresh, sleeper=lambda _seconds: None)
    assert result['content'] == 'Checked.' and len(refreshes) >= 3
    assert len(requests) == 1
    assert_closed(root)


@with_proxy
def test_priority_suspends_then_resumes_actual_native_work(root, observed, requests):
    observed['models'][0].update(parallel_sequences=1, loaded_context=32768)
    observed['resource_envelope']['maximum_context_tokens'] = 32768
    delayed = root / 'delay-backend'; delayed.touch()
    outcomes = []
    errors = []
    cancellation_seen = threading.Event()
    def background():
        try:
            outcomes.append(managed_inference.request('model-a', [{'role': 'user', 'content': 'background'}], 96, root=root))
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=background, daemon=True); thread.start()
    deadline = time.monotonic() + 5
    while not requests and time.monotonic() < deadline:
        time.sleep(.01)
    assert requests, 'background request did not reach the proxy'
    def release_after_cancellation():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            credentials = json.loads((root / 'state/inference-proxy.json').read_text())['credentials']
            # Allocation intent can race normal completion. Closing is written
            # by the native monitor after it observes preemption and calls cancel.
            if any(item['state'] == 'closing' for item in credentials.values()):
                if len(requests) != 1:
                    errors.append(AssertionError('priority request overlapped occupied single-slot inference'))
                cancellation_seen.set()
                delayed.unlink(missing_ok=True)
                return
            time.sleep(.01)
        delayed.unlink(missing_ok=True)
    monitor = threading.Thread(target=release_after_cancellation, daemon=True); monitor.start()
    try:
        result = managed_inference.request('model-a', [{'role': 'user', 'content': 'priority'}], 96, root=root, control=True)
        assert result['content'] == 'Checked.'
    finally:
        delayed.unlink(missing_ok=True); monitor.join(6); thread.join(6)
    assert not thread.is_alive() and not errors, errors
    assert cancellation_seen.is_set(), 'native cancellation was never observed'
    assert outcomes[0]['content'] == 'Checked.'
    assert [item['messages'][-1]['content'] for item in requests] == ['background', 'priority', 'background']
    assert_closed(root)


@with_proxy
def test_cancel_waiting_demand_without_issuing_a_credential(root, observed, requests):
    calls = []
    def refresh():
        calls.append(1)
        return {**observed, 'fresh': False}
    try:
        managed_inference.request('model-a', [], 96, root=root, refresh=refresh,
                                  cancelled=lambda: len(calls) >= 3, sleeper=lambda _seconds: None)
    except InterruptedError:
        pass
    else:
        raise AssertionError('cancellation was ignored')
    assert not requests
    record = json.loads(next((root / 'state/inference-runs').glob('*.json')).read_text())
    assert record['state'] == 'cancelled'


@with_proxy
def test_setup_failure_releases_worker_without_backend_request(root, _observed, requests):
    from ecosystem import executor
    class SpawnUnavailable(OSError):
        pass
    def spawn_unavailable(config_fd, *args, **kwargs):
        error = SpawnUnavailable('spawn unavailable')
        error.launch_failure = {'spawned': False}
        if type(config_fd) is int and config_fd >= 0:
            os.close(config_fd)   # faithful: the real Popen-failure path consumes the fd
        raise error
    with patch.object(executor, 'gated_child_launch', side_effect=spawn_unavailable):
        try:
            managed_inference.request('model-a', [], 96, root=root)
        except SpawnUnavailable:
            pass
        else:
            raise AssertionError('spawn failure was ignored')
    assert not requests
    workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
    record = json.loads(next((root / 'state/inference-runs').glob('*.json')).read_text())
    assert record['state'] == 'failed' and record['worker_lease_id'] in workers
    assert workers[record['worker_lease_id']]['state'] == 'quiescent'


def _caller_script(root, barrier):
    """A real caller that deterministically stops at `barrier`.

    barrier is a durable record state ('starting'/'acquiring'/'running'): the
    child wraps cli.atomic_json and blocks forever right after that durable
    write. barrier 'post_release' instead wraps executor.gated_child_release so
    the caller blocks only after the gate is released and the child is running
    the backend. In every case the real allocator/child lifecycle is retained;
    the test kills the stopped caller.
    """
    if barrier == 'post_release':
        hook = (
            "import ecosystem.executor as executor\n"
            "original_release = executor.gated_child_release\n"
            "def release_and_stop(record):\n"
            "    result = original_release(record)\n"
            "    while True:\n"
            "        time.sleep(0.05)\n"
            "executor.gated_child_release = release_and_stop\n")
    elif barrier == 'pre_register':
        # Let gated_child_launch complete (Popen happens, spawn_intent is
        # durably set) but block before the child identity is registered, so
        # the worker lease has no process and the birth is unobserved.
        hook = (
            "import ecosystem.workload_control as workload_control\n"
            "original_register = workload_control.register_process\n"
            "def register_and_stop(*args, **kwargs):\n"
            "    while True:\n"
            "        time.sleep(0.05)\n"
            "workload_control.register_process = register_and_stop\n")
    else:
        hook = (
            "original = cli.atomic_json\n"
            "def wrapping(path, record):\n"
            "    original(path, record)\n"
            "    if isinstance(record, dict) and record.get('state') == " + repr(barrier) + ":\n"
            "        while True:\n"
            "            time.sleep(0.05)\n"
            "cli.atomic_json = wrapping\n")
    return (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "import ecosystem.cli as cli\n"
        "from tests.test_inference_capacity import inventory\n"
        "from ecosystem import managed_inference\n\n"
        "root = Path(" + repr(str(root)) + ")\n"
        "observed = inventory()\n"
        "observed['models'][0]['capabilities'].append('tool-calling')\n"
        "messages = [{'role': 'user', 'content': 'recovery'}]\n"
        + hook +
        "managed_inference.request('model-a', messages, 96,\n"
        "                          root=root, refresh=lambda: observed, timeout=3600)\n")


def spawn_caller(root, barrier):
    env = {'PYTHONPATH': str(Path(__file__).resolve().parents[1]), 'PATH': '/usr/bin:/bin'}
    return subprocess.Popen([sys.executable, '-c', _caller_script(root, barrier)],
                            env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _wait_record_state(root, state, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        files = list((root / 'state/inference-runs').glob('native-*.json'))
        if files and json.loads(files[-1].read_text()).get('state') == state:
            return
        time.sleep(0.01)
    raise AssertionError(f'caller never durably reached {state!r}')


def hold_caller_at(root, barrier):
    handle = spawn_caller(root, barrier)
    try:
        _wait_record_state(root, barrier)
        handle.kill()
        handle.wait(timeout=30)
    finally:
        handle.stdout.close()


def _record(root):
    files = list((root / 'state/inference-runs').glob('native-*.json'))
    assert len(files) == 1
    return json.loads(files[0].read_text()), files[0]


def _wait_child_ended(record, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if managed_inference._process_ended(
                record.get('child_pid'), record.get('child_start_ticks')) is True:
            return
        time.sleep(.02)
    raise AssertionError('orphaned gated child was not reaped before reconciliation')


@with_proxy
def test_live_owner_is_untouched_by_reconciliation(root, _observed, requests):
    # Freeze the live request's writer at its durable 'running' write so the
    # snapshots below are taken while the writer is paused. Waiting for an
    # allocated state alone is not a frozen writer: the request thread would
    # otherwise keep advancing state between the before and after snapshots.
    reached = threading.Event()
    release = threading.Event()
    original_atomic_json = cli.atomic_json
    def barrier_atomic_json(path, record):
        original_atomic_json(path, record)
        if isinstance(record, dict) and record.get('state') == 'running':
            reached.set()
            release.wait(60)
    outcome = []
    errors = []
    def background():
        try:
            with patch.object(cli, 'atomic_json', barrier_atomic_json):
                outcome.append(managed_inference.request(
                    'model-a', [{'role': 'user', 'content': 'live'}], 96, root=root))
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=background, daemon=True); thread.start()
    try:
        assert reached.wait(30), 'live request never durably reached running'
        record, path = _record(root)
        before = json.loads(path.read_text())
        workers_before = json.loads((root / 'state/workload-control.json').read_text())
        result = managed_inference.reconcile_dead_callers(root)
        assert result == {'live': 1, 'recovered': 0, 'retained': 0, 'cancelled': 0,
                          'ignored': 0, 'pending': []}
        assert json.loads(path.read_text()) == before, 'reconciliation touched a live owner'
        assert json.loads((root / 'state/workload-control.json').read_text()) == workers_before
    finally:
        release.set()
        thread.join(30)
    assert not thread.is_alive() and not errors, errors
    assert outcome and outcome[0]['content'] == 'Checked.'
    assert_closed(root)


@with_proxy
def test_reused_or_unknown_caller_identity_is_safe(root, _observed, requests):
    hold_caller_at(root, 'starting')
    record, path = _record(root)
    worker_lease = record['worker_lease_id']
    live = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        with patch.object(managed_inference, '_kernel_start_ticks', return_value=('unreadable', None)):
            result = managed_inference.reconcile_dead_callers(root)
        assert result == {'live': 0, 'recovered': 0, 'retained': 1, 'cancelled': 0,
                          'ignored': 0, 'pending': []}
        retained = json.loads(path.read_text())
        assert retained['state'] == 'reconciliation_required'
        assert retained['reconciliation']['next_check'] == 'verify_caller_identity'
        workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
        assert workers[worker_lease]['state'] != 'quiescent', \
            'unreadable /proc evidence was treated as caller death'
        reused = {**retained, 'owner_pid': live.pid, 'owner_start_ticks': 1}
        cli.atomic_json(path, reused)
        result = managed_inference.reconcile_dead_callers(root)
        assert result['cancelled'] + result['recovered'] == 1, \
            'a reused pid must prove the original caller gone, not keep it alive'
        final = json.loads(path.read_text())
        assert final['state'] in {'cancelled', 'completed'}
        workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
        assert workers[worker_lease]['state'] == 'quiescent'
        os.kill(live.pid, 0), 'reused live process must be untouched by reconciliation'
    finally:
        live.kill(); live.wait(timeout=10)
    assert not requests


@with_proxy
def test_dead_caller_releases_unissued_attempt_without_backend_request(root, _observed, requests):
    hold_caller_at(root, 'acquiring')
    record, path = _record(root)
    assert record['state'] == 'acquiring' and record.get('child_pid')
    _wait_child_ended(record)
    result = managed_inference.reconcile_dead_callers(root)
    assert result['recovered'] == 1 and result['pending'] == []
    record = json.loads(path.read_text())
    assert record['state'] in {'cancelled', 'completed'}
    assert record['reason'].startswith('caller_terminated')
    workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
    assert workers[record['worker_lease_id']]['state'] == 'quiescent'
    path_capacity = root / 'state/inference-capacity.json'
    if path_capacity.exists():
        leases = json.loads(path_capacity.read_text())['leases']
        held = [item for item in leases.values()
                if item['request']['worker_lease_id'] == record['worker_lease_id']]
        assert all(item['state'] == 'released' for item in held)
    path_proxy = root / 'state/inference-proxy.json'
    if path_proxy.exists():
        credentials = json.loads(path_proxy.read_text())['credentials']
        assert all(item['state'] == 'revoked' and not item['digest'] for item in credentials.values())
    assert not requests, 'reconciliation must not re-run the request'
    assert 'credential' not in path.read_text()


@with_proxy
def test_issued_attempt_retains_occupancy_until_verified_end(root, _observed, requests):
    delayed = root / 'delay-backend'; delayed.touch()
    handle = spawn_caller(root, 'post_release')
    try:
        deadline = time.monotonic() + 30
        while not requests and time.monotonic() < deadline:
            time.sleep(0.02)
        assert requests, 'released child never issued an inert-backend request'
        record, path = _record(root)
        assert record['state'] == 'running'
        handle.kill()
        handle.wait(timeout=30)
        result = managed_inference.reconcile_dead_callers(root)
        assert result['recovered'] == 0 and result['pending'] == []
        retained = json.loads(path.read_text())
        assert retained['state'] == 'reconciliation_required'
        assert retained['reconciliation']['next_check'] == 'verify_backend_termination'
        assert retained['reason'].startswith('caller_terminated')
        capacities = json.loads((root / 'state/inference-capacity.json').read_text())['leases']
        assert capacities[retained['inference_lease_id']]['state'] != 'released'
        credentials = json.loads((root / 'state/inference-proxy.json').read_text())['credentials']
        assert credentials[retained['inference_lease_id']]['state'] != 'revoked'
        assert 'credential' not in path.read_text()
        delayed.unlink()
        _wait_child_ended(retained)
        result = managed_inference.reconcile_dead_callers(root)
        assert result['recovered'] == 1 and result['pending'] == []
        record = json.loads(path.read_text())
        assert record['state'] == 'completed'
        assert_closed(root)
        assert [item['messages'][-1]['content'] for item in requests] == ['recovery']
    finally:
        handle.stdout.close()
        delayed.unlink(missing_ok=True)


@with_proxy
def test_spawned_but_unobserved_birth_is_retained_not_attested(root, _observed, requests):
    handle = spawn_caller(root, 'pre_register')
    try:
        deadline = time.monotonic() + 30
        record = None
        while time.monotonic() < deadline:
            files = list((root / 'state/inference-runs').glob('native-*.json'))
            if files:
                record = json.loads(files[0].read_text())
                if record.get('spawn_intent') is True and record.get('state') == 'starting':
                    break
            time.sleep(0.01)
        assert record and record.get('spawn_intent') is True, \
            'caller did not durably record spawn intent before the barrier'
        handle.kill()
        handle.wait(timeout=30)
        result = managed_inference.reconcile_dead_callers(root)
        assert result['recovered'] == 0 and result['pending'] == []
        retained = json.loads(
            next((root / 'state/inference-runs').glob('native-*.json')).read_text())
        assert retained['state'] == 'reconciliation_required'
        assert retained['reconciliation']['next_check'] == 'verify_worker_birth'
        assert retained['reason'].startswith('caller_terminated')
        workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
        assert workers[retained['worker_lease_id']]['state'] != 'quiescent', \
            'an unobserved birth must not be attested as never_spawned'
    finally:
        handle.stdout.close()
    assert not requests


@with_proxy
def test_post_popen_launch_failure_attests_reaped_spawn(root, _observed, requests):
    from ecosystem import executor
    class PostPopenFailure(ValueError):
        pass
    error = PostPopenFailure('gated child failed identity validation')
    error.launch_failure = {'spawned': True, 'pid': 424242, 'pgid': 424242,
                            'cleanup': {'state': 'reaped', 'returncode': -15,
                                        'start_ticks': None, 'process_group_alive': False}}
    with patch.object(executor, 'gated_child_launch', side_effect=error):
        try:
            managed_inference.request('model-a', [], 96, root=root)
        except PostPopenFailure:
            pass
        else:
            raise AssertionError('post-Popen launch failure was ignored')
    assert not requests
    record = json.loads(next((root / 'state/inference-runs').glob('native-*.json')).read_text())
    assert record['state'] == 'failed'
    workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
    lease = workers[record['worker_lease_id']]
    assert lease['state'] == 'quiescent'
    observation = lease.get('observation') or {}
    assert observation.get('never_spawned') is not True
    assert observation.get('reaped_spawn') == {'pid': 424242, 'process_start_ticks': None,
                                               'returncode': -15, 'process_group_alive': False}


@with_proxy
def test_real_popen_launch_failure_preserves_interruption_and_fd(root, _observed, requests):
    # Real gated Popen with a real memfd: the first process_identity read is
    # interrupted, the executor reaps the gated child, and the original
    # interruption must escape (no EBADF, no false never_spawned).
    from ecosystem import executor
    calls = {'n': 0}
    real_identity = executor.process_identity
    def flaky_identity(pid):
        calls['n'] += 1
        if calls['n'] == 1:
            raise KeyboardInterrupt('simulated first-identity interruption')
        return real_identity(pid)
    with patch.object(executor, 'process_identity', side_effect=flaky_identity):
        try:
            managed_inference.request('model-a', [], 96, root=root)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError('original interruption was not preserved')
    assert not requests
    record = json.loads(next((root / 'state/inference-runs').glob('native-*.json')).read_text())
    assert record['state'] == 'failed'
    workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
    lease = workers[record['worker_lease_id']]
    assert lease['state'] == 'quiescent'
    observation = lease.get('observation') or {}
    assert observation.get('never_spawned') is not True
    assert observation.get('reaped_spawn', {}).get('process_group_alive') is False


@with_proxy
def test_untagged_launch_failure_after_attempt_is_retained_not_closed(root, _observed, requests):
    # An attempted launch that fails without launch_failure metadata proves
    # neither nonbirth nor a reap: the attempt is retained and the fd (already
    # consumed by the launch) is not closed a second time.
    from ecosystem import executor
    def untagged_failure(config_fd, *args, **kwargs):
        if type(config_fd) is int and config_fd >= 0:
            os.close(config_fd)
        raise KeyboardInterrupt('untagged launch interruption')
    with patch.object(executor, 'gated_child_launch', side_effect=untagged_failure):
        try:
            managed_inference.request('model-a', [], 96, root=root)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError('original interruption was not preserved')
    assert not requests
    record = json.loads(next((root / 'state/inference-runs').glob('native-*.json')).read_text())
    assert record['state'] == 'reconciliation_required'
    assert record['reconciliation']['next_check'] == 'verify_worker_birth'
    workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
    assert workers[record['worker_lease_id']]['state'] != 'quiescent', \
        'an untagged launch failure must not attest a stop'


@with_proxy
def test_legacy_record_without_spawn_marker_is_retained(root, _observed, requests):
    # A record that durably reached 'starting' but predates the explicit
    # spawn_intent marker has no birth proof at all, so it must be retained,
    # never attested as never_spawned. New records always carry the marker, so
    # remove it to simulate a legacy record.
    hold_caller_at(root, 'starting')
    record, path = _record(root)
    assert record.get('spawn_intent') is False
    legacy = {key: value for key, value in record.items() if key != 'spawn_intent'}
    cli.atomic_json(path, legacy)
    result = managed_inference.reconcile_dead_callers(root)
    assert result['recovered'] == 0 and result['pending'] == []
    retained = json.loads(path.read_text())
    assert retained['state'] == 'reconciliation_required'
    assert retained['reconciliation']['next_check'] == 'verify_worker_birth'
    workers = json.loads((root / 'state/workload-control.json').read_text())['leases']
    assert workers[retained['worker_lease_id']]['state'] != 'quiescent', \
        'a missing spawn marker must not imply nonbirth'
    assert not requests


@with_proxy
def test_reconciliation_binds_current_worker_lease_not_stale_inference_id(root, _observed, requests):
    delayed = root / 'delay-backend'; delayed.touch()
    handle = spawn_caller(root, 'post_release')
    try:
        deadline = time.monotonic() + 30
        while not requests and time.monotonic() < deadline:
            time.sleep(0.02)
        assert requests, 'released child never issued an inert-backend request'
        record, path = _record(root)
        assert record['state'] == 'running'
        # Simulate a leaked per-attempt field from a prior attempt: the record
        # still names a stale inference lease while its worker lease is current.
        stale = {**record, 'inference_lease_id': 'capacity-stale-never-issued'}
        cli.atomic_json(path, stale)
        handle.kill()
        handle.wait(timeout=30)
        delayed.unlink()
        _wait_child_ended(record)
        result = managed_inference.reconcile_dead_callers(root)
        assert result['recovered'] == 1 and result['pending'] == []
        reconciled = json.loads(path.read_text())
        assert reconciled['state'] == 'completed'
        # The stale id was replaced by the current worker-bound lease.
        assert reconciled['inference_lease_id'] == record['inference_lease_id']
        assert reconciled['inference_lease_id'] != 'capacity-stale-never-issued'
        assert_closed(root)
    finally:
        handle.stdout.close()
        delayed.unlink(missing_ok=True)


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(function) for name, function in globals().items()
                              if name.startswith('test_') and callable(function))
