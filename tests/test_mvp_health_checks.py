import inspect
import unittest

from ecosystem.health_checks import evaluate_checks


def test_process_alive_does_not_hide_queue_failure():
    definition = {"subsystem_id": "work", "required_checks": ["process", "queue"],
                  "maximum_age_seconds": 30}
    observed = {
        "process": {"boot_id": "b", "observed_monotonic": 9,
                    "status": "pass", "evidence_code": "process_alive"},
        "queue": {"boot_id": "b", "observed_monotonic": 9,
                  "status": "fail", "evidence_code": "dead_running_owner"}}
    result = evaluate_checks(definition, observed,
                             {"boot_id": "b", "monotonic": 10, "utc": "2026-09-05T00:00:00Z"})
    assert result["status"] == "fail"
    assert result["checks"]["queue"]["evidence_code"] == "dead_running_owner"


def test_wrong_boot_observation_is_never_healthy():
    definition = {"subsystem_id": "work", "required_checks": ["process", "queue"],
                  "maximum_age_seconds": 30}
    observed = {
        "process": {"boot_id": "old-boot", "observed_monotonic": 9,
                    "status": "pass", "evidence_code": "process_alive"},
        "queue": {"boot_id": "old-boot", "observed_monotonic": 9,
                  "status": "pass", "evidence_code": "queue_drained"}}
    result = evaluate_checks(definition, observed,
                             {"boot_id": "b", "monotonic": 10, "utc": "2026-09-05T00:00:00Z"})
    assert result["status"] == "fail"


def test_missing_required_check_is_never_healthy():
    definition = {"subsystem_id": "work", "required_checks": ["process", "queue"],
                  "maximum_age_seconds": 30}
    observed = {
        "process": {"boot_id": "b", "observed_monotonic": 9,
                    "status": "pass", "evidence_code": "process_alive"}}
    result = evaluate_checks(definition, observed,
                             {"boot_id": "b", "monotonic": 10, "utc": "2026-09-05T00:00:00Z"})
    assert result["status"] == "fail"


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and inspect.isfunction(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(value) for value in functions)
