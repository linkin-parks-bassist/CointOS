import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ecosystem import cli
from ecosystem.executor import _run_preemptibly, execute_next
from tests.test_scheduler import scheduling_policy as scheduling_document

LARGE_BUDGET = {"run_seconds": 300, "task_seconds": 900,
                "maximum_attempts": 3, "maximum_output_bytes": 10_000_000,
                "maximum_evidence_items": 100, "maximum_children": 5}


def _utc_stamp():
    return (datetime.now(timezone.utc).replace(microsecond=0)).isoformat()


def _fake_process(poll_sequence):
    state = {"polls": 0}

    def poll():
        index = state["polls"]
        state["polls"] += 1
        return poll_sequence[index] if index < len(poll_sequence) else poll_sequence[-1]

    return SimpleNamespace(pid=os.getpid(), poll=poll, returncode=0, wait=lambda: 0)


def test_two_rounds_accumulate_task_usage_and_reset_run_seconds():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        job = {
            "id": "task-cum", "kind": "agent-task", "state": "running",
            "role": "worker", "source": "local-cli", "attempts": 1,
            "created_at": _utc_stamp(), "authority_profile": "worker",
            "remaining_budget": LARGE_BUDGET,
        }
        cli.atomic_json(cli.ROOT / "state/jobs/task-cum.json", job)
        output_path = cli.ROOT / "logs/runs/task-cum.opencode.log"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Fast startup write: present before the first poll, baseline zero.
        output_path.write_bytes(b"hello")
        with patch("time.monotonic", side_effect=[0.0, 3.0, 3.0]):
            outcome1 = _run_preemptibly(
                _fake_process([None, 0]), ["bash", "-c", "true"], job, output_path,
                lambda: None, scheduling_document(), initial_output_bytes=0)
        usage1 = outcome1["usage"]
        assert "run_started" not in usage1 and "task_started" not in usage1
        assert usage1["task_seconds"] == 3.0
        assert usage1["run_seconds"] == 3.0
        assert usage1["output_bytes"] == 5
        # execute_next persists the returned usage between rounds; the
        # queue gap (100s here) must not be charged.
        job["budget_usage"] = usage1
        job["attempts"] = 2
        output_path.write_bytes(b"hello" + b" world!")
        with patch("time.monotonic", side_effect=[100.0, 104.0, 104.0]):
            outcome2 = _run_preemptibly(
                _fake_process([None, 0]), ["bash", "-c", "true"], job, output_path,
                lambda: None, scheduling_document(), initial_output_bytes=5)
        usage2 = outcome2["usage"]
        assert "run_started" not in usage2 and "task_started" not in usage2
        assert usage2["task_seconds"] == 7.0
        assert usage2["run_seconds"] == 4.0
        assert usage2["output_bytes"] == 12
        assert usage2["attempts"] == 2


def test_persisted_near_limit_usage_checkpoints_later_round():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        budget = dict(LARGE_BUDGET, task_seconds=10)
        job = {
            "id": "task-near", "kind": "agent-task", "state": "running",
            "role": "worker", "source": "local-cli", "attempts": 1,
            "created_at": _utc_stamp(), "authority_profile": "worker",
            "remaining_budget": budget,
            "budget_usage": {"task_seconds": 9.0, "output_bytes": 0, "attempts": 1},
        }
        cli.atomic_json(cli.ROOT / "state/jobs/task-near.json", job)
        output_path = cli.ROOT / "logs/runs/task-near.opencode.log"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with patch("time.monotonic", side_effect=[0.0, 2.0, 2.0]), \
             patch("ecosystem.execution_budget.stop_process_group",
                   return_value={"state": "exited", "signal": None}):
            outcome = _run_preemptibly(
                _fake_process([None, 0]), ["bash", "-c", "true"], job, output_path,
                lambda: None, scheduling_document(), initial_output_bytes=0)
        assert outcome["budget_checkpoint"]["reason"] == "task_seconds"
        usage = outcome["usage"]
        assert "run_started" not in usage and "task_started" not in usage
        assert usage["task_seconds"] == 11.0
        assert usage["run_seconds"] == 2.0


