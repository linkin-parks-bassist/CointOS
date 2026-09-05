import unittest

from ecosystem.models import choose_route, safe_routes, validate_route


def inventory(models, **envelope):
    return {
        "verified": True,
        "stale": False,
        "models": models,
        "resource_envelope": {
            "maximum_model_bytes": 24_000_000_000,
            "maximum_context_tokens": 98_304,
            **envelope,
        },
    }


def model(model_id="large", **changes):
    return {
        "id": model_id,
        "parameter_count": 27_000_000_000,
        "size_bytes": 18_000_000_000,
        "labels": ["coding", "tool-calling"],
        "context": 131_072,
        "supported_context_quantum": 1_024,
        "parallel_sequences": 1,
        "loaded": False,
        "metadata_verified": True,
        "provenance": "registry:test",
        **changes,
    }


def request(**changes):
    return {
        "requirements": {
            "required_capabilities": ["coding"],
            "minimum_context_tokens": 32_768,
        },
        "prompt_tokens": 4_096,
        "tool_tokens": 2_048,
        "max_output_tokens": 4_096,
        "handoff_tokens": 2_048,
        **changes,
    }


def test_new_role_uses_explicit_requirements_without_code_change():
    current = inventory([
        model("small", parameter_count=4_000_000_000, size_bytes=3_000_000_000,
              labels=["tool-calling"], context=100_000),
        model(),
    ])
    selected = choose_route(safe_routes(current, {}, request(role="documenter")),
                            request(role="documenter"))
    assert selected["model_id"] == "large"
    assert selected["context_tokens_per_sequence"] == 98_304


def test_parameter_count_and_model_bytes_are_distinct():
    current = inventory([
        model("more_parameters", parameter_count=30_000_000_000,
              size_bytes=20_000_000_000),
        model("more_bytes", parameter_count=20_000_000_000,
              size_bytes=23_000_000_000),
    ])
    selected = choose_route(safe_routes(current, {}, request()), request())
    assert selected["model_id"] == "more_parameters"
    assert selected["parameter_count"] == 30_000_000_000
    assert selected["model_bytes"] == 20_000_000_000


def test_non_candidate_context_quantum_is_allowed():
    current = inventory([model(supported_context_quantum=3_072)],
                        maximum_context_tokens=70_000)
    selected = choose_route(safe_routes(current, {}, request()), request())
    assert selected["context_tokens_per_sequence"] == 67_584
    assert selected["context_exclusion_reasons"] == [
        "context:resource_envelope", "context:backend_quantum"
    ]


def test_total_context_is_divided_across_sequences():
    current = inventory([model(parallel_sequences=2)],
                        maximum_context_tokens=65_536)
    divided = request(
        requirements={"required_capabilities": ["coding"],
                      "minimum_context_tokens": 16_384},
        prompt_tokens=0, tool_tokens=0, max_output_tokens=0, handoff_tokens=0,
    )
    selected = choose_route(safe_routes(current, {}, divided), divided)
    assert selected["backend_context_tokens"] == 65_536
    assert selected["context_tokens_per_sequence"] == 32_768


def test_prompt_tool_output_and_handoff_are_reserved():
    constrained = request(
        requirements={"required_capabilities": ["coding"],
                      "minimum_context_tokens": 8_192},
        prompt_tokens=8_192, tool_tokens=4_096,
        max_output_tokens=4_096, handoff_tokens=4_096,
    )
    selected = choose_route(
        safe_routes(inventory([model()], maximum_context_tokens=20_000), {}, constrained),
        constrained,
    )
    assert selected["state"] == "deferred"
    assert "context_reserve" in selected["exclusion_reasons"]


def test_loaded_model_rechecks_current_pressure():
    selected = choose_route(
        safe_routes(inventory([model(loaded=True)], safe=False), {}, request()),
        request(),
    )
    assert selected["state"] == "deferred"
    assert "resource_envelope:unsafe" in selected["exclusion_reasons"]


def test_stale_inventory_defers():
    current = {**inventory([model()]), "stale": True}
    selected = choose_route(safe_routes(current, {}, request()), request())
    assert selected["state"] == "deferred"
    assert "inventory:stale" in selected["exclusion_reasons"]


def test_validate_route_closes_route_load_race():
    initial = inventory([model()])
    selected = choose_route(safe_routes(initial, {}, request()), request())
    fresh = inventory([model()], maximum_model_bytes=17_000_000_000)
    validated = validate_route(selected, fresh, {}, request())
    assert validated["state"] == "deferred"
    assert "model_bytes" in validated["exclusion_reasons"]


def test_physical_host_and_gtt_reserves_bound_routes():
    current = inventory(
        [model()],
        available_host_bytes=62_000_000_000,
        gtt_used_bytes=40_000_000_000,
        gtt_limit_bytes=64_000_000_000,
    )
    policy = {
        "protected_host_bytes": 32_000_000_000,
        "load_transient_bytes": 12_000_000_000,
        "estimated_kv_bytes_per_token": 1_024,
    }
    selected = choose_route(safe_routes(current, policy, request()), request())
    assert selected["state"] == "deferred"
    assert "host_capacity" in selected["exclusion_reasons"]
    assert "gtt_capacity" in selected["exclusion_reasons"]
    route_record = safe_routes(current, policy, request())[0]
    assert route_record["load_transient_bytes"] == 12_000_000_000
    assert route_record["protected_host_bytes"] == 32_000_000_000


def test_selected_route_records_excluded_larger_model():
    current = inventory([
        model("too_large", parameter_count=40_000_000_000,
              size_bytes=30_000_000_000),
        model("selected"),
    ])
    selected = choose_route(safe_routes(current, {}, request()), request())
    assert selected["model_id"] == "selected"
    assert selected["excluded_routes"] == [
        {"model_id": "too_large", "exclusion_reasons": ["model_bytes"]},
    ]


def test_context_smaller_than_one_backend_quantum_defers():
    current = inventory([model(supported_context_quantum=131_072)],
                        maximum_context_tokens=65_536)
    selected = choose_route(safe_routes(current, {}, request()), request())
    assert selected["state"] == "deferred"
    assert "context:unsupported" in selected["exclusion_reasons"]


def test_missing_explicit_capability_requirements_defers():
    selected = choose_route(safe_routes(inventory([model()]), {}, {}), {})
    assert selected["state"] == "deferred"
    assert "requirements:required_capabilities" in selected["exclusion_reasons"]


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
