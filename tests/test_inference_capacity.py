import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from ecosystem.inference_capacity import (
    effective_priority,
    realize_context_tokens,
    release_sequence,
    reserve_sequence,
    resource_envelope,
)


GIB = 1024 ** 3


def scheduling_values():
    return {
        "version": 1,
        "priority_bands": {
            "sole_survivor": 1000,
            "coin": 900,
            "small_health": 800,
            "large_health": 700,
            "default": 500,
        },
        "authority_profiles": {
            "sole_survivor": "sole_survivor",
            "coin": "coin",
        },
        "execution_profiles": {
            "small_health": "small_health",
            "large_health": "large_health",
        },
        "role_priorities": {
            "verifier": 600,
            "coder": 550,
            "worker": 550,
            "auditor": 500,
            "refactorer": 450,
            "gardener": 350,
            "janitor": 300,
            "documenter": 250,
            "chunker": 200,
            "innovator": 150,
            "speculator": 100,
            "default": 250,
        },
        "aging_seconds_per_point": 60,
    }


def accepted_scheduling_policy():
    values = scheduling_values()
    canonical = json.dumps(
        values, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "values": values,
        "digest": hashlib.sha256(canonical).hexdigest(),
        "activated_at": "2026-09-05T00:00:00+00:00",
        "source_path": "config/scheduling.json",
    }


def capacity_policy():
    return {
        "front_sequences": 1,
        "total_sequences": 2,
        "protected_host_bytes": 32 * GIB,
        "coin_reserved_bytes": 8 * GIB,
        "load_transient_bytes": 12 * GIB,
        "gtt_limit_bytes": 64 * GIB,
        "maximum_work_models": 1,
        "front_proxy_identity": "proxy:coin-front",
        "work_proxy_identity": "proxy:work",
        "lease_seconds": 300,
    }


def route():
    return {
        "state": "admitted",
        "model_id": "model-a",
        "context_tokens_per_sequence": 32_768,
        "backend_context_tokens": 65_536,
        "parallel_sequences": 2,
        "max_output_tokens": 2_048,
        "prompt_tokens": 1_024,
        "tool_tokens": 1_024,
        "handoff_tokens": 1_024,
        "kv_estimate_bytes": 64 * 1024 ** 2,
    }


def inventory():
    return {
        "host": {
            "available_host_bytes": 100 * GIB,
            "gtt_used_bytes": 20 * GIB,
        },
        "resident_models": [],
    }


