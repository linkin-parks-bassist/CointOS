import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from ecosystem.execution_budget import (
    account_usage,
    budget_outcome,
    checkpoint_job_state,
    record_budget_handoff,
    stop_process_group,
)

BUDGET = {"run_seconds": 300, "task_seconds": 900,
          "maximum_attempts": 3, "maximum_output_bytes": 100,
          "maximum_evidence_items": 4, "maximum_children": 1}


def test_output_limit_yields_partial_handoff():
    usage = {"run_started": 0.0, "task_started": 0.0, "attempts": 1,
             "output_bytes": 101, "evidence_items": 1, "children": 0}
    result = budget_outcome(BUDGET, usage, 10.0)
    assert result == {"state": "checkpoint_required",
                      "reason": "maximum_output_bytes"}


def test_missing_handoff_stays_checkpoint_required():
    outcome = {"state": "checkpoint_required", "reason": "maximum_output_bytes"}
    assert checkpoint_job_state(outcome, None) == {
        "state": "checkpoint_required", "reason": "maximum_output_bytes"}
    try:
        record_budget_handoff({"state": "within_budget"}, {
            "path": "x", "bytes": 1, "job_id": "x", "agent_generation": 1})
        raise AssertionError("within_budget must not enter the handoff path")
    except ValueError:
        pass
    try:
        record_budget_handoff(outcome, {
            "path": "x", "bytes": 0, "job_id": "x", "agent_generation": 1})
        raise AssertionError("empty artifact must not count as a handoff")
    except ValueError:
        pass


def test_verified_handoff_enters_partial_handoff_ready():
    outcome = {"state": "checkpoint_required", "reason": "maximum_output_bytes"}
    artifact = {"path": "state/jobs/task-x.handoff.md", "bytes": 1234,
                "job_id": "task-x", "agent_generation": 2}
    record = checkpoint_job_state(outcome, artifact)
    assert record["state"] == "partial_handoff_ready"
    assert record["reason"] == "maximum_output_bytes"
    assert record["artifact"] == artifact


def test_approval_wait_does_not_consume_task_seconds():
    usage = account_usage(BUDGET, {},
                          {"kind": "wait", "reason": "approval", "at": 0.0})
    usage = account_usage(BUDGET, usage, {"kind": "task_started", "at": 500.0})
    assert budget_outcome(BUDGET, usage, 800.0) == {"state": "within_budget"}
    assert budget_outcome(BUDGET, usage, 1400.0) == {
        "state": "checkpoint_required", "reason": "task_seconds"}


def test_running_interval_consumes_task_seconds():
    usage = account_usage(BUDGET, {}, {"kind": "run_started", "at": 0.0})
    usage = account_usage(BUDGET, usage, {"kind": "run_stopped", "at": 50.0})
    usage = account_usage(BUDGET, usage, {"kind": "run_started", "at": 100.0})
    assert budget_outcome(BUDGET, usage, 120.0) == {"state": "within_budget"}
    uninterrupted = account_usage(BUDGET, {}, {"kind": "run_started", "at": 0.0})
    assert budget_outcome(BUDGET, uninterrupted, 300.0) == {
        "state": "checkpoint_required", "reason": "run_seconds"}
    try:
        account_usage(BUDGET, {}, {"kind": "pause_requested"})
        raise AssertionError("unknown event kind must be rejected")
    except ValueError:
        pass


def test_pid_reuse_is_not_killed():
    with patch("ecosystem.execution_budget.os.killpg",
               side_effect=AssertionError("signalled an unobserved pid")):
        result = stop_process_group(4242, 30.0, 15.0, lambda: None)
    assert result == {"state": "exited", "signal": None}


def _run_group_child(*code):
    return subprocess.Popen(
        [sys.executable, "-c", *code], start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _observe(process):
    def observe():
        return {"pid": process.pid} if process.poll() is None else None
    return observe


def test_wrapup_sigint_stops_group():
    with _run_group_child("import time; time.sleep(30)") as process:
        result = stop_process_group(process.pid, 5.0, 5.0, _observe(process))
    assert result == {"state": "stopped", "signal": "int"}


def test_escalation_terminates_then_kills():
    ignore_int = _run_group_child(
        "import signal, time; signal.signal(signal.SIGINT, lambda *a: None); "
        "time.sleep(30)")
    try:
        time.sleep(0.5)  # let the interpreter install its trap
        result = stop_process_group(ignore_int.pid, 0.3, 5.0,
                                    _observe(ignore_int))
    finally:
        if ignore_int.poll() is None:
            ignore_int.kill(); ignore_int.wait()
    assert result == {"state": "stopped", "signal": "term"}
    ignores_both = _run_group_child(
        "import signal, time; "
        "signal.signal(signal.SIGINT, lambda *a: None); "
        "signal.signal(signal.SIGTERM, lambda *a: None); time.sleep(30)")
    try:
        time.sleep(0.5)  # let the interpreter install its traps
        result = stop_process_group(ignores_both.pid, 0.3, 0.3,
                                    _observe(ignores_both))
    finally:
        if ignores_both.poll() is None:
            ignores_both.kill(); ignores_both.wait()
    assert result == {"state": "killed", "signal": "kill"}


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite((
        unittest.FunctionTestCase(test_output_limit_yields_partial_handoff),
        unittest.FunctionTestCase(test_missing_handoff_stays_checkpoint_required),
        unittest.FunctionTestCase(test_verified_handoff_enters_partial_handoff_ready),
        unittest.FunctionTestCase(test_approval_wait_does_not_consume_task_seconds),
        unittest.FunctionTestCase(test_running_interval_consumes_task_seconds),
        unittest.FunctionTestCase(test_pid_reuse_is_not_killed),
        unittest.FunctionTestCase(test_wrapup_sigint_stops_group),
        unittest.FunctionTestCase(test_escalation_terminates_then_kills),
    ))
