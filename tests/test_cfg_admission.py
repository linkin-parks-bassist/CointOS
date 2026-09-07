import inspect
import json
import tempfile
import unittest
from pathlib import Path

from test_inference_capacity import (
    GIB,
    accepted_scheduling_policy,
    ended_observation,
    inventory,
    resource_policy,
    route,
)

from ecosystem.inference_capacity import (
    _load_capacity_policy,
    realize_context_tokens,
    release_sequence,
    reserve_sequence,
)


GLOBAL_8_1_CFG = (
    "[inference]\n"
    "work_slots = 8\n"
    "front_slots = 1\n"
    "context_tokens_per_slot = 262144\n"
    "backend_context_tokens = 262144\n"
    "context_mode = shared\n"
)

GLOBAL_3_2_CFG = (
    "[inference]\n"
    "work_slots = 3\n"
    "front_slots = 2\n"
    "context_tokens_per_slot = 262144\n"
    "backend_context_tokens = 262144\n"
    "context_mode = shared\n"
)

OVERRIDE_CFG = GLOBAL_8_1_CFG + (
    "\n"
    "[model:model-a]\n"
    "work_slots = 1\n"
)

BROKEN_FIXED_CFG = (
    "[inference]\n"
    "work_slots = 8\n"
    "front_slots = 1\n"
    "context_tokens_per_slot = 262144\n"
    "backend_context_tokens = 1\n"
    "context_mode = fixed\n"
)


def work_worker_state(count):
    return {
        "schema_version": 1,
        "mode": "open",
        "generation": 1,
        "owner": None,
        "leases": {
            f"worker-{index}": {
                "lease_id": f"worker-{index}",
                "state": "active",
                "request": {
                    "workload_class": "work",
                    "owner_identity": f"worker:{index}",
                    "request_id": f"worker-request-{index}",
                    "role": "worker",
                    "model_id": "model-a",
                    "context_tokens": 32_768,
                    "max_output_tokens": 2_048,
                    "stop_method": "process_group",
                    "requirements": {"required_capabilities": ["coding"],
                                     "minimum_context_tokens": 16_384},
                    "prompt_tokens": 1_024,
                    "tool_tokens": 1_024,
                    "handoff_tokens": 1_024,
                    "authority_profile": "ordinary",
                    "execution_profile": None,
                },
                "acquired_monotonic": 0.0,
            }
            for index in range(1, count + 1)
        },
    }


def work_request(request_id, worker_index):
    return {
        "request_id": request_id,
        "worker_lease_id": f"worker-{worker_index}",
        "worker_request_id": f"worker-request-{worker_index}",
        "owner_identity": f"worker:{worker_index}",
        "workload_class": "work",
        "proxy_identity": "proxy:work",
        "route": route(),
        "role": "worker",
        "execution_profile": None,
        "authority_profile": "ordinary",
        "preemption_method": "process_group",
        "requirements": {"required_capabilities": ["coding"],
                         "minimum_context_tokens": 16_384},
        "prompt_tokens": 1_024,
        "tool_tokens": 1_024,
        "max_output_tokens": 2_048,
        "handoff_tokens": 1_024,
    }


def front_worker_lease(model_id="model-a"):
    return {
        "worker-front": {
            "lease_id": "worker-front",
            "state": "active",
            "request": {
                "workload_class": "front",
                "owner_identity": "coin:one",
                "request_id": "worker-request-front",
                "role": "coin",
                "model_id": model_id,
                "context_tokens": 32_768,
                "max_output_tokens": 2_048,
                "stop_method": "process_group",
                "requirements": {"required_capabilities": ["coding"],
                                 "minimum_context_tokens": 16_384},
                "prompt_tokens": 1_024,
                "tool_tokens": 1_024,
                "handoff_tokens": 1_024,
                "authority_profile": "coin",
                "execution_profile": None,
            },
            "acquired_monotonic": 0.0,
        }
    }


def front_request(request_id, model_id="model-a"):
    route_facts = {
        **route(),
        "model_id": model_id,
        "parameter_count": 3_000_000_000,
        "model_bytes": 20 * GIB,
        "backend_context_tokens": 32_768,
        "parallel_sequences": 1,
        "context_tokens_per_sequence": 32_768,
    } if model_id == "model-b" else route()
    return {
        "request_id": request_id,
        "worker_lease_id": "worker-front",
        "worker_request_id": "worker-request-front",
        "owner_identity": "coin:one",
        "workload_class": "front",
        "proxy_identity": "proxy:coin-front",
        "route": route_facts,
        "role": "coin",
        "execution_profile": None,
        "authority_profile": "coin",
        "preemption_method": "process_group",
        "requirements": {"required_capabilities": ["coding"],
                         "minimum_context_tokens": 16_384},
        "prompt_tokens": 1_024,
        "tool_tokens": 1_024,
        "max_output_tokens": 2_048,
        "handoff_tokens": 1_024,
    }


