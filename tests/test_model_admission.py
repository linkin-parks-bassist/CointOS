import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem.inference_capacity import resource_envelope
from ecosystem.models import (
    _get_backend, _observed_model_record, choose_route, realize, safe_routes,
    snapshot, validate_route,
)


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
    scheduling_values = {"version": 1, "priority_bands": {
        "sole_survivor": 1000,
        "coin": 900,
        "user_driven": 850,
        "small_health": 800,
        "large_health": 700,
        "default": 500,
    }}
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


def observed_inputs():
    return (
        {
            "id": "Qwen3-Coder-30B-131K-GGUF",
            "downloaded": True,
            "recipe": "llamacpp",
        },
        {
            "model_name": "Qwen3-Coder-30B-131K-GGUF",
            "loaded": True,
            "backend_alive": True,
            "pid": 4242,
            "backend_url": "http://127.0.0.1:13306/v1",
            "launch_command": [
                "/usr/bin/llama-server",
                "--model", "/models/qwen3-coder-30b.gguf",
                "--ctx-size", "65536",
            ],
            "recipe_options": {"ctx_size": 65_536},
            "is_busy": False,
            "pinned": False,
        },
        {
            "data": [{
                "id": "/models/qwen3-coder-30b.gguf",
                "meta": {
                    "n_params": 30_000_000_000,
                    "size": 18 * GIB,
                    "n_ctx_train": 131_072,
                },
            }]
        },
        {
            "model_path": "/models/qwen3-coder-30b.gguf",
            "total_slots": 2,
            "chat_template_caps": {"supports_tools": True},
        },
    )


def observed_json(document):
    return json.loads(json.dumps(document))


def realistic_resident_inputs(name, port, registry_context, ctx_size, slots,
                              n_ctx, n_ctx_train, n_params, size):
    path = f"/models/{name}.gguf"
    return (
        {
            "id": name,
            "downloaded": True,
            "recipe": "llamacpp",
            "context_length": registry_context,
        },
        {
            "model_name": name,
            "loaded": True,
            "backend_alive": True,
            "pid": 4242,
            "backend_url": f"http://127.0.0.1:{port}/v1",
            "launch_command": [
                "/usr/bin/llama-server",
                "--model", path,
                "--ctx-size", str(ctx_size),
                "--parallel", str(slots),
            ],
            "recipe_options": {"ctx_size": ctx_size},
            "parallel_sequences": slots,
            "is_busy": False,
            "pinned": False,
        },
        {
            "data": [{
                "id": path,
                "meta": {
                    "n_params": n_params,
                    "size": size,
                    "n_ctx": n_ctx,
                    "n_ctx_train": n_ctx_train,
                },
            }]
        },
        {
            "model_path": path,
            "total_slots": slots,
            "chat_template_caps": {"supports_tools": True},
        },
    )


def test_observed_record_normalizes_realistic_4b_and_27b_residents():
    specs = (
        dict(name="qwen3.5-4b", port=13306, registry_context=65_536,
             ctx_size=65_536, slots=2, n_ctx=32_768, n_ctx_train=262_144,
             n_params=4_000_000_000, size=2 * GIB),
        dict(name="qwen3.5-27b", port=13307, registry_context=131_072,
             ctx_size=131_072, slots=1, n_ctx=131_072, n_ctx_train=262_144,
             n_params=27_000_000_000, size=16 * GIB),
    )
    for spec in specs:
        item, resident, backend_document, props = realistic_resident_inputs(**spec)
        result = _observed_model_record(item, resident, backend_document, props, 10.0)
        assert result is not None
        assert result["id"] == spec["name"]
        assert result["parameter_count"] == spec["n_params"]
        assert result["size_bytes"] == spec["size"]
        assert result["context"] == spec["n_ctx_train"]
        assert result["loaded_context"] == spec["ctx_size"]
        assert result["supported_context_quantum"] == spec["ctx_size"] // spec["slots"]
        assert result["registry_context_length"] == spec["registry_context"]
        root = f"http://127.0.0.1:{spec['port']}"
        assert result["provenance"] == (
            f"{root}/v1/models;{root}/props;"
            "lemonade:/api/v1/health;observed-allocation-only"
        )


