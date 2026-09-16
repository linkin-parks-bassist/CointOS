"""Mechanical task budget accounting, outcomes, handoff records, and process stop.

Consumes A1's budget validation; this module never re-parses the contract.
All time values are monotonic. Waits (approval, queue, drain, pause) cost no
running budget; only observed running intervals do.
"""
from __future__ import annotations

import math
import os
import signal
import time
from typing import Callable

from ecosystem.task_contracts import validate_budget

WAIT_REASONS = ("approval", "queue", "drain", "pause")


def _finite_number(value: object, name: str) -> float:
    if type(value) is bool or type(value) not in (int, float) \
            or not math.isfinite(float(value)):
        raise ValueError(f"invalid {name}")
    return float(value)


def _count(value: object, name: str) -> int:
    if type(value) is bool or type(value) is not int or value < 0:
        raise ValueError(f"invalid {name}")
    return value


def account_usage(budget: dict, usage: dict, event: dict) -> dict:
    """Return updated usage after one observed event; inputs stay unchanged.

    Event kinds: run_started, run_stopped, task_started, task_stopped
    (interval boundaries, cost charged only between observed boundaries),
    attempt, child, output (delta bytes), evidence (delta items), and
    wait (reason in WAIT_REASONS, explicitly costs nothing).
    """
    validate_budget(budget)
    if type(usage) is not dict:
        raise ValueError("usage must be a dict")
    if type(event) is not dict or type(event.get("kind")) is not str:
        raise ValueError("usage event must name a kind")
    kind = event["kind"]
    result = dict(usage)
    if kind == "wait":
        if event.get("reason") not in WAIT_REASONS:
            raise ValueError(f"invalid wait reason {event.get('reason')!r}")
        _finite_number(event.get("at"), "event at")
        return result
    if kind in ("run_started", "task_started", "run_stopped", "task_stopped"):
        field = kind.split("_", 1)[0]
        marker = f"{field}_started"
        total = f"{field}_seconds"
        at = _finite_number(event.get("at"), f"{kind} at")
        if at < 0:
            raise ValueError(f"invalid {kind} at")
        if kind.endswith("started"):
            if marker in result:
                raise ValueError(f"overlapping {field} interval")
            result[marker] = at
            return result
        if marker not in result:
            raise ValueError(f"{kind} without a matching {field}_started")
        started = _finite_number(result[marker], marker)
        if at < started:
            raise ValueError(f"{kind} precedes its {field}_started")
        result[total] = _finite_number(result.get(total, 0.0), total) + (at - started)
        del result[marker]
        return result
    if kind == "attempt":
        result["attempts"] = _count(result.get("attempts", 0), "attempts") + 1
        return result
    if kind == "child":
        result["children"] = _count(result.get("children", 0), "children") + 1
        return result
    if kind == "output":
        delta = _count(event.get("bytes"), "output bytes")
        result["output_bytes"] = _count(result.get("output_bytes", 0),
                                        "output_bytes") + delta
        return result
    if kind == "evidence":
        delta = _count(event.get("items"), "evidence items")
        result["evidence_items"] = _count(result.get("evidence_items", 0),
                                          "evidence_items") + delta
        return result
    raise ValueError(f"unknown usage event kind {kind!r}")


def _reached_ceiling(total: float, limit: float) -> bool:
    """Continuous usage (time, output, evidence) is never admitted: the
    running interval has no admission, so reaching the ceiling already
    exhausts the budget."""
    return total >= limit


def _exceeded_ceiling(total: float, limit: float) -> bool:
    """Admitted counts (the running attempt, created children) may stand at
    their ceiling: the attempt was admitted before it started and the child
    only exists because creation was admitted. Only exceeding the ceiling is
    an overrun."""
    return total > limit


