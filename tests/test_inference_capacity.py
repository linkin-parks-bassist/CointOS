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
        "gtt_limit_bytes": 100 * GIB,
        "maximum_work_models": 1,
        "front_proxy_identity": "proxy:coin-front",
        "work_proxy_identity": "proxy:work",
        "lease_seconds": 300,
        "release_observer_identity": "observer:inference-backend",
        "release_observation_maximum_age_seconds": 5,
    }


def route():
    return {
        "state": "admitted",
        "model_id": "model-a",
        "model_bytes": 30 * GIB,
        "loaded": True,
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
            "gtt_total_bytes": 100 * GIB,
            "gtt_total_fresh": True,
        },
        "resident_models": [
            {"model_id": "model-a", "model_bytes": 30 * GIB, "work_model": True},
        ],
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
        "schema_version": 1,
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
                    "request_id": "worker-request-one",
                    "role": "worker",
                    "model_id": "model-a",
                    "context_tokens": 32_768,
                    "max_output_tokens": 2_048,
                    "stop_method": "process_group",
                    "authority_profile": "ordinary",
                    "execution_profile": None,
                },
                "acquired_monotonic": 0.0,
            },
            "worker-survivor": {
                "lease_id": "worker-survivor",
                "state": "active",
                "request": {
                    "workload_class": "work",
                    "owner_identity": "survivor:one",
                    "request_id": "worker-request-survivor",
                    "role": "worker",
                    "model_id": "model-a",
                    "context_tokens": 32_768,
                    "max_output_tokens": 2_048,
                    "stop_method": "process_group",
                    "authority_profile": "sole_survivor",
                    "execution_profile": None,
                },
                "acquired_monotonic": 0.0,
            },
            "worker-coin": {
                "lease_id": "worker-coin",
                "state": "active",
                "request": {
                    "workload_class": "front",
                    "owner_identity": "coin:one",
                    "request_id": "worker-request-coin",
                    "role": "coin",
                    "model_id": "model-a",
                    "context_tokens": 32_768,
                    "max_output_tokens": 2_048,
                    "stop_method": "process_group",
                    "authority_profile": "coin",
                    "execution_profile": None,
                },
                "acquired_monotonic": 0.0,
            },
        },
    }
    (root / "state" / "workload-control.json").write_text(
        json.dumps(worker_state), encoding="utf-8",
    )


def sequence_request(request_id="request-one", authority_profile="ordinary",
                     workload_class="work", proxy_identity="proxy:work"):
    if authority_profile == "sole_survivor":
        worker_lease_id = "worker-survivor"
        owner_identity = "survivor:one"
        worker_request_id = "worker-request-survivor"
        role = "worker"
    elif authority_profile == "coin":
        worker_lease_id = "worker-coin"
        owner_identity = "coin:one"
        worker_request_id = "worker-request-coin"
        role = "coin"
    else:
        worker_lease_id = "worker-one"
        owner_identity = "worker:one"
        worker_request_id = "worker-request-one"
        role = "worker"
    return {
        "request_id": request_id,
        "worker_lease_id": worker_lease_id,
        "worker_request_id": worker_request_id,
        "owner_identity": owner_identity,
        "workload_class": workload_class,
        "proxy_identity": proxy_identity,
        "route": route(),
        "role": role,
        "execution_profile": None,
        "authority_profile": authority_profile,
        "preemption_method": "process_group",
    }


def ended_observation(lease, observed_monotonic):
    return {
        "lease_id": lease["lease_id"],
        "request_id": lease["request"]["request_id"],
        "proxy_identity": lease["proxy_identity"],
        "observer_identity": "observer:inference-backend",
        "backend_sequence": lease["backend_sequence"],
        "backend_sequence_state": "ended",
        "sequence_active": False,
        "observed_monotonic": observed_monotonic,
    }


def test_work_cannot_consume_reserved_front_sequence():
    result = resource_envelope(
        {"available_host_bytes": 80 * GIB, "gtt_used_bytes": 20 * GIB,
         "gtt_total_bytes": 100 * GIB, "gtt_total_fresh": True},
        [], [{"workload_class": "work", "backend_sequence": 1}],
        capacity_policy(),
    )
    assert result["available_work_sequences"] == 0
    assert result["reserved_front_sequences"] == 1
    assert result["gtt_capacity_bytes"] == 100 * GIB
    assert result["gtt_headroom_bytes"] == 68 * GIB
    for host in (
        {"available_host_bytes": 80 * GIB, "gtt_used_bytes": 20 * GIB},
        {"available_host_bytes": 80 * GIB, "gtt_used_bytes": 20 * GIB,
         "gtt_total_bytes": 100 * GIB, "gtt_total_fresh": False},
    ):
        failed = resource_envelope(host, [], [], capacity_policy())
        assert failed["safe"] is False
        assert "gtt_total_bytes" in failed["unknown_facts"]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        stale_inventory = inventory()
        stale_inventory["host"]["gtt_total_fresh"] = False
        deferred = reserve_sequence(
            root, sequence_request(), stale_inventory, lambda: 10.0,
        )
        assert deferred == {"state": "deferred", "reasons": ["gtt_total_bytes"]}


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