def test_preemption_returns_closed_usage_with_final_output():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        running = {
            "id": "task-prec", "kind": "agent-task", "state": "running",
            "role": "steward", "source": "watchdog:review", "dispatch_count": 0,
            "created_at": _utc_stamp(), "authority_profile": "worker",
            "remaining_budget": LARGE_BUDGET, "opencode_session": "ses_prec",
        }
        waiting = {
            "id": "task-user", "kind": "agent-task", "state": "queued",
            "role": "worker", "source": "telegram:42",
            "created_at": _utc_stamp(), "authority_profile": "worker",
        }
        cli.atomic_json(cli.ROOT / "state/jobs/task-prec.json", running)
        cli.atomic_json(cli.ROOT / "state/jobs/task-user.json", waiting)
        output_path = cli.ROOT / "logs/runs/task-prec.opencode.log"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"abcde")
        with patch("time.monotonic", side_effect=[0.0, 5.0, 5.0]), \
             patch("ecosystem.execution_budget.stop_process_group",
                   return_value={"state": "exited", "signal": None}):
            outcome = _run_preemptibly(
                _fake_process([None, 0]), ["bash", "-c", "true"], running, output_path,
                lambda: None, scheduling_document(), initial_output_bytes=0)
        assert outcome["preempted"] is True
        assert outcome["session"] == "ses_prec"
        usage = outcome["usage"]
        assert "run_started" not in usage and "task_started" not in usage
        assert usage["task_seconds"] == 5.0
        assert usage["run_seconds"] == 5.0
        assert usage["output_bytes"] == 5


def test_execute_next_persists_usage_before_reconciliation():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        prompt = cli.ROOT / "state/jobs/task-exec.prompt.md"
        prompt.write_text("do the work", encoding="utf-8")
        (cli.ROOT / "logs/runs").mkdir(parents=True, exist_ok=True)
        job = {
            "id": "task-exec", "kind": "agent-task", "state": "ready",
            "role": "worker", "source": "local-cli", "model": "test-model",
            "attempts": 0, "created_at": _utc_stamp(), "authority_profile": "worker",
            "remaining_budget": LARGE_BUDGET,
            "prompt": "state/jobs/task-exec.prompt.md",
        }
        path = cli.ROOT / "state/jobs/task-exec.json"
        cli.atomic_json(path, job)

        def fake_launch(job_, path_, decision, inventory, command, **kwargs):
            proc = subprocess.Popen(
                ["bash", "-c", "sleep 0.3; printf '12345'"],
                start_new_session=True, stdin=subprocess.DEVNULL,
                stdout=kwargs["stdout"], stderr=subprocess.STDOUT)
            return {"state": "started",
                    "inference_lease": {"lease_id": "inf-test"},
                    "worker_lease": {"lease_id": "work-test"},
                    "launch": {"process": proc}}

        def fake_close(job_, path_, context, child_outcome):
            job_.update(state="reconciliation_required",
                        reconciliation_reason="runner process group termination is unresolved")
            cli.atomic_json(path_, job_)
            return {"state": "reconciliation_required"}

        patches = [
            patch("ecosystem.executor.snapshot", return_value={}),
            patch("ecosystem.executor.choose",
                  side_effect=lambda ready, _inv, _sched: (
                      ready[0][0], ready[0][1], "test")),
            patch("ecosystem.executor.resource_mode", return_value="normal"),
            patch("ecosystem.executor.route", return_value={
                "action": "run", "model": "test-model", "reason": "test",
                "context_tokens": 1024}),
            patch("ecosystem.executor.realize", return_value={"state": "realized"}),
            patch("ecosystem.executor.job_admitted_in_current_mode", return_value=True),
            patch("ecosystem.executor.launch_runner_round", side_effect=fake_launch),
            patch("ecosystem.executor.gated_child_wait", return_value={
                "state": "reaped", "process_group_alive": False, "returncode": 0}),
            patch("ecosystem.executor.close_runner_round", side_effect=fake_close),
            patch("ecosystem.scheduler.scheduling_document", return_value={}),
        ]
        for entry in patches:
            entry.start()
        try:
            assert execute_next() is True
        finally:
            for entry in patches:
                entry.stop()
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["state"] == "reconciliation_required"
        usage = saved["budget_usage"]
        assert "run_started" not in usage and "task_started" not in usage
        assert usage["task_seconds"] > 0
        assert usage["run_seconds"] > 0
        assert usage["output_bytes"] == 5
        assert usage["attempts"] == 1


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite([
        unittest.FunctionTestCase(
            test_two_rounds_accumulate_task_usage_and_reset_run_seconds),
        unittest.FunctionTestCase(test_persisted_near_limit_usage_checkpoints_later_round),
        unittest.FunctionTestCase(test_preemption_returns_closed_usage_with_final_output),
        unittest.FunctionTestCase(test_execute_next_persists_usage_before_reconciliation),
    ])