def write_root(root):
    (root / "state").mkdir()
    (root / "config").mkdir()
    (root / "config" / "resource-policy.json").write_text(
        json.dumps({"inference_capacity": capacity_policy()}), encoding="utf-8",
    )
    (root / "config" / "scheduling.json").write_text(
        json.dumps(scheduling_values()), encoding="utf-8",
    )
    values = scheduling_values()
    canonical = json.dumps(
        values, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    snapshot = accepted_scheduling_policy()
    assert snapshot["digest"] == hashlib.sha256(canonical).hexdigest()
    (root / "state" / "scheduling-policy.json").write_text(
        json.dumps(snapshot), encoding="utf-8",
    )
    worker_state = {
        "version": 1,
        "mode": "open",
        "generation": 1,
        "owner": None,
        "leases": {
            "worker-one": {
                "lease_id": "worker-one",
                "state": "active",
                "request": {
                    "workload_class": "work",
                    "owner_identity": "worker:one",
                    "authority_profile": "ordinary",
                    "execution_profile": None,
                },
            },
            "worker-survivor": {
                "lease_id": "worker-survivor",
                "state": "active",
                "request": {
                    "workload_class": "work",
                    "owner_identity": "survivor:one",
                    "authority_profile": "sole_survivor",
                    "execution_profile": None,
                },
            },
        },
    }
    (root / "state" / "workload-control.json").write_text(
        json.dumps(worker_state), encoding="utf-8",
    )


def sequence_request(request_id="request-one", authority_profile="ordinary",
                     workload_class="work", proxy_identity="proxy:work"):
    worker_lease_id = (
        "worker-survivor" if authority_profile == "sole_survivor" else "worker-one"
    )
    return {
        "request_id": request_id,
        "worker_lease_id": worker_lease_id,
        "workload_class": workload_class,
        "proxy_identity": proxy_identity,
        "route": route(),
        "role": "worker",
        "execution_profile": None,
        "authority_profile": authority_profile,
        "preemption_method": "process_group",
    }


def test_work_cannot_consume_reserved_front_sequence():
    result = resource_envelope(
        {"available_host_bytes": 80 * GIB, "gtt_used_bytes": 20 * GIB},
        [], [{"workload_class": "work", "backend_sequence": 1}],
        capacity_policy(),
    )
    assert result["available_work_sequences"] == 0
    assert result["reserved_front_sequences"] == 1


def test_realized_context_maps_per_sequence_to_backend_total():
    realized = realize_context_tokens(route(), 2)
    assert realized["context_tokens"] == 32_768
    assert realized["ctx_size"] == 65_536
    inconsistent = {**route(), "backend_context_tokens": 32_768}
    with unittest.TestCase().assertRaisesRegex(ValueError, "inconsistent"):
        realize_context_tokens(inconsistent, 2)


def test_front_proxy_cannot_be_claimed_by_survivor_or_work():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        for authority_profile in ("sole_survivor", "ordinary"):
            request = sequence_request(
                request_id=f"request-{authority_profile}",
                authority_profile=authority_profile,
                proxy_identity="proxy:coin-front",
            )
            with unittest.TestCase().assertRaisesRegex(ValueError, "front proxy"):
                reserve_sequence(root, request, inventory(), lambda: 10.0)


def test_priority_bands_match_validated_policy():
    policy = accepted_scheduling_policy()
    assert effective_priority(policy, None, None, "sole_survivor", 0) == 1000
    assert effective_priority(policy, None, None, "coin", 0) == 900
    assert effective_priority(policy, None, "small_health", "ordinary", 0) == 800
    assert effective_priority(policy, None, "large_health", "ordinary", 0) == 700
    assert effective_priority(policy, "gardener", None, "ordinary", 0) == 350
    assert effective_priority(policy, "health_inspector", None, "ordinary", 0) == 250


def test_caller_priority_is_ignored():
    policy = accepted_scheduling_policy()
    policy["values"]["caller_priority"] = 10_000
    with unittest.TestCase().assertRaisesRegex(ValueError, "scheduling policy"):
        effective_priority(policy, "gardener", None, "ordinary", 0)
    assert effective_priority(accepted_scheduling_policy(), "gardener", None,
                              "ordinary", 0) == 350
    assert effective_priority(accepted_scheduling_policy(), "sole_survivor", None,
                              "ordinary", 0) == 250


def test_aging_cannot_cross_band():
    policy = accepted_scheduling_policy()
    assert effective_priority(policy, "worker", None, "ordinary", 10 ** 9) == 699
    assert effective_priority(policy, None, "large_health", "ordinary", 10 ** 9) == 799


def test_high_priority_arrival_preempts_work_lease():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        first = reserve_sequence(root, sequence_request(), inventory(), lambda: 10.0)
        assert first["state"] == "starting"
        survivor = sequence_request(
            request_id="request-survivor", authority_profile="sole_survivor",
        )
        result = reserve_sequence(root, survivor, inventory(), lambda: 20.0)
        assert result["state"] == "waiting_for_preemption"
        assert result["preempts_lease_id"] == first["lease_id"]
        state = json.loads(
            (root / "state" / "inference-capacity.json").read_text(encoding="utf-8")
        )
        assert state["leases"][first["lease_id"]]["state"] == "preemption_requested"


def test_release_requires_observed_sequence_end():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        lease = reserve_sequence(root, sequence_request(), inventory(), lambda: 10.0)
        incomplete = release_sequence(
            root, lease["lease_id"],
            {"backend_sequence": lease["backend_sequence"], "sequence_active": True},
            lambda: 20.0,
        )
        assert incomplete["state"] == "release_requested"
        released = release_sequence(
            root, lease["lease_id"],
            {"backend_sequence": lease["backend_sequence"], "sequence_active": False},
            lambda: 30.0,
        )
        assert released["state"] == "released"
        assert released["observed_release"]["observed_monotonic"] == 30.0


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and inspect.isfunction(value)
    ]
    return unittest.TestSuite(unittest.FunctionTestCase(value) for value in functions)
