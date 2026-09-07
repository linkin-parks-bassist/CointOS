"""Resident fixed KV pools must not be charged again to every request."""
import unittest
from ecosystem.models import _observed_model_record, safe_routes
from ecosystem.inference_capacity import resource_envelope
from test_model_admission import realistic_resident_inputs, inventory, admission_policy
from test_inference_capacity import capacity_policy

GIB = 1024 ** 3


def observed(shared=False):
    values = realistic_resident_inputs('qwen', 8002, 262144, 262144, 2,
                                      262144 if shared else 131072, 262144,
                                      27000000000, 17 * GIB)
    if shared:
        values[1]['launch_command'].append('--kv-unified')
    return _observed_model_record(*values, '2026-09-07T00:00:00Z')


def admitted():
    policy = admission_policy()
    policy.update(estimated_kv_bytes_per_token=131072,
                  gtt_limit_bytes=64 * GIB)
    facts = inventory([observed()], maximum_model_bytes=9 * GIB,
                      maximum_context_tokens=262144,
                      maximum_kv_bytes=21 * GIB, gtt_used_bytes=43 * GIB,
                      gtt_limit_bytes=64 * GIB, available_host_bytes=75 * GIB)
    request = {'requirements': {'required_capabilities': ['tool-calling'],
                               'minimum_context_tokens': 65536}}
    return safe_routes(facts, policy, request)[0], facts, policy, request


def test_observed_fixed_pool_is_credited_but_shared_mode_is_not_guessed():
    fixed = observed()
    assert fixed.get('context_mode') == 'fixed'
    assert fixed.get('preallocated_context_tokens') == 262144
    proven = observed(True)
    assert proven is not None
    assert proven.get('context_mode') == 'shared'
    assert proven.get('context_tokens_per_sequence') == 262144
    assert proven.get('preallocated_context_tokens') == 262144
    guessed = realistic_resident_inputs('qwen', 8002, 262144, 262144, 2,
                                        131072, 262144, 27000000000, 17 * GIB)
    guessed[1]['launch_command'].append('--kv-unified')
    assert _observed_model_record(*guessed, '2026-09-07T00:00:00Z') is None


def test_resident_weights_and_pool_are_not_charged_as_new_allocations():
    route, facts, policy, request = admitted()
    assert route['state'] == 'admitted', route
    assert route['kv_estimate_bytes'] == 32 * GIB
    assert route['incremental_kv_bytes'] == 0
    facts['models'][0].pop('preallocated_context_tokens', None)
    assert safe_routes(facts, policy, request)[0]['state'] == 'deferred'


def test_two_resident_requests_fit_without_two_extra_whole_pools():
    route, _, _, _ = admitted()
    assert route['state'] == 'admitted', route
    policy = capacity_policy()
    policy.update(total_sequences=3, gtt_limit_bytes=64 * GIB)
    host = {'available_host_bytes':75 * GIB, 'gtt_used_bytes':43 * GIB,
            'gtt_total_bytes':64 * GIB, 'gtt_total_fresh':True}
    resident = [{'model_id':'qwen', 'model_bytes':17 * GIB, 'work_model':True}]
    leases = [{'backend_sequence':i, 'workload_class':'work', 'route':route}
              for i in (1, 2)]
    result = resource_envelope(host, resident, leases, policy)
    assert result['safe'], result
    assert result['active_allocation_bytes'] == 32
    host['available_host_bytes'] = 40 * GIB
    assert not resource_envelope(host, resident, leases, policy)['safe']


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for name, fn in
                              globals().items() if name.startswith('test_'))
