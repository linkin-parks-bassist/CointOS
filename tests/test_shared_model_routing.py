"""Shared llama.cpp KV pools route against the observed per-slot cap."""
import unittest

from ecosystem.models import (
    _observed_model_record, realize, safe_routes,
)
from test_model_admission import (
    GIB, admission_policy, inventory, model, realistic_resident_inputs, request,
)


def shared_inputs():
    item, resident, backend_document, props = realistic_resident_inputs(
        "qwen3.5-27b", 13307, None, 262_144, 8, 262_144, 262_144,
        27_000_000_000, 17 * GIB,
    )
    resident["launch_command"].append("--kv-unified")
    return item, resident, backend_document, props


def shared_record():
    return _observed_model_record(*shared_inputs(), 10.0)


def fixed_record():
    item, resident, backend_document, props = realistic_resident_inputs(
        "qwen3.5-4b", 13306, None, 262_144, 2, 131_072, 262_144,
        4_000_000_000, 2 * GIB,
    )
    return _observed_model_record(item, resident, backend_document, props, 10.0)


def shared_request():
    return {
        "requirements": {"required_capabilities": ["tool-calling"],
                         "minimum_context_tokens": 65_536},
        "prompt_tokens": 1, "tool_tokens": 1,
        "max_output_tokens": 1, "handoff_tokens": 1,
    }


def shared_facts(**envelope):
    return inventory(
        [shared_record()], maximum_context_tokens=262_144,
        maximum_kv_bytes=21 * GIB, **envelope,
    )


def test_fixed_partition_routes_per_slot_cap():
    route = safe_routes(
        inventory([fixed_record()], maximum_context_tokens=262_144,
                  maximum_kv_bytes=21 * GIB),
        admission_policy(), shared_request())[0]
    assert route["state"] == "admitted", route
    assert route["context_mode"] == "fixed"
    assert route["parallel_sequences"] == 2
    assert route["context_tokens_per_sequence"] == 131_072
    assert route["backend_context_tokens"] == 262_144
    assert route["incremental_kv_bytes"] == 0


def test_shared_pool_routes_observed_backend_total_not_product():
    route = safe_routes(shared_facts(), admission_policy(), shared_request())[0]
    assert route["state"] == "admitted", route
    assert route["context_mode"] == "shared"
    assert route["parallel_sequences"] == 8
    assert route["context_tokens_per_sequence"] == 262_144
    assert route["backend_context_tokens"] == 262_144
    assert route["backend_context_tokens"] != 262_144 * 8


def test_shared_pool_does_not_charge_resident_kv_twice():
    policy = admission_policy()
    policy.update(estimated_kv_bytes_per_token=131_072)
    route = safe_routes(shared_facts(), policy, shared_request())[0]
    assert route["state"] == "admitted", route
    assert route["kv_estimate_bytes"] == 262_144 * 131_072
    assert route["incremental_kv_bytes"] == 0


def test_shared_pool_still_defers_under_gtt_pressure():
    route = safe_routes(
        shared_facts(gtt_used_bytes=64_000_000_001),
        admission_policy(), shared_request())[0]
    assert route["state"] == "deferred", route
    assert "gtt_capacity" in route["exclusion_reasons"]


def test_observed_shared_pool_rejects_contradictory_facts():
    assert shared_record() is not None
    item, resident, backend_document, props = shared_inputs()
    backend_document["data"][0]["meta"]["n_ctx"] = 131_072
    assert _observed_model_record(
        item, resident, backend_document, props, 10.0) is None
    item, resident, backend_document, props = shared_inputs()
    resident["launch_command"][-2] = "7"
    assert _observed_model_record(
        item, resident, backend_document, props, 10.0) is None
    item, resident, backend_document, props = shared_inputs()
    resident["launch_command"][-4] = "2097152"
    assert _observed_model_record(
        item, resident, backend_document, props, 10.0) is None


def test_forged_shared_mode_is_deferred_without_observed_proof():
    forged = model(
        loaded=True, residency_verified=True, context_mode="shared",
        context=262_144, supported_context_quantum=262_144,
        parallel_sequences=8, loaded_context=262_144,
        context_tokens_per_sequence=262_144,
        preallocated_context_tokens=262_144,
    )
    route = safe_routes(inventory([forged], maximum_context_tokens=262_144,
                                  maximum_kv_bytes=21 * GIB),
                        admission_policy(), shared_request())[0]
    assert route["state"] == "deferred", route
    assert "context:shared_unverified" in route["exclusion_reasons"]
    bogus = model(context_mode="bogus")
    route = safe_routes(inventory([bogus]), admission_policy(), request())[0]
    assert route["state"] == "deferred", route
    assert "context_mode:unknown" in route["exclusion_reasons"]


def test_realize_shared_route_accepts_coherent_pool_and_rejects_drift():
    facts = shared_facts()
    route = safe_routes(facts, admission_policy(), shared_request())[0]
    assert route["state"] == "admitted", route
    decision = {**route, "valid": True, "action": "use_loaded",
                "model": route["model_id"],
                "context_tokens": route["context_tokens_per_sequence"]}
    assert realize(decision, facts) == {
        "action": "already_loaded", "model": "qwen3.5-27b",
        "context_tokens": 262_144, "backend_context_tokens": 262_144,
        "parallel_sequences": 8,
    }
    unknown_mode = {**decision, "context_mode": "bogus"}
    try:
        realize(unknown_mode, facts)
    except ValueError as error:
        assert "unknown context mode" in str(error)
    else:
        raise AssertionError("expected ValueError for unknown context mode")
    unloaded_model = model(
        loaded=False, residency_verified=True, context_mode="shared",
        context=262_144, supported_context_quantum=262_144,
        parallel_sequences=8, loaded_context=262_144,
        context_tokens_per_sequence=262_144,
        preallocated_context_tokens=262_144,
    )
    unloaded = inventory([unloaded_model], maximum_context_tokens=262_144)
    unloaded_decision = {**decision, "model": "large"}
    try:
        realize(unloaded_decision, unloaded)
    except ValueError as error:
        assert "coherent shared resident pool" in str(error)
    else:
        raise AssertionError("expected ValueError for unloaded shared pool")


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
