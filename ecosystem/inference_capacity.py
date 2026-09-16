"""Physical inference capacity, trusted priority, and sequence leases."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from contextlib import contextmanager
from pathlib import Path

from ecosystem import inference_policy, models


STATE_VERSION = 1
SNAPSHOT_FIELDS = frozenset((
    "schema_version", "values", "digest", "activated_at", "source_path",
))
LEASE_STATES = frozenset((
    "starting", "active", "preemption_requested", "waiting_for_preemption",
    "ready_for_revalidation", "release_requested", "released",
))


def validate_launch_capacity(lease, record):
    """Validate one admitted inference lease against one live effective record.

    Pure function: returns the effective record when the lease's model identity
    and its context and output lease terms all fit the live per-request
    capacity, or raises ValueError naming the single disagreeing lease term.
    The record must be the validated effective capacity record produced by
    `ecosystem.opencode_capacity.effective_inference_capacity`; its context and
    output caps are the live per-request facts the lease must never exceed.
    """
    if not isinstance(lease, dict):
        raise ValueError("lease must be a dictionary")
    if not isinstance(record, dict):
        raise ValueError("record must be a dictionary")
    for key in ("model_id", "context_tokens_per_sequence", "max_output_tokens"):
        if key not in lease:
            raise ValueError(f"lease is missing required key {key!r}")
    for key in ("model_id", "opencode_context_tokens", "opencode_output_tokens"):
        if key not in record:
            raise ValueError(f"record is missing required key {key!r}")
    lease_model = lease["model_id"]
    if not isinstance(lease_model, str) or not lease_model:
        raise ValueError("lease model_id must be a non-empty string")
    record_model = record["model_id"]
    if not isinstance(record_model, str) or not record_model:
        raise ValueError("record model_id must be a non-empty string")
    if lease_model != record_model:
        raise ValueError(
            f"lease model {lease_model!r} differs from the live observed model "
            f"{record_model!r}; launch stays closed")
    lease_context = lease["context_tokens_per_sequence"]
    if type(lease_context) is not int or lease_context <= 0:
        raise ValueError(
            "lease context_tokens_per_sequence must be a positive integer")
    live_context = record["opencode_context_tokens"]
    if type(live_context) is not int or live_context <= 0:
        raise ValueError(
            "record opencode_context_tokens must be a positive integer")
    if lease_context > live_context:
        raise ValueError(
            f"lease context {lease_context} exceeds the live effective context "
            f"{live_context}; launch stays closed")
    lease_output = lease["max_output_tokens"]
    if type(lease_output) is not int or lease_output <= 0:
        raise ValueError("lease max_output_tokens must be a positive integer")
    live_output = record["opencode_output_tokens"]
    if type(live_output) is not int or live_output <= 0:
        raise ValueError("record opencode_output_tokens must be a positive integer")
    if lease_output > live_output:
        raise ValueError(
            f"lease output {lease_output} exceeds the live effective output "
            f"{live_output}; launch stays closed")
    return record


def constrain_launch_capacity(lease, record):
    """Preserve observed backend facts, but configure the admitted allowance.

    Fitting a larger live cap does not authorize requests larger than the lease.
    The proxy enforces that lease, including the exact max_tokens value.
    """
    validate_launch_capacity(lease, record)
    context = lease["context_tokens_per_sequence"]
    output = lease["max_output_tokens"]
    if output >= context or record.get("prompt_estimate_tokens", 0) + output > context:
        raise ValueError("admitted prompt/output allowance does not fit admitted context")
    return dict(record, opencode_context_tokens=context, opencode_output_tokens=output)


def resource_envelope(
    host: dict,
    resident_models: list[dict],
    active_leases: list[dict],
    policy: dict,
) -> dict:
    """Return a fail-closed byte and physical-sequence envelope."""
    unknown = []
    available_host = _nonnegative_integer(host.get("available_host_bytes"))
    gtt_used = _nonnegative_integer(host.get("gtt_used_bytes"))
    measured_gtt_total = _positive_integer(host.get("gtt_total_bytes"))
    if "gtt_total_fresh" in host:
        gtt_total_fresh = host.get("gtt_total_fresh") is True
    else:
        gtt_total_fresh = host.get("fresh") is True and host.get("stale") is not True
    protected = _nonnegative_integer(policy.get("protected_host_bytes"))
    coin_reserved = _nonnegative_integer(policy.get("coin_reserved_bytes"))
    transient = _nonnegative_integer(policy.get("load_transient_bytes"))
    gtt_limit = _positive_integer(policy.get("gtt_limit_bytes"))
    gtt_capacity = (min(measured_gtt_total, gtt_limit)
                    if measured_gtt_total is not None and gtt_total_fresh
                    and gtt_limit is not None else None)
    total_sequences = _positive_integer(policy.get("total_sequences"))
    front_sequences = _positive_integer(policy.get("front_sequences"))
    for name, value in (
        ("available_host_bytes", available_host),
        ("gtt_used_bytes", gtt_used),
        ("gtt_total_bytes", measured_gtt_total if gtt_total_fresh else None),
        ("protected_host_bytes", protected),
        ("coin_reserved_bytes", coin_reserved),
        ("load_transient_bytes", transient),
        ("gtt_limit_bytes", gtt_limit),
        ("total_sequences", total_sequences),
        ("front_sequences", front_sequences),
    ):
        if value is None:
            unknown.append(name)
    if total_sequences is not None and front_sequences is not None \
            and front_sequences >= total_sequences:
        unknown.append("sequence_partition")

    resident_bytes = 0
    resident_ids = set()
    work_models = set()
    for index, model in enumerate(resident_models):
        if type(model) is not dict:
            unknown.append(f"resident_models:{index}")
            continue
        model_id = model.get("model_id", model.get("id"))
        model_bytes = _positive_integer(model.get("model_bytes", model.get("size_bytes")))
        if type(model_id) is not str or not model_id or model_bytes is None:
            unknown.append(f"resident_models:{index}")
            continue
        if model_id not in resident_ids:
            resident_ids.add(model_id)
            resident_bytes += model_bytes
        if model.get("work_model") is True or model.get("workload_class") == "work":
            work_models.add(model_id)

    occupied = set()
    active_bytes = 0
    nonresident_model_bytes = 0
    nonresident_model_ids = set()
    work_occupied = 0
    for index, lease in enumerate(active_leases):
        if type(lease) is not dict:
            unknown.append(f"active_leases:{index}")
            continue
        sequence = lease.get("backend_sequence")
        if type(sequence) is not int or isinstance(sequence, bool) or sequence < 0:
            unknown.append(f"active_leases:{index}:backend_sequence")
        elif sequence in occupied:
            unknown.append(f"active_leases:{index}:duplicate_sequence")
        else:
            occupied.add(sequence)
            if total_sequences is not None and sequence >= total_sequences:
                unknown.append(f"active_leases:{index}:sequence_range")
            if front_sequences is not None and sequence >= front_sequences:
                work_occupied += 1
            if (front_sequences is not None and sequence < front_sequences
                    and lease.get("workload_class") != "front"):
                unknown.append(f"active_leases:{index}:front_violation")
        allocation = _lease_allocation_bytes(lease, policy)
        if allocation is None:
            unknown.append(f"active_leases:{index}:allocation")
        else:
            active_bytes += allocation
        route = lease.get("route", lease.get("request", {}).get("route", {}))
        if type(route) is not dict:
            unknown.append(f"active_leases:{index}:model")
            continue
        loaded = route.get("loaded")
        model_id = route.get("model_id")
        model_bytes = _positive_integer(route.get("model_bytes"))
        if (type(loaded) is not bool or type(model_id) is not str or not model_id
                or model_bytes is None):
            unknown.append(f"active_leases:{index}:model")
        elif loaded and model_id not in resident_ids:
            unknown.append(f"active_leases:{index}:resident_model")
        elif not loaded:
            if model_id not in resident_ids and model_id not in nonresident_model_ids:
                nonresident_model_ids.add(model_id)
                nonresident_model_bytes += model_bytes

    available_work_sequences = 0
    if total_sequences is not None and front_sequences is not None:
        available_work_sequences = max(
            0, total_sequences - front_sequences - work_occupied,
        )
    host_headroom = None
    gtt_headroom = None
    if None not in (available_host, protected, coin_reserved, transient):
        host_headroom = (
            available_host - protected - coin_reserved - transient
            - active_bytes - nonresident_model_bytes
        )
    if None not in (gtt_used, gtt_capacity, transient):
        gtt_headroom = (
            gtt_capacity - gtt_used - transient - active_bytes - nonresident_model_bytes
        )
    maximum_work_models = _positive_integer(policy.get("maximum_work_models"))
    if maximum_work_models is None:
        unknown.append("maximum_work_models")
    safe = (
        not unknown
        and host_headroom is not None and host_headroom >= 0
        and gtt_headroom is not None and gtt_headroom >= 0
        and maximum_work_models is not None
        and len(work_models | nonresident_model_ids) <= maximum_work_models
    )
    return {
        "safe": safe,
        "unknown_facts": unknown,
        "reserved_front_sequences": front_sequences or 0,
        "available_work_sequences": available_work_sequences,
        "occupied_sequences": sorted(occupied),
        "resident_model_bytes": resident_bytes,
        "active_allocation_bytes": active_bytes,
        "nonresident_model_bytes": nonresident_model_bytes,
        "host_headroom_bytes": host_headroom,
        "gtt_capacity_bytes": gtt_capacity,
        "gtt_headroom_bytes": gtt_headroom,
        "resident_work_models": len(work_models),
        "proposed_work_models": len(work_models | nonresident_model_ids),
    }


def effective_priority(
    policy: dict,
    role: str | None,
    execution_profile: str | None,
    authority_profile: str,
    age_seconds: float,
    operator_session: bool = False,
) -> int:
    """Resolve trusted configured bands; age may rise only within its band."""
    if type(operator_session) is not bool:
        raise ValueError("invalid operator session flag")
    values = _validated_scheduling_snapshot(policy)
    if type(role) not in (str, type(None)) or type(execution_profile) not in (str, type(None)):
        raise ValueError("invalid scheduling identity")
    if type(authority_profile) is not str or not authority_profile:
        raise ValueError("invalid scheduling authority profile")
    age = _finite_number(age_seconds, "age_seconds")
    if age < 0:
        raise ValueError("invalid age_seconds")
    bands = values["priority_bands"]
    authority = values["authority_profiles"]
    execution = values["execution_profiles"]
    if authority_profile == authority["sole_survivor"]:
        band = "sole_survivor"
    elif authority_profile == authority["coin"]:
        band = "coin"
    elif operator_session:
        band = "user_driven"
    elif execution_profile == execution["small_health"]:
        band = "small_health"
    elif execution_profile == execution["large_health"]:
        band = "large_health"
    else:
        band = "default"
    base = (bands[band] if band != "default"
            else values["role_priorities"].get(role, values["role_priorities"]["default"]))
    ceilings = {
        "default": bands["large_health"] - 1,
        "large_health": bands["small_health"] - 1,
        "small_health": bands["user_driven"] - 1,
        "user_driven": bands["coin"] - 1,
        "coin": bands["sole_survivor"] - 1,
        "sole_survivor": bands["sole_survivor"] + 99,
    }
    age_points = int(age // values["aging_seconds_per_point"])
    return min(base + age_points, ceilings[band])


def realize_context_tokens(route: dict, parallel_sequences: int) -> dict:
    """Map R2's per-sequence context to the backend total exactly once."""
    if type(route) is not dict or route.get("state") != "admitted":
        raise ValueError("route is not admitted")
    mode = route.get("context_mode")
    if mode is None:
        mode = "fixed"
    if mode not in ("fixed", "shared"):
        raise ValueError(f"route context mode {mode!r} is not fixed or shared")
    parallel = _positive_integer(parallel_sequences)
    context = _positive_integer(route.get("context_tokens_per_sequence"))
    recorded_parallel = _positive_integer(route.get("parallel_sequences"))
    backend_total = _positive_integer(route.get("backend_context_tokens"))
    if (parallel is None or context is None or recorded_parallel != parallel
            or backend_total is None):
        raise ValueError("route has inconsistent context totals")
    if mode == "shared":
        if context > backend_total:
            raise ValueError(
                "shared route per-sequence context exceeds the backend pool",
            )
        return {"context_tokens": context, "ctx_size": backend_total,
                "context_mode": "shared"}
    if backend_total != context * parallel:
        raise ValueError("route has inconsistent context totals")
    return {"context_tokens": context, "ctx_size": backend_total,
            "context_mode": "fixed"}


