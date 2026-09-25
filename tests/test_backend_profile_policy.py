"""Model-neutral profile demand follows the next executable route."""

import unittest

from ecosystem.backend_profile_policy import model_demand


def test_ready_job_uses_fresh_route_not_previous_model():
    job = {"kind": "agent-task", "state": "ready", "model": "old-model"}
    routed = []
    def route(candidate):
        routed.append(candidate)
        return {"valid": True, "model": "new-model"}
    assert model_demand([job], "old-model", route) == 0
    assert model_demand([job], "new-model", route) == 1
    assert routed == [job, job]


def test_active_job_remains_bound_to_its_physical_model():
    job = {"kind": "agent-task", "state": "running", "model": "old-model"}
    def should_not_route(_candidate):
        raise AssertionError("an active job must retain its physical model")
    assert model_demand([job], "old-model", should_not_route) == 1
    assert model_demand([job], "new-model", should_not_route) == 0


def test_invalid_pending_route_does_not_create_phantom_demand():
    job = {"kind": "agent-task", "state": "ready", "model": "old-model"}
    assert model_demand([job], "old-model",
                        lambda _candidate: {"valid": False, "model": "old-model"}) == 0


def load_tests(_loader, tests, _pattern):
    tests.addTests(unittest.FunctionTestCase(function)
                   for name, function in sorted(globals().items())
                   if name.startswith("test_") and callable(function))
    return tests