def test_candidate_post_state_includes_sequence_and_nonresident_model_bytes():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        constrained = inventory()
        constrained["host"]["available_host_bytes"] = 70 * GIB
        constrained["resident_models"] = []
        request = sequence_request()
        request["route"] = {**route(), "loaded": False}
        result = reserve_sequence(root, request, constrained, lambda: 10.0)
        assert result == {"state": "deferred", "reasons": ["physical_capacity"]}
        request = sequence_request(request_id="request-unknown-residency")
        request["route"] = {key: value for key, value in route().items()
                            if key != "loaded"}
        result = reserve_sequence(root, request, inventory(), lambda: 10.0)
        assert result == {"state": "deferred", "reasons": [
            "active_leases:0:model",
        ]}
        request = sequence_request(request_id="request-kv")
        request["route"] = {**route(), "kv_estimate_bytes": 60 * GIB}
        result = reserve_sequence(root, request, inventory(), lambda: 10.0)
        assert result == {"state": "deferred", "reasons": ["physical_capacity"]}


def test_scheduling_snapshot_cannot_come_from_caller_inventory():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        (root / "state" / "scheduling-policy.json").unlink()
        supplied = inventory()
        supplied["scheduling_policy"] = accepted_scheduling_policy()
        with unittest.TestCase().assertRaisesRegex(ValueError, "scheduling-policy"):
            reserve_sequence(root, sequence_request(), supplied, lambda: 10.0)


def test_front_release_never_assigns_a_work_waiter():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        coin = reserve_sequence(
            root,
            sequence_request("coin-request", "coin", "front", "proxy:coin-front"),
            inventory(), lambda: 10.0,
        )
        reserve_sequence(root, sequence_request(), inventory(), lambda: 11.0)
        waiter = reserve_sequence(
            root, sequence_request("request-survivor", "sole_survivor"),
            inventory(), lambda: 12.0,
        )
        release_sequence(root, coin["lease_id"], ended_observation(coin, 13.0),
                         lambda: 13.0)
        state = json.loads(
            (root / "state" / "inference-capacity.json").read_text(encoding="utf-8")
        )
        retained = state["leases"][waiter["lease_id"]]
        assert retained["state"] == "waiting_for_preemption"
        assert retained["backend_sequence"] is None


def test_sequence_identity_is_bound_to_exact_worker_lease():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        mutations = (
            {"owner_identity": "worker:other"},
            {"worker_request_id": "worker-request-other"},
            {"role": "auditor"},
            {"authority_profile": "sole_survivor"},
        )
        for index, mutation in enumerate(mutations):
            request = {**sequence_request(f"request-forged-{index}"), **mutation}
            with unittest.TestCase().assertRaisesRegex(ValueError, "worker and inference"):
                reserve_sequence(root, request, inventory(), lambda: 10.0)


def test_waiter_selection_recomputes_trusted_age_within_band():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        active = reserve_sequence(root, sequence_request(), inventory(), lambda: 10.0)
        state_path = root / "state" / "inference-capacity.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        template = state["leases"][active["lease_id"]]
        for lease_id, role, enqueued, stale_priority in (
            ("old-gardener", "gardener", 0.0, 350),
            ("new-auditor", "auditor", 20_940.0, 500),
        ):
            waiting = json.loads(json.dumps(template))
            waiting.update(
                lease_id=lease_id, state="waiting_for_preemption",
                backend_sequence=None, priority=stale_priority,
                enqueued_monotonic=enqueued,
            )
            waiting["request"]["request_id"] = f"{lease_id}-request"
            waiting["request"]["role"] = role
            state["leases"][lease_id] = waiting
        state_path.write_text(json.dumps(state), encoding="utf-8")
        release_sequence(root, active["lease_id"], ended_observation(active, 21_000.0),
                         lambda: 21_000.0)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["leases"]["old-gardener"]["state"] == "starting"
        assert state["leases"]["old-gardener"]["priority"] == 699
        assert state["leases"]["new-auditor"]["state"] == "waiting_for_preemption"


def test_release_requires_observed_sequence_end():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_root(root)
        lease = reserve_sequence(root, sequence_request(), inventory(), lambda: 10.0)
        assert lease["release_observer_identity"] == "observer:inference-backend"
        adversarial = (
            {"backend_sequence": lease["backend_sequence"], "sequence_active": False},
            {**ended_observation(lease, 20.0), "observer_identity": "caller:forged"},
            ended_observation(lease, 10.0),
        )
        for observed in adversarial:
            incomplete = release_sequence(root, lease["lease_id"], observed,
                                          lambda: 20.0)
            assert incomplete["state"] == "release_requested"
        released = release_sequence(
            root, lease["lease_id"], ended_observation(lease, 30.0), lambda: 30.0,
        )
        assert released["state"] == "released"
        assert released["observed_release"]["observed_monotonic"] == 30.0


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and inspect.isfunction(value)
    ]
    return unittest.TestSuite(unittest.FunctionTestCase(value) for value in functions)