def reserve_sequence(
    root: Path,
    request: dict,
    inventory: dict,
    clock,
) -> dict:
    """Reserve after fresh R2 validation and persist the release binding."""
    root = Path(root)
    now = _clock_value(clock)
    if type(inventory) is not dict:
        raise ValueError("invalid inference inventory")
    resource_policy = _load_json(root / "config" / "resource-policy.json")
    capacity_policy = _load_capacity_policy(root)
    scheduling_policy = _load_json(root / "state" / "scheduling-policy.json")
    scheduling_values = _validated_scheduling_snapshot(scheduling_policy)
    validated = _validate_sequence_request(request, capacity_policy, scheduling_values)
    # Reconcile abandoned physical ownership before counting occupied slots.
    # This runs outside workload/capacity locks because proxy revocation releases capacity.
    from ecosystem.inference_proxy import reconcile_available_capacity
    reconcile_available_capacity(root, clock)
    with _locked_states(root) as (worker_state, state, save):
        worker_lease = _validate_worker_lease(worker_state, validated)
        worker_request = worker_lease["request"]
        for field in (
            "requirements", "prompt_tokens", "tool_tokens", "max_output_tokens",
            "handoff_tokens",
        ):
            if field in worker_request:
                validated[field] = _durable_copy(worker_request[field])
        normalized_route = models.validate_route(
            validated["route"], inventory, resource_policy, worker_request,
        )
        if normalized_route.get("state") != "admitted":
            return {
                "state": "deferred",
                "reasons": normalized_route.get("exclusion_reasons", ["route:invalid"]),
            }
        validated["route"] = _durable_copy(normalized_route)
        _validate_worker_allocation(worker_request, normalized_route)
        realized = realize_context_tokens(
            normalized_route, normalized_route["parallel_sequences"],
        )
        enqueued_monotonic = _finite_number(
            worker_lease.get("acquired_monotonic"), "worker enqueue time",
        )
        if enqueued_monotonic > now:
            raise ValueError("worker enqueue time is in the future")
        validated["operator_session"] = _worker_is_operator(root, worker_lease)
        priority = effective_priority(
            scheduling_policy, validated.get("role"), validated.get("execution_profile"),
            validated["authority_profile"], now - enqueued_monotonic,
            operator_session=validated["operator_session"],
        )
        prior = _lease_for_request(state, validated["request_id"])
        if prior is not None:
            if (_stable_sequence_request(prior["request"])
                    != _stable_sequence_request(validated)):
                raise ValueError("inference request identity mismatch")
            if prior["state"] != "ready_for_revalidation":
                return _public_lease(prior)
        retrying = prior is not None
        active = [
            lease for lease in state["leases"].values()
            if lease["state"] in {"starting", "active", "preemption_requested",
                                  "release_requested"}
        ]
        lease_id = (prior["lease_id"] if retrying
                    else _lease_id(validated["request_id"], state["generation"]))
        workload_class = validated["workload_class"]
        if workload_class == "front":
            # Front sequences are a guaranteed reserve, not a ceiling. Prefer the
            # reserve, then spill into any idle general sequence.
            available = (
                _available_sequences(active, 0, capacity_policy["front_sequences"])
                + _available_sequences(active, capacity_policy["front_sequences"],
                                       capacity_policy["total_sequences"])
            )
        else:
            available = _available_sequences(
                active, capacity_policy["front_sequences"],
                capacity_policy["total_sequences"],
            )
        sequence = available[0] if available else None
        preempted = None
        lease_state = "starting"
        if sequence is None:
            victims = [
                lease for lease in active
                if (workload_class == "front" or lease["workload_class"] != "front")
                and _lease_priority(scheduling_policy, lease, now) < priority
                and lease["state"] not in {"preemption_requested", "release_requested"}
            ]
            if not victims:
                return {"state": "deferred", "reasons": ["sequence_unavailable"]}
            victim = min(
                victims,
                key=lambda item: (_lease_priority(scheduling_policy, item, now),
                                  item["acquired_monotonic"]),
            )
            sequence = victim["backend_sequence"]
            preempted = victim["lease_id"]
            lease_state = "waiting_for_preemption"
        if preempted is None:
            model_active = [
                lease for lease in active
                if lease.get("model_id") == normalized_route["model_id"]
            ]
            held = sum(
                1 for lease in model_active
                if (lease.get("workload_class") == "front")
                == (workload_class == "front")
            )
            limit = _model_slot_limit(
                workload_class, capacity_policy, normalized_route,
                _model_work_slots(root, normalized_route["model_id"]),
            )
            if (len(model_active) >= normalized_route["parallel_sequences"]
                    or held >= limit):
                victims = [item for item in model_active
                           if _lease_priority(scheduling_policy, item, now) < priority
                           and item["state"] not in {"preemption_requested", "release_requested"}
                           and (len(model_active) >= normalized_route["parallel_sequences"]
                                or (item.get("workload_class") == "front") == (workload_class == "front"))]
                if not victims:
                    return {"state": "deferred", "reasons": ["model_sequence_unavailable"]}
                victim = min(victims, key=lambda item: _lease_priority(scheduling_policy, item, now))
                preempted = victim["lease_id"]
                lease_state = "waiting_for_preemption"
        lease = {
            "lease_id": lease_id,
            "generation": state["generation"],
            "state": lease_state,
            "class": workload_class,
            "workload_class": workload_class,
            "proxy_identity": validated["proxy_identity"],
            "model_id": validated["route"]["model_id"],
            "context_tokens": realized["context_tokens"],
            "context_mode": normalized_route["context_mode"],
            "backend_context_tokens": normalized_route["backend_context_tokens"],
            "parallel_sequences": normalized_route["parallel_sequences"],
            "max_output_tokens": validated["route"]["max_output_tokens"],
            "backend_sequence": sequence,
            "expires_monotonic": now + capacity_policy["lease_seconds"],
            "preemption_method": validated["preemption_method"],
            "release_observer_identity": capacity_policy["release_observer_identity"],
            "allocation_generation": state["generation"],
            "expected_release_binding": None,
            "priority": priority,
            "enqueued_monotonic": enqueued_monotonic,
            "request": validated,
            "acquired_monotonic": prior["acquired_monotonic"] if retrying else now,
            "observed_release": None,
        }
        if preempted is not None:
            lease["preempts_lease_id"] = preempted
            lease["preempted_sequences"] = [victim["backend_sequence"]]
        if normalized_route["context_mode"] == "shared":
            lease["shared_context_accounting"] = (
                "backend_enforced_pending_precise_claims"
            )
        displaced = [victim] if preempted is not None else []
        proposed_active = [item for item in active if item["lease_id"] != preempted]
        proposed_active.append(lease)
        envelope = resource_envelope(
            inventory.get("host", {}), inventory.get("resident_models", []),
            proposed_active, capacity_policy,
        )
        if not envelope["safe"] and not envelope["unknown_facts"]:
            # Reclaim every necessary lower-priority allocation before declaring
            # a real byte shortfall; suspending one blocker may not be enough.
            candidates = sorted(
                [item for item in active if item not in displaced
                 and item["state"] not in {"preemption_requested", "release_requested"}
                 and _lease_priority(scheduling_policy, item, now) < priority],
                key=lambda item: _lease_priority(scheduling_policy, item, now))
            for blocker in candidates:
                displaced.append(blocker)
                proposed_active = [item for item in proposed_active if item["lease_id"] != blocker["lease_id"]]
                envelope = resource_envelope(inventory.get("host", {}), inventory.get("resident_models", []),
                                             proposed_active, capacity_policy)
                if envelope["safe"]:
                    break
        if not envelope["safe"]:
            return {"state": "deferred", "reasons": envelope["unknown_facts"] or [
                "physical_capacity",
            ]}
        if displaced:
            lease["state"] = "waiting_for_preemption"
            lease["preempts_lease_ids"] = [item["lease_id"] for item in displaced]
            lease["preempts_lease_id"] = displaced[0]["lease_id"]
            lease["preempted_sequences"] = [item["backend_sequence"] for item in displaced]
            for blocker in displaced:
                blocker["preemption_prior_state"] = blocker["state"]
                blocker["state"] = "preemption_requested"
                blocker["preemption_requested_monotonic"] = now
            lease["backend_sequence"] = None
        if lease["backend_sequence"] is not None:
            lease["expected_release_binding"] = _release_binding(lease)
        state["leases"][lease_id] = lease
        save()
        return _public_lease(lease)


