"""Durable, model-neutral transitions between llama.cpp parallel profiles.

The capacity state is the acquisition fence. A profile change may start only
after every allocation for that model has released physical occupancy. The
transition remains fenced after an error so a later invocation can resume it.
"""

from __future__ import annotations

import json
import shlex
import sys
import time
import uuid
from pathlib import Path

from ecosystem import inference_capacity, models, resource_control


class ProfileDeferred(RuntimeError):
    """An expected temporary condition; keep or avoid the transition fence."""


def resource_mode(root: Path) -> str:
    """Treat missing or malformed resource state as unsafe for profile reload."""
    try:
        state = json.loads((Path(root) / "state/resource-control.json").read_text())
        return state["mode"] if state["mode"] in {
            "normal", "pressure", "emergency"} else "unavailable"
    except (OSError, ValueError, KeyError, TypeError):
        return "unavailable"


def plan_parallel_profile(profile: dict, ready_demand: int,
                          work_slot_ceiling: int, qualified_parallel_ceiling: int,
                          kv_headroom_bytes: int,
                          estimated_kv_bytes_per_token: int) -> dict:
    """Choose a demand-sized pool within conservative incremental KV headroom.

    `ready_demand` includes running logical work and queued work for this model.
    The estimate is an admission bound, not a claim that Lemonade will load it.
    One idle slot is retained until ordinary residency reclamation unloads it.
    """
    for name, value, minimum in (
            ("ready_demand", ready_demand, 0),
            ("work_slot_ceiling", work_slot_ceiling, 1),
            ("qualified_parallel_ceiling", qualified_parallel_ceiling, 1),
            ("kv_headroom_bytes", kv_headroom_bytes, 0),
            ("estimated_kv_bytes_per_token", estimated_kv_bytes_per_token, 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an exact integer >= {minimum}")
    if (type(profile) is not dict or type(profile.get("model_id")) is not str
            or not profile["model_id"]):
        raise ValueError("invalid current backend profile identity")
    current = profile.get("parallel_sequences")
    context = profile.get("context_tokens_per_sequence")
    if (type(current) is not int or current <= 0
            or type(context) is not int or context <= 0):
        raise ValueError("invalid current backend profile")
    per_slot_estimate = context * estimated_kv_bytes_per_token
    incremental_slots = kv_headroom_bytes // per_slot_estimate
    feasible_ceiling = min(work_slot_ceiling, qualified_parallel_ceiling,
                           current + incremental_slots)
    target = min(max(1, ready_demand), feasible_ceiling)
    return {"model_id": profile.get("model_id"),
            "current_parallel_sequences": current,
            "target_parallel_sequences": target,
            "ready_demand": ready_demand,
            "estimated_incremental_slot_bytes": per_slot_estimate,
            "kv_limited_ceiling": feasible_ceiling,
            "state": "change" if target != current else "unchanged"}


def observed_profile(record: dict) -> dict:
    """Read the exact loaded profile without guessing a model-specific recipe."""
    if (type(record) is not dict or not resource_control.model_is_live(record)
            or record.get("is_busy") is not False):
        raise ValueError("model must be live and observed idle")
    options = record.get("recipe_options")
    if type(options) is not dict:
        raise ValueError("resident model has no recipe options")
    parallel = resource_control._observed_parallel_requests(record)
    context = options.get("ctx_size")
    args = options.get("llamacpp_args")
    if (parallel is None or type(context) is not int or context <= 0
            or context % parallel or type(args) is not str or not args
            or options.get("merge_args") is not True
            or type(record.get("pinned")) is not bool):
        raise ValueError("resident profile is not an exact context allocation")
    return {"model_id": record["model_name"],
            "parallel_sequences": parallel,
            "context_tokens_per_sequence": context // parallel,
            "backend_context_tokens": context,
            "llamacpp_args": args,
            "pinned": record["pinned"],
            "recipe_options": dict(options)}


def profile_payload(profile: dict, parallel_sequences: int) -> dict:
    """Retain every observed recipe option except the two pool-size fields."""
    if type(parallel_sequences) is not int or parallel_sequences <= 0:
        raise ValueError("parallel_sequences must be a positive exact integer")
    if (type(profile) is not dict or type(profile.get("model_id")) is not str
            or not profile["model_id"] or type(profile.get("pinned")) is not bool
            or type(profile.get("recipe_options")) is not dict
            or type(profile.get("llamacpp_args")) is not str):
        raise ValueError("invalid original backend profile")
    context = profile.get("context_tokens_per_sequence")
    if (type(context) is not int or context <= 0
            or context > sys.maxsize // parallel_sequences):
        raise ValueError("backend context pool is invalid or too large")
    tokens = shlex.split(profile["llamacpp_args"])
    positions = []
    for index, token in enumerate(tokens):
        if token == "--parallel":
            if index + 1 >= len(tokens):
                raise ValueError("parallel argument has no value")
            positions.append((index, index + 1))
        elif token.startswith("--parallel="):
            positions.append((index, index))
    if len(positions) != 1:
        raise ValueError("recipe must have exactly one parallel argument")
    if resource_control._observed_parallel_requests(
            {"recipe_options": profile["recipe_options"]}) \
            != profile.get("parallel_sequences"):
        raise ValueError("original recipe and parallel count disagree")
    flag, value = positions[0]
    if flag == value:
        tokens[flag] = f"--parallel={parallel_sequences}"
    else:
        tokens[value] = str(parallel_sequences)
    return {**profile["recipe_options"],
            "model_name": profile["model_id"],
            "pinned": profile["pinned"],
            "ctx_size": context * parallel_sequences,
            "llamacpp_args": shlex.join(tokens),
            "save_options": False}


def begin_transition(root: Path, profile: dict, target: int,
                     backend_process: dict) -> dict:
    """Atomically fence new model allocations after physical occupancy drains."""
    model_id = profile["model_id"]
    if type(model_id) is not str or not model_id:
        raise ValueError("invalid model identity")
    if (type(backend_process) is not dict
            or type(backend_process.get("pid")) is not int
            or backend_process["pid"] <= 0
            or type(backend_process.get("process_start_ticks")) is not int
            or backend_process["process_start_ticks"] <= 0
            or type(backend_process.get("boot_id")) is not str
            or not backend_process["boot_id"]):
        raise ValueError("backend process identity is not exact")
    profile_payload(profile, target)
    with inference_capacity._locked_states(Path(root)) as (_workers, state, save):
        existing = state.get("backend_profile_transition")
        if existing is not None:
            if (type(existing) is not dict
                    or existing.get("model_id") != model_id
                    or existing.get("target_parallel_sequences") != target):
                raise RuntimeError("another backend profile transition is fenced")
            return dict(existing)
        occupied = [lease.get("lease_id") for lease in state["leases"].values()
                    if lease.get("state") not in {
                        "released", "ready_for_revalidation"}
                    and lease.get("model_id") in {model_id, None}]
        if occupied:
            raise ProfileDeferred("model inference allocations have not parked")
        transition = {"id": uuid.uuid4().hex, "model_id": model_id,
                      "target_parallel_sequences": target,
                      "original_profile": profile,
                      "backend_process": dict(backend_process)}
        state["backend_profile_transition"] = transition
        save()
        return dict(transition)


def mark_rollback(root: Path, transition: dict, reason: str) -> None:
    """Persist rollback intent before attempting to recover the old profile."""
    with inference_capacity._locked_states(Path(root)) as (_workers, state, save):
        current = state.get("backend_profile_transition")
        if (type(current) is not dict
                or current.get("id") != transition.get("id")):
            raise RuntimeError("backend profile transition identity changed")
        current["recovery"] = "original"
        current["failure_reason"] = str(reason)[:512]
        save()


def finish_transition(root: Path, transition: dict,
                      *, outcome: str = "reconfigured") -> None:
    """Remove only the fence for the exact successfully verified transition."""
    with inference_capacity._locked_states(Path(root)) as (_workers, state, save):
        current = state.get("backend_profile_transition")
        if (type(current) is not dict
                or current.get("id") != transition.get("id")):
            raise RuntimeError("backend profile transition identity changed")
        state.pop("backend_profile_transition")
        if outcome == "reconfigured":
            state["backend_profile_last_change"] = {
                "model_id": current["model_id"],
                "from_parallel_sequences": current["original_profile"]["parallel_sequences"],
                "to_parallel_sequences": current["target_parallel_sequences"],
                "completed_monotonic": time.monotonic(),
                "boot_id": current["backend_process"]["boot_id"],
            }
        elif outcome == "rolled_back":
            state["backend_profile_last_failure"] = {
                "model_id": current["model_id"],
                "target_parallel_sequences": current["target_parallel_sequences"],
                "reason": current.get("failure_reason", "target_unverified"),
                "completed_monotonic": time.monotonic(),
                "boot_id": current["backend_process"]["boot_id"],
            }
        else:
            raise ValueError("invalid backend profile transition outcome")
        state["backend_profile_dispatch_pending"] = {
            "transition_id": current["id"], "model_id": current["model_id"]}
        save()


def require_qualified_allocation(inventory: dict, profile: dict) -> None:
    """Prove that the backend's effective per-request pool matches the recipe."""
    if type(inventory) is not dict or type(inventory.get("models")) is not list:
        raise RuntimeError("model inventory is unavailable")
    matches = [item for item in inventory.get("models", [])
               if type(item) is dict and item.get("id") == profile["model_id"]]
    if len(matches) != 1:
        raise RuntimeError("resident model identity is not unique")
    model = matches[0]
    if (model.get("loaded") is not True
            or model.get("residency_verified") is not True
            or model.get("fresh") is not True
            or model.get("context_mode") != "fixed"
            or model.get("parallel_sequences") != profile["parallel_sequences"]
            or model.get("loaded_context") != profile["backend_context_tokens"]
            or model.get("context_tokens_per_sequence")
            != profile["context_tokens_per_sequence"]):
        raise RuntimeError("observed backend allocation disagrees with profile")


def _profile_matches(profile: dict, payload: dict,
                     parallel: int, context: int, pinned: bool) -> bool:
    return (profile["parallel_sequences"] == parallel
            and profile["context_tokens_per_sequence"] == context
            and profile["pinned"] == pinned
            and shlex.split(profile["llamacpp_args"])
            == shlex.split(payload["llamacpp_args"]))


def _restore_original(root: Path, transition: dict, *, health, request,
                      inventory, observe_mode, process_identity,
                      process_ended) -> dict:
    """Recover service after a target load failed; keep the fence until proved."""
    model_id = transition["model_id"]
    original = transition["original_profile"]
    old_process = transition["backend_process"]
    payload = profile_payload(original, original["parallel_sequences"])
    current = resource_control.model_residency_status(health(), model_id)
    if current["state"] == "live":
        if current["record"].get("is_busy") is not False:
            raise ProfileDeferred("backend is busy during rollback")
        current_process = process_identity(current["record"].get("pid"))
        if current_process is None:
            raise RuntimeError("rollback backend identity is unavailable")
        current_profile = observed_profile(current["record"])
        if _profile_matches(current_profile, payload,
                            original["parallel_sequences"],
                            original["context_tokens_per_sequence"],
                            original["pinned"]):
            if (current_process != old_process
                    and process_ended(old_process) is not True):
                raise RuntimeError("old backend termination is unproved; fenced")
            require_qualified_allocation(inventory(root), current_profile)
            finish_transition(root, transition, outcome="rolled_back")
            return {"state": "rolled_back", "profile": current_profile,
                    "reason": transition.get("failure_reason")}
        if observe_mode(root) != "normal":
            raise ProfileDeferred("resource mode changed; rollback stays fenced")
        request("/v1/unload", {"model_name": model_id},
                timeout=resource_control._seconds(
                    "inference", "model_stop_deadline_seconds"))
        current = resource_control.model_residency_status(health(), model_id)
        if current["state"] != "not_loaded":
            raise RuntimeError("rollback unload was not verified; fenced")
        if process_ended(current_process) is not True:
            raise ProfileDeferred("rollback backend process has not ended; fenced")
    if current["state"] != "not_loaded":
        raise RuntimeError("rollback model state is unavailable; fenced")
    if process_ended(old_process) is not True:
        raise ProfileDeferred("old backend process has not ended; fenced")
    if observe_mode(root) != "normal":
        raise ProfileDeferred("resource mode changed; rollback stays fenced")
    request("/v1/load", payload,
            timeout=resource_control._seconds(
                "inference", "model_start_deadline_seconds"))
    after = resource_control.model_residency_status(health(), model_id)
    if after["state"] != "live":
        raise RuntimeError("rollback load was not verified; fenced")
    restored = observed_profile(after["record"])
    new_process = process_identity(after["record"].get("pid"))
    if (not _profile_matches(restored, payload,
                             original["parallel_sequences"],
                             original["context_tokens_per_sequence"],
                             original["pinned"])
            or new_process is None or new_process == old_process):
        raise RuntimeError("rollback profile or incarnation is unverified; fenced")
    require_qualified_allocation(inventory(root), restored)
    finish_transition(root, transition, outcome="rolled_back")
    return {"state": "rolled_back", "profile": restored,
            "reason": transition.get("failure_reason")}


def reconfigure(root: Path, model_id: str, parallel_sequences: int,
                *, health=None, request=None, inventory=None,
                observe_mode=None, process_identity=None,
                process_ended=None) -> dict:
    """Resume or perform a fenced unload/load, leaving failure fenced for repair.

    The caller chooses the target from qualified demand and capacity. This
    primitive does not invent a slot count or interrupt an occupied sequence.
    """
    root = Path(root)
    health = health or resource_control.lemonade_health
    request = request or resource_control._lemonade_request
    inventory = inventory or models.snapshot
    observe_mode = observe_mode or resource_mode
    if process_identity is None or process_ended is None:
        from ecosystem import inference_proxy
        process_identity = process_identity or inference_proxy._backend_process_identity
        process_ended = process_ended or inference_proxy._bound_process_ended
    if type(model_id) is not str or not model_id:
        raise ValueError("invalid model identity")
    if type(parallel_sequences) is not int or parallel_sequences <= 0:
        raise ValueError("invalid target parallel count")
    with models.realization_lock(root):
        if observe_mode(root) != "normal":
            raise ProfileDeferred("resource mode does not permit backend reload")
        before = resource_control.model_residency_status(health(), model_id)
        with inference_capacity._locked_states(root) as (_workers, state, _save):
            existing = state.get("backend_profile_transition")
        if existing is None:
            if before["state"] != "live":
                raise ProfileDeferred("model is not live for a new profile transition")
            if before["record"].get("is_busy") is not False:
                raise ProfileDeferred("model is not idle for profile transition")
            original = observed_profile(before["record"])
            require_qualified_allocation(inventory(root), original)
            if original["parallel_sequences"] == parallel_sequences:
                return {"state": "unchanged", "profile": original}
            old_process = process_identity(before["record"].get("pid"))
            transition = begin_transition(
                root, original, parallel_sequences, old_process)
        else:
            if (type(existing) is not dict or existing.get("model_id") != model_id
                    or existing.get("target_parallel_sequences") != parallel_sequences):
                raise RuntimeError("another backend profile transition is fenced")
            transition = existing
            original = transition["original_profile"]
        old_process = transition.get("backend_process")
        if (type(old_process) is not dict
                or type(old_process.get("pid")) is not int
                or old_process["pid"] <= 0
                or type(old_process.get("process_start_ticks")) is not int
                or old_process["process_start_ticks"] <= 0
                or type(old_process.get("boot_id")) is not str
                or not old_process["boot_id"]):
            raise RuntimeError("transition lacks exact old backend identity")
        if transition.get("recovery") == "original":
            return _restore_original(
                root, transition, health=health, request=request,
                inventory=inventory, observe_mode=observe_mode,
                process_identity=process_identity,
                process_ended=process_ended)
        target_payload = profile_payload(original, parallel_sequences)
        current = resource_control.model_residency_status(health(), model_id)
        if current["state"] == "live":
            if current["record"].get("is_busy") is not False:
                raise ProfileDeferred("model became busy during profile transition")
            current_profile = observed_profile(current["record"])
            current_process = process_identity(current["record"].get("pid"))
            if (current_profile["parallel_sequences"] == parallel_sequences
                    and current_profile["context_tokens_per_sequence"]
                    == original["context_tokens_per_sequence"]
                    and current_profile["pinned"] == original["pinned"]
                    and shlex.split(current_profile["llamacpp_args"])
                    == shlex.split(target_payload["llamacpp_args"])):
                if (current_process is None or current_process == old_process
                        or process_ended(old_process) is not True):
                    raise RuntimeError("old backend termination is unproved; fenced")
                require_qualified_allocation(inventory(root), current_profile)
                finish_transition(root, transition)
                return {"state": "reconfigured", "profile": current_profile}
            if current_profile != original:
                raise RuntimeError("resident profile changed outside the transition")
            if current_process != old_process:
                raise RuntimeError("resident backend incarnation changed; fenced")
            if observe_mode(root) != "normal":
                raise ProfileDeferred("resource mode changed; transition stays fenced")
            request("/v1/unload", {"model_name": model_id},
                    timeout=resource_control._seconds(
                        "inference", "model_stop_deadline_seconds"))
            current = resource_control.model_residency_status(health(), model_id)
        if current["state"] != "not_loaded":
            raise RuntimeError("model unload was not verified; transition stays fenced")
        if process_ended(old_process) is not True:
            raise ProfileDeferred("old backend process has not ended; fenced")
        if observe_mode(root) != "normal":
            raise ProfileDeferred("resource mode changed; transition stays fenced")
        try:
            request("/v1/load", target_payload,
                    timeout=resource_control._seconds(
                        "inference", "model_start_deadline_seconds"))
            after = resource_control.model_residency_status(health(), model_id)
            if after["state"] != "live":
                raise RuntimeError("model reload was not verified")
            verified = observed_profile(after["record"])
            new_process = process_identity(after["record"].get("pid"))
            if (not _profile_matches(
                    verified, target_payload, parallel_sequences,
                    original["context_tokens_per_sequence"], original["pinned"])
                    or new_process is None or new_process == old_process):
                raise RuntimeError("reloaded profile or incarnation is unverified")
            require_qualified_allocation(inventory(root), verified)
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            mark_rollback(root, transition, reason)
            return _restore_original(
                root, {**transition, "recovery": "original",
                       "failure_reason": reason},
                health=health, request=request, inventory=inventory,
                observe_mode=observe_mode, process_identity=process_identity,
                process_ended=process_ended)
        finish_transition(root, transition)
        return {"state": "reconfigured", "profile": verified}
