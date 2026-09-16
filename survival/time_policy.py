"""Single strict owner for operational timing policy."""

import configparser
import math
from pathlib import Path

from survival import records
from survival.json_codec import decode_json_object


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "time.cfg"

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
        "poll_seconds", "pressure_confirmation_seconds", "emergency_confirmation_seconds",
        "healthy_release_seconds",
    },
    "lifecycle": {
        "restart_checkpoint_grace_seconds", "service_stop_deadline_seconds",
        "terminate_grace_seconds", "kill_grace_seconds",
        "reconciliation_deadline_seconds", "progress_update_period_seconds",
    },
    "control_turn": {"run_deadline_seconds"},
    "executor": {"run_deadline_seconds", "time_slice_seconds", "cleanup_deadline_seconds"},
    "workload": {
        "maximum_run_seconds", "wrapup_seconds", "termination_grace_seconds",
    },
    "verification": {"run_deadline_seconds"},
    "outbox": {"poll_seconds", "retry_initial_seconds", "retry_maximum_seconds"},
}


def _value(section, key, raw_value):
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(f"invalid time policy {section}.{key}") from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"invalid time policy {section}.{key}")
    return value


def _validate(policy, required):
    if type(policy) is not dict:
        raise ValueError("invalid time policy projection")
    for section, values in policy.items():
        if section not in required:
            raise ValueError(f"unknown time policy section {section}")
        if type(values) is not dict:
            raise ValueError(f"invalid time policy section {section}")
        for key in values:
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


def validate(policy):
    _validate(policy, REQUIRED_KEYS)


def load(path=CONFIG_PATH, required=REQUIRED_KEYS):
    parser = configparser.ConfigParser(interpolation=None, default_section=None)
    parser.optionxform = str
    try:
        source = Path(path).read_text(encoding="utf-8")
        parser.read_string(source, source=str(path))
    except configparser.Error as error:
        raise ValueError(f"invalid time policy: {error}") from error
    if parser.defaults():
        raise ValueError("unknown time policy section DEFAULT")
    policy = {}
    for section in parser.sections():
        if section not in required:
            raise ValueError(f"unknown time policy section {section}")
        values = {}
        for key, raw_value in parser.items(section):
            if key not in required[section]:
                raise ValueError(f"unknown time policy {section}.{key}")
            values[key] = _value(section, key, raw_value)
        policy[section] = values
    _validate(policy, required)
    return policy


def seconds(policy, section, key):
    try:
        value = policy[section][key]
    except (KeyError, TypeError) as error:
        raise KeyError(f"missing time policy {section}.{key}") from error
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"invalid time policy {section}.{key}")
    return float(value)


def reload_if_changed(active, active_mtime_ns, path=CONFIG_PATH):
    try:
        current_mtime_ns = Path(path).stat().st_mtime_ns
        if current_mtime_ns == active_mtime_ns:
            return active, active_mtime_ns, None
        replacement = load(path)
    except (OSError, ValueError) as error:
        return active, active_mtime_ns, str(error) or error.__class__.__name__
    return replacement, current_mtime_ns, None


def read_accepted_policy(path):
    try:
        policy = decode_json_object(Path(path).read_bytes(), "accepted time policy")
    except OSError as error:
        raise ValueError("cannot read accepted time policy") from error
    validate(policy)
    return policy


def adopt_last_known_good(source_path, accepted_path):
    """Atomically publish one complete policy or retain the prior valid projection."""
    try:
        policy = load(source_path)
    except (OSError, ValueError) as error:
        return read_accepted_policy(accepted_path), str(error) or error.__class__.__name__
    accepted_path = Path(accepted_path)
    try:
        previous = read_accepted_policy(accepted_path)
    except ValueError:
        previous = None
    try:
        accepted_mode = accepted_path.stat().st_mode & 0o777
    except OSError:
        accepted_mode = None
    if previous != policy or accepted_mode != records.SHARED_RECORD_MODE:
        records.atomic_json(
            accepted_path, policy, mode=records.SHARED_RECORD_MODE,
        )
    return policy, None