def release_sequence(root: Path, lease_id: str, observed: dict, clock) -> dict:
    """Apply an R4/R7-trusted, fresh attestation to the matching allocation."""
    root = Path(root)
    now = _clock_value(clock)
    if type(observed) is not dict:
        raise ValueError("invalid sequence observation")
    capacity_policy = _load_capacity_policy(root)
    scheduling_policy = _load_json(root / "state" / "scheduling-policy.json")
    _validated_scheduling_snapshot(scheduling_policy)
    with _locked_states(root) as (_worker_state, state, save):
        lease = state["leases"].get(lease_id)
        if lease is None:
            raise ValueError("unknown inference lease")
        if lease["state"] == "released":
            return _public_lease(lease)
        expected = lease["backend_sequence"]
        matching = _valid_release_attestation(
            lease, observed, expected, now, capacity_policy,
        )
        if not matching:
            lease["state"] = "release_requested"
            lease["release_requested_monotonic"] = now
            save()
            return _public_lease(lease)
        lease["state"] = "released"
        lease["observed_release"] = {
            **_durable_copy(observed),
            "accepted_monotonic": now,
        }
        lease["released_monotonic"] = now
        _activate_waiter(
            state, expected, now, scheduling_policy, capacity_policy,
        )
        save()
        return _public_lease(lease)



