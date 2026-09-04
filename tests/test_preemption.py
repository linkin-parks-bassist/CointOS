import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli
from ecosystem.executor import _run_preemptibly, recover_abandoned_jobs


def test_higher_priority_work_preempts_and_preserves_session():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        running_path = cli.ROOT / "state/jobs/task-background.json"
        running = {
            "id": "task-background", "kind": "agent-task", "state": "running",
            "role": "steward", "source": "watchdog:review", "dispatch_count": 0,
        }
        waiting = {
            "id": "task-user", "kind": "agent-task", "state": "queued",
            "role": "worker", "source": "telegram:42",
        }
        cli.atomic_json(running_path, running)
        cli.atomic_json(cli.ROOT / "state/jobs/task-user.json", waiting)
        output_path = cli.ROOT / "logs/runs/task-background.opencode.log"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('{"sessionID":"ses_preemption_test"}\n', encoding="utf-8")
        with open(os.devnull, "rb") as prompt, output_path.open("ab") as output:
            outcome = _run_preemptibly(
                ["bash", "-c", "sleep 60"], prompt, output, os.environ.copy(),
                running, running_path, output_path,
            )
        assert outcome["preempted"]
        assert outcome["session"] == "ses_preemption_test"
        assert "higher-priority job task-user" in outcome["reason"]


def test_abandoned_running_job_returns_to_model_routing():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        path = cli.ROOT / "state/jobs/task-abandoned.json"
        cli.atomic_json(path, {
            "id": "task-abandoned", "kind": "agent-task", "state": "running",
            "role": "worker", "source": "local-cli", "model": "old-model",
            "output": "logs/runs/missing.log",
        })
        assert recover_abandoned_jobs() == 1
        recovered = json.loads(path.read_text(encoding="utf-8"))
        assert recovered["state"] == "queued"
        assert recovered["model"] is None
        assert recovered["requested_model"] == "old-model"
        assert not recovered["resume_available"]


def test_context_rollover_preempts_at_seventy_five_percent():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        cli.initialize()
        path = cli.ROOT / "state/jobs/task-context.json"
        running = {
            "id": "task-context", "kind": "agent-task", "state": "running",
            "role": "worker", "source": "local-cli", "context_tokens": 100,
        }
        cli.atomic_json(path, running)
        output_path = cli.ROOT / "logs/runs/task-context.opencode.log"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "type": "step_finish", "sessionID": "ses_context_test",
            "part": {"tokens": {"total": 75, "input": 70, "output": 5}},
        }
        output_path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        with open(os.devnull, "rb") as prompt, output_path.open("ab") as output:
            outcome = _run_preemptibly(
                ["bash", "-c", "sleep 60"], prompt, output, os.environ.copy(),
                running, path, output_path,
            )
        assert outcome["preempted"]
        assert outcome["context_rollover"]
        assert outcome["session"] == "ses_context_test"
        assert "75/100" in outcome["reason"]


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite([
        unittest.FunctionTestCase(test_higher_priority_work_preempts_and_preserves_session),
        unittest.FunctionTestCase(test_abandoned_running_job_returns_to_model_routing),
        unittest.FunctionTestCase(test_context_rollover_preempts_at_seventy_five_percent),
    ])
