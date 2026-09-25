"""Plain-data job transitions after a runner's physical close is verified.

The caller owns durable-marker checks, persistence, audit, and publication.
"""


def budget_checkpoint_job(job: dict, checkpoint: dict, session: str | None,
                          at: str) -> dict:
    """Return the continuation or terminal budget-checkpoint job record."""
    updated = job.copy()
    if session:
        updated["opencode_session"] = session
    if updated.get("opencode_session"):
        updated.update(state="ready", logical_run_state="continuing",
                       budget_outcome=checkpoint, resume_available=True,
                       budget_usage={}, updated_at=at)
    else:
        updated.update(state="checkpoint_required", logical_run_state="terminal",
                       budget_outcome=checkpoint, resume_available=False,
                       updated_at=at)
    updated.pop("executor_pid", None)
    return updated


def preempted_job(job: dict, session: str | None, reason: str,
                  at: str) -> dict:
    """Return the ready job after a recoverable preemption."""
    updated = job.copy()
    if session:
        updated["opencode_session"] = session
    updated["resume_available"] = bool(session)
    updated.pop("executor_pid", None)
    updated.pop("pending_preemption_reason", None)
    updated.update(state="ready", updated_at=at,
                   last_preemption_reason=reason,
                   preemption_count=int(job.get("preemption_count", 0)) + 1)
    return updated
