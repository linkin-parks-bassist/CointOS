"""Replay only generation-bound outcomes after verified physical close."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, executor


def recover(result, *, cancelled=False, legacy=False, bad_close=False,
            missing_artifact=False):
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        generation = 3
        state = "run_finished" if result["returncode"] == 0 else "failed"
        job = {
            "id": "task-post-close", "kind": "agent-task", "state": state,
            "runner_generation": generation,
            "runner_closed_generation": generation,
            "runner_close_state": state,
            "runner_close_outcome": {"state": "reaped",
                                     "process_group_alive": bad_close,
                                     "returncode": result["returncode"]},
            "opencode_session": "ses_replay", "output": "logs/runs/test.log",
        }
        if missing_artifact:
            job["task_contract"] = {"acceptance": [{
                "kind": "artifact", "path": str(cli.ROOT / "missing-result.md")}]}
        if not legacy:
            job["runner_round_outcome"] = {
                "runner_generation": generation, "result": result}
        if cancelled:
            job["cancellation_requested_at"] = "now"
            job["cancellation_reason"] = "user requested"
        path = cli.ROOT / "state/jobs/task-post-close.json"
        cli.atomic_json(path, job)
        with patch.object(executor, "_process_alive", return_value=False), \
             patch.object(cli, "audit"), \
             patch.object(executor, "queue_notifications"):
            first = executor.recover_abandoned_jobs()
            saved = json.loads(path.read_text())
            second = executor.recover_abandoned_jobs()
        return first, second, saved


def test_closed_budget_round_recovers_retained_session_without_rerun():
    first, second, saved = recover({"returncode": -15, "preempted": False,
                                    "usage": {"tokens": 12},
                                    "budget_checkpoint": {"reason": "task_seconds"},
                                    "session": "ses_replay"})
    assert (first, second) == (1, 0)
    assert saved["state"] == "ready"
    assert saved["logical_run_state"] == "continuing"
    assert saved["budget_usage"] == {}


def test_closed_preemption_round_recovers_ready():
    first, second, saved = recover({"returncode": -15, "preempted": True,
                                    "reason": "priority", "usage": {},
                                    "session": "ses_replay"})
    assert (first, second) == (1, 0)
    assert saved["state"] == "ready"
    assert saved["preemption_count"] == 1


def test_closed_round_cancellation_beats_budget_and_preemption():
    first, second, saved = recover({"returncode": -15, "preempted": True,
                                    "reason": "priority", "usage": {},
                                    "session": "ses_replay",
                                    "budget_checkpoint": {"reason": "task_seconds"}},
                                   cancelled=True)
    assert (first, second) == (1, 0)
    assert saved["state"] == "cancelled"
    assert saved["logical_run_state"] == "terminal"


def test_closed_success_rechecks_acceptance_and_completes_once():
    first, second, saved = recover({"returncode": 0, "preempted": False,
                                    "usage": {}})
    assert (first, second) == (1, 0)
    assert saved["state"] == "completed"
    assert saved["runner_logical_finalized_generation"] == 3


def test_closed_success_with_missing_artifact_fails_once():
    first, second, saved = recover({"returncode": 0, "preempted": False,
                                    "usage": {}}, missing_artifact=True)
    assert (first, second) == (1, 0)
    assert saved["state"] == "failed"
    assert "missing artifact" in saved["error"]
    assert saved["runner_logical_finalized_generation"] == 3


def test_old_closed_record_without_round_result_is_not_guessed():
    first, second, saved = recover({"returncode": 0, "preempted": False,
                                    "usage": {}}, legacy=True)
    assert (first, second) == (0, 0)
    assert saved["state"] == "run_finished"


def test_inconsistent_close_evidence_requires_review_not_completion():
    first, second, saved = recover({"returncode": 0, "preempted": False,
                                    "usage": {}}, bad_close=True)
    assert (first, second) == (1, 0)
    assert saved["state"] == "reconciliation_required"
    assert saved["post_close_outcome_review_required"] is True


def test_malformed_checkpoint_does_not_guess_completion():
    first, second, saved = recover({"returncode": 0, "preempted": False,
                                    "usage": {}, "budget_checkpoint": {}})
    assert (first, second) == (1, 0)
    assert saved["state"] == "reconciliation_required"


def test_failed_record_before_close_finishes_physical_close_then_replays():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        result = {"returncode": -15, "preempted": True,
                  "reason": "priority", "session": "ses_replay", "usage": {}}
        path = cli.ROOT / "state/jobs/task-unclosed.json"
        cli.atomic_json(path, {
            "id": "task-unclosed", "kind": "agent-task", "state": "failed",
            "runner_generation": 3, "runner_close_outcome": {
                "state": "reaped", "process_group_alive": False,
                "returncode": -15},
            "runner_round_outcome": {"runner_generation": 3, "result": result},
            "worker_lease_id": "worker-test", "inference_lease_id": "lease-test",
            "executor_pid": 123, "executor_start_ticks": 456,
            "executor_pgid": 123,
        })

        def close(job, job_path, _context, _child):
            job.update(runner_closed_generation=3, runner_close_state="failed")
            cli.atomic_json(job_path, job)
            return {"state": "failed"}

        with patch.object(executor, "_process_alive", return_value=False), \
             patch.object(executor, "_stop_recovered_runner", return_value=False), \
             patch.object(executor, "close_runner_round", side_effect=close), \
             patch.object(cli, "audit"):
            assert executor.recover_abandoned_jobs() == 1
        saved = json.loads(path.read_text())
        assert saved["state"] == "ready"
        assert saved["preemption_count"] == 1


def load_tests(_loader, tests, _pattern):
    tests.addTests(unittest.FunctionTestCase(function)
                   for name, function in sorted(globals().items())
                   if name.startswith("test_") and callable(function))
    return tests