def reacquire_sequence(root: Path, lease_id: str, inventory: dict, clock) -> dict:
    """Revalidate a live logical run's relinquished physical allocation."""
    from ecosystem.inference_proxy import _validate_registered_process
    root = Path(root)
    with _locked_states(root) as (workers, state, save):
        lease = state["leases"].get(lease_id)
        if lease is None:
            raise ValueError("unknown inference allocation")
        request = _durable_copy(lease["request"])
        worker = _validate_worker_lease(workers, request)
        _validate_registered_process(worker)
        if lease["state"] == "released":
            lease["state"] = "ready_for_revalidation"
            lease["backend_sequence"] = None
            for field in ("expected_release_binding", "observed_release", "released_monotonic"):
                lease.pop(field, None)
            save()
    # Queue and allocation use the original identity, priority and context claims.
    # Do not hold state locks during fresh routing or physical reclamation.
    return reserve_sequence(root, request, inventory, clock)


def withdraw_unissued_sequence(root: Path, lease_id: str, clock) -> dict:
    """Release a stopped acquisition attempt which could never call the backend."""
    from ecosystem import inference_proxy
    root = Path(root)
    with inference_proxy._locked_states(root) as (workers, state, proxy_state, _save):
        lease = state["leases"].get(lease_id)
        if lease is None:
            raise ValueError("unknown inference acquisition")
        if lease["state"] == "released":
            return _public_lease(lease)
        if lease_id in proxy_state["credentials"]:
            raise ValueError("issued inference must close through the proxy")
        worker = workers["leases"][lease["request"]["worker_lease_id"]]
        if inference_proxy._bound_process_ended(worker.get("process", {})) is not True:
            raise ValueError("acquisition process has not ended")
        sequence = lease.get("backend_sequence")
        lease.update(state="released", released_monotonic=_clock_value(clock),
                     withdrawal_reason="stopped_before_credential_issuance")
        if sequence is not None:
            scheduling = _load_json(root / "state/scheduling-policy.json")
            _activate_waiter(state, sequence, _clock_value(clock), scheduling, _load_capacity_policy(root))
        for victim_id in lease.get("preempts_lease_ids", [lease.get("preempts_lease_id")]):
            victim = state["leases"].get(victim_id)
            others = [item for item in state["leases"].values()
                      if item["state"] in {"waiting_for_preemption", "ready_for_revalidation"}
                      and victim_id in item.get("preempts_lease_ids", [item.get("preempts_lease_id")])]
            if victim and victim["state"] == "preemption_requested" and not others:
                victim["state"] = victim.pop("preemption_prior_state", "starting")
                victim.pop("preemption_requested_monotonic", None)
        state["generation"] += 1
        _atomic_write(root / "state/inference-capacity.json", state)
        return _public_lease(lease)