def write_cfg_root(root, cfg, workers=3, policy=None, worker_state=None):
    (root / "state").mkdir()
    (root / "config").mkdir()
    (root / "config" / "resource-policy.json").write_text(
        json.dumps(policy if policy is not None else resource_policy()),
        encoding="utf-8",
    )
    if cfg is not None:
        (root / "config" / "inference.cfg").write_text(cfg, encoding="utf-8")
    (root / "state" / "scheduling-policy.json").write_text(
        json.dumps(accepted_scheduling_policy()), encoding="utf-8",
    )
    (root / "state" / "workload-control.json").write_text(
        json.dumps(worker_state if worker_state is not None
                   else work_worker_state(workers)),
        encoding="utf-8",
    )


def durable_leases(root):
    state = json.loads(
        (root / "state" / "inference-capacity.json").read_text(encoding="utf-8"),
    )
    return state["leases"]


def test_global_cfg_derives_front_and_total_sequences():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "config").mkdir()
        (root / "config" / "resource-policy.json").write_text(
            json.dumps(resource_policy()), encoding="utf-8",
        )
        (root / "config" / "inference.cfg").write_text(
            GLOBAL_8_1_CFG, encoding="utf-8",
        )
        policy = _load_capacity_policy(root)
        assert policy["front_sequences"] == 1
        assert policy["total_sequences"] == 9
        (root / "config" / "inference.cfg").write_text(
            GLOBAL_3_2_CFG, encoding="utf-8",
        )
        policy = _load_capacity_policy(root)
        assert policy["front_sequences"] == 2
        assert policy["total_sequences"] == 5


def test_observed_two_backend_defers_third_same_model_lease():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_cfg_root(root, GLOBAL_8_1_CFG, workers=3)
        first = reserve_sequence(
            root, work_request("request-one", 1), inventory(), lambda: 10.0,
        )
        second = reserve_sequence(
            root, work_request("request-two", 2), inventory(), lambda: 11.0,
        )
        third = reserve_sequence(
            root, work_request("request-three", 3), inventory(), lambda: 12.0,
        )
        assert first["state"] == "starting"
        assert first["backend_sequence"] == 1
        assert second["state"] == "starting"
        assert second["backend_sequence"] == 2
        assert third == {
            "state": "deferred", "reasons": ["model_sequence_unavailable"],
        }
        leases = durable_leases(root)
        assert set(leases) == {first["lease_id"], second["lease_id"]}
        assert leases[second["lease_id"]]["state"] == "starting"


def test_front_and_work_leases_together_fill_observed_parallel_cap():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        worker_state = work_worker_state(2)
        worker_state["leases"].update(front_worker_lease())
        write_cfg_root(root, GLOBAL_8_1_CFG, worker_state=worker_state)
        front = reserve_sequence(
            root, front_request("front-one"), inventory(), lambda: 10.0,
        )
        first = reserve_sequence(
            root, work_request("request-one", 1), inventory(), lambda: 11.0,
        )
        second = reserve_sequence(
            root, work_request("request-two", 2), inventory(), lambda: 12.0,
        )
        assert front["state"] == "starting"
        assert front["backend_sequence"] == 0
        assert first["state"] == "starting"
        assert first["backend_sequence"] == 1
        assert second == {
            "state": "deferred", "reasons": ["model_sequence_unavailable"],
        }
        leases = durable_leases(root)
        assert set(leases) == {front["lease_id"], first["lease_id"]}
        assert leases[front["lease_id"]]["state"] == "starting"
        assert leases[first["lease_id"]]["state"] == "starting"


