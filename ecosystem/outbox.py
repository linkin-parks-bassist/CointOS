"""Durable conditional outbound-message jobs."""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable

from ecosystem import cli


TERMINAL_STATES = {"completed", "failed", "rejected"}


def mark_interrupted_deliveries_unknown() -> int:
    """Do not replay a Telegram send whose prior delivery outcome is unknowable."""
    changed = 0
    for path in sorted((cli.ROOT / "state/jobs").glob("outbox-*.json")):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("state") != "sending":
            continue
        job.update(state="delivery_unknown", updated_at=cli.now(),
                   error="notifier stopped while delivery was in progress; not replayed")
        cli.atomic_json(path, job)
        cli.audit("outbox.delivery_unknown", job_id=job["id"], user_id=job["user_id"])
        changed += 1
    return changed


def enqueue(user_id: int, message: str = "", depends_on: str | None = None, result_of: str | None = None,
            origin_job: str | None = None, severity: str = "info", needs_response: bool = False) -> str:
    job_id = f"outbox-{uuid.uuid4().hex[:16]}"
    job = {
        "id": job_id, "kind": "outbound-message", "state": "waiting" if depends_on else "queued",
        "attempts": 0, "created_at": cli.now(), "updated_at": cli.now(),
        "user_id": user_id, "message": message, "depends_on": depends_on, "result_of": result_of,
        "origin_job": origin_job, "severity": severity, "needs_response": needs_response,
    }
    cli.atomic_json(cli.ROOT / "state/jobs" / f"{job_id}.json", job)
    cli.audit("outbox.queued", job_id=job_id, depends_on=depends_on, user_id=user_id)
    return job_id


def dependency(job: dict) -> dict | None:
    dependency_id = job.get("depends_on")
    if not dependency_id:
        return None
    path = cli.ROOT / "state/jobs" / f"{dependency_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def render(job: dict, dependency_job: dict | None) -> str:
    message = job.get("message", "")
    if not job.get("result_of") or not dependency_job:
        prefix = {"warning":"Important warning: ", "question":"Question that needs David's input: ", "approval":"Approval needed: "}.get(job.get("severity"), "")
        suffix = "\n\nReply naturally; I’ll route your answer with this conversation in context." if job.get("needs_response") else ""
        return prefix + message + suffix
    output_path = cli.ROOT / dependency_job["output"] if dependency_job.get("output") else None
    clean = ""
    if output_path and output_path.exists():
        clean = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", output_path.read_text(encoding="utf-8", errors="replace")).strip()
    name = dependency_job.get("agent_name", "The agent")
    if dependency_job["state"] == "completed":
        header = f"{name}'s work passed an independent check."
    elif dependency_job["state"] == "rejected":
        header = f"{name}'s run ended, but an independent check did not accept the work."
    else:
        header = f"{name} ran into trouble with the earlier work and it may need attention."
    verification = dependency_job.get("verification_summary")
    if verification:
        header += f"\n\nVerification: {verification}"
    show_output = clean and dependency_job["state"] != "rejected"
    return header + ("\n\nResult (tail):\n" + clean[-3000:] if show_output else "")


def drain(send: Callable[[int, str], None]) -> int:
    delivered = 0
    for path in sorted((cli.ROOT / "state/jobs").glob("outbox-*.json")):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job["state"] not in {"waiting", "queued"}:
            continue
        if job.get("attempts", 0) >= 3:
            job.update(state="failed", updated_at=cli.now(), error="notification generation or delivery failed three times")
            cli.atomic_json(path, job)
            cli.audit("outbox.exhausted", job_id=job["id"], user_id=job["user_id"])
            continue
        dependency_job = dependency(job)
        if job.get("depends_on") and (not dependency_job or dependency_job.get("state") not in TERMINAL_STATES):
            continue
        job.update(state="sending", attempts=job["attempts"] + 1, updated_at=cli.now())
        cli.atomic_json(path, job)
        try:
            send(int(job["user_id"]), render(job, dependency_job))
            job.update(state="delivered", updated_at=cli.now())
            delivered += 1
            cli.audit("outbox.delivered", job_id=job["id"], user_id=job["user_id"])
        except Exception as error:
            job.update(state="waiting", updated_at=cli.now(), error=f"{type(error).__name__}: {error}")
            cli.audit("outbox.delivery_failed", job_id=job["id"], error=job["error"])
        cli.atomic_json(path, job)
    return delivered