def scheduling_snapshot(root: Path) -> dict:
    """Load and validate the published scheduling snapshot; return its values."""
    document = _load_json(Path(root) / "state" / "scheduling-policy.json")
    return _validated_scheduling_snapshot(document)


def _validated_scheduling_snapshot(snapshot: dict) -> dict:
    if type(snapshot) is not dict or set(snapshot) != SNAPSHOT_FIELDS:
        raise ValueError("invalid accepted scheduling policy snapshot")
    values = snapshot.get("values")
    try:
        canonical = json.dumps(
            values, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("invalid accepted scheduling policy snapshot") from error
    shape = (
        snapshot.get("schema_version") == 1
        and type(snapshot.get("digest")) is str
        and hashlib.sha256(canonical).hexdigest() == snapshot["digest"]
        and type(snapshot.get("activated_at")) is str and bool(snapshot["activated_at"])
        and type(snapshot.get("source_path")) is str and bool(snapshot["source_path"])
    )
    if not shape:
        raise ValueError("invalid accepted scheduling policy snapshot")
    _validate_scheduling_values(values)
    return values


def _validate_scheduling_values(values: object) -> None:
    expected = {
        "version", "priority_bands", "authority_profiles", "execution_profiles",
        "role_priorities", "aging_seconds_per_point",
    }
    if type(values) is not dict or set(values) != expected or values.get("version") != 1:
        raise ValueError("invalid accepted scheduling policy snapshot")
    bands = values.get("priority_bands")
    if type(bands) is not dict or "user_driven" not in bands:
        raise ValueError("scheduling values missing user_driven band")
    if set(bands) != {
        "sole_survivor", "coin", "user_driven", "small_health", "large_health",
        "default",
    }:
        raise ValueError("invalid accepted scheduling policy snapshot")
    ordered = [bands.get(name) for name in (
        "sole_survivor", "coin", "small_health", "large_health", "default",
    )]
    if ordered[:4] != [1000, 900, 800, 700]:
        raise ValueError("priority bands out of order")
    if not _positive_integer(bands["user_driven"]) \
            or not 800 < bands["user_driven"] < 900:
        raise ValueError(
            "user_driven band must sit strictly between small_health and coin")
    if not _positive_integer(ordered[4]) or ordered[4] >= 700:
        raise ValueError("invalid default priority band")
    authority = values.get("authority_profiles")
    execution = values.get("execution_profiles")
    role_priorities = values.get("role_priorities")
    if (type(authority) is not dict or set(authority) != {"sole_survivor", "coin"}
            or type(execution) is not dict
            or set(execution) != {"small_health", "large_health"}
            or any(type(value) is not str or not value
                   for value in (*authority.values(), *execution.values()))
            or len(set((*authority.values(), *execution.values()))) != 4
            or type(role_priorities) is not dict or "default" not in role_priorities
            or any(type(name) is not str or not name or not _positive_integer(priority)
                   or priority >= 700 for name, priority in role_priorities.items())
            or _finite_number(values.get("aging_seconds_per_point"), "aging") <= 0):
        raise ValueError("invalid accepted scheduling policy snapshot")


def _validate_sequence_request(request: object, policy: dict, scheduling: dict) -> dict:
    required = {
        "request_id", "worker_lease_id", "workload_class", "proxy_identity", "route",
        "owner_identity", "worker_request_id", "role", "execution_profile",
        "authority_profile", "preemption_method",
    }
    if type(request) is not dict or not required <= request.keys():
        raise ValueError("invalid inference sequence request")
    durable = _durable_copy(request)
    durable.pop("operator_session", None)  # Only authoritative worker/session state grants this band.
    for field in ("request_id", "worker_lease_id", "worker_request_id",
                  "owner_identity", "proxy_identity", "authority_profile",
                  "preemption_method"):
        if type(durable[field]) is not str or not durable[field]:
            raise ValueError(f"invalid inference {field}")
    if durable["workload_class"] not in {"front", "repair", "work", "monitor"}:
        raise ValueError("invalid inference workload class")
    is_coin_front = (
        durable["workload_class"] == "front"
        and durable["authority_profile"] == scheduling["authority_profiles"]["coin"]
    )
    if durable["workload_class"] == "front" and not is_coin_front:
        raise ValueError("front inference is reserved for Coin authority")
    if durable["proxy_identity"] == policy["front_proxy_identity"] and not is_coin_front:
        raise ValueError("front proxy is reserved for Coin")
    expected_proxy = (policy["front_proxy_identity"] if is_coin_front
                      else policy["work_proxy_identity"])
    if durable["proxy_identity"] != expected_proxy:
        raise ValueError("inference proxy identity mismatch")
    return durable


def _validate_worker_lease(worker_state: dict, request: dict) -> dict:
    if worker_state.get("mode") != "open":
        raise ValueError("worker admission is closed")
    lease = worker_state.get("leases", {}).get(request["worker_lease_id"])
    if lease is None or lease.get("state") not in {"starting", "active"}:
        raise ValueError("worker lease is not admitted")
    worker_request = lease.get("request", {})
    if worker_request.get("workload_class") != request["workload_class"]:
        raise ValueError("worker and inference workload classes differ")
    if worker_request.get("request_id") != request["worker_request_id"]:
        raise ValueError("worker and inference request identities differ")
    if worker_request.get("owner_identity") != request["owner_identity"]:
        raise ValueError("worker and inference owner identities differ")
    if worker_request.get("role") != request.get("role"):
        raise ValueError("worker and inference roles differ")
    if worker_request.get("authority_profile") != request["authority_profile"]:
        raise ValueError("worker and inference authority profiles differ")
    if worker_request.get("execution_profile") != request.get("execution_profile"):
        raise ValueError("worker and inference execution profiles differ")
    if worker_request.get("stop_method") != request["preemption_method"]:
        raise ValueError("worker and inference preemption methods differ")
    return lease


def _worker_is_operator(root: Path, worker: dict) -> bool:
    request = worker.get("request", {})
    session_id = request.get("operator_session_id")
    if session_id is None:
        return False
    path = Path(root) / "state/operator-sessions.json"
    if not path.exists():
        return False
    session = _load_json(path).get("sessions", {}).get(session_id, {})
    if session.get("state") != "active" or worker.get("process") is None:
        return False
    try:
        bound = worker["process"]
        bound_stat = (Path("/proc") / str(bound["pid"]) / "stat").read_text().rsplit(")", 1)[1].split()
        if int(bound_stat[19]) != bound["process_start_ticks"] or bound_stat[0] == "Z":
            return False
        process_matches = session.get("process") == bound
        if not process_matches:
            parent = session["process"]
            parent_stat = (Path("/proc") / str(parent["pid"]) / "stat").read_text().rsplit(")", 1)[1].split()
            child_stat = (Path("/proc") / str(worker["process"]["pid"]) / "stat").read_text().rsplit(")", 1)[1].split()
            process_matches = (parent_stat[0] != "Z"
                               and int(parent_stat[19]) == parent["process_start_ticks"]
                               and int(child_stat[1]) == parent["pid"]
                               and int(child_stat[19]) == worker["process"]["process_start_ticks"])
    except (OSError, KeyError, ValueError, IndexError):
        return False
    return (process_matches
            and session.get("request", {}).get("owner_identity") == request.get("owner_identity"))


def _validate_worker_allocation(worker_request: dict, route: dict) -> None:
    if worker_request.get("model_id") != route.get("model_id"):
        raise ValueError("worker and inference model identities differ")
    if worker_request.get("context_tokens") != route.get("context_tokens_per_sequence"):
        raise ValueError("worker and inference context allocations differ")
    if worker_request.get("max_output_tokens") != route.get("max_output_tokens"):
        raise ValueError("worker and inference output allocations differ")


def _lease_allocation_bytes(lease: dict, policy: dict) -> int | None:
    if "allocation_bytes" in lease:
        return _nonnegative_integer(lease["allocation_bytes"])
    route = lease.get("route", lease.get("request", {}).get("route", {}))
    if type(route) is not dict:
        return None
    kv_bytes = _nonnegative_integer(route.get("incremental_kv_bytes",
                                             route.get("kv_estimate_bytes")))
    token_bytes = _positive_integer(policy.get("non_kv_bytes_per_token", 4))
    token_fields = ("prompt_tokens", "tool_tokens", "max_output_tokens", "handoff_tokens")
    tokens = [_nonnegative_integer(route.get(field)) for field in token_fields]
    if kv_bytes is None or token_bytes is None or any(value is None for value in tokens):
        return None
    return kv_bytes + sum(tokens) * token_bytes


def _available_sequences(active: list[dict], start: int, stop: int) -> list[int]:
    occupied = {lease["backend_sequence"] for lease in active
                if lease.get("backend_sequence") is not None}
    return [sequence for sequence in range(start, stop) if sequence not in occupied]


def _lease_priority(scheduling_policy: dict, lease: dict, now: float) -> int:
    enqueued = _finite_number(lease.get("enqueued_monotonic"), "lease enqueue time")
    if enqueued > now:
        raise ValueError("lease enqueue time is in the future")
    request = lease.get("request", {})
    return effective_priority(
        scheduling_policy, request.get("role"), request.get("execution_profile"),
        request.get("authority_profile"), now - enqueued,
        operator_session=request.get("operator_session", False),
    )


def _activate_waiter(
    state: dict,
    backend_sequence: int,
    now: float,
    scheduling_policy: dict,
    capacity_policy: dict,
) -> None:
    front_sequence = backend_sequence < capacity_policy["front_sequences"]
    coin_authority = _validated_scheduling_snapshot(
        scheduling_policy,
    )["authority_profiles"]["coin"]

    def compatible(lease: dict) -> bool:
        request = lease.get("request", {})
        if backend_sequence in lease.get("preempted_sequences", []):
            return True
        if front_sequence:
            return (
                lease.get("workload_class") == "front"
                and lease.get("proxy_identity") == capacity_policy["front_proxy_identity"]
                and request.get("authority_profile") == coin_authority
            )
        return (
            lease.get("workload_class") != "front"
            and lease.get("proxy_identity") == capacity_policy["work_proxy_identity"]
        )

    waiting = [
        lease for lease in state["leases"].values()
        if lease["state"] == "waiting_for_preemption"
        and compatible(lease)
        and all(state["leases"].get(victim_id, {}).get("state") == "released"
                for victim_id in lease.get("preempts_lease_ids", []))
    ]
    if not waiting:
        return
    selected = max(
        waiting,
        key=lambda item: (
            _lease_priority(scheduling_policy, item, now),
            -item["enqueued_monotonic"],
        ),
    )
    selected["priority"] = _lease_priority(scheduling_policy, selected, now)
    selected["backend_sequence"] = None
    selected["state"] = "ready_for_revalidation"
    selected["revalidation_requested_monotonic"] = now


def _load_capacity_policy(root: Path) -> dict:
    """Resolve slot counts from the accepted cfg and the remaining capacity fields."""
    root = Path(root)
    document = _load_json(root / "config" / "resource-policy.json")
    policy = document.get("inference_capacity")
    if type(policy) is dict:
        for key in ("front_sequences", "total_sequences"):
            if key in policy:
                raise ValueError(
                    f"resource policy must not pin {key}; slot counts come "
                    "from inference.cfg",
                )
    slots = inference_policy.load_inference_policy(
        root / "config" / "inference.cfg",
    )
    policy = dict(policy) if type(policy) is dict else {}
    policy["front_sequences"] = slots["front_slots"]
    policy["total_sequences"] = slots["front_slots"] + slots["work_slots"]
    return _validated_capacity_policy(
        {**document, "inference_capacity": policy},
    )


def _model_work_slots(root: Path, model_id: str) -> int:
    return inference_policy.load_inference_policy(
        Path(root) / "config" / "inference.cfg", model_id=model_id,
    )["work_slots"]


def _model_slot_limit(workload_class: str, capacity_policy: dict,
                      route: dict, work_slots: int) -> int:
    observed = route["parallel_sequences"]
    if workload_class == "front":
        return observed
    return min(work_slots, observed)


def _validated_capacity_policy(document: dict) -> dict:
    policy = document.get("inference_capacity")
    required = {
        "front_sequences", "total_sequences", "protected_host_bytes",
        "coin_reserved_bytes", "load_transient_bytes", "gtt_limit_bytes",
        "maximum_work_models",
        "front_proxy_identity", "work_proxy_identity", "lease_seconds",
        "release_observer_identity", "release_observation_maximum_age_seconds",
        "clock_domain_id",
    }
    if type(policy) is not dict or not required <= policy.keys():
        raise ValueError("invalid inference capacity policy")
    numeric = required - {
        "front_proxy_identity", "work_proxy_identity", "release_observer_identity",
        "clock_domain_id",
    }
    if any(_positive_integer(policy[field]) is None for field in numeric):
        raise ValueError("invalid inference capacity policy")
    if (policy["front_sequences"] >= policy["total_sequences"]
            or any(type(policy[field]) is not str or not policy[field]
                   for field in ("front_proxy_identity", "work_proxy_identity",
                                 "release_observer_identity", "clock_domain_id"))
            or policy["front_proxy_identity"] == policy["work_proxy_identity"]):
        raise ValueError("invalid inference capacity policy")
    return policy


def _valid_release_attestation(
    lease: dict,
    observed: dict,
    backend_sequence: int | None,
    now: float,
    policy: dict,
) -> bool:
    required = {
        "schema_version", "binding", "kind", "observer_identity",
        "observer_generation", "observed_monotonic", "clock_domain_id",
        "evidence_id",
    }
    if type(observed) is not dict or set(observed) != required:
        return False
    try:
        observed_at = _finite_number(
            observed.get("observed_monotonic"), "release observation time",
        )
    except ValueError:
        return False
    kind = observed.get("kind")
    sequence_state_is_valid = kind in {
        "sequence_end", "reconciled_absent", "never_requested",
    }
    return (
        backend_sequence is not None
        and observed.get("schema_version") == 1
        and observed.get("binding") == lease.get("expected_release_binding")
        and sequence_state_is_valid
        and lease.get("release_observer_identity") == policy["release_observer_identity"]
        and observed.get("observer_identity") == lease["release_observer_identity"]
        and _positive_integer(observed.get("observer_generation")) is not None
        and observed.get("clock_domain_id") == policy["clock_domain_id"]
        and type(observed.get("evidence_id")) is str
        and bool(observed["evidence_id"])
        and observed_at <= now
        and now - observed_at <= policy["release_observation_maximum_age_seconds"]
    )


def _public_lease(lease: dict) -> dict:
    return _durable_copy(lease)


def _stable_sequence_request(request: dict) -> dict:
    return {key: value for key, value in request.items() if key != "route"}


def _release_binding(lease: dict) -> dict:
    request = lease["request"]
    return {
        "lease_id": lease["lease_id"],
        "allocation_generation": lease["allocation_generation"],
        "request_id": request["request_id"],
        "worker_lease_id": request["worker_lease_id"],
        "owner_identity": request["owner_identity"],
        "proxy_identity": lease["proxy_identity"],
        "backend_sequence": lease["backend_sequence"],
    }


@contextmanager
def _locked_states(root: Path):
    state_directory = root / "state"
    state_directory.mkdir(parents=True, exist_ok=True)
    workload_lock = state_directory / "workload-control.lock"
    inference_lock = state_directory / "inference-capacity.lock"
    with workload_lock.open("a+b") as workload_stream:
        fcntl.flock(workload_stream.fileno(), fcntl.LOCK_EX)
        with inference_lock.open("a+b") as inference_stream:
            fcntl.flock(inference_stream.fileno(), fcntl.LOCK_EX)
            worker_state = _load_json(state_directory / "workload-control.json")
            path = state_directory / "inference-capacity.json"
            state = (_load_json(path) if path.exists() else {
                "version": STATE_VERSION, "generation": 1, "leases": {},
            })
            if (state.get("version") != STATE_VERSION
                    or type(state.get("generation")) is not int
                    or type(state.get("leases")) is not dict
                    or any(lease.get("state") not in LEASE_STATES
                           for lease in state["leases"].values())):
                raise ValueError("invalid inference capacity state")
            def save():
                state["generation"] += 1
                _atomic_write(path, state)

            try:
                yield worker_state, state, save
            finally:
                fcntl.flock(inference_stream.fileno(), fcntl.LOCK_UN)
        fcntl.flock(workload_stream.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {path}") from error
    if type(value) is not dict:
        raise ValueError(f"invalid JSON object {path}")
    return value


def _lease_for_request(state: dict, request_id: str) -> dict | None:
    return next((lease for lease in state["leases"].values()
                 if lease["request"]["request_id"] == request_id), None)


def _lease_id(request_id: str, generation: int) -> str:
    digest = hashlib.sha256(f"{request_id}\0{generation}".encode("utf-8")).hexdigest()
    return f"inference-{generation}-{digest[:20]}"


def _durable_copy(value):
    try:
        return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError("value is not durable JSON") from error


def _positive_integer(value) -> int | None:
    return value if type(value) is int and value > 0 else None


def _nonnegative_integer(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _finite_number(value, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"invalid {label}")
    return float(value)


def _clock_value(clock) -> float:
    try:
        return _finite_number(clock(), "inference clock")
    except TypeError as error:
        raise ValueError("invalid inference clock") from error
