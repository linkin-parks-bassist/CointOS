"""Trusted user priority, model contention and cancellable preemption intents."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from ecosystem import inference_capacity
from ecosystem import executor
from tests.test_inference_capacity import write_root, inventory, sequence_request, reserve, ended_observation


def test_operator_band_comes_from_live_worker_identity_not_a_caller_flag():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); write_root(root)
        request = sequence_request(); request['operator_session'] = True
        ordinary = reserve(root, request, inventory(), lambda: 10.)
        assert ordinary['priority'] == 550
        workers = json.loads((root / 'state/workload-control.json').read_text())
        process = executor.process_identity(os.getpid())
        identity = {'pid': process['pid'], 'process_start_ticks': process['start_ticks']}
        worker = workers['leases']['worker-one']
        worker['process'] = identity; worker['request']['operator_session_id'] = 'user-one'
        (root / 'state/workload-control.json').write_text(json.dumps(workers))
        (root / 'state/operator-sessions.json').write_text(json.dumps({'schema_version': 1, 'sessions': {
            'user-one': {'state': 'active', 'process': identity, 'request': {'owner_identity': 'worker:one'}}}}))
        # Reuse the slot after authoritative cleanup rather than overcommitting it.
        inference_capacity.release_sequence(root, ordinary['lease_id'], ended_observation(ordinary, 11.), lambda: 11.)
        user = reserve(root, sequence_request('user-request'), inventory(), lambda: 12.)
        assert user['priority'] == 850 and user['request']['operator_session'] is True


def test_coin_preempts_a_model_blocker_even_with_its_front_slot_free():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); write_root(root)
        observed = inventory()
        observed['models'][0].update(parallel_sequences=1, loaded_context=32768)
        observed['resource_envelope']['maximum_context_tokens'] = 32768
        work = sequence_request(); work['route'].update(parallel_sequences=1, backend_context_tokens=32768)
        first = reserve(root, work, observed, lambda: 10.)
        coin = sequence_request('coin-demand', 'coin', 'front', 'proxy:coin-front')
        coin['route'].update(parallel_sequences=1, backend_context_tokens=32768)
        waiting = reserve(root, coin, observed, lambda: 11.)
        assert waiting['state'] == 'waiting_for_preemption'
        assert waiting['backend_sequence'] is None and waiting['preempts_lease_id'] == first['lease_id']
        inference_capacity.release_sequence(root, first['lease_id'], ended_observation(first, 12.), lambda: 12.)
        ready = reserve(root, coin, observed, lambda: 13.)
        assert ready['state'] == 'starting' and ready['backend_sequence'] == 0


def test_withdraw_waiter_releases_no_live_gpu_and_clears_obsolete_preemption():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); write_root(root)
        first = reserve(root, sequence_request(), inventory(), lambda: 10.)
        survivor = sequence_request('survivor-demand', 'sole_survivor')
        waiting = reserve(root, survivor, inventory(), lambda: 11.)
        workers = json.loads((root / 'state/workload-control.json').read_text())
        workers['leases']['worker-survivor']['process'] = {'pid': 2 ** 30, 'process_start_ticks': 1}
        (root / 'state/workload-control.json').write_text(json.dumps(workers))
        withdrawn = inference_capacity.withdraw_unissued_sequence(root, waiting['lease_id'], lambda: 12.)
        assert withdrawn['state'] == 'released'
        state = json.loads((root / 'state/inference-capacity.json').read_text())['leases']
        assert state[first['lease_id']]['state'] == 'starting'
        assert state[first['lease_id']]['backend_sequence'] == first['backend_sequence']


def test_multiple_byte_blockers_wait_for_every_verified_release():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); write_root(root)
        workers = json.loads((root / 'state/workload-control.json').read_text())
        # Two existing occupied allocations consume measured per-request bytes.
        route = sequence_request()['route']
        base = {'state': 'starting', 'workload_class': 'work', 'model_id': 'model-a',
                'backend_sequence': 1, 'allocation_bytes': 12 * 1024 ** 3,
                'enqueued_monotonic': 0., 'acquired_monotonic': 0., 'route': route,
                'request': {'request_id': 'blocker-one', 'role': 'worker', 'authority_profile': 'ordinary', 'route': route},
                'lease_id': 'blocker-one'}
        other = {**base, 'lease_id': 'blocker-two', 'backend_sequence': 2,
                 'request': {**base['request'], 'request_id': 'blocker-two'}}
        (root / 'config/inference.cfg').write_text('[inference]\nfront_slots=1\nwork_slots=3\ncontext_tokens_per_slot=32768\nbackend_context_tokens=98304\ncontext_mode=fixed\n')
        (root / 'state/inference-capacity.json').write_text(json.dumps({'version': 1, 'generation': 1,
                                                                       'leases': {'blocker-one': base, 'blocker-two': other}}))
        observed = inventory(); observed['host']['available_host_bytes'] = 60 * 1024 ** 3
        survivor = sequence_request('memory-demand', 'sole_survivor')
        waiting = reserve(root, survivor, observed, lambda: 10.)
        assert waiting['state'] == 'waiting_for_preemption'
        assert set(waiting['preempts_lease_ids']) == {'blocker-one', 'blocker-two'}
        state = json.loads((root / 'state/inference-capacity.json').read_text())
        state['leases']['blocker-one']['state'] = 'released'
        inference_capacity._activate_waiter(state, 1, 11., json.loads((root / 'state/scheduling-policy.json').read_text()),
                                            inference_capacity._load_capacity_policy(root))
        assert state['leases'][waiting['lease_id']]['state'] == 'waiting_for_preemption'
        state['leases']['blocker-two']['state'] = 'released'
        inference_capacity._activate_waiter(state, 2, 12., json.loads((root / 'state/scheduling-policy.json').read_text()),
                                            inference_capacity._load_capacity_policy(root))
        assert state['leases'][waiting['lease_id']]['state'] == 'ready_for_revalidation'


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(function) for name, function in globals().items()
                              if name.startswith('test_') and callable(function))
