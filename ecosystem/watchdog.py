"""Cheap periodic checks which enqueue a reasoning Steward when due."""
from __future__ import annotations
import fcntl, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from ecosystem import cli

CONFIG = cli.ROOT / "config/watchdog.json"
SOURCE = "watchdog:periodic-steward"

def service_state(name: str) -> str:
    result = subprocess.run(["systemctl", "--user", "is-active", name], text=True, capture_output=True)
    return result.stdout.strip() or "unknown"

def findings(config: dict) -> list[str]:
    now = datetime.now(timezone.utc)
    found = []
    if service_state("agent-telegram.service") != "active": found.append("Telegram gateway is not active.")
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("kind") == "agent-task" and job.get("state") == "running":
            age = (now - datetime.fromisoformat(job["updated_at"])).total_seconds()
            if age >= config["running_job_warn_seconds"]: found.append(f"{job['id']} has run for {int(age)} seconds.")
            output = cli.ROOT / job.get("output", "")
            if output.exists() and now.timestamp() - output.stat().st_mtime >= config["output_idle_warn_seconds"]:
                found.append(f"{job['id']} output has not advanced for at least {config['output_idle_warn_seconds']} seconds.")
    return found

def pending_review() -> bool:
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("source") == SOURCE and job.get("state") in {"queued", "ready", "running"}: return True
    return False

def tick() -> str:
    cli.initialize()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    lock_path = cli.ROOT / "state/watchdog.lock"
    with lock_path.open("w") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return "watchdog already active"
        state_path = cli.ROOT / "state/watchdog.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        now = datetime.now(timezone.utc)
        last = datetime.fromisoformat(state["last_review_enqueued_at"]) if state.get("last_review_enqueued_at") else None
        due = not last or (now-last).total_seconds() >= config["steward_review_seconds"]
        issues = findings(config)
        if (due or issues) and not pending_review() and not (cli.ROOT / "state/PAUSED").exists():
            issue_text = "\n".join(f"- {item}" for item in issues) or "- No deterministic warning; perform the scheduled qualitative review."
            task = f"""Perform the periodic ecosystem sanity review.

Work from `/home/david/agent-ecosystem`. Read the last 30 conversational entries
in `/home/david/agent-ecosystem/state/conversations` without copying secrets into
durable notes. Review recent audit events, failed/running jobs, executor output
tails, model choices and rationales, systemd user-service state, and
`/home/david/agent-ecosystem/docs/status.md`.

Deterministic findings at enqueue time:
{issue_text}

Look for confusing or dishonest bot replies, missed context, jobs that did not produce what David requested, stalls, notification failures, unsafe behavior, and documentation drift. Make bounded user-level fixes when evidence is clear; run tests; update status/ADRs when warranted. You may enqueue a focused follow-up job if another role/model is more appropriate. Do not perform approval-required actions. Send David a concise evidence-based handoff."""
            job_id = cli.enqueue_task("steward", task, source=SOURCE, model=config["review_model"], model_reason="Pinned small control model chosen for frequent low-latency transcript and health review.")
            state.update(last_review_enqueued_at=now.isoformat(), last_job_id=job_id, last_findings=issues)
            cli.atomic_json(state_path, state); cli.audit("watchdog.steward_enqueued", job_id=job_id, findings=len(issues))
            return f"enqueued {job_id}"
        state.update(last_tick_at=now.isoformat(), last_findings=issues)
        cli.atomic_json(state_path, state)
        return "healthy; review not due" if not issues else f"findings={len(issues)}; review already pending"

if __name__ == "__main__": print(tick())
