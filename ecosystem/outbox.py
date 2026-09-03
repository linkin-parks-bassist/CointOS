"""Durable conditional outbound-message jobs."""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable

from ecosystem import cli


TERMINAL_STATES = {"completed", "failed"}


def enqueue(user_id: int, message: str = "", depends_on: str | None = None, result_of: str | None = None) -> str:
    job_id = f"outbox-{uuid.uuid4().hex[:16]}"
    job = {
        "id": job_id, "kind": "outbound-message", "state": "waiting" if depends_on else "queued",
        "attempts": 0, "created_at": cli.now(), "updated_at": cli.now(),
        "user_id": user_id, "message": message, "depends_on": depends_on, "result_of": result_of,
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
        return message
    output_path = cli.ROOT / dependency_job["output"] if dependency_job.get("output") else None
    clean = ""
    if output_path and output_path.exists():
        clean = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", output_path.read_text(encoding="utf-8", errors="replace")).strip()
    header = f"Job {dependency_job['id']} {dependency_job['state']} ({dependency_job['role']})."
    return header + ("\n\nResult (tail):\n" + clean[-3000:] if clean else "")


def drain(send: Callable[[int, str], None]) -> int:
    delivered = 0
    for path in sorted((cli.ROOT / "state/jobs").glob("outbox-*.json")):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job["state"] not in {"waiting", "queued"}:
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

