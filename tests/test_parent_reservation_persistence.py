"""Regression: cached parent write-back clobbers a durable child reservation.

R5 shared budget enforcement: execute_next caches the parent job in memory
for the whole runner round and, before close, persists that cached copy
together with the observed usage (pre-close write in executor.py). A
managed caller that enqueues a child during the launch window reaches the
real cli.enqueue_child, which reloads the parent under task-enqueue.lock,
deducts the child's 300 task_seconds from the parent's 600
remaining_budget, and durably records child_reservations plus the child
task. The cached write-back then overwrites the reserved parent with the
stale 600s budget, losing the reduced remaining_budget and
child_reservations while the durable child still exists.

The test drives the real execute_next and _run_preemptibly against a
harmless real subprocess. The fake launch starts that subprocess and calls
the real enqueue_child on the cached parent before returning; the fake
close neither writes nor mutates the parent. Expected RED: the durable
parent keeps 600 instead of the reserved 300 task_seconds. The managed
enqueue_child caller is not wired yet; this is composition readiness, not
observed live damage.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli
from ecosystem.executor import execute_next
from tests.test_mvp_task_contracts import accepted_workspace_policy, contract

PARENT_ID = "task-parent"
CHILD_KEY = "test:parent-reservation"
PARENT_BUDGET = {
    "run_seconds": 300,
    "task_seconds": 600,
    "maximum_attempts": 2,
    "maximum_output_bytes": 65536,
    "maximum_evidence_items": 20,
    "maximum_children": 2,
}
CHILD_BUDGET = {
    "run_seconds": 1,
    "task_seconds": 300,
    "maximum_attempts": 1,
    "maximum_output_bytes": 1,
    "maximum_evidence_items": 1,
    "maximum_children": 0,
}


def _utc_stamp():
    return (datetime.now(timezone.utc).replace(microsecond=0)).isoformat()


def test_parent_reservation_survives_cached_parent_write_back():
    with tempfile.TemporaryDirectory() as temporary, \
            patch.object(cli, "ROOT", Path(temporary)):
        root = Path(temporary).resolve()
        cli.initialize()
        for relative in ("ecosystem", "workspace_notes", "roles", "logs/runs"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "roles/_base.md").write_text("# Base Agent\n", encoding="utf-8")
        accepted_workspace_policy(root)
        (root / "state/jobs" / f"{PARENT_ID}.prompt.md").write_text(
            "do the work", encoding="utf-8")
        parent = {
            "id": PARENT_ID, "kind": "agent-task", "state": "ready",
            "role": "worker", "source": "local-cli", "model": "test-model",
            "attempts": 0, "agent_generation": 1,
            "created_at": _utc_stamp(), "authority_profile": "worker",
            "remaining_budget": dict(PARENT_BUDGET),
            "task_contract": contract(root, budget=dict(PARENT_BUDGET)),
            "prompt": f"state/jobs/{PARENT_ID}.prompt.md",
        }
        parent_path = root / "state/jobs" / f"{PARENT_ID}.json"
        cli.atomic_json(parent_path, parent)
        child_contract = contract(
            root,
            scope={"workspace": str(root),
                   "read_paths": [str(root / "ecosystem")],
                   "write_paths": [str(root / "workspace_notes" / "child.md")]},
            budget=dict(CHILD_BUDGET),
            source_key=CHILD_KEY,
            parent_job_id=PARENT_ID,
        )
        child_id = f"task-{hashlib.sha256(CHILD_KEY.encode()).hexdigest()[:16]}"
        child_path = root / "state/jobs" / f"{child_id}.json"
        launched = []
        durable_at_close = []

        def fake_launch(job_, path_, decision, inventory, command, **kwargs):
            proc = subprocess.Popen(
                ["bash", "-c", "true"],
                start_new_session=True, stdin=subprocess.DEVNULL,
                stdout=kwargs["stdout"], stderr=subprocess.STDOUT)
            launched.append(proc)
            assert cli.enqueue_child(job_, child_contract, CHILD_KEY) == child_id
            saved = json.loads(path_.read_text(encoding="utf-8"))
            assert saved["remaining_budget"]["task_seconds"] == 300
            assert saved["child_reservations"][CHILD_KEY]["child_job_id"] == child_id
            assert child_path.exists()
            return {"state": "started",
                    "inference_lease": {"lease_id": "inf-test"},
                    "worker_lease": {"lease_id": "work-test"},
                    "launch": {"process": proc}}

        def fake_close(job_, path_, context, child_outcome):
            durable_at_close.append(json.loads(path_.read_text(encoding="utf-8")))
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
            patch("ecosystem.executor.job_admitted_in_current_mode",
                  return_value=True),
            patch("ecosystem.executor.cancel_proxy",
                  return_value={"state": "cancelled"}),
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
            for proc in launched:
                if proc.poll() is None:
                    proc.terminate()
                proc.wait()
        saved = json.loads(parent_path.read_text(encoding="utf-8"))
        assert saved["remaining_budget"]["task_seconds"] == 300, (
            f"cached parent write-back clobbered the child reservation: "
            f"remaining_budget.task_seconds="
            f"{saved['remaining_budget']['task_seconds']}, expected 300 (600 - 300)")
        assert saved["child_reservations"][CHILD_KEY]["child_job_id"] == child_id
        assert saved["remaining_budget"]["maximum_children"] == 1
        assert saved["attempts"] == 1
        assert child_path.exists()
        child = json.loads(child_path.read_text(encoding="utf-8"))
        assert child["state"] == "queued"
        assert child["idempotency_key"] == CHILD_KEY
        assert child["remaining_budget"]["task_seconds"] == 300
        usage = saved["budget_usage"]
        assert usage["task_seconds"] > 0
        assert usage["output_bytes"] == 0
        assert usage["attempts"] == 1
        assert durable_at_close


def load_tests(loader, tests, pattern):
    module = sys.modules[__name__]
    names = sorted(name for name in vars(module)
                   if name.startswith("test_") and callable(getattr(module, name)))
    return unittest.TestSuite(
        unittest.FunctionTestCase(getattr(module, name)) for name in names)
