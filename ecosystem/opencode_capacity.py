"""Pure effective-capacity record for every OpenCode launch.

Every OpenCode launch derives one effective capacity record from a fresh
backend per-request allocation (the incarnation-bound layout observation
owned by `context_layout`), a version-qualified OpenCode capability, and an
explicit policy. Total pool size, the model's trained maximum, static
catalogues, and saved user configuration are not runtime capacity truth.
Contradictory, stale, or unknown inputs fail closed with a ValueError that
names the disagreeing facts and their evidence.
"""

from __future__ import annotations

import hashlib
from fractions import Fraction

CONTEXT_MODES = ("fixed", "shared")

OBSERVATION_KEYS = (
    "selected_model_id",
    "observed_model_id",
    "backend_incarnation",
    "layout",
    "observed_at",
    "evidence",
    "prompt_estimate_tokens",
    "backend_output_ceiling",
)
INCARNATION_KEYS = ("backend_url", "pid", "launch_command", "launch_fingerprint")
LAYOUT_KEYS = (
    "context_mode",
    "backend_context_tokens",
    "parallel_sequences",
    "context_tokens_per_sequence",
    "preallocated_context_tokens",
)
CLIENT_KEYS = ("version", "qualified", "maximum_output_tokens")
POLICY_KEYS = ("output_reserve_tokens", "rollover_fraction", "max_age_seconds")


def launch_fingerprint(launch_command):
    """Canonical sha256 binding for one observed launch argument vector."""
    if not isinstance(launch_command, list) or not launch_command:
        raise ValueError("launch_fingerprint requires a non-empty argument list")
    if not all(isinstance(argument, str) for argument in launch_command):
        raise ValueError("launch_fingerprint requires string arguments")
    return hashlib.sha256("\n".join(launch_command).encode("utf-8")).hexdigest()


def _positive_integer(value, where):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{where} must be a positive integer")
    return value


def _nonnegative_integer(value, where):
    if type(value) is not int or value < 0:
        raise ValueError(f"{where} must be a non-negative integer")
    return value


def _positive_number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{where} must be a positive number")
    return float(value)


def _require_keys(record, keys, where):
    if not isinstance(record, dict):
        raise ValueError(f"{where} must be a dictionary")
    missing = [key for key in keys if key not in record]
    if missing:
        raise ValueError(f"{where} is missing required keys {missing}")
    unknown = sorted(set(record) - set(keys))
    if unknown:
        raise ValueError(f"{where} has unknown keys {unknown}")


def _validate_incarnation(incarnation):
    _require_keys(incarnation, INCARNATION_KEYS, "backend_incarnation")
    url = incarnation["backend_url"]
    if not isinstance(url, str) or not url:
        raise ValueError("backend_incarnation backend_url must be a non-empty string")
    _positive_integer(incarnation["pid"], "backend_incarnation pid")
    command = incarnation["launch_command"]
    if not isinstance(command, list) or not command:
        raise ValueError("backend_incarnation launch_command must be a non-empty argument list")
    if not all(isinstance(argument, str) and argument for argument in command):
        raise ValueError(
            "backend_incarnation launch_command must contain only non-empty arguments")
    fingerprint = incarnation["launch_fingerprint"]
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("backend_incarnation launch_fingerprint must be a non-empty string")
    if launch_fingerprint(command) != fingerprint:
        raise ValueError(
            "backend_incarnation mismatch: launch_command no longer matches its "
            "launch_fingerprint; the layout is bound to a different backend incarnation")


def _validate_layout(layout):
    _require_keys(layout, LAYOUT_KEYS, "layout")
    mode = layout["context_mode"]
    if mode not in CONTEXT_MODES:
        raise ValueError(f"layout has unknown context_mode {mode!r}")
    pool = _positive_integer(
        layout["backend_context_tokens"], "layout backend_context_tokens")
    parallel = _positive_integer(
        layout["parallel_sequences"], "layout parallel_sequences")
    per_sequence = _positive_integer(
        layout["context_tokens_per_sequence"], "layout context_tokens_per_sequence")
    preallocated = _positive_integer(
        layout["preallocated_context_tokens"], "layout preallocated_context_tokens")
    if preallocated != pool:
        raise ValueError(
            f"layout preallocated_context_tokens {preallocated} disagrees with "
            f"backend_context_tokens {pool}")
    if mode == "fixed":
        if pool % parallel != 0 or per_sequence != pool // parallel:
            raise ValueError(
                f"layout fixed partition is contradictory: per-sequence "
                f"{per_sequence} is not pool {pool} divided evenly over {parallel} slots")
    elif per_sequence > pool:
        raise ValueError(
            f"layout shared per-sequence cap {per_sequence} exceeds pool {pool}")


def _validate_client(client):
    _require_keys(client, CLIENT_KEYS, "client capability")
    version = client["version"]
    if not isinstance(version, str) or not version:
        raise ValueError("client capability version must be a non-empty string")
    if client["qualified"] is not True:
        raise ValueError(
            f"OpenCode version {version!r} is not qualified; launch stays closed "
            "until the version is requalified")
    _positive_integer(
        client["maximum_output_tokens"], "client capability maximum_output_tokens")


