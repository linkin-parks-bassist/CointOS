import tempfile
import unittest
from pathlib import Path

from ecosystem import time_policy


DEFAULT_POLICY = {
    "telegram": {
        "poll_seconds": 1,
        "long_poll_seconds": 25,
        "request_timeout_seconds": 40,
        "command_acknowledgement_deadline_seconds": 2,
        "degraded_response_deadline_seconds": 3,
    },
    "fast_control": {
        "response_deadline_seconds": 10,
        "maximum_queue_age_seconds": 5,
    },
    "inference": {
        "model_stop_deadline_seconds": 15,
        "model_start_deadline_seconds": 180,
        "health_verification_deadline_seconds": 60,
    },
    "heartbeat": {
        "probe_period_seconds": 20,
        "probe_deadline_seconds": 15,
        "maximum_age_seconds": 60,
        "guardian_poll_seconds": 5,
    },
    "monitor": {
        "activation_period_seconds": 300,
        "stagger_spacing_seconds": 25,
        "run_deadline_seconds": 120,
    },
    "repair": {
        "initial_model_deadline_seconds": 180,
        "progress_lease_seconds": 60,
        "progress_update_period_seconds": 60,
        "emergency_model_deadline_seconds": 900,
    },
    "resource": {
        "pressure_confirmation_seconds": 5,
        "emergency_confirmation_seconds": 10,
        "healthy_release_seconds": 60,
    },
    "lifecycle": {
        "restart_checkpoint_grace_seconds": 30,
        "service_stop_deadline_seconds": 10,
        "terminate_grace_seconds": 5,
        "kill_grace_seconds": 2,
        "reconciliation_deadline_seconds": 60,
        "progress_update_period_seconds": 30,
    },
    "control_turn": {"run_deadline_seconds": 600},
    "executor": {"run_deadline_seconds": 1800, "time_slice_seconds": 300},
    "verification": {"run_deadline_seconds": 900},
    "outbox": {
        "poll_seconds": 2,
        "retry_initial_seconds": 5,
        "retry_maximum_seconds": 60,
    },
}


def write_complete_policy(root: Path, **overrides) -> Path:
    policy = {section: values.copy() for section, values in DEFAULT_POLICY.items()}
    for name, value in overrides.items():
        section, key = name.split(".", 1) if "." in name else ("heartbeat", name)
        policy[section][key] = value
    path = root / "time.cfg"
    path.write_text(
        "\n".join(
            f"[{section}]\n" + "\n".join(f"{key} = {value}" for key, value in values.items())
            for section, values in policy.items()
        ) + "\n",
        encoding="utf-8",
    )
    return path


def test_loads_explicit_seconds():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "time.cfg"
        path.write_text("[heartbeat]\nprobe_deadline_seconds = 15\nmaximum_age_seconds = 60\n")
        policy = time_policy.load(path, required={"heartbeat": {
            "probe_deadline_seconds", "maximum_age_seconds"}})
        time_policy.validate(time_policy.load(write_complete_policy(Path(temporary))))
        assert time_policy.seconds(policy, "heartbeat", "maximum_age_seconds") == 60.0


def test_probe_deadline_must_be_shorter_than_lease():
    with tempfile.TemporaryDirectory() as temporary:
        path = write_complete_policy(Path(temporary), probe_deadline_seconds=60,
                                     maximum_age_seconds=60)
        with unittest.TestCase().assertRaisesRegex(ValueError, "probe_deadline_seconds"):
            time_policy.load(path)


def test_invalid_reload_keeps_last_known_good():
    with tempfile.TemporaryDirectory() as temporary:
        path = write_complete_policy(Path(temporary))
        active = time_policy.load(path)
        mtime = path.stat().st_mtime_ns
        path.write_text("[heartbeat]\nmaximum_age_seconds = nope\n")
        current, current_mtime, error = time_policy.reload_if_changed(active, mtime, path)
        assert current == active
        assert current_mtime == mtime
        assert "maximum_age_seconds" in error


def test_load_rejects_missing_unknown_boolean_nonfinite_and_nonpositive_values():
    cases = (
        ("[DEFAULT]\n\n[heartbeat]\nprobe_deadline_seconds = 15\nmaximum_age_seconds = 60\n",
         "unknown time policy section DEFAULT"),
        ("[heartbeat]\nprobe_deadline_seconds = 15\n", "missing time policy heartbeat.maximum_age_seconds"),
        ("[heartbeat]\nprobe_deadline_seconds = 15\nmaximum_age_seconds = 60\nextra_seconds = 1\n",
         "unknown time policy heartbeat.extra_seconds"),
        ("[heartbeat]\nprobe_deadline_seconds = true\nmaximum_age_seconds = 60\n",
         "invalid time policy heartbeat.probe_deadline_seconds"),
        ("[heartbeat]\nprobe_deadline_seconds = nan\nmaximum_age_seconds = 60\n",
         "invalid time policy heartbeat.probe_deadline_seconds"),
        ("[heartbeat]\nprobe_deadline_seconds = 0\nmaximum_age_seconds = 60\n",
         "invalid time policy heartbeat.probe_deadline_seconds"),
    )
    required = {"heartbeat": {"probe_deadline_seconds", "maximum_age_seconds"}}
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "time.cfg"
        for text, error in cases:
            path.write_text(text, encoding="utf-8")
            with unittest.TestCase().assertRaisesRegex(ValueError, error):
                time_policy.load(path, required=required)


def test_partial_required_mapping_only_checks_relations_when_all_keys_are_present():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "time.cfg"
        path.write_text("[heartbeat]\nprobe_deadline_seconds = 60\n", encoding="utf-8")
        policy = time_policy.load(path, required={"heartbeat": {"probe_deadline_seconds"}})
        assert time_policy.seconds(policy, "heartbeat", "probe_deadline_seconds") == 60.0


def test_seconds_rejects_missing_or_invalid_values():
    with unittest.TestCase().assertRaisesRegex(KeyError, "missing time policy heartbeat.missing"):
        time_policy.seconds({"heartbeat": {}}, "heartbeat", "missing")
    with unittest.TestCase().assertRaisesRegex(ValueError, "invalid time policy heartbeat.probe_deadline_seconds"):
        time_policy.seconds({"heartbeat": {"probe_deadline_seconds": True}}, "heartbeat",
                            "probe_deadline_seconds")


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in (
        test_loads_explicit_seconds,
        test_probe_deadline_must_be_shorter_than_lease,
        test_invalid_reload_keeps_last_known_good,
        test_load_rejects_missing_unknown_boolean_nonfinite_and_nonpositive_values,
        test_partial_required_mapping_only_checks_relations_when_all_keys_are_present,
        test_seconds_rejects_missing_or_invalid_values,
    ))