def test_observed_record_normalizes_registry_gaps_and_keeps_inputs_immutable():
    item, resident, backend_document, props = observed_inputs()
    kept = [observed_json(document) for document in (item, resident, backend_document, props)]
    result = _observed_model_record(item, resident, backend_document, props, 1_700_000_000.0)
    assert result is not None
    assert result["id"] == "Qwen3-Coder-30B-131K-GGUF"
    assert result["parameter_count"] == 30_000_000_000
    assert result["size_bytes"] == 18 * GIB
    assert result["context"] == 131_072
    assert result["capabilities"] == ["tool-calling"]
    assert result["parallel_sequences"] == 2
    assert result["supported_context_quantum"] == 32_768
    assert "registry_context_length" not in result
    assert result["loaded"] is True
    assert result["loaded_context"] == 65_536
    assert result["metadata_verified"] is True
    assert result["residency_verified"] is True
    assert result["fresh"] is True
    assert result["observed_at"] == 1_700_000_000.0
    assert result["provenance"] == (
        "http://127.0.0.1:13306/v1/models;http://127.0.0.1:13306/props;"
        "lemonade:/api/v1/health;observed-allocation-only"
    )
    for original, before in zip((item, resident, backend_document, props), kept):
        assert original == before


def test_observed_record_keeps_parameter_count_distinct_from_bytes():
    item, resident, backend_document, props = observed_inputs()
    result = _observed_model_record(item, resident, backend_document, props, 10.0)
    assert result is not None
    assert result["parameter_count"] == 30_000_000_000
    assert result["size_bytes"] == 18 * GIB
    assert result["parameter_count"] != result["size_bytes"]


def test_observed_record_rejects_path_launch_and_identity_mismatches():
    for change in (
        lambda item, resident, backend_document, props: props.__setitem__(
            "model_path", "/models/other.gguf"),
        lambda item, resident, backend_document, props: resident.__setitem__(
            "launch_command", ["/usr/bin/llama-server"]),
        lambda item, resident, backend_document, props: item.__setitem__("id", "model-b"),
        lambda item, resident, backend_document, props: backend_document.__setitem__(
            "data", [{
                "id": "/models/other.gguf",
                "meta": {
                    "n_params": 30_000_000_000,
                    "size": 18 * GIB,
                    "n_ctx_train": 131_072,
                },
            }]),
        lambda item, resident, backend_document, props: backend_document.__setitem__(
            "data", []),
    ):
        item, resident, backend_document, props = observed_inputs()
        change(item, resident, backend_document, props)
        assert _observed_model_record(
            item, resident, backend_document, props, 10.0) is None


def test_observed_record_rejects_missing_or_bool_numeric_facts():
    cases = (
        ("resident", "pid", None),
        ("resident", "pid", True),
        ("resident", "pid", 0),
        ("backend", "n_params", None),
        ("backend", "n_params", True),
        ("backend", "size", None),
        ("backend", "n_ctx_train", True),
        ("props", "total_slots", None),
        ("props", "total_slots", True),
        ("props", "total_slots", 0),
        ("resident", "ctx_size", None),
    )
    for target, name, value in cases:
        item, resident, backend_document, props = observed_inputs()
        if target == "resident":
            container = resident["recipe_options"] if name == "ctx_size" else resident
            if value is None:
                del container[name]
            else:
                container[name] = value
        elif target == "backend":
            if value is None:
                del backend_document["data"][0]["meta"][name]
            else:
                backend_document["data"][0]["meta"][name] = value
        else:
            if value is None:
                del props[name]
            else:
                props[name] = value
        assert _observed_model_record(
            item, resident, backend_document, props, 10.0) is None, (target, name, value)


def test_observed_record_rejects_slot_and_context_mismatches():
    item, resident, backend_document, props = observed_inputs()
    resident["recipe_options"]["ctx_size"] = 65_535
    assert _observed_model_record(item, resident, backend_document, props, 10.0) is None
    item, resident, backend_document, props = observed_inputs()
    backend_document["data"][0]["meta"]["n_ctx_train"] = 16_384
    assert _observed_model_record(item, resident, backend_document, props, 10.0) is None
    item, resident, backend_document, props = observed_inputs()
    resident["parallel_sequences"] = 4
    assert _observed_model_record(item, resident, backend_document, props, 10.0) is None
    item, resident, backend_document, props = observed_inputs()
    resident["recipe_options"]["llamacpp_args"] = "--parallel 3 --batch-size 512"
    assert _observed_model_record(item, resident, backend_document, props, 10.0) is None


