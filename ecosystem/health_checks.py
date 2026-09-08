"""Deterministic H1 health evaluation over boot-bound probe observations.

evaluate_checks is the pure boundary between raw probe observations and a
subsystem health verdict. A required check is healthy only when its own
observation exists, was taken on the current boot, is fresh under the
definition deadline, and reports a passing status. One healthy check never
masks another failed check; missing, wrong-boot, stale, and mismatched
evidence each keep an explicit reason instead of an inferred failure.
"""
from __future__ import annotations


def _evaluate_check(name: str, definition: dict, observations: dict,
                    clock: dict) -> dict:
    observation = observations.get(name)
    if observation is None:
        return {"healthy": False, "reason": "missing", "evidence_code": None}
    if observation["boot_id"] != clock["boot_id"]:
        reason = "wrong_boot"
    else:
        age = clock["monotonic"] - observation["observed_monotonic"]
        if not 0 <= age < definition["maximum_age_seconds"]:
            reason = "stale"
        elif observation["status"] != "pass":
            reason = "mismatch"
        else:
            reason = None
    entry = dict(observation)
    entry["healthy"] = reason is None
    entry["reason"] = reason
    return entry


def _evaluate_definition(definition: dict, observations: dict, clock: dict) -> dict:
    checks = {name: _evaluate_check(name, definition, observations, clock)
              for name in definition["required_checks"]}
    return {
        "subsystem_id": definition["subsystem_id"],
        "required_checks": list(definition["required_checks"]),
        "checks": checks,
        "status": "pass" if all(item["healthy"] for item in checks.values()) else "fail",
        "deadline_monotonic": clock["monotonic"] + definition["maximum_age_seconds"],
    }


def evaluate_checks(definitions: dict | list[dict], observations: dict,
                    clock: dict) -> dict:
    """Evaluate one or more subsystem definitions against probe observations.

    clock is {boot_id, monotonic, utc}. A single definition dict returns its
    result dict; a list of definitions returns a dict keyed by subsystem_id.
    A subsystem is healthy only when every required check is healthy.
    """
    if isinstance(definitions, dict):
        return _evaluate_definition(definitions, observations, clock)
    results = [_evaluate_definition(definition, observations, clock)
               for definition in definitions]
    return {item["subsystem_id"]: item for item in results}
