"""Fast durable cancellation checks without launching a worker or backend."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, executor


def test_cancellation_wins_over_budget_checkpoint_after_runner_close():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        job_path = root / "job.json"
        durable = {"id": "task-1", "state": "running",
                   "cancellation_requested_at": "now",
                   "cancellation_reason": "user requested"}
        job_path.write_text(json.dumps(durable))
        cached = {"id": "task-1", "state": "running",
                  "pending_preemption_reason": "budget"}
        outcome = {"session": "session-1", "reason": "budget checkpoint",
                   "budget_checkpoint": {"reason": "task_seconds"},
                   "preempted": True}
        with patch.object(executor.cli, "ROOT", root), \
             patch.object(executor.cli, "audit"):
            assert executor._complete_requested_cancellation(cached, job_path, outcome)
        saved = json.loads(job_path.read_text())
        assert saved["state"] == "cancelled"
        assert saved["logical_run_state"] == "terminal"
        assert saved["runner_close_state"] == "cancelled"
        assert saved["opencode_session"] == "session-1"
        assert "pending_preemption_reason" not in saved


def test_ready_job_with_cancellation_marker_is_not_claimed():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        job_path = root / "job.json"
        job = {"id": "task-1", "state": "ready",
               "cancellation_requested_at": "now"}
        job_path.write_text(json.dumps(job))
        with patch.object(executor.cli, "ROOT", root), \
             patch.object(executor.cli, "audit"):
            assert executor._durably_claim_job(job_path, job) is False
        saved = json.loads(job_path.read_text())
        assert saved["state"] == "cancelled"
        assert saved["logical_run_state"] == "terminal"


def test_stale_budget_write_cannot_erase_durable_cancellation():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        job_path = root / "job.json"
        job_path.write_text(json.dumps({
            "id": "task-1", "state": "running",
            "cancellation_requested_at": "now",
            "cancellation_reason": "user requested"}))
        stale = {"id": "task-1", "state": "ready",
                 "budget_outcome": {"reason": "task_seconds"}}
        with patch.object(executor.cli, "ROOT", root):
            executor._persist_job(job_path, stale)
        saved = json.loads(job_path.read_text())
        assert saved["cancellation_requested_at"] == "now"
        assert saved["cancellation_reason"] == "user requested"
        with patch.object(executor.cli, "ROOT", root), \
             patch.object(executor.cli, "audit"):
            assert executor._durably_claim_job(job_path, saved) is False
        assert json.loads(job_path.read_text())["state"] == "cancelled"


def test_restart_recovery_cancellation_beats_pending_preemption():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with patch.object(cli, "ROOT", root):
            cli.initialize()
            path = root / "state/jobs/task-recovery.json"
            cli.atomic_json(path, {
                "id": "task-recovery", "kind": "agent-task",
                "state": "reconciliation_required", "runner_generation": 2,
                "runner_close_outcome": {"state": "reaped", "returncode": 0,
                                         "process_group_alive": False},
                "worker_lease_id": "worker-test",
                "inference_lease_id": "inference-test",
                "executor_pid": 123, "executor_start_ticks": 456,
                "executor_pgid": 123, "opencode_session": "ses_test",
                "pending_preemption_reason": "priority",
                "cancellation_requested_at": "now",
                "cancellation_reason": "user requested",
            })
            with patch.object(executor, "_process_alive", return_value=False), \
                 patch.object(executor, "_stop_recovered_runner", return_value=False), \
                 patch.object(executor, "close_runner_round", return_value={"state": "closed"}), \
                 patch.object(cli, "audit"):
                assert executor.recover_abandoned_jobs() == 1
            saved = json.loads(path.read_text())
            assert saved["state"] == "cancelled"
            assert saved["logical_run_state"] == "terminal"
            assert saved["runner_close_state"] == "cancelled"
            assert "pending_preemption_reason" not in saved


def load_tests(_loader, tests, _pattern):
    tests.addTests(unittest.FunctionTestCase(function)
                   for name, function in sorted(globals().items())
                   if name.startswith("test_") and callable(function))
    return tests