def _validate_policy(policy):
    _require_keys(policy, POLICY_KEYS, "policy")
    reserve = _positive_integer(
        policy["output_reserve_tokens"], "policy output_reserve_tokens")
    fraction = policy["rollover_fraction"]
    if (isinstance(fraction, bool) or not isinstance(fraction, (int, float))
            or not 0 < fraction < 1):
        raise ValueError(
            f"policy rollover_fraction {fraction!r} must be a number in (0, 1)")
    age = _positive_number(policy["max_age_seconds"], "policy max_age_seconds")
    return reserve, float(fraction), age


def _validate_observation(observation):
    _require_keys(observation, OBSERVATION_KEYS, "observation")
    selected = observation["selected_model_id"]
    if not isinstance(selected, str) or not selected:
        raise ValueError("observation selected_model_id must be a non-empty string")
    observed = observation["observed_model_id"]
    if not isinstance(observed, str) or not observed:
        raise ValueError("observation observed_model_id must be a non-empty string")
    if selected != observed:
        raise ValueError(
            f"selected model {selected!r} differs from the observed backend model "
            f"{observed!r}")
    _validate_incarnation(observation["backend_incarnation"])
    _validate_layout(observation["layout"])
    observed_at = _positive_number(observation["observed_at"], "observation observed_at")
    evidence = observation["evidence"]
    if not isinstance(evidence, str) or not evidence:
        raise ValueError("observation evidence must be a non-empty evidence reference")
    prompt = _nonnegative_integer(
        observation["prompt_estimate_tokens"], "observation prompt_estimate_tokens")
    ceiling = observation["backend_output_ceiling"]
    if ceiling is not None:
        _positive_integer(ceiling, "observation backend_output_ceiling")
    return observed_at, evidence, prompt, ceiling


def effective_inference_capacity(observation, client_capability, policy, now):
    """Derive the one effective capacity record for an OpenCode launch.

    Pure function: copies its plain-dictionary inputs and returns a new record,
    or raises ValueError naming the disagreeing facts. The per-request context
    cap comes verbatim from the incarnation-bound layout observation (fixed or
    shared); it is never the pool re-divided and never an unqualified maximum.
    The effective output is the smallest of the qualified OpenCode ceiling,
    any observed backend output ceiling, and the selected policy reserve.
    Absent, stale, contradictory, or unknown facts fail closed.
    """
    now_value = _positive_number(now, "now")
    observed_at, evidence, prompt, ceiling = _validate_observation(observation)
    _validate_client(client_capability)
    reserve, fraction, max_age = _validate_policy(policy)

    if observed_at > now_value:
        raise ValueError(
            f"observation at {observed_at} is in the future relative to now "
            f"{now_value}; the evidence cannot be fresh")
    age = now_value - observed_at
    if age > max_age:
        raise ValueError(
            f"observation is stale: age {age} seconds exceeds max_age_seconds "
            f"{max_age}")

    layout = observation["layout"]
    effective_context = layout["context_tokens_per_sequence"]
    client_ceiling = client_capability["maximum_output_tokens"]
    candidates = [client_ceiling, reserve]
    if ceiling is not None:
        candidates.append(ceiling)
    effective_output = min(candidates)
    if effective_output >= effective_context:
        raise ValueError(
            f"effective output {effective_output} must be strictly smaller than "
            f"effective context {effective_context}")
    threshold = -(-Fraction(fraction) * effective_context // 1)
    if threshold < prompt:
        raise ValueError(
            f"rollover threshold {threshold} leaves no room before the prompt "
            f"estimate {prompt} inside effective context {effective_context}")
    if prompt + effective_output > effective_context:
        raise ValueError(
            f"prompt estimate {prompt} plus effective output {effective_output} "
            f"does not fit effective context {effective_context}")

    return {
        "model_id": observation["observed_model_id"],
        "backend_incarnation": dict(observation["backend_incarnation"],
                                    launch_command=list(observation["backend_incarnation"]["launch_command"])),
        "observed_at": observation["observed_at"],
        "evidence": evidence,
        "context_mode": layout["context_mode"],
        "backend_context_tokens": layout["backend_context_tokens"],
        "parallel_sequences": layout["parallel_sequences"],
        "effective_context_tokens": effective_context,
        "opencode_version": client_capability["version"],
        "opencode_maximum_output_tokens": client_ceiling,
        "effective_output_tokens": effective_output,
        "output_reserve_tokens": reserve,
        "rollover_fraction": fraction,
        "rollover_threshold_tokens": threshold,
        "prompt_estimate_tokens": prompt,
        "opencode_context_tokens": effective_context,
        "opencode_output_tokens": effective_output,
        "derived_from": f"{evidence};opencode:{client_capability['version']}",
    }
