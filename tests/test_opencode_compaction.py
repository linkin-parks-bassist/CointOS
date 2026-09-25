"""Context pressure must not replace a durable OpenCode session."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ecosystem import cli
from ecosystem.executor import execute_next
from ecosystem.resource_control import opencode_session_id
from ecosystem.task_contracts import default_task_contract


def test_session_lookup_skips_non_event_json():
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "run.jsonl"
        output.write_text('12345\nnull\n[]\n"text"\nplain text\n'
                          '{"sessionID":"ses_retained"}\n')
        assert opencode_session_id(output) == "ses_retained"


def _execute_context_case(context_state="running", session="ses_compaction", budget_stop=False):
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(cli, "ROOT", Path(temporary)))
        cli.initialize()
        (cli.ROOT / "logs/runs").mkdir(parents=True, exist_ok=True)
        prompt = "state/jobs/task-context.prompt.md"
        (cli.ROOT / prompt).write_text("do the assigned work")
        job = {
            "id": "task-context", "kind": "agent-task", "state": "ready",
            "model": "test-model", "role": "worker", "task": "do the work",
            "attempts": 1, "agent_generation": 2, "prompt": prompt,
            "original_prompt": prompt, "context_state": context_state,
            "task_contract": default_task_contract("do the work", cli.ROOT, "test:context"),
        }
        if session:
            job["opencode_session"] = session
        path = cli.ROOT / "state/jobs/task-context.json"
        cli.atomic_json(path, job)
        commands = []

        def launch(job_, path_, decision, inventory, command, **kwargs):
            commands.append(command)
            event = {"type": "step_finish", "sessionID": "ses_compaction",
                     "part": {"tokens": {"total": 990, "input": 980, "output": 10}}}
            kwargs["stdout"].write((json.dumps(event) + "\n").encode())
            kwargs["stdout"].flush()
            return {"state": "started", "inference_lease": {"lease_id": "test"},
                    "launch": {"process": SimpleNamespace(returncode=0)}}

        def close(job_, path_, context, outcome):
            job_.update(state="run_finished", exit_code=0)
            return {"state": "closed"}

        outcome = {"returncode": 0, "preempted": False, "usage": {},
                   "elapsed_seconds": 1}
        if budget_stop:
            outcome.update(budget_checkpoint={"state": "checkpoint_required",
                                              "reason": "task_seconds"},
                           session="ses_compaction")
        patches = [
            patch("ecosystem.executor.snapshot", return_value={}),
            patch("ecosystem.executor.choose", side_effect=lambda ready, *_: (*ready[0], "test")),
            patch("ecosystem.scheduler.scheduling_document", return_value={}),
            patch("ecosystem.executor.job_admitted_in_current_mode", return_value=True),
            patch("ecosystem.executor.resource_mode", return_value="normal"),
            patch("ecosystem.executor.route", return_value={"action": "run", "model": "test-model",
                                                           "reason": "test", "context_tokens": 1000}),
            patch("ecosystem.executor.realize", return_value={"state": "realized", "model": "test-model"}),
            patch("ecosystem.executor.launch_runner_round", side_effect=launch),
            patch("ecosystem.executor._run_preemptibly", return_value=outcome),
            patch("ecosystem.executor.gated_child_wait", return_value={"state": "reaped"}),
            patch("ecosystem.executor.close_runner_round", side_effect=close),
            patch("ecosystem.verification.enqueue"),
        ]
        for entry in patches:
            stack.enter_context(entry)
        result = execute_next()
        saved = json.loads(path.read_text())
        assert not list((cli.ROOT / "state/jobs").glob("*.handoff*"))
        assert not list((cli.ROOT / "state/jobs").glob("*.rollover.md"))
        assert not list((cli.ROOT / "logs/runs").glob("*.context-*.opencode.log"))
        return result, saved, commands


def test_near_full_context_finishes_without_detaching_session():
    result, saved, commands = _execute_context_case()
    assert result is True
    assert saved["state"] == "completed"
    assert saved["opencode_session"] == "ses_compaction"
    assert saved["context_state"] == "running"
    assert commands[0][commands[0].index("--session") + 1] == "ses_compaction"


def test_legacy_handoff_request_resumes_retained_session():
    result, saved, commands = _execute_context_case("handoff_requested")
    assert result is True
    assert saved["state"] == "completed"
    assert saved["context_state"] == "running"
    assert "--session" in commands[0]


def test_detached_legacy_context_is_deferred_for_recovery():
    result, saved, commands = _execute_context_case("handoff_durable", session=None)
    assert result is False
    assert saved["state"] == "queued"
    assert saved["context_state"] == "handoff_durable"
    assert commands == []


def test_budget_stop_retains_session_without_consuming_handoff():
    result, saved, _ = _execute_context_case(session=None, budget_stop=True)
    assert result is True
    assert saved["state"] == "ready"
    assert saved["logical_run_state"] == "continuing"
    assert saved["opencode_session"] == "ses_compaction"
    assert saved["resume_available"] is True
    assert saved["budget_usage"] == {}
    assert "budget_handoff" not in saved


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_session_lookup_skips_non_event_json,
        test_near_full_context_finishes_without_detaching_session,
        test_legacy_handoff_request_resumes_retained_session,
        test_detached_legacy_context_is_deferred_for_recovery,
        test_budget_stop_retains_session_without_consuming_handoff,
    ))
