from __future__ import annotations

import configparser
import math
from pathlib import Path

from ecosystem import cli


CONFIG_PATH = cli.ROOT / "config/time.cfg"

REQUIRED_KEYS = {
    "telegram": {
        "poll_seconds", "long_poll_seconds", "request_timeout_seconds",
        "command_acknowledgement_deadline_seconds", "degraded_response_deadline_seconds",
    },
    "fast_control": {"response_deadline_seconds", "maximum_queue_age_seconds"},
    "inference": {
        "model_stop_deadline_seconds", "model_start_deadline_seconds",
        "health_verification_deadline_seconds",
    },
    "heartbeat": {
        "probe_period_seconds", "probe_deadline_seconds", "maximum_age_seconds",
        "guardian_poll_seconds",
    },
    "monitor": {"activation_period_seconds", "stagger_spacing_seconds", "run_deadline_seconds"},
    "repair": {
        "initial_model_deadline_seconds", "progress_lease_seconds", "progress_update_period_seconds",
        "emergency_model_deadline_seconds",
    },
    "resource": {
        "pressure_confirmation_seconds", "emergency_confirmation_seconds", "healthy_release_seconds",
    },
    "lifecycle": {
        "restart_checkpoint_grace_seconds", "service_stop_deadline_seconds", "terminate_grace_seconds",
        "kill_grace_seconds", "reconciliation_deadline_seconds", "progress_update_period_seconds",
    },
    "control_turn": {"run_deadline_seconds"},
    "executor": {"run_deadline_seconds", "time_slice_seconds"},
    "verification": {"run_deadline_seconds"},
    "outbox": {"poll_seconds", "retry_initial_seconds", "retry_maximum_seconds"},
}


def _value(section: str, key: str, raw_value: str) -> float:
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(f"invalid time policy {section}.{key}") from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"invalid time policy {section}.{key}")
    return value


def _validate(policy: dict, required: dict[str, set[str]]) -> None:
    for section in policy:
        if section not in required:
            raise ValueError(f"unknown time policy section {section}")
        for key in policy[section]:
            if key not in required[section]:
                raise ValueError(f"unknown time policy {section}.{key}")
            seconds(policy, section, key)
    for section in sorted(required):
        for key in sorted(required[section]):
            if section not in policy or key not in policy[section]:
                raise ValueError(f"missing time policy {section}.{key}")
    heartbeat = policy.get("heartbeat", {})
    if {"probe_deadline_seconds", "maximum_age_seconds"} <= heartbeat.keys():
        if heartbeat["probe_deadline_seconds"] >= heartbeat["maximum_age_seconds"]:
            raise ValueError("probe_deadline_seconds must be shorter than maximum_age_seconds")


def validate(policy: dict) -> None:
    _validate(policy, REQUIRED_KEYS)


def load(path: Path = CONFIG_PATH,
         required: dict[str, set[str]] = REQUIRED_KEYS) -> dict[str, dict[str, float]]:
    parser = configparser.ConfigParser(interpolation=None, default_section=None)
    parser.optionxform = str
    try:
        source = path.read_text(encoding="utf-8")
        parser.read_string(source, source=str(path))
    except configparser.Error as error:
        raise ValueError(f"invalid time policy: {error}") from error
    if parser.defaults():
        raise ValueError("unknown time policy section DEFAULT")
    policy: dict[str, dict[str, float]] = {}
    for section in parser.sections():
        if section not in required:
            raise ValueError(f"unknown time policy section {section}")
        values: dict[str, float] = {}
        for key, raw_value in parser.items(section):
            if key not in required[section]:
                raise ValueError(f"unknown time policy {section}.{key}")
            values[key] = _value(section, key, raw_value)
        policy[section] = values
    _validate(policy, required)
    return policy


def seconds(policy: dict, section: str, key: str) -> float:
    try:
        value = policy[section][key]
    except KeyError as error:
        raise KeyError(f"missing time policy {section}.{key}") from error
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value <= 0):
        raise ValueError(f"invalid time policy {section}.{key}")
    return float(value)


def reload_if_changed(active: dict, active_mtime_ns: int,
                      path: Path = CONFIG_PATH) -> tuple[dict, int, str | None]:
    try:
        current_mtime_ns = path.stat().st_mtime_ns
        if current_mtime_ns == active_mtime_ns:
            return active, active_mtime_ns, None
        replacement = load(path)
    except (OSError, ValueError) as error:
        return active, active_mtime_ns, str(error) or error.__class__.__name__
    return replacement, current_mtime_ns, None
