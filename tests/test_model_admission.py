import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem.inference_capacity import resource_envelope
from ecosystem.models import choose_route, realize, safe_routes, snapshot, validate_route


GIB = 1024 ** 3


def admission_policy():
    return {
        "protected_host_bytes": 32_000_000_000,
        "coin_reserved_bytes": 4_000_000_000,
        "load_transient_bytes": 12_000_000_000,
        "gtt_limit_bytes": 64_000_000_000,
        "estimated_kv_bytes_per_token": 1_024,
        "context_reserves": {
            "prompt_tokens": 1,
            "tool_tokens": 1,
            "max_output_tokens": 1,
            "handoff_tokens": 1,
        },
    }


def inventory(models, **envelope):
    return {
        "verified": True,
        "fresh": True,
        "provenance": "resource-observer:test",
        "models": models,
        "resource_envelope": {
            "verified": True,
            "fresh": True,
            "safe": True,
            "provenance": "resource-observer:test",
            "maximum_model_bytes": 24_000_000_000,
            "maximum_context_tokens": 98_304,
            "available_host_bytes": 100_000_000_000,
            "gtt_used_bytes": 1_000_000_000,
            "gtt_limit_bytes": 64_000_000_000,
            "maximum_kv_bytes": 20_000_000_000,
            **envelope,
        },
    }


