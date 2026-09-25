"""Demand and qualified ceilings for physical backend profiles.

This layer decides; it never loads, unloads, or fences a backend. A ceiling is
an observed-and-explicitly-qualified capability for an exact model recipe and
per-request context, not a constant attached to a model name.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from pathlib import Path

from ecosystem import backend_profiles, cli

STATE_VERSION = 1
BOUND_STATES = frozenset({"runner_starting", "running"})
ROUTING_STATES = frozenset({"queued", "ready", "claimed"})


def profile_key(profile: dict, model: dict) -> str:
    """Identify a qualified weight/recipe/context without embedding slot count."""
    if (type(model) is not dict or model.get("id") != profile.get("model_id")
            or type(model.get("size_bytes")) is not int
            or model["size_bytes"] <= 0
            or type(model.get("parameter_count")) is not int
            or model["parameter_count"] <= 0):
        raise ValueError("model identity and measured size are not qualified")
    canonical = backend_profiles.profile_payload(profile, 1)
    canonical.pop("save_options")
    key = {"model_id": profile["model_id"],
           "model_bytes": model["size_bytes"],
           "parameter_count": model["parameter_count"],
           "context_tokens_per_sequence": profile["context_tokens_per_sequence"],
           "recipe": model.get("recipe"),
           "load_options_at_one_sequence": canonical}
    data = json.dumps(key, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def qualification_path(root: Path) -> Path:
    return Path(root) / "state/backend-profile-qualifications.json"


def load_qualifications(root: Path) -> dict:
    path = qualification_path(root)
    if not path.exists():
        return {"version": STATE_VERSION, "profiles": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if (type(value) is not dict or value.get("version") != STATE_VERSION
            or type(value.get("profiles")) is not dict):
        raise ValueError("invalid backend profile qualifications")
    for key, record in value["profiles"].items():
        if (type(key) is not str or len(key) != 64
                or type(record) is not dict
                or record.get("key") != key
                or type(record.get("maximum_parallel_sequences")) is not int
                or record["maximum_parallel_sequences"] <= 0
                or type(record.get("evidence")) is not str
                or not record["evidence"]):
            raise ValueError("invalid backend profile qualification record")
    return value


def qualified_ceiling(qualifications: dict, profile: dict,
                      model: dict) -> int | None:
    key = profile_key(profile, model)
    record = qualifications.get("profiles", {}).get(key)
    return record["maximum_parallel_sequences"] if record is not None else None


def record_qualification(root: Path, profile: dict, model: dict,
                         evidence: str) -> dict:
    """Record an explicitly reviewed, currently observed working profile."""
    if type(evidence) is not str or not evidence.strip():
        raise ValueError("qualification requires concrete evidence")
    if (model.get("loaded") is not True
            or model.get("residency_verified") is not True
            or model.get("fresh") is not True):
        raise ValueError("model is not freshly observed resident")
    backend_profiles.require_qualified_allocation({"models": [model]}, profile)
    key = profile_key(profile, model)
    path = qualification_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = load_qualifications(root)
        previous = state["profiles"].get(key)
        if (previous is not None and previous["maximum_parallel_sequences"]
                >= profile["parallel_sequences"]):
            return dict(previous)
        record = {"key": key, "model_id": profile["model_id"],
                  "context_tokens_per_sequence": profile["context_tokens_per_sequence"],
                  "maximum_parallel_sequences": profile["parallel_sequences"],
                  "evidence": evidence.strip(), "qualified_at": cli.now()}
        state["profiles"][key] = record
        cli.atomic_json(path, state)
        return record


def model_demand(jobs: list[dict], model_id: str, route_for_job) -> int:
    """Count durable work actually assigned or freshly routed to one model."""
    if type(model_id) is not str or not model_id:
        raise ValueError("invalid model identity")
    demand = 0
    for job in jobs:
        if type(job) is not dict or job.get("kind") != "agent-task":
            continue
        state = job.get("state")
        if state in BOUND_STATES:
            demand += job.get("model") == model_id
        elif state in ROUTING_STATES:
            cancellation = job.get("cancellation_requested_at")
            if state == "claimed" and type(cancellation) is str and cancellation:
                continue
            try:
                decision = route_for_job(job)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            demand += (type(decision) is dict and decision.get("valid") is True
                       and decision.get("model") == model_id)
    return demand
