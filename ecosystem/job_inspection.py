"""Read-only helpers for inspecting durable CointOS agent jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


ACTIVE_STATES = frozenset({
    "queued", "ready", "claimed", "runner_starting", "running", "awaiting_verification",
    "reconciliation_required",
})
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


def validate_job_id(value: str) -> str:
    if not value.startswith("task-") or not value[5:].replace("-", "").isalnum():
        raise ValueError("job ID must look like task-abc123")
    return value


def load_job(root: Path, job_id: str) -> dict[str, Any]:
    validate_job_id(job_id)
    path = root / "state" / "jobs" / f"{job_id}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("id") != job_id:
        raise ValueError(f"job record identity does not match {job_id}")
    return value


def _process_start_ticks(pid: int) -> int | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return int(fields[19])
    except (FileNotFoundError, PermissionError, OSError, ValueError, IndexError):
        return None


def runner_observation(job: dict[str, Any]) -> dict[str, Any]:
    pid = job.get("executor_pid")
    expected_ticks = job.get("executor_start_ticks")
    if type(pid) is not int or pid <= 0:
        return {"pid": pid, "state": "not_registered", "identity_matches": None}

    observed_ticks = _process_start_ticks(pid)
    if observed_ticks is None:
        return {"pid": pid, "state": "absent", "identity_matches": False}
    identity_matches = (observed_ticks == expected_ticks
                        if type(expected_ticks) is int else None)
    return {
        "pid": pid,
        "state": ("alive" if identity_matches else
                  "exists_unverified" if identity_matches is None else "pid_reused"),
        "identity_matches": identity_matches,
        "expected_start_ticks": expected_ticks,
        "observed_start_ticks": observed_ticks,
    }


def summarize_job(root: Path, job: dict[str, Any]) -> dict[str, Any]:
    state = job.get("state")
    close = job.get("runner_close_outcome")
    close = close if isinstance(close, dict) else {}
    runner = runner_observation(job)
    clean_process_exit = (
        state == "completed"
        and job.get("exit_code") == 0
        and close.get("state") == "reaped"
        and close.get("process_group_alive") is False
    )
    return {
        "id": job.get("id"),
        "state": state,
        "terminal": state in TERMINAL_STATES,
        "clean_process_exit": clean_process_exit,
        "model": job.get("model"),
        "agent_name": job.get("agent_name"),
        "attempts": job.get("attempts"),
        "generation": job.get("agent_generation"),
        "session": job.get("opencode_session"),
        "created_at": job.get("created_at"),
        "started_at": job.get("last_started_at"),
        "completed_at": job.get("completed_at"),
        "updated_at": job.get("updated_at"),
        "exit_code": job.get("exit_code"),
        "error": job.get("error") or job.get("last_error"),
        "runner": runner,
        "runner_close": close or None,
        "budget_usage": job.get("budget_usage"),
        "output_log": str(root / "logs" / "runs" / f"{job.get('id')}.opencode.log"),
    }


def iter_jobs(root: Path) -> Iterable[dict[str, Any]]:
    for path in (root / "state" / "jobs").glob("task-*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("kind") == "agent-task":
            yield value


def compact(value: Any, limit: int = 100) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"