def model(model_id="large", **changes):
    return {
        "id": model_id,
        "parameter_count": 27_000_000_000,
        "size_bytes": 18_000_000_000,
        "capabilities": ["coding", "tool-calling"],
        "context": 131_072,
        "supported_context_quantum": 1_024,
        "parallel_sequences": 1,
        "loaded": False,
        "metadata_verified": True,
        "fresh": True,
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


def _write_snapshot_policy(root):
    (root / "config").mkdir()
    (root / "state").mkdir()
    resource_policy = {
        "physical_capacity": {
            "protected_host_bytes": 32 * GIB,
            "coin_reserved_bytes": 8 * GIB,
            "load_transient_bytes": 12 * GIB,
            "gtt_limit_bytes": 100 * GIB,
        },
        "dynamic_models": {
            "estimated_kv_bytes_per_token": 131_072,
            "context_reserves": admission_policy()["context_reserves"],
        },
    }
    scheduling_values = {"version": 1, "priority_bands": {"default": 500}}
    canonical = json.dumps(
        scheduling_values, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    accepted = {
        "schema_version": 1,
        "values": scheduling_values,
        "digest": hashlib.sha256(canonical).hexdigest(),
        "activated_at": "2026-09-05T00:00:00+00:00",
        "source_path": "config/scheduling.json",
    }
    (root / "config" / "resource-policy.json").write_text(
        json.dumps(resource_policy), encoding="utf-8",
    )
    (root / "config" / "model-policy.json").write_text(
        json.dumps({
            "priority_bands": {"default": -1},
            "control_plane": {"model": "model-a"},
        }), encoding="utf-8",
    )
    (root / "state" / "scheduling-policy.json").write_text(
        json.dumps(accepted), encoding="utf-8",
    )
    return accepted


def test_snapshot_produces_verified_r2_and_r3_capacity_records():
    registry = {"data": [{
        "id": "model-a",
        "downloaded": True,
        "parameter_count": 10_000_000_000,
        "size_bytes": 30 * GIB,
        "capabilities": ["coding", "tool-calling"],
        "context_length": 131_072,
        "supported_context_quantum": 32_768,
        "parallel_sequences": 2,
        "recipe": "llamacpp",
    }]}
    health = {"all_models_loaded": [{
        "model_name": "model-a",
        "recipe_options": {
            "ctx_size": 65_536,
            "llamacpp_args": "--parallel 2 --batch-size 512",
        },
        "is_busy": False,
        "pinned": False,
    }]}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accepted = _write_snapshot_policy(root)
        with patch("ecosystem.models._get", side_effect=(registry, health)), \
                patch("ecosystem.models._host_memory", return_value={
                    "total_bytes": 128 * GIB,
                    "available_bytes": 92 * GIB,
                    "provenance": "linux:/proc/meminfo",
                    "fresh": True,
                }), patch("ecosystem.models.gpu_memory", return_value={
                    "firmware_carveout_bytes": 512 * 1024 ** 2,
                    "gtt_total_bytes": 100 * GIB,
                    "gtt_used_bytes": 20 * GIB,
                    "provenance": "amdgpu:sysfs",
                    "fresh": True,
                }), patch("ecosystem.models.os.getloadavg", return_value=(1.0, 2.0, 3.0)):
            current = snapshot(root=root, clock=lambda: 1000.0)

    assert current["verified"] is True
    assert current["fresh"] is True
    assert current["observed_at"] == 1000.0
    assert current["scheduling_policy"] == accepted
    assert current["host"] == {
        "available_host_bytes": 92 * GIB,
        "total_host_bytes": 128 * GIB,
        "gtt_used_bytes": 20 * GIB,
        "gtt_total_bytes": 100 * GIB,
        "gtt_total_fresh": True,
        "fresh": True,
        "stale": False,
        "observed_at": 1000.0,
        "provenance": "linux:/proc/meminfo;amdgpu:sysfs",
    }
    assert current["resident_models"] == [{
        "model_id": "model-a", "model_bytes": 30 * GIB,
        "work_model": False, "backend_context_tokens": 65_536,
        "parallel_sequences": 2, "context_tokens_per_sequence": 32_768,
        "fresh": True, "observed_at": 1000.0,
        "provenance": "lemonade:/api/v1/health;policy:config/model-policy.json",
    }]
    produced = current["models"][0]
    assert produced["parameter_count"] == 10_000_000_000
    assert produced["size_bytes"] == 30 * GIB
    assert produced["capabilities"] == ["coding", "tool-calling"]
    assert produced["context"] == 131_072
    assert produced["supported_context_quantum"] == 32_768
    assert produced["loaded_context"] == 65_536
    assert produced["parallel_sequences"] == 2
    assert produced["metadata_verified"] is True
    envelope = current["resource_envelope"]
    assert envelope["gtt_limit_bytes"] == 100 * GIB
    assert envelope["available_host_bytes"] == 92 * GIB
    assert envelope["protected_host_bytes"] == 32 * GIB
    assert envelope["coin_reserved_bytes"] == 8 * GIB
    assert envelope["load_transient_bytes"] == 12 * GIB
    assert envelope["maximum_model_bytes"] == 40 * GIB
    assert envelope["maximum_kv_bytes"] == 52 * GIB
    assert envelope["maximum_context_tokens"] == 131_072
    modest_request = request(
        requirements={"required_capabilities": ["coding"],
                      "minimum_context_tokens": 16_384},
        prompt_tokens=1, tool_tokens=1, max_output_tokens=1, handoff_tokens=1,
    )
    selected = choose_route(
        safe_routes(current, admission_policy(), modest_request), modest_request,
    )
    assert selected["state"] == "admitted", selected
    physical = resource_envelope(
        current["host"], current["resident_models"], [], {
            "front_sequences": 1,
            "total_sequences": 2,
            "protected_host_bytes": 32 * GIB,
            "coin_reserved_bytes": 8 * GIB,
            "load_transient_bytes": 12 * GIB,
            "gtt_limit_bytes": 100 * GIB,
            "maximum_work_models": 1,
        },
    )
    assert physical["safe"] is True
    assert physical["resident_work_models"] == 0
    assert physical["gtt_capacity_bytes"] == 100 * GIB


def test_snapshot_never_derives_missing_metadata_from_model_name():
    registry = {"data": [{
        "id": "Qwen3-Coder-30B-131K-GGUF", "downloaded": True,
        "size_bytes": 18 * GIB, "capabilities": ["coding"],
    }]}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write_snapshot_policy(root)
        with patch("ecosystem.models._get", side_effect=(registry, {"all_models_loaded": []})), \
                patch("ecosystem.models._host_memory", return_value={
                    "total_bytes": 128 * GIB, "available_bytes": 92 * GIB,
                    "provenance": "linux:/proc/meminfo", "fresh": True,
                }), patch("ecosystem.models.gpu_memory", return_value={
                    "firmware_carveout_bytes": 512 * 1024 ** 2,
                    "gtt_total_bytes": 100 * GIB, "gtt_used_bytes": 1 * GIB,
                    "provenance": "amdgpu:sysfs", "fresh": True,
                }):
            produced = snapshot(root=root, clock=lambda: 1000.0)["models"][0]

    assert produced["parameter_count"] is None
    assert produced["context"] is None
    assert produced["supported_context_quantum"] is None
    assert produced["metadata_verified"] is False
    assert produced["fresh"] is True


def test_snapshot_marks_failed_residency_observation_unknown_and_stale():
    registry = {"data": [{
        "id": "model-a", "downloaded": True,
        "parameter_count": 1, "size_bytes": GIB,
        "capabilities": ["coding"], "context_length": 32_768,
        "supported_context_quantum": 1_024, "parallel_sequences": 1,
    }]}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write_snapshot_policy(root)
        with patch("ecosystem.models._get", side_effect=(registry, OSError("health unavailable"))), \
                patch("ecosystem.models._host_memory", return_value={
                    "total_bytes": 128 * GIB, "available_bytes": 92 * GIB,
                    "provenance": "linux:/proc/meminfo", "fresh": True,
                }), patch("ecosystem.models.gpu_memory", return_value={
                    "firmware_carveout_bytes": 512 * 1024 ** 2,
                    "gtt_total_bytes": 100 * GIB, "gtt_used_bytes": GIB,
                    "provenance": "amdgpu:sysfs", "fresh": True,
                }):
            current = snapshot(root=root, clock=lambda: 1000.0)

    assert current["verified"] is False
    assert current["fresh"] is False
    assert current["resident_models"] == []
    assert current["models"][0]["loaded"] is None
    assert current["models"][0]["fresh"] is False


def test_new_role_uses_explicit_requirements_without_code_change():
    current = inventory([
        model("small", parameter_count=4_000_000_000, size_bytes=3_000_000_000,
              capabilities=["tool-calling"], context=100_000),
        model(),
    ])
    selected = choose_route(safe_routes(current, admission_policy(), request(role="documenter")),
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
    selected = choose_route(safe_routes(current, admission_policy(), request()), request())
    assert selected["model_id"] == "more_parameters"
    assert selected["parameter_count"] == 30_000_000_000
    assert selected["model_bytes"] == 20_000_000_000


def test_non_candidate_context_quantum_is_allowed():
    current = inventory([model(supported_context_quantum=3_072)],
                        maximum_context_tokens=70_000)
    selected = choose_route(safe_routes(current, admission_policy(), request()), request())
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
    selected = choose_route(safe_routes(current, admission_policy(), divided), divided)
    assert selected["backend_context_tokens"] == 65_536
    assert selected["context_tokens_per_sequence"] == 32_768
    assert selected["prompt_tokens"] == 1
    assert selected["tool_tokens"] == 1
    assert selected["max_output_tokens"] == 1
    assert selected["handoff_tokens"] == 1


def test_prompt_tool_output_and_handoff_are_reserved():
    constrained = request(
        requirements={"required_capabilities": ["coding"],
                      "minimum_context_tokens": 8_192},
        prompt_tokens=8_192, tool_tokens=4_096,
        max_output_tokens=4_096, handoff_tokens=4_096,
    )
    selected = choose_route(
        safe_routes(inventory([model()], maximum_context_tokens=20_000), admission_policy(), constrained),
        constrained,
    )
    assert selected["state"] == "deferred"
    assert "context_reserve" in selected["exclusion_reasons"]


def test_loaded_model_rechecks_current_pressure():
    selected = choose_route(
        safe_routes(inventory([model(loaded=True)], safe=False), admission_policy(), request()),
        request(),
    )
    assert selected["state"] == "deferred"
    assert "resource_envelope:unsafe" in selected["exclusion_reasons"]


def test_stale_inventory_defers():
    current = {**inventory([model()]), "fresh": False}
    selected = choose_route(safe_routes(current, admission_policy(), request()), request())
    assert selected["state"] == "deferred"
    assert "inventory:stale" in selected["exclusion_reasons"]


def test_validate_route_closes_route_load_race():
    initial = inventory([model()])
    selected = choose_route(safe_routes(initial, admission_policy(), request()), request())
    fresh = inventory([model()], maximum_model_bytes=17_000_000_000)
    validated = validate_route(selected, fresh, admission_policy(), request())
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
        "coin_reserved_bytes": 4_000_000_000,
        "load_transient_bytes": 12_000_000_000,
        "gtt_limit_bytes": 64_000_000_000,
        "estimated_kv_bytes_per_token": 1_024,
        "context_reserves": admission_policy()["context_reserves"],
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
    selected = choose_route(safe_routes(current, admission_policy(), request()), request())
    assert selected["model_id"] == "selected"
    assert selected["excluded_routes"] == [
        {"model_id": "too_large", "exclusion_reasons": ["model_bytes"]},
    ]


def test_context_smaller_than_one_backend_quantum_defers():
    current = inventory([model(supported_context_quantum=131_072)],
                        maximum_context_tokens=65_536)
    selected = choose_route(safe_routes(current, admission_policy(), request()), request())
    assert selected["state"] == "deferred"
    assert "context:unsupported" in selected["exclusion_reasons"]


def test_missing_explicit_capability_requirements_defers():
    selected = choose_route(safe_routes(inventory([model()]), admission_policy(), {}), {})
    assert selected["state"] == "deferred"
    assert "requirements:required_capabilities" in selected["exclusion_reasons"]


def test_missing_verified_fresh_or_provenance_evidence_defers():
    base = inventory([model()])
    cases = (
        {key: value for key, value in base.items() if key != "verified"},
        {key: value for key, value in base.items() if key != "fresh"},
        {key: value for key, value in base.items() if key != "provenance"},
        {**base, "models": [{key: value for key, value in model().items()
                              if key != "metadata_verified"}]},
        {**base, "models": [{key: value for key, value in model().items()
                              if key != "fresh"}]},
        {**base, "models": [{key: value for key, value in model().items()
                              if key != "provenance"}]},
    )
    for current in cases:
        selected = choose_route(safe_routes(current, admission_policy(), request()), request())
        assert selected["state"] == "deferred"


def test_missing_physical_envelope_evidence_defers():
    for field in ("verified", "fresh", "safe", "provenance", "available_host_bytes",
                  "gtt_used_bytes", "gtt_limit_bytes", "maximum_model_bytes",
                  "maximum_context_tokens", "maximum_kv_bytes"):
        current = inventory([model()])
        del current["resource_envelope"][field]
        selected = choose_route(safe_routes(current, admission_policy(), request()), request())
        assert selected["state"] == "deferred", field


def test_legacy_labels_do_not_satisfy_explicit_capabilities():
    legacy = model()
    legacy["labels"] = legacy.pop("capabilities")
    selected = choose_route(
        safe_routes(inventory([legacy]), admission_policy(), request()), request())
    assert selected["state"] == "deferred"
    assert "capabilities" in selected["exclusion_reasons"]


def test_realize_requires_privileged_owner_for_nonresident_loading():
    current = inventory([
        model(parallel_sequences=2, size_gb=18.0, recipe="llamacpp")
    ], maximum_context_tokens=65_536)
    current["memory_available_gb"] = 100.0
    current["memory"] = {"gtt_used_gb": 1.0}
    divided = request(
        requirements={"required_capabilities": ["coding"],
                      "minimum_context_tokens": 16_384},
        prompt_tokens=1, tool_tokens=1, max_output_tokens=1, handoff_tokens=1,
    )
    selected = choose_route(safe_routes(current, admission_policy(), divided), divided)
    decision = {**selected, "valid": True, "action": "load",
                "model": selected["model_id"],
                "context_tokens": selected["context_tokens_per_sequence"]}
    with unittest.TestCase().assertRaisesRegex(
            RuntimeError, "requires privileged resource-control loading"):
        realize(decision, current)


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
