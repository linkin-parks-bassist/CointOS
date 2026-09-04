"""Behavioral tests for the unprivileged lifecycle checkpoint consumer."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from survival import checkpoint


REQUEST_FIELDS = {
    "schema_version", "request_id", "job_ids", "requested_at",
    "deadline_monotonic",
}
RESULT_FIELDS = {
    "schema_version", "request_id", "job_id", "state", "opencode_session",
}


def checkpoint_request(request_id="telegram-1", job_ids=None, deadline=10.0):
    if job_ids is None:
        job_ids = ["task-active"]
    return {
        "schema_version": 1,
        "request_id": request_id,
        "job_ids": job_ids,
        "requested_at": "2026-09-05T00:00:00+00:00",
        "deadline_monotonic": deadline,
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_job(agent_state, job_id, state="running", session=None, output=None):
    job = {"id": job_id, "kind": "agent-task", "state": state}
    if session is not None:
        job["opencode_session"] = session
    if output is not None:
        job["output"] = output
    write_json(agent_state / "jobs" / f"{job_id}.json", job)
    return job


def write_session(agent_state, job_id, session):
    path = agent_state.parent / "logs" / "runs" / f"{job_id}.opencode.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "type": "step_start",
        "sessionID": session,
    }) + "\n", encoding="utf-8")
    return path


def read_result(result_root, request_id, job_id):
    return json.loads(
        (result_root / request_id / f"{job_id}.json").read_text(encoding="utf-8")
    )


def test_checkpoint_request_schema_is_exact_and_canonical():
    request = checkpoint_request(job_ids=["task-alpha", "task-beta"])
    assert checkpoint.validate_checkpoint_request(request) == request

    malformed = []
    malformed.append({**request, "unexpected": True})
    malformed.append({key: value for key, value in request.items() if key != "requested_at"})
    malformed.append({**request, "schema_version": True})
    malformed.append({**request, "request_id": "telegram-01"})
    malformed.append({**request, "job_ids": ["task-beta", "task-alpha"]})
    malformed.append({**request, "job_ids": ["task-alpha", "task-alpha"]})
    for job_id in ("", ".", "..", "../task-alpha", "/tmp/task-alpha", "a/b", "a\\b"):
        malformed.append({**request, "job_ids": [job_id]})
    malformed.append({**request, "requested_at": "not-a-time"})
    for deadline in (True, -1, math.nan, math.inf, -math.inf):
        malformed.append({**request, "deadline_monotonic": deadline})

    for value in malformed:
        with unittest.TestCase().assertRaisesRegex(ValueError, "checkpoint request"):
            checkpoint.validate_checkpoint_request(value)


def test_checkpoint_result_schema_is_exact_and_request_scoped():
    result = {
        "schema_version": 1,
        "request_id": "telegram-1",
        "job_id": "task-alpha",
        "state": "checkpointed",
        "opencode_session": "ses_alpha",
    }
    assert checkpoint.validate_checkpoint_result(
        result, "telegram-1", "task-alpha",
    ) == result
    malformed = [
        {**result, "unexpected": True},
        {key: value for key, value in result.items() if key != "state"},
        {**result, "schema_version": True},
        {**result, "request_id": "telegram-2"},
        {**result, "job_id": "task-beta"},
        {**result, "state": "sleep_finished"},
        {**result, "opencode_session": None},
        {**result, "state": "unsupported"},
    ]
    for value in malformed:
        with unittest.TestCase().assertRaisesRegex(ValueError, "checkpoint result"):
            checkpoint.validate_checkpoint_result(
                value, "telegram-1", "task-alpha",
            )


def test_mixed_checkpoint_outcomes_publish_one_exact_atomic_result_per_job():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        result_root = root / "results"
        request_path = root / "requests/telegram-1.json"
        job_ids = [
            "task-active", "task-finished", "task-malformed", "task-missing",
            "task-unsupported",
        ]
        write_json(request_path, checkpoint_request(job_ids=job_ids))
        write_job(
            agent_state,
            "task-active",
            session="ses_active",
            output="logs/runs/task-active.opencode.log",
        )
        write_session(agent_state, "task-active", "ses_active")
        write_job(agent_state, "task-finished", state="completed")
        write_json(agent_state / "jobs/task-malformed.json", ["not", "a", "record"])
        write_job(agent_state, "task-unsupported")

        processed = checkpoint.process_checkpoint_request(
            request_path, agent_state, result_root, now=lambda: 1.0,
        )

        assert processed == len(job_ids)
        expected = {
            "task-active": ("checkpointed", "ses_active"),
            "task-finished": ("already_terminal", None),
            "task-malformed": ("unsupported", None),
            "task-missing": ("unsupported", None),
            "task-unsupported": ("unsupported", None),
        }
        assert sorted((result_root / "telegram-1").glob("*.json")) == [
            result_root / "telegram-1" / f"{job_id}.json" for job_id in job_ids
        ]
        for job_id, (state, session) in expected.items():
            result = read_result(result_root, "telegram-1", job_id)
            assert set(result) == RESULT_FIELDS
            assert result == {
                "schema_version": 1,
                "request_id": "telegram-1",
                "job_id": job_id,
                "state": state,
                "opencode_session": session,
            }
        assert json.loads(
            (agent_state / "jobs/task-active.json").read_text(encoding="utf-8")
        )["state"] == "running"


def test_deadline_expiry_is_terminal_without_inspecting_later_job_state():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        result_root = root / "results"
        request_path = root / "requests/telegram-1.json"
        write_json(request_path, checkpoint_request(deadline=2.0))
        write_job(
            agent_state,
            "task-active",
            session="ses_active",
            output="logs/runs/task-active.opencode.log",
        )
        write_session(agent_state, "task-active", "ses_active")

        assert checkpoint.process_checkpoint_request(
            request_path, agent_state, result_root, now=lambda: 2.0,
        ) == 1
        assert read_result(result_root, "telegram-1", "task-active") == {
            "schema_version": 1,
            "request_id": "telegram-1",
            "job_id": "task-active",
            "state": "deadline_expired",
            "opencode_session": None,
        }


def test_replay_preserves_the_exact_first_terminal_result():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        result_root = root / "results"
        request_path = root / "requests/telegram-1.json"
        write_json(request_path, checkpoint_request())
        write_job(
            agent_state,
            "task-active",
            session="ses_first",
            output="logs/runs/task-active.opencode.log",
        )
        write_session(agent_state, "task-active", "ses_first")
        checkpoint.process_checkpoint_request(
            request_path, agent_state, result_root, now=lambda: 1.0,
        )
        result_path = result_root / "telegram-1/task-active.json"
        first_bytes = result_path.read_bytes()

        write_json(agent_state / "jobs/task-active.json", {"corrupt": True})
        assert checkpoint.process_checkpoint_request(
            request_path, agent_state, result_root, now=lambda: 20.0,
        ) == 1
        assert result_path.read_bytes() == first_bytes


def test_results_are_request_scoped_when_the_same_job_runs_again():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        result_root = root / "results"
        first_request = root / "requests/telegram-1.json"
        second_request = root / "requests/telegram-2.json"
        write_json(first_request, checkpoint_request("telegram-1", deadline=10.0))
        write_job(
            agent_state,
            "task-active",
            session="ses_first",
            output="logs/runs/task-active.opencode.log",
        )
        write_session(agent_state, "task-active", "ses_first")
        checkpoint.process_checkpoint_request(
            first_request, agent_state, result_root, now=lambda: 1.0,
        )

        write_json(second_request, checkpoint_request("telegram-2", deadline=20.0))
        write_job(
            agent_state,
            "task-active",
            session="ses_second",
            output="logs/runs/task-active.opencode.log",
        )
        write_session(agent_state, "task-active", "ses_second")
        checkpoint.process_checkpoint_request(
            second_request, agent_state, result_root, now=lambda: 11.0,
        )

        assert read_result(
            result_root, "telegram-1", "task-active",
        )["opencode_session"] == "ses_first"
        assert read_result(
            result_root, "telegram-2", "task-active",
        )["opencode_session"] == "ses_second"


def test_claimed_session_must_resolve_in_the_canonical_durable_output():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        result_root = root / "results"
        request_path = root / "requests/telegram-1.json"
        write_json(request_path, checkpoint_request())
        write_job(
            agent_state,
            "task-active",
            session="ses_claimed",
            output="logs/runs/task-active.opencode.log",
        )
        write_session(agent_state, "task-active", "ses_other")

        checkpoint.process_checkpoint_request(
            request_path, agent_state, result_root, now=lambda: 1.0,
        )

        assert read_result(
            result_root, "telegram-1", "task-active",
        )["state"] == "unsupported"


def test_job_output_cannot_escape_the_canonical_handoff_root():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        result_root = root / "results"
        request_path = root / "requests/telegram-1.json"
        sentinel = root / "outside.log"
        sentinel.write_text('{"sessionID":"ses_escape"}\n', encoding="utf-8")
        write_json(request_path, checkpoint_request())
        write_job(
            agent_state,
            "task-active",
            session="ses_escape",
            output="../outside.log",
        )

        checkpoint.process_checkpoint_request(
            request_path, agent_state, result_root, now=lambda: 1.0,
        )

        assert read_result(
            result_root, "telegram-1", "task-active",
        )["state"] == "unsupported"
        assert sentinel.read_text(encoding="utf-8") == '{"sessionID":"ses_escape"}\n'


def test_symlinked_job_and_handoff_directories_are_not_consumed():
    for linked_boundary in ("jobs", "logs"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            agent_state = root / "agent-state"
            result_root = root / "results"
            request_path = root / "requests/telegram-1.json"
            outside = root / "outside"
            outside.mkdir()
            write_json(request_path, checkpoint_request())
            if linked_boundary == "jobs":
                (agent_state).mkdir()
                outside_jobs = outside / "jobs"
                outside_jobs.mkdir()
                write_json(outside_jobs / "task-active.json", {
                    "id": "task-active",
                    "kind": "agent-task",
                    "state": "running",
                    "opencode_session": "ses_escape",
                    "output": "logs/runs/task-active.opencode.log",
                })
                (agent_state / "jobs").symlink_to(outside_jobs, target_is_directory=True)
                write_session(agent_state, "task-active", "ses_escape")
            else:
                write_job(
                    agent_state,
                    "task-active",
                    session="ses_escape",
                    output="logs/runs/task-active.opencode.log",
                )
                outside_logs = outside / "logs"
                (outside_logs / "runs").mkdir(parents=True)
                (outside_logs / "runs/task-active.opencode.log").write_text(
                    '{"sessionID":"ses_escape"}\n', encoding="utf-8",
                )
                (root / "logs").symlink_to(outside_logs, target_is_directory=True)

            checkpoint.process_checkpoint_request(
                request_path, agent_state, result_root, now=lambda: 1.0,
            )

            assert read_result(
                result_root, "telegram-1", "task-active",
            )["state"] == "unsupported"


def test_symlinked_request_and_result_directories_fail_before_external_access():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        outside = root / "outside"
        outside.mkdir()
        outside_request = outside / "telegram-1.json"
        write_json(outside_request, checkpoint_request())
        linked_requests = root / "requests"
        linked_requests.symlink_to(outside, target_is_directory=True)
        with unittest.TestCase().assertRaisesRegex(ValueError, "checkpoint request"):
            checkpoint.process_checkpoint_request(
                linked_requests / "telegram-1.json",
                agent_state,
                root / "results",
                now=lambda: 1.0,
            )

        request_root = root / "real-requests"
        request_path = request_root / "telegram-1.json"
        write_json(request_path, checkpoint_request())
        write_job(agent_state, "task-active", state="completed")
        result_root = root / "results"
        result_root.mkdir()
        outside_results = outside / "results"
        outside_results.mkdir()
        (result_root / "telegram-1").symlink_to(
            outside_results, target_is_directory=True,
        )
        with unittest.TestCase().assertRaisesRegex(ValueError, "result directory"):
            checkpoint.process_checkpoint_request(
                request_path, agent_state, result_root, now=lambda: 1.0,
            )
        assert list(outside_results.iterdir()) == []


def test_request_path_identity_and_existing_result_schema_fail_closed():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        result_root = root / "results"
        request_path = root / "requests/telegram-2.json"
        write_json(request_path, checkpoint_request("telegram-1"))
        with unittest.TestCase().assertRaisesRegex(ValueError, "identity"):
            checkpoint.process_checkpoint_request(
                request_path, agent_state, result_root, now=lambda: 1.0,
            )

        write_json(request_path, checkpoint_request("telegram-2"))
        write_json(result_root / "telegram-2/task-active.json", {
            "schema_version": 1,
            "request_id": "telegram-1",
            "job_id": "task-active",
            "state": "checkpointed",
            "opencode_session": "ses_stale",
        })
        with unittest.TestCase().assertRaisesRegex(ValueError, "checkpoint result"):
            checkpoint.process_checkpoint_request(
                request_path, agent_state, result_root, now=lambda: 1.0,
            )


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions
    )