def budget_outcome(budget: dict, usage: dict, now_monotonic: float) -> dict:
    """Mechanical budget state. An exhausted budget yields checkpoint_required;
    a timer alone never proves completion. Field order is authoritative when
    several limits are exhausted at once. Continuous usage exhausts at its
    ceiling; an admitted running attempt or already created child exhausts
    only when its quota is exceeded."""
    validated = validate_budget(budget)
    now = _finite_number(now_monotonic, "now_monotonic")
    if type(usage) is not dict:
        raise ValueError("usage must be a dict")

    def consumed(marker: str, field: str) -> float:
        total = _finite_number(usage.get(field, 0.0), field)
        if marker in usage:
            started = _finite_number(usage[marker], marker)
            if now < started:
                raise ValueError(f"{marker} is in the future")
            total += now - started
        return total

    checks = (
        ("task_seconds", consumed("task_started", "task_seconds"),
         validated["task_seconds"], _reached_ceiling),
        ("run_seconds", consumed("run_started", "run_seconds"),
         validated["run_seconds"], _reached_ceiling),
        ("maximum_attempts", _count(usage.get("attempts", 0), "attempts"),
         validated["maximum_attempts"], _exceeded_ceiling),
        ("maximum_output_bytes",
         _count(usage.get("output_bytes", 0), "output_bytes"),
         validated["maximum_output_bytes"], _reached_ceiling),
        ("maximum_evidence_items",
         _count(usage.get("evidence_items", 0), "evidence_items"),
         validated["maximum_evidence_items"], _reached_ceiling),
        ("maximum_children", _count(usage.get("children", 0), "children"),
         validated["maximum_children"], _exceeded_ceiling),
    )
    for reason, total, limit, exhausted in checks:
        if limit is None:
            continue
        if exhausted(total, limit):
            return {"state": "checkpoint_required", "reason": reason}
    return {"state": "within_budget"}


def record_budget_handoff(outcome: dict, artifact: dict) -> dict:
    """Deferred handoff experiment; the active executor retains OpenCode sessions.

    The only path from checkpoint_required to partial_handoff_ready.

    The artifact attests a durable, nonempty file bound to the job and the
    agent generation that produced it; the caller supplies disk facts.
    """
    if (type(outcome) is not dict or outcome.get("state") != "checkpoint_required"
            or type(outcome.get("reason")) is not str or not outcome["reason"]):
        raise ValueError("budget handoff requires a checkpoint_required outcome")
    if type(artifact) is not dict:
        raise ValueError("budget handoff artifact must be a dict")
    path = artifact.get("path")
    if type(path) is not str or not path:
        raise ValueError("budget handoff artifact requires a durable path")
    size = artifact.get("bytes")
    if type(size) is bool or type(size) is not int or size <= 0:
        raise ValueError("budget handoff artifact must be nonempty")
    job_id = artifact.get("job_id")
    if type(job_id) is not str or not job_id:
        raise ValueError("budget handoff artifact must be bound to its job")
    generation = artifact.get("agent_generation")
    if type(generation) is bool or type(generation) is not int or generation < 1:
        raise ValueError(
            "budget handoff artifact must be bound to its agent generation")
    return {"state": "partial_handoff_ready", "reason": outcome["reason"],
            "artifact": artifact}


def checkpoint_job_state(outcome: dict, handoff: dict | None) -> dict:
    """Missing handoff stays checkpoint_required; a verified one becomes
    partial_handoff_ready via record_budget_handoff and nothing else."""
    if handoff is None:
        return {"state": "checkpoint_required", "reason": outcome["reason"]}
    return record_budget_handoff(outcome, handoff)


def _wait_gone(observe: Callable[[], dict | None], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if observe() is None:
            return True
        time.sleep(0.05)
    return observe() is None


def stop_process_group(pid: int, wrapup_seconds: float, grace_seconds: float,
                       observe: Callable[[], dict | None]) -> dict:
    """Request wrap-up (SIGINT), then SIGTERM, then identity-checked SIGKILL.

    observe() returns the process-group identity only while the pid still
    matches the identity registered at launch; None means gone or reused.
    A reused pid is never signalled.
    """
    if type(pid) is bool or type(pid) is not int or pid <= 0:
        raise ValueError("pid must be a positive integer")
    if not callable(observe):
        raise ValueError("observe must be callable")
    wrapup = _finite_number(wrapup_seconds, "wrapup_seconds")
    grace = _finite_number(grace_seconds, "grace_seconds")
    if wrapup < 0 or grace < 0:
        raise ValueError("stop intervals must be nonnegative")
    if observe() is None:
        return {"state": "exited", "signal": None}
    try:
        os.killpg(pid, signal.SIGINT)
    except ProcessLookupError:
        return {"state": "exited", "signal": None}
    if _wait_gone(observe, wrapup):
        return {"state": "stopped", "signal": "int"}
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"state": "exited", "signal": None}
    if _wait_gone(observe, grace):
        return {"state": "stopped", "signal": "term"}
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return {"state": "exited", "signal": None}
    return {"state": "killed", "signal": "kill"}