def test_observed_record_accepts_missing_explicit_parallel_from_props():
    item, resident, backend_document, props = observed_inputs()
    result = _observed_model_record(item, resident, backend_document, props, 10.0)
    assert result is not None
    assert result["parallel_sequences"] == props["total_slots"]
    item, resident, backend_document, props = observed_inputs()
    resident["recipe_options"]["llamacpp_args"] = "--parallel 2 --batch-size 512"
    result = _observed_model_record(item, resident, backend_document, props, 10.0)
    assert result is not None
    assert result["parallel_sequences"] == 2


def test_observed_record_derives_only_tool_calling_capability():
    def capabilities_for(supports_tools, registry_capabilities=...):
        item, resident, backend_document, props = observed_inputs()
        if registry_capabilities is ...:
            item.pop("capabilities", None)
        else:
            item["capabilities"] = registry_capabilities
        props["chat_template_caps"]["supports_tools"] = supports_tools
        result = _observed_model_record(item, resident, backend_document, props, 10.0)
        return None if result is None else result["capabilities"]

    assert capabilities_for(True) == ["tool-calling"]
    assert capabilities_for(False) == []
    assert capabilities_for(True, ["coding", "tool-calling"]) == ["coding", "tool-calling"]
    assert capabilities_for("yes") is None
    item, resident, backend_document, props = observed_inputs()
    props["chat_template_caps"].pop("supports_tools")
    assert _observed_model_record(item, resident, backend_document, props, 10.0) is None
    assert capabilities_for(True, ["coding"]) is None
    assert capabilities_for(False, ["coding", "tool-calling"]) is None


def test_observed_record_rejects_registry_contradictions():
    # Observed evidence from both residents: the registry context_length
    # records the allocated/advertised context (65_536 for the 4B,
    # 131_072 for the 27B), a distinct fact from the measured training
    # maximum backend meta.n_ctx_train (262_144 for both). The former
    # expectation that a differing registry context_length was a
    # contradiction conflated those two facts; now the raw registry value
    # is retained distinctly as registry_context_length while context
    # stays the measured n_ctx_train. Genuine parameter/byte
    # contradictions still reject.
    def normalized(**registry_fields):
        item, resident, backend_document, props = observed_inputs()
        item.update(registry_fields)
        return _observed_model_record(item, resident, backend_document, props, 10.0)

    assert normalized(parameter_count=30_000_000_000, size_bytes=18 * GIB,
                      context_length=131_072) is not None
    assert normalized(parameter_count=27_000_000_000) is None
    assert normalized(parameter_count="30000000000") is None
    assert normalized(size_bytes=17 * GIB) is None
    retained = normalized(context_length=65_536)
    assert retained is not None
    assert retained["registry_context_length"] == 65_536
    assert retained["context"] == 131_072
    absent = normalized(parameter_count=None, size_bytes=None, context_length=None)
    assert absent is not None
    assert "registry_context_length" not in absent


def test_observed_record_never_guesses_capability_or_count_from_name():
    item, resident, backend_document, props = observed_inputs()
    backend_document["data"][0]["meta"]["n_params"] = 27_000_000_000
    props["chat_template_caps"]["supports_tools"] = False
    result = _observed_model_record(item, resident, backend_document, props, 10.0)
    assert result is not None
    assert result["capabilities"] == []
    assert "coding" not in result["capabilities"]
    assert result["parameter_count"] == 27_000_000_000
    assert result["metadata_verified"] is True


def _expect_backend_value_error(backend_base, path):
    with patch("http.client.HTTPConnection") as connection:
        try:
            _get_backend(backend_base, path)
        except ValueError:
            connection.assert_not_called()
        else:
            raise AssertionError("expected ValueError for %r / %r" % (backend_base, path))


def _backend_round_trip(backend_base, path, host, port, document):
    with patch("http.client.HTTPConnection") as connection:
        instance = connection.return_value
        response = instance.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps(document).encode("utf-8")
        result = _get_backend(backend_base, path)
        connection.assert_called_once_with(host, port, timeout=1)
        instance.request.assert_called_once_with("GET", path)
        response.read.assert_called_once_with(1_048_577)
        instance.close.assert_called_once()
    return result


