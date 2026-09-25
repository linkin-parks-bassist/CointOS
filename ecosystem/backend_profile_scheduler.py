"""Translate durable work demand into qualified backend-profile transitions."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from ecosystem import (backend_profile_policy, backend_profiles, cli, dispatch,
                       inference_capacity, inference_policy, models,
                       resource_control)


def capacity_state(root: Path) -> dict:
    path = Path(root) / "state/inference-capacity.json"
    if not path.exists():
        return {"version": 1, "leases": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict or type(value.get("leases")) is not dict:
        raise ValueError("invalid inference capacity state")
    return value


def shrink_dwell_remaining(last_change: object, model_id: str,
                           boot_id: str, now: float,
                           minimum_seconds: int) -> float:
    """Delay only another shrink; real new demand may grow immediately."""
    if type(minimum_seconds) is not int or minimum_seconds < 0:
        raise ValueError("invalid backend profile dwell policy")
    if (type(last_change) is not dict
            or last_change.get("model_id") != model_id
            or last_change.get("boot_id") != boot_id):
        return 0.0
    completed = last_change.get("completed_monotonic")
    if (type(completed) not in (int, float) or not math.isfinite(completed)
            or completed < 0 or now < completed):
        return float(minimum_seconds)
    return max(0.0, minimum_seconds - (now - completed))


def assess_profiles(root: Path, jobs: list[dict], inventory: dict,
                    health: dict, qualifications: dict, capacity: dict,
                    resource_policy: dict, *, now: float,
                    boot_id: str, route_for_job) -> dict:
    """Choose at most one idle work-model transition without backend mutation."""
    if (type(inventory) is not dict or type(inventory.get("models")) is not list
            or type(inventory.get("control_model")) is not str
            or not inventory["control_model"]):
        return {"state": "wait", "reason": "inventory_unavailable"}
    envelope = inventory.get("resource_envelope")
    if (type(envelope) is not dict or envelope.get("verified") is not True
            or envelope.get("fresh") is not True):
        return {"state": "wait", "reason": "resource_envelope_unavailable"}
    headroom = envelope.get("maximum_kv_bytes")
    if type(resource_policy) is not dict:
        return {"state": "wait", "reason": "profile_policy_unavailable"}
    dynamic = resource_policy.get("dynamic_models", {})
    if type(dynamic) is not dict:
        return {"state": "wait", "reason": "profile_policy_unavailable"}
    estimate = dynamic.get("estimated_kv_bytes_per_token")
    dwell = dynamic.get("profile_minimum_dwell_seconds", 300)
    failure_cooldown = dynamic.get("profile_failure_cooldown_seconds", 3600)
    minimum_lanes = dynamic.get("profile_minimum_parallel_sequences", 1)
    if (type(headroom) is not int or headroom < 0
            or type(estimate) is not int or estimate <= 0
            or type(dwell) is not int or dwell < 0
            or type(failure_cooldown) is not int or failure_cooldown < 0
            or type(minimum_lanes) is not int or minimum_lanes < 1):
        return {"state": "wait", "reason": "profile_policy_unavailable"}
    candidates = sorted(
        (item for item in inventory["models"]
         if type(item) is dict and item.get("loaded") is True
         and item.get("id") != inventory["control_model"]),
        key=lambda item: str(item.get("id")))
    deferred = None
    shrink_candidate = None
    for model in candidates:
        model_id = model.get("id")
        if type(model_id) is not str or not model_id:
            continue
        resident = resource_control.model_residency_status(health, model_id)
        if resident["state"] != "live":
            continue
        if resident["record"].get("is_busy") is not False:
            continue
        if resident["record"].get("pinned") is not False:
            continue
        try:
            profile = backend_profiles.observed_profile(resident["record"])
            backend_profiles.require_qualified_allocation(inventory, profile)
            qualified = backend_profile_policy.qualified_ceiling(
                qualifications, profile, model)
        except (KeyError, RuntimeError, ValueError):
            continue
        if qualified is None:
            continue
        try:
            work_ceiling = inference_policy.load_inference_policy(
                Path(root) / "config/inference.cfg", model_id=model_id)["work_slots"]
            demand = max(backend_profile_policy.model_demand(jobs, model_id, route_for_job),
                         minimum_lanes)
            plan = backend_profiles.plan_parallel_profile(
                profile, demand, work_ceiling, qualified, headroom, estimate)
        except (OSError, KeyError, RuntimeError, ValueError):
            continue
        if plan["state"] != "change":
            continue
        failure = capacity.get("backend_profile_last_failure")
        if (type(failure) is dict
                and failure.get("model_id") == model_id
                and failure.get("target_parallel_sequences")
                == plan["target_parallel_sequences"]
                and failure.get("boot_id") == boot_id):
            failed_at = failure.get("completed_monotonic")
            if (type(failed_at) in (int, float) and math.isfinite(failed_at)
                    and 0 <= now - failed_at < failure_cooldown):
                if deferred is None:
                    deferred = {"state": "wait", "reason": "profile_failure_cooldown",
                                "model_id": model_id,
                                "remaining_seconds": failure_cooldown - (now - failed_at),
                                "plan": plan}
                continue
        if plan["target_parallel_sequences"] < profile["parallel_sequences"]:
            remaining = shrink_dwell_remaining(
                capacity.get("backend_profile_last_change"), model_id,
                boot_id, now, dwell)
            if remaining > 0:
                if deferred is None:
                    deferred = {"state": "wait", "reason": "shrink_dwell",
                                "model_id": model_id,
                                "remaining_seconds": remaining, "plan": plan}
                continue
        candidate = {"state": "change", "model_id": model_id,
                     "target_parallel_sequences": plan["target_parallel_sequences"],
                     "plan": plan}
        if plan["target_parallel_sequences"] > profile["parallel_sequences"]:
            return candidate
        if shrink_candidate is None:
            shrink_candidate = candidate
    return shrink_candidate or deferred or {"state": "unchanged"}


def plan_once(root: Path = cli.ROOT, *, observe_inventory=None,
              observe_health=None, get_jobs=None,
              route_for_job=None) -> dict:
    """Inspect one reconciliation decision without changing backend state."""
    root = Path(root)
    if backend_profiles.resource_mode(root) != "normal":
        return {"state": "wait", "reason": "resource_mode"}
    if (root / "state/PAUSED").exists():
        return {"state": "wait", "reason": "ecosystem_paused"}
    capacity = capacity_state(root)
    transition = capacity.get("backend_profile_transition")
    if transition is not None:
        if (type(transition) is not dict
                or type(transition.get("model_id")) is not str
                or type(transition.get("target_parallel_sequences")) is not int):
            raise ValueError("invalid fenced backend profile transition")
        return {"state": "recovery_required",
                "model_id": transition["model_id"],
                "target_parallel_sequences": transition[
                    "target_parallel_sequences"],
                "recovery": transition.get("recovery", "target")}
    pending = capacity.get("backend_profile_dispatch_pending")
    if pending is not None:
        if (type(pending) is not dict
                or type(pending.get("transition_id")) is not str
                or not pending["transition_id"]):
            raise ValueError("invalid backend profile dispatch wakeup")
        return {"state": "dispatch_wakeup_required",
                "model_id": pending.get("model_id")}
    observe_inventory = observe_inventory or models.snapshot
    observe_health = observe_health or resource_control.lemonade_health
    get_jobs = get_jobs or (lambda: dispatch.actionable_jobs(root))
    inventory = observe_inventory(root)
    health = observe_health()
    jobs = get_jobs()
    qualifications = backend_profile_policy.load_qualifications(root)
    resource_policy = json.loads((root / "config/resource-policy.json").read_text())
    route_for_job = route_for_job or (lambda job: models.route(job, inventory))
    return assess_profiles(
        root, jobs, inventory, health, qualifications, capacity,
        resource_policy, now=time.monotonic(),
        boot_id=resource_control.boot_id(), route_for_job=route_for_job)


def reconcile_once(root: Path = cli.ROOT, *, observe_inventory=None,
                   observe_health=None, get_jobs=None, reconfigure=None,
                   route_for_job=None) -> dict:
    """Resume a fence first, otherwise apply one qualified demand change."""
    root = Path(root)
    reconfigure = reconfigure or backend_profiles.reconfigure
    def wake_pending_dispatch() -> None:
        capacity = capacity_state(root)
        pending = capacity.get("backend_profile_dispatch_pending")
        if pending is None:
            return
        cli.wake_dispatch(root)
        with inference_capacity._locked_states(root) as (
                _workers, state, save):
            current = state.get("backend_profile_dispatch_pending")
            if current == pending:
                state.pop("backend_profile_dispatch_pending")
                save()

    def apply_transition(model_id: str, target: int) -> dict:
        result = reconfigure(root, model_id, target)
        if result.get("state") in {"reconfigured", "rolled_back"}:
            # New physical capacity can admit a queued sibling immediately;
            # the ordinary ecosystem fallback scan is five minutes apart.
            wake_pending_dispatch()
        return result

    decision = plan_once(
        root, observe_inventory=observe_inventory,
        observe_health=observe_health, get_jobs=get_jobs,
        route_for_job=route_for_job)
    if decision["state"] == "dispatch_wakeup_required":
        wake_pending_dispatch()
        return {"state": "dispatch_woken", "model_id": decision["model_id"]}
    if decision["state"] == "recovery_required":
        try:
            return apply_transition(decision["model_id"],
                                    decision["target_parallel_sequences"])
        except backend_profiles.ProfileDeferred as error:
            return {"state": "wait", "reason": str(error),
                    "model_id": decision["model_id"], "fenced": True}
    if decision["state"] != "change":
        return decision
    try:
        return apply_transition(decision["model_id"],
                                decision["target_parallel_sequences"])
    except backend_profiles.ProfileDeferred as error:
        return {"state": "wait", "reason": str(error),
                "model_id": decision["model_id"], "fenced": False}
