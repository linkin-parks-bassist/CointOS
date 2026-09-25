"""Atomic worker admission, drain, and smoke exclusion."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from survival import records


STATE_VERSION = 1
WORKLOAD_CLASSES = frozenset(("front", "repair", "work", "monitor", "smoke"))
STOP_METHODS = frozenset(("process_group", "hosted"))
REQUIRED_REQUEST_FIELDS = frozenset((
    "workload_class", "model_id", "context_tokens", "max_output_tokens",
    "deadline_monotonic", "owner_identity", "job_id", "agent_generation",
    "caller_handle", "request_id", "stop_method",
))


def acquire_worker(root: Path, request: dict, clock: Callable[[], float]) -> dict:
    validated = _validate_request(request)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        prior = _lease_for_request(state, validated["request_id"])
        if prior is not None:
            if prior["request"] != validated:
                raise ValueError("worker request identity mismatch")
            return prior.copy()
        if state["mode"] != "open" and not _emergency_survivor_admitted(
                root, state, validated):
            reason = "drain" if state["mode"] == "draining" else state["mode"]
            return {"state": "deferred", "reasons": [reason]}
        lease_id = _lease_id(validated["request_id"], state["generation"])
        lease = {
            "lease_id": lease_id,
            "generation": state["generation"],
            "state": "starting",
            "request": validated,
            "acquired_monotonic": now,
            "process": None,
            "observation": None,
            "checkpoint_required": False,
        }
        state["leases"][lease_id] = lease
        save()
        return lease.copy()


def _emergency_survivor_admitted(root: Path, gate: dict, request: dict) -> bool:
    """Keep the drain closed except for its recorded emergency repair job."""
    if (gate.get("mode") != "draining"
            or gate.get("owner") != {"owner_identity": "resource-control",
                                     "covered_paths": []}
            or request.get("authority_profile") != "sole_survivor"
            or request.get("role") != "sole_survivor"
            or request.get("workload_class") != "repair"):
        return False
    root = Path(root)
    try:
        resource = json.loads((root / "state/resource-control.json").read_text(
            encoding="utf-8"))
        if (resource.get("mode") != "emergency"
                or resource.get("emergency_phase") not in {"survivor_ready", "active"}
                or resource.get("sole_survivor_job") != request["job_id"]):
            return False
        job = json.loads((root / "state/jobs" / f"{request['job_id']}.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return (job.get("id") == request["job_id"]
            and job.get("source") == f"resource-emergency:{resource.get('incident_id')}"
            and job.get("authority_profile") == "sole_survivor"
            and job.get("role") == "sole_survivor"
            and job.get("model") == request["model_id"]
            and job.get("owner_identity") == request["owner_identity"])


def find_worker_lease_by_request(root: Path, request_id: str) -> dict | None:
    """Read one durable lease without creating or altering admission state."""
    if type(request_id) is not str or not request_id:
        raise ValueError("worker request identity is required")
    with _locked_state(root) as (state, _save):
        matches = [lease for lease in state["leases"].values()
                   if lease.get("request", {}).get("request_id") == request_id]
        if len(matches) > 1:
            raise ValueError("duplicate worker leases for one request identity")
        return json.loads(json.dumps(matches[0])) if matches else None


def register_process(
    root: Path,
    lease_id: str,
    pid: int,
    process_start_ticks: int,
    clock: Callable[[], float],
) -> dict:
    if type(pid) is not int or pid <= 0:
        raise ValueError("invalid process pid")
    if type(process_start_ticks) is not int or process_start_ticks < 0:
        raise ValueError("invalid process start identity")
    now = _now(clock)
    with _locked_state(root) as (state, save):
        lease = _lease(state, lease_id)
        identity = {"pid": pid, "process_start_ticks": process_start_ticks}
        if lease["process"] is not None:
            if lease["process"] != identity:
                raise ValueError("worker process identity mismatch")
            return lease.copy()
        if lease["request"]["stop_method"] != "process_group":
            raise ValueError("hosted worker has no local process identity")
        if lease["state"] != "starting":
            raise ValueError("worker process registration is no longer admissible")
        lease["process"] = identity
        lease["state"] = "active"
        lease["registered_monotonic"] = now
        save()
        return lease.copy()


def begin_drain(root: Path, owner: dict, clock: Callable[[], float]) -> dict:
    validated_owner = _validate_owner(owner)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        if state["mode"] in {"draining", "smoke"}:
            if state["owner"] != validated_owner:
                raise ValueError("drain owner mismatch")
        else:
            state["mode"] = "draining"
            state["generation"] += 1
            state["owner"] = validated_owner
            state["drain_started_monotonic"] = now
            for lease in state["leases"].values():
                if lease["state"] not in {"quiescent"}:
                    lease["checkpoint_required"] = (
                        lease["request"]["stop_method"] == "process_group"
                    )
                    lease["wrapup_requested_monotonic"] = now
            save()
        result = _public_state(state)
        result["active_leases"] = [
            lease.copy() for lease in state["leases"].values()
            if lease["state"] != "quiescent"
        ]
        return result


def observe_workers(
    root: Path,
    observed_workers: list[dict],
    clock: Callable[[], float],
) -> dict:
    observations = _validate_observations(observed_workers)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        _apply_observations(state, observations, now)
        save()
        return _public_state(state)


def enter_smoke(
    root: Path,
    owner: dict,
    clock: Callable[[], float],
    observed_workers: list[dict],
) -> dict:
    validated_owner = _validate_owner(owner)
    observations = _validate_observations(observed_workers)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        if state["mode"] == "smoke" and state["owner"] == validated_owner:
            return _public_state(state)
        if state["mode"] != "draining" or state["owner"] != validated_owner:
            raise ValueError("smoke owner mismatch")
        _apply_observations(state, observations, now)
        reasons = _smoke_blockers(state)
        if reasons:
            save()
            return {"state": "deferred", "mode": "draining", "reasons": reasons}
        state["mode"] = "smoke"
        state["smoke_started_monotonic"] = now
        save()
        result = _public_state(state)
        result["state"] = "admitted"
        return result


def end_smoke(
    root: Path,
    owner: dict,
    outcome: dict,
    clock: Callable[[], float],
) -> dict:
    validated_owner = _validate_owner(owner)
    validated_outcome = _validate_outcome(outcome)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        prior = state.get("last_smoke")
        if state["mode"] != "smoke":
            if prior is None or prior["owner"] != validated_owner:
                raise ValueError("smoke owner mismatch")
            if prior["outcome"] != validated_outcome:
                raise ValueError("smoke outcome mismatch")
            return _public_state(state)
        if state["owner"] != validated_owner:
            raise ValueError("smoke owner mismatch")
        state["last_smoke"] = {
            "owner": validated_owner,
            "outcome": validated_outcome,
            "ended_monotonic": now,
        }
        if _outcome_passed(validated_outcome):
            state["mode"] = "open"
            state["owner"] = None
        else:
            state["mode"] = "draining"
        save()
        return _public_state(state)


def release_worker(
    root: Path,
    lease_id: str,
    outcome: dict,
    clock: Callable[[], float],
) -> dict:
    validated_outcome = _validate_outcome(outcome)
    now = _now(clock)
    with _locked_state(root) as (state, save):
        lease = _lease(state, lease_id)
        if "release_outcome" in lease:
            if lease["release_outcome"] != validated_outcome:
                raise ValueError("worker release outcome mismatch")
            return lease.copy()
        lease["release_outcome"] = validated_outcome
        lease["release_requested_monotonic"] = now
        if lease["state"] == "observed_stopped":
            lease["state"] = "quiescent"
            lease["quiescent_monotonic"] = now
        elif lease["state"] != "quiescent":
            lease["state"] = "release_requested"
        save()
        return lease.copy()


def admission_reasons(
    resource_state: dict,
    lifecycle_state: dict,
    work_state: dict,
) -> list[str]:
    if any(type(state) is not dict for state in (
        resource_state, lifecycle_state, work_state,
    )):
        raise ValueError("invalid admission state")
    reasons = []
    resource_mode = resource_state.get("mode", "unknown")
    if resource_mode != "normal":
        reasons.append(f"resource:{resource_mode}")
    paused = lifecycle_state.get("paused")
    if paused is not None and type(paused) is not bool:
        raise ValueError("invalid lifecycle pause")
    if paused:
        reasons.append("lifecycle:paused")
    lifecycle_mode = lifecycle_state.get("phase", lifecycle_state.get("mode"))
    if lifecycle_mode is not None:
        if type(lifecycle_mode) is not str or not lifecycle_mode:
            raise ValueError("invalid lifecycle mode")
        if lifecycle_mode not in {"normal", "completed"}:
            reason = f"lifecycle:{lifecycle_mode}"
            if reason not in reasons:
                reasons.append(reason)
    elif paused is None:
        reasons.append("lifecycle:unknown")
    for restriction in ("operator", "deployment"):
        reason = _restriction_reason(
            restriction, resource_state, lifecycle_state, work_state)
        if reason is not None:
            reasons.append(reason)
    if work_state.get("mode") in {"draining", "smoke"}:
        reasons.append(f"work:{work_state['mode']}")
    return reasons


def worker_lease_health(root: Path) -> dict:
    state = _read_state(Path(root) / "state" / "workload-control.json")
    counts: dict[str, int] = {}
    for lease in state["leases"].values():
        counts[lease["state"]] = counts.get(lease["state"], 0) + 1
    return {
        "mode": state["mode"],
        "generation": state["generation"],
        "lease_counts": counts,
    }


def _restriction_reason(name: str, *states: dict) -> str | None:
    for state in states:
        for key in (f"{name}_paused", f"{name}_pause"):
            if key in state:
                value = state[key]
                if type(value) is not bool:
                    raise ValueError(f"invalid {name} pause")
                if value:
                    return f"{name}:paused"
        mode_key = f"{name}_mode"
        if mode_key in state:
            mode = state[mode_key]
            if type(mode) is not str or not mode:
                raise ValueError(f"invalid {name} mode")
            if mode != "normal":
                return f"{name}:{mode}"
        nested = state.get(name)
        if nested is not None:
            if type(nested) is not dict:
                raise ValueError(f"invalid {name} state")
            paused = nested.get("paused")
            if paused is not None and type(paused) is not bool:
                raise ValueError(f"invalid {name} pause")
            if paused:
                return f"{name}:paused"
            mode = nested.get("mode")
            if mode is not None:
                if type(mode) is not str or not mode:
                    raise ValueError(f"invalid {name} mode")
                if mode != "normal":
                    return f"{name}:{mode}"
    return None


@contextmanager
def _locked_state(root: Path):
    state_directory = Path(root) / "state"
    state_directory.mkdir(parents=True, exist_ok=True)
    state_path = state_directory / "workload-control.json"
    lock_path = state_directory / "workload-control.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _read_state(state_path)
        dirty = False

        def save():
            nonlocal dirty
            dirty = True

        yield state, save
        if dirty:
            records.atomic_json(state_path, state)


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {
            "schema_version": STATE_VERSION,
            "mode": "open",
            "generation": 0,
            "owner": None,
            "leases": {},
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid workload control state") from error
    if (
        type(value) is not dict
        or value.get("schema_version") != STATE_VERSION
        or value.get("mode") not in {"open", "draining", "smoke"}
        or type(value.get("generation")) is not int
        or value["generation"] < 0
        or type(value.get("leases")) is not dict
    ):
        raise ValueError("invalid workload control state")
    return value


def _validate_request(request: dict) -> dict:
    if type(request) is not dict or not REQUIRED_REQUEST_FIELDS <= request.keys():
        raise ValueError("invalid worker request")
    if request["workload_class"] not in WORKLOAD_CLASSES:
        raise ValueError("invalid worker workload class")
    for field in ("model_id", "owner_identity", "job_id", "caller_handle", "request_id"):
        if type(request[field]) is not str or not request[field]:
            raise ValueError(f"invalid worker {field}")
    for field in ("context_tokens", "max_output_tokens"):
        if type(request[field]) is not int or request[field] <= 0:
            raise ValueError(f"invalid worker {field}")
    if type(request["agent_generation"]) is not int or request["agent_generation"] < 0:
        raise ValueError("invalid worker agent_generation")
    if request["deadline_monotonic"] is not None:
        _number(request["deadline_monotonic"], "worker deadline")
    if request["stop_method"] not in STOP_METHODS:
        raise ValueError("invalid worker stop_method")
    if "write_paths" in request and (
        type(request["write_paths"]) is not list
        or any(type(path) is not str or not path for path in request["write_paths"])
    ):
        raise ValueError("invalid worker write_paths")
    try:
        json.dumps(request)
    except (TypeError, ValueError) as error:
        raise ValueError("worker request is not durable JSON") from error
    return json.loads(json.dumps(request, sort_keys=True))


def _validate_owner(owner: dict) -> dict:
    if type(owner) is not dict:
        raise ValueError("invalid smoke owner")
    identity = owner.get("owner_identity")
    if type(identity) is not str or not identity:
        raise ValueError("invalid smoke owner")
    covered = owner.get("covered_paths", [])
    if type(covered) is not list or any(type(path) is not str or not path for path in covered):
        raise ValueError("invalid smoke covered paths")
    try:
        return json.loads(json.dumps(owner, sort_keys=True))
    except (TypeError, ValueError) as error:
        raise ValueError("smoke owner is not durable JSON") from error


def _validate_outcome(outcome: dict) -> dict:
    if type(outcome) is not dict or not outcome:
        raise ValueError("invalid outcome")
    try:
        return json.loads(json.dumps(outcome, sort_keys=True))
    except (TypeError, ValueError) as error:
        raise ValueError("outcome is not durable JSON") from error


def _validate_observations(observations: list[dict]) -> list[dict]:
    if type(observations) is not list or any(type(item) is not dict for item in observations):
        raise ValueError("invalid worker observations")
    seen = set()
    durable = []
    for item in observations:
        lease_id = item.get("lease_id")
        if type(lease_id) is not str or not lease_id or lease_id in seen:
            raise ValueError("invalid worker observation identity")
        seen.add(lease_id)
        if "never_spawned" in item and type(item["never_spawned"]) is not bool:
            raise ValueError("invalid worker never_spawned attestation")
        if ("managed_clients_stopped" in item
                and type(item["managed_clients_stopped"]) is not bool):
            raise ValueError("invalid managed client stop attestation")
        if item.get("managed_clients_stopped") is True and not (
                item.get("process_group_alive") is False
                and item.get("backend_request_active") is False
                and item.get("inference_lease_active") is False
                and item.get("checkpoint_observed") is True):
            raise ValueError("incomplete managed client stop attestation")
        if "reaped_spawn" in item:
            reaped = item["reaped_spawn"]
            if (
                type(reaped) is not dict
                or type(reaped.get("pid")) is not int or reaped["pid"] <= 0
                or (
                    reaped.get("process_start_ticks") is not None
                    and (
                        type(reaped["process_start_ticks"]) is not int
                        or reaped["process_start_ticks"] < 0
                    )
                )
                or (
                    reaped.get("returncode") is not None
                    and type(reaped["returncode"]) is not int
                )
                or reaped.get("process_group_alive") is not False
            ):
                raise ValueError("invalid worker reaped_spawn attestation")
        try:
            durable.append(json.loads(json.dumps(item, sort_keys=True)))
        except (TypeError, ValueError) as error:
            raise ValueError("worker observation is not durable JSON") from error
    return durable


def _apply_observations(state: dict, observations: list[dict], now: float) -> None:
    for observation in observations:
        lease = _lease(state, observation["lease_id"])
        request = lease["request"]
        lease["observation"] = {**observation, "observed_monotonic": now}
        if request["stop_method"] == "hosted":
            if observation.get("caller_handle") != request["caller_handle"]:
                lease["state"] = "dead_unreconciled"
            elif observation.get(
                "writer_active", observation.get("writer")) is False:
                if "release_outcome" in lease:
                    lease["state"] = "quiescent"
                    lease["quiescent_monotonic"] = now
                else:
                    lease["state"] = "observed_stopped"
            else:
                lease["state"] = "active"
            continue
        process = lease.get("process")
        if _attested_stop(observation):
            if process is not None:
                lease["state"] = "dead_unreconciled"
            elif "release_outcome" in lease:
                lease["state"] = "quiescent"
                lease["quiescent_monotonic"] = now
            else:
                lease["state"] = "observed_stopped"
            continue
        if process is None:
            continue
        if (
            observation.get("pid") != process["pid"]
            or observation.get("process_start_ticks") != process["process_start_ticks"]
        ):
            lease["state"] = "dead_unreconciled"
            continue
        process_active = observation.get(
            "process_group_alive", observation.get("process_alive")) is not False
        backend_active = observation.get(
            "backend_request_active", observation.get("inference_requests_active")) is not False
        inference_active = observation.get("inference_lease_active") is not False
        checkpoint_missing = (
            lease.get("checkpoint_required")
            and observation.get(
                "checkpoint_observed", observation.get("checkpoint")) is not True
        )
        if not process_active and not backend_active and not inference_active and not checkpoint_missing:
            if "release_outcome" in lease:
                lease["state"] = "quiescent"
                lease["quiescent_monotonic"] = now
            else:
                lease["state"] = "observed_stopped"
        elif not process_active:
            lease["state"] = "dead_unreconciled"
        else:
            lease["state"] = "active"


def _smoke_blockers(state: dict) -> list[str]:
    reasons = []
    for lease_id, lease in state["leases"].items():
        if lease["state"] == "quiescent":
            continue
        observation = lease.get("observation") or {}
        prefix = f"lease:{lease_id}"
        if lease["state"] in {"starting", "dead_unreconciled", "release_requested"}:
            reasons.append(f"{prefix}:{lease['state']}")
        if lease["state"] == "observed_stopped":
            reasons.append(f"{prefix}:terminal_outcome_missing")
        if lease["request"]["stop_method"] == "hosted":
            if _hosted_writer_blocks(state["owner"], lease["request"], observation):
                reasons.append(f"{prefix}:hosted_writer_active")
            continue
        if observation.get(
            "process_group_alive", observation.get("process_alive")) is not False:
            reasons.append(f"{prefix}:process_group_active")
        if observation.get(
            "backend_request_active", observation.get("inference_requests_active")) is not False:
            reasons.append(f"{prefix}:backend_request_active")
        if observation.get("inference_lease_active") is not False:
            reasons.append(f"{prefix}:inference_lease_active")
        if (
            lease.get("checkpoint_required")
            and not _attested_stop(observation)
            and observation.get(
                "checkpoint_observed", observation.get("checkpoint")) is not True
        ):
            reasons.append(f"{prefix}:checkpoint_missing")
    return reasons


def _attested_stop(observation: dict) -> bool:
    return (observation.get("never_spawned") is True
            or observation.get("managed_clients_stopped") is True
            or "reaped_spawn" in observation)


def _hosted_writer_blocks(owner: dict | None, request: dict, observation: dict) -> bool:
    covered_paths = [] if owner is None else owner.get("covered_paths", [])
    write_paths = observation.get(
        "write_paths", observation.get("paths", request.get("write_paths", [])))
    covered_writer = any(
        _paths_overlap(path, covered)
        for path in write_paths
        for covered in covered_paths
    )
    writer_active = observation.get("writer_active", observation.get("writer"))
    return covered_writer and writer_active is not False


def _paths_overlap(first: str, second: str) -> bool:
    first_parts = Path(first).parts
    second_parts = Path(second).parts
    shorter = min(len(first_parts), len(second_parts))
    return first_parts[:shorter] == second_parts[:shorter]


def _lease_for_request(state: dict, request_id: str) -> dict | None:
    for lease in state["leases"].values():
        if lease["request"]["request_id"] == request_id:
            return lease
    return None


def _lease(state: dict, lease_id: str) -> dict:
    if type(lease_id) is not str or lease_id not in state["leases"]:
        raise ValueError("unknown worker lease")
    return state["leases"][lease_id]


def _lease_id(request_id: str, generation: int) -> str:
    identity = f"{request_id}\0{generation}".encode("utf-8")
    return f"lease-{generation}-{hashlib.sha256(identity).hexdigest()[:20]}"


def _now(clock: Callable[[], float]) -> float:
    try:
        value = clock()
    except TypeError as error:
        raise ValueError("invalid workload clock") from error
    return _number(value, "workload clock")


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"invalid {label}")
    return float(value)


def _outcome_passed(outcome: dict) -> bool:
    return (
        outcome.get("success") is True
        or outcome.get("state") in {"passed", "succeeded", "completed"}
        or outcome.get("status") in {"passed", "succeeded", "completed"}
    )


def _public_state(state: dict) -> dict:
    return json.loads(json.dumps(state, sort_keys=True))
