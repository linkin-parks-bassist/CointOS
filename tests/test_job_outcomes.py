"""Pure post-close job transitions, without a backend or durable runtime."""

import unittest

from ecosystem.job_outcomes import budget_checkpoint_job, preempted_job


def test_budget_checkpoint_keeps_retained_session_and_resets_round_usage():
    original = {"id": "task", "state": "run_finished", "executor_pid": 23,
                "opencode_session": "ses_old", "budget_usage": {"tokens": 42}}
    checkpoint = {"reason": "task_seconds"}
    updated = budget_checkpoint_job(original, checkpoint, None, "now")
    assert updated["state"] == "ready"
    assert updated["logical_run_state"] == "continuing"
    assert updated["opencode_session"] == "ses_old"
    assert updated["resume_available"] is True
    assert updated["budget_usage"] == {}
    assert updated["budget_outcome"] == checkpoint
    assert "executor_pid" not in updated
    assert original["state"] == "run_finished"
    assert original["budget_usage"] == {"tokens": 42}


def test_budget_checkpoint_without_session_is_terminal_and_keeps_usage():
    original = {"id": "task", "state": "run_finished", "executor_pid": 23,
                "budget_usage": {"tokens": 42}}
    updated = budget_checkpoint_job(original, {"reason": "task_seconds"},
                                    None, "now")
    assert updated["state"] == "checkpoint_required"
    assert updated["logical_run_state"] == "terminal"
    assert updated["resume_available"] is False
    assert updated["budget_usage"] == {"tokens": 42}
    assert "executor_pid" not in updated


def test_preemption_uses_observed_session_and_clears_pending_marker():
    original = {"id": "task", "state": "interrupted", "executor_pid": 23,
                "pending_preemption_reason": "pressure", "preemption_count": 2,
                "opencode_session": "ses_old"}
    updated = preempted_job(original, "ses_new", "priority", "now")
    assert updated["state"] == "ready"
    assert updated["opencode_session"] == "ses_new"
    assert updated["resume_available"] is True
    assert updated["last_preemption_reason"] == "priority"
    assert updated["preemption_count"] == 3
    assert "pending_preemption_reason" not in updated
    assert "executor_pid" not in updated
    assert original["state"] == "interrupted"


def test_preemption_without_observed_session_is_not_marked_resumable():
    updated = preempted_job({"state": "run_finished", "opencode_session": "old"},
                            None, "pressure", "now")
    assert updated["state"] == "ready"
    assert updated["opencode_session"] == "old"
    assert updated["resume_available"] is False
    assert updated["preemption_count"] == 1


def load_tests(_loader, tests, _pattern):
    tests.addTests(unittest.FunctionTestCase(function)
                   for name, function in sorted(globals().items())
                   if name.startswith("test_") and callable(function))
    return tests
