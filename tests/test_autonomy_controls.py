"""Focused checks for the cointos stop/halt controls without touching live units."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ecosystem import cli


def write_job(root, job_id, **fields):
    record = {"id": job_id, "kind": "agent-task", "state": "queued",
              "updated_at": "2026-09-26T00:00:00+00:00", **fields}
    path = root / "state/jobs" / f"{job_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def load_job(path):
    return json.loads(path.read_text(encoding="utf-8"))


def with_root(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            cli.initialize()
            function(Path(temporary))
    run.__name__ = function.__name__
    return run


@with_root
def test_emergency_stop_cancels_autonomous_work_and_sares_survivor_and_user_work(root):
    spawner = write_job(root, "task-spawner",
                        source="spawner:queued:/proj/.knowledge/what/is/queued/item.md",
                        agent_name="Agent", role="worker", state="queued")
    running = write_job(root, "task-running",
                        source="spawner:urgent:/proj/.knowledge/what/is/urgent/item.md",
                        agent_name="Agent", role="worker", state="running")
    survivor = write_job(root, "task-survivor", source="spawner:maintenance:/proj",
                         agent_name="Survivor", role="sole_survivor", state="running")
    user = write_job(root, "task-user", source="telegram:42", agent_name="Noether",
                     role="worker", state="queued", user_directed_origin="telegram_contact")
    done = write_job(root, "task-done",
                     source="spawner:queued:/proj/.knowledge/what/is/queued/other.md",
                     agent_name="Agent", role="worker", state="done")
    results = cli.emergency_stop()
    assert (root / "state/PAUSED").exists()
    assert len(results) == 2
    assert sorted(result["agent_name"] for result in results) == ["Agent", "Agent"]
    assert {result["cancelled"] for result in results} == {True, False}
    cancelled = load_job(spawner)
    assert cancelled["state"] == "cancelled"
    assert cancelled["logical_run_state"] == "terminal"
    assert "cancellation_requested_at" not in cancelled
    requested = load_job(running)
    assert requested["state"] == "running"
    assert requested["cancellation_requested_at"]
    survivor_saved = load_job(survivor)
    assert survivor_saved["state"] == "running"
    assert "cancellation_requested_at" not in survivor_saved
    assert "cancelled_at" not in survivor_saved
    assert load_job(user)["state"] == "queued"
    assert load_job(done)["state"] == "done"


@with_root
def test_emergency_stop_include_user_work_cancels_user_directed_jobs(root):
    user = write_job(root, "task-user", source="telegram:42", agent_name="Noether",
                     role="worker", state="queued", user_directed_origin="local_operator")
    cli.emergency_stop()
    assert load_job(user)["state"] == "queued"
    cli.emergency_stop(include_user_work=True)
    saved = load_job(user)
    assert saved["state"] == "cancelled"
    assert saved["cancellation_reason"] == "authenticated contact requested cancellation"


@with_root
def test_halt_stops_timer_and_path_units_before_agent_units_and_unloads_models(root):
    calls = []
    unloaded = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0, stderr="")

    with patch("ecosystem.cli.subprocess.run", side_effect=fake_run), \
         patch("ecosystem.resource_control.unload_all_models",
               side_effect=lambda: unloaded.append(True)):
        notes = cli.halt()
    assert (root / "state/PAUSED").exists()
    assert calls == [
        ["systemctl", "--user", "stop", "agent-*.timer", "agent-*.path"],
        ["systemctl", "--user", "stop", "agent-*"],
    ]
    assert unloaded == [True]
    assert notes == []


@with_root
def test_halt_records_failures_and_returns_when_the_backend_is_unreachable(root):
    def fake_run(command, **_kwargs):
        return SimpleNamespace(returncode=1, stderr="Failed to stop agent-ecosystem.timer\n")

    def unload():
        raise ConnectionError("backend unreachable")

    with patch("ecosystem.cli.subprocess.run", side_effect=fake_run), \
         patch("ecosystem.resource_control.unload_all_models", side_effect=unload):
        notes = cli.halt()
    assert (root / "state/PAUSED").exists()
    assert notes == [
        "Failed to stop agent-ecosystem.timer",
        "model unload: ConnectionError: backend unreachable",
    ]


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