def test_distinct_model_front_lease_keeps_model_a_physical_cap():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        inventory_with_b = inventory()
        inventory_with_b["models"].append({
            "id": "model-b",
            "parameter_count": 3_000_000_000,
            "size_bytes": 20 * GIB,
            "capabilities": ["coding"],
            "context": 32_768,
            "supported_context_quantum": 32_768,
            "parallel_sequences": 1,
            "loaded": True,
            "loaded_context": 32_768,
            "metadata_verified": True,
            "fresh": True,
            "provenance": "registry:test",
        })
        inventory_with_b["resident_models"].append(
            {"model_id": "model-b", "model_bytes": 20 * GIB},
        )
        worker_state = work_worker_state(2)
        worker_state["leases"].update(front_worker_lease("model-b"))
        write_cfg_root(root, GLOBAL_8_1_CFG, worker_state=worker_state)
        front = reserve_sequence(
            root, front_request("front-b", model_id="model-b"),
            inventory_with_b, lambda: 10.0,
        )
        first = reserve_sequence(
            root, work_request("request-one", 1), inventory_with_b, lambda: 11.0,
        )
        second = reserve_sequence(
            root, work_request("request-two", 2), inventory_with_b, lambda: 12.0,
        )
        assert front["state"] == "starting"
        assert front["backend_sequence"] == 0
        assert first["state"] == "starting"
        assert second["state"] == "starting"
        assert second["backend_sequence"] == 2
        assert set(durable_leases(root)) == {
            front["lease_id"], first["lease_id"], second["lease_id"],
        }


def test_model_override_shrinks_work_cap():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_cfg_root(root, OVERRIDE_CFG, workers=2)
        first = reserve_sequence(
            root, work_request("request-one", 1), inventory(), lambda: 10.0,
        )
        second = reserve_sequence(
            root, work_request("request-two", 2), inventory(), lambda: 11.0,
        )
        assert first["state"] == "starting"
        assert second == {
            "state": "deferred", "reasons": ["model_sequence_unavailable"],
        }
        assert set(durable_leases(root)) == {first["lease_id"]}


def test_missing_cfg_fails_explicitly():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_cfg_root(root, None, workers=1)
        with unittest.TestCase().assertRaisesRegex(ValueError, "inference policy"):
            reserve_sequence(
                root, work_request("request-one", 1), inventory(), lambda: 10.0,
            )


def test_invalid_cfg_fails_explicitly():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_cfg_root(root, BROKEN_FIXED_CFG, workers=1)
        with unittest.TestCase().assertRaisesRegex(
                ValueError, "fixed backend_context_tokens"):
            reserve_sequence(
                root, work_request("request-one", 1), inventory(), lambda: 10.0,
            )


def test_duplicate_json_counts_are_rejected():
    for key in ("front_sequences", "total_sequences"):
        policy = resource_policy()
        policy["inference_capacity"][key] = 99
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_cfg_root(root, GLOBAL_8_1_CFG, workers=1, policy=policy)
            with unittest.TestCase().assertRaisesRegex(ValueError, "must not pin"):
                reserve_sequence(
                    root, work_request("request-one", 1),
                    inventory(), lambda: 10.0,
                )


def test_idempotent_replay_returns_existing_lease():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_cfg_root(root, GLOBAL_8_1_CFG, workers=1)
        request = work_request("request-one", 1)
        first = reserve_sequence(root, request, inventory(), lambda: 10.0)
        replay = reserve_sequence(root, request, inventory(), lambda: 11.0)
        assert first["state"] == "starting"
        assert replay["lease_id"] == first["lease_id"]
        assert replay["state"] == "starting"
        assert set(durable_leases(root)) == {first["lease_id"]}


def test_released_slot_can_be_reused_by_new_request():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_cfg_root(root, GLOBAL_8_1_CFG, workers=2)
        first = reserve_sequence(
            root, work_request("request-one", 1), inventory(), lambda: 10.0,
        )
        assert first["backend_sequence"] == 1
        released = release_sequence(
            root, first["lease_id"], ended_observation(first, 20.0), lambda: 20.0,
        )
        assert released["state"] == "released"
        second = reserve_sequence(
            root, work_request("request-two", 2), inventory(), lambda: 21.0,
        )
        assert second["state"] == "starting"
        assert second["backend_sequence"] == 1


def test_shared_realization_is_rejected_despite_fixed_product_equality():
    shared = {**route(), "context_mode": "shared"}
    with unittest.TestCase().assertRaisesRegex(ValueError, "not fixed"):
        realize_context_tokens(shared, 2)
    unknown = {**route(), "context_mode": "batched"}
    with unittest.TestCase().assertRaisesRegex(ValueError, "not fixed"):
        realize_context_tokens(unknown, 2)
    fixed = {**route(), "context_mode": "fixed"}
    assert realize_context_tokens(fixed, 2) == {
        "context_tokens": 32_768, "ctx_size": 65_536,
    }
    assert realize_context_tokens(route(), 2) == {
        "context_tokens": 32_768, "ctx_size": 65_536,
    }


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and inspect.isfunction(value)
    ]
    return unittest.TestSuite(unittest.FunctionTestCase(value) for value in functions)
