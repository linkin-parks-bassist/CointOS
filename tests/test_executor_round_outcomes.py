"""Runner-close outcome ordering with no live worker or inference backend."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ecosystem import cli, executor
from ecosystem.task_contracts import default_task_contract


def run_round(outcome, *, late_cancellation=False, interrupted=False,
              emit_session=True, reconciliation_required=False):
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        stack.enter_context(patch.object(cli, "ROOT", root))
        cli.initialize()
        (root / "logs/runs").mkdir(parents=True, exist_ok=True)
        prompt = "state/jobs/task-round.prompt.md"
        (root / prompt).write_text("do the work")
        job = {"id": "task-round", "kind": "agent-task", "state": "ready",
               "model": "test-model", "role": "worker", "task": "do the work",
               "attempts": 1, "agent_generation": 2, "prompt": prompt,
               "original_prompt": prompt,
               "task_contract": default_task_contract("do the work", root,
                                                      "test:round-outcome")}
        path = root / "state/jobs/task-round.json"
        cli.atomic_json(path, job)

        def launch(_job, _path, _decision, _inventory, _command, **kwargs):
            _job["runner_generation"] = 1
            cli.atomic_json(_path, _job)
            if emit_session:
                kwargs["stdout"].write(b'{"sessionID":"ses_round"}\n')
                kwargs["stdout"].flush()
            return {"state": "started", "inference_lease": {"lease_id": "test"},
                    "launch": {"process": SimpleNamespace(returncode=0)}}

        def close(current, job_path, _context, _child_outcome):
            observed = json.loads(job_path.read_text())
            assert observed["runner_round_outcome"] == {
                "runner_generation": current.get("runner_generation"),
                "result": outcome,
            }
            close_state = ("reconciliation_required" if reconciliation_required
                           else "interrupted" if interrupted else "run_finished")
            current.update(state=close_state, exit_code=0)
            cli.atomic_json(job_path, current)
            return {"state": close_state if reconciliation_required else "closed"}

        original_cancel = executor._complete_requested_cancellation
        checks = []
        def cancellation_check(current, job_path, result):
            checks.append(1)
            if late_cancellation and len(checks) == 2:
                durable = json.loads(job_path.read_text())
                durable["cancellation_requested_at"] = "now"
                durable["cancellation_reason"] = "user requested"
                cli.atomic_json(job_path, durable)
            return original_cancel(current, job_path, result)

        patches = [
            patch("ecosystem.executor.snapshot", return_value={}),
            patch("ecosystem.executor.choose",
                  side_effect=lambda ready, *_: (*ready[0], "test")),
            patch("ecosystem.scheduler.scheduling_document", return_value={}),
            patch("ecosystem.executor.job_admitted_in_current_mode", return_value=True),
            patch("ecosystem.executor.resource_mode", return_value="normal"),
            patch("ecosystem.executor.route", return_value={
                "action": "run", "model": "test-model", "reason": "test",
                "context_tokens": 1000}),
            patch("ecosystem.executor.realize", return_value={
                "state": "realized", "model": "test-model"}),
            patch("ecosystem.executor.launch_runner_round", side_effect=launch),
            patch("ecosystem.executor._run_preemptibly", return_value=outcome),
            patch("ecosystem.executor.gated_child_wait", return_value={"state": "reaped"}),
            patch("ecosystem.executor.close_runner_round", side_effect=close),
            patch("ecosystem.executor._complete_requested_cancellation",
                  side_effect=cancellation_check),
        ]
        for entry in patches:
            stack.enter_context(entry)
        assert executor.execute_next() is True
        return json.loads(path.read_text()), len(checks)


def test_late_cancellation_during_preemption_is_terminal():
    saved, checks = run_round({"returncode": 0, "preempted": True,
                               "reason": "priority", "session": "ses_round",
                               "usage": {}}, late_cancellation=True)
    assert checks == 2
    assert saved["state"] == "cancelled"
    assert saved["logical_run_state"] == "terminal"
    assert saved["runner_close_state"] == "cancelled"


def test_late_cancellation_as_runner_exits_is_terminal():
    saved, checks = run_round({"returncode": 0, "preempted": False,
                               "usage": {}}, late_cancellation=True)
    assert checks == 2
    assert saved["state"] == "cancelled"
    assert saved["opencode_session"] == "ses_round"
    assert saved["runner_close_state"] == "cancelled"


def test_interrupted_resource_checkpoint_does_not_become_ready():
    saved, _ = run_round({"returncode": 0, "preempted": True,
                          "reason": "resource checkpoint", "usage": {}},
                         interrupted=True)
    assert saved["state"] == "interrupted"


def test_budget_checkpoint_without_session_is_terminal():
    saved, _ = run_round({"returncode": 0, "preempted": False, "usage": {},
                          "budget_checkpoint": {"reason": "task_seconds"}},
                         emit_session=False)
    assert saved["state"] == "checkpoint_required"
    assert saved["logical_run_state"] == "terminal"


def test_budget_checkpoint_with_session_queues_continuation():
    saved, _ = run_round({"returncode": 0, "preempted": False,
                          "usage": {"tokens": 42},
                          "budget_checkpoint": {"reason": "task_seconds"},
                          "session": "ses_round"})
    assert saved["state"] == "ready"
    assert saved["logical_run_state"] == "continuing"
    assert saved["opencode_session"] == "ses_round"
    assert saved["budget_usage"] == {}


def test_preemption_without_interruption_queues_ready():
    saved, _ = run_round({"returncode": 0, "preempted": True,
                          "reason": "priority", "session": "ses_round",
                          "usage": {}})
    assert saved["state"] == "ready"
    assert saved["resume_available"] is True
    assert saved["last_preemption_reason"] == "priority"
    assert saved["preemption_count"] == 1


def test_unverified_physical_close_does_not_apply_logical_outcome():
    saved, checks = run_round({"returncode": 0, "preempted": False,
                               "usage": {}}, reconciliation_required=True)
    assert checks == 0
    assert saved["state"] == "reconciliation_required"


def load_tests(_loader, tests, _pattern):
    tests.addTests(unittest.FunctionTestCase(function)
                   for name, function in sorted(globals().items())
                   if name.startswith("test_") and callable(function))
    return tests