def test_get_backend_reads_models_and_props_on_numeric_loopback():
    for path in ("/v1/models", "/props"):
        document = {"path": path, "ok": True}
        result = _backend_round_trip("http://127.0.0.1:1234/v1", path, "127.0.0.1", 1234, document)
        assert result == document


def test_get_backend_accepts_bracketed_ipv6_loopback():
    result = _backend_round_trip("http://[::1]:8000/v1", "/v1/models", "::1", 8000, {"models": []})
    assert result == {"models": []}


def test_get_backend_rejects_base_violations_before_connecting():
    bad_bases = [
        "http://localhost:1234/v1",
        "http://192.168.1.5:1234/v1",
        "http://10.0.0.1:1234/v1",
        "http://0.0.0.0:1234/v1",
        "http://user:pass@127.0.0.1:1234/v1",
        "http://127.0.0.1:1234/v1?x=1",
        "http://127.0.0.1:1234/v1#frag",
        "http://127.0.0.1:1234/v1/",
        "http://127.0.0.1:1234/api/v1",
        "http://127.0.0.1:1234/",
        "http://127.0.0.1/v1",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1:99999/v1",
        "http://127.0.0.1:abc/v1",
        "https://127.0.0.1:1234/v1",
        "ftp://127.0.0.1:1234/v1",
        "http://:1234/v1",
    ]
    for base in bad_bases:
        _expect_backend_value_error(base, "/v1/models")


def test_get_backend_rejects_request_paths_before_connecting():
    for path in ("/v1", "/v1/", "/v1/models/", "/models", "/v1/other", "/props/", "", "/"):
        _expect_backend_value_error("http://127.0.0.1:1234/v1", path)


def test_get_backend_requires_http_200_and_never_follows_redirects():
    for status in (301, 302, 404, 500):
        with patch("http.client.HTTPConnection") as connection:
            instance = connection.return_value
            response = instance.getresponse.return_value
            response.status = status
            response.read.return_value = b"{}"
            try:
                _get_backend("http://127.0.0.1:1234/v1", "/v1/models")
            except ValueError:
                pass
            else:
                raise AssertionError("expected ValueError for status %d" % status)
            instance.request.assert_called_once_with("GET", "/v1/models")
            response.read.assert_not_called()
            instance.close.assert_called_once()


def test_get_backend_rejects_oversized_response():
    with patch("http.client.HTTPConnection") as connection:
        instance = connection.return_value
        response = instance.getresponse.return_value
        response.status = 200
        response.read.return_value = b"x" * 1_048_577
        try:
            _get_backend("http://127.0.0.1:1234/v1", "/v1/models")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for oversized response")
        response.read.assert_called_once_with(1_048_577)
        instance.close.assert_called_once()


def test_get_backend_accepts_response_at_exact_limit():
    base, tail = b'{"pad":"', b'"}'
    payload = base + b"x" * (1_048_576 - len(base) - len(tail)) + tail
    assert len(payload) == 1_048_576
    with patch("http.client.HTTPConnection") as connection:
        instance = connection.return_value
        response = instance.getresponse.return_value
        response.status = 200
        response.read.return_value = payload
        result = _get_backend("http://127.0.0.1:1234/v1", "/props")
        response.read.assert_called_once_with(1_048_577)
        instance.close.assert_called_once()
    assert result["pad"] == payload[len(base):-len(tail)].decode("ascii")


def test_get_backend_rejects_malformed_json():
    with patch("http.client.HTTPConnection") as connection:
        instance = connection.return_value
        response = instance.getresponse.return_value
        response.status = 200
        response.read.return_value = b"{not valid json"
        try:
            _get_backend("http://127.0.0.1:1234/v1", "/v1/models")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for malformed JSON")
        instance.close.assert_called_once()


def test_get_backend_propagates_transport_error_and_closes():
    with patch("http.client.HTTPConnection") as connection:
        instance = connection.return_value
        instance.request.side_effect = ConnectionRefusedError("connection refused")
        try:
            _get_backend("http://127.0.0.1:1234/v1", "/v1/models")
        except ConnectionRefusedError:
            pass
        else:
            raise AssertionError("expected transport error to propagate")
        instance.close.assert_called_once()


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
