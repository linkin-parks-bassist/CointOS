"""Cheap periodic checks which enqueue a reasoning Steward when due."""
from __future__ import annotations
import fcntl, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from ecosystem import cli
from ecosystem.steward_tasks import select
from ecosystem.models import snapshot

CONFIG = cli.ROOT / "config/watchdog.json"
SOURCE = "watchdog:periodic-steward"

def reconcile_verifications() -> list[str]:
    from ecosystem.verification import enqueue
    jobs = [json.loads(path.read_text(encoding="utf-8")) for path in (cli.ROOT / "state/jobs").glob("*.json")]
    linked = {job.get("verifies") for job in jobs if job.get("verifies")}
    repaired = []
    for job in jobs:
        if job.get("kind") == "agent-task" and job.get("state") == "awaiting_verification" and job["id"] not in linked:
            verifier_id = enqueue(job)
            repaired.append(job["id"])
            cli.audit("watchdog.verification_relinked", target_job_id=job["id"], verifier_job_id=verifier_id)
    return repaired

def service_state(name: str) -> str:
    result = subprocess.run(["systemctl", "--user", "is-active", name], text=True, capture_output=True)
    return result.stdout.strip() or "unknown"

def findings(config: dict) -> list[str]:
    now = datetime.now(timezone.utc)
    found = []
    if service_state("agent-telegram.service") != "active": found.append("Telegram gateway is not active.")
    try:
        inventory = snapshot()
        executor_config = json.loads((cli.ROOT / "config/executor-opencode.json").read_text(encoding="utf-8"))
        configured = set(executor_config.get("provider", {}).get("Lemonade", {}).get("models", {}))
        unregistered = sorted(item["id"] for item in inventory.get("models", []) if item["id"] not in configured)
        if unregistered:
            found.append("Downloaded models are not integrated into the executor catalogue: " + ", ".join(unregistered))
    except Exception as error:
        found.append(f"Model inventory handshake failed: {type(error).__name__}: {error}")
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("kind") == "agent-task" and job.get("state") == "running":
            age = (now - datetime.fromisoformat(job["updated_at"])).total_seconds()
            if age >= config["running_job_warn_seconds"]: found.append(f"{job['id']} has run for {int(age)} seconds.")
            output = cli.ROOT / job.get("output", "")
            if output.exists() and now.timestamp() - output.stat().st_mtime >= config["output_idle_warn_seconds"]:
                found.append(f"{job['id']} output has not advanced for at least {config['output_idle_warn_seconds']} seconds.")
        if job.get("kind") == "agent-task" and job.get("state") == "awaiting_verification":
            age = (now - datetime.fromisoformat(job["updated_at"])).total_seconds()
            linked = [candidate for candidate in (cli.ROOT / "state/jobs").glob("*.json")
                      if json.loads(candidate.read_text(encoding="utf-8")).get("verifies") == job["id"]]
            if not linked:
                found.append(f"{job['id']} is awaiting verification without a linked verifier.")
            elif age >= config["verification_warn_seconds"]:
                found.append(f"{job['id']} has awaited verification for {int(age)} seconds.")
    event_path = cli.ROOT / "logs/runs" / f"{now:%Y-%m-%d}.jsonl"
    if event_path.exists():
        recent_errors = []
        for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]:
            try: event = json.loads(line)
            except json.JSONDecodeError: continue
            age = (now - datetime.fromisoformat(event["at"])).total_seconds()
            if age <= config["event_error_window_seconds"] and event.get("event") in {"telegram.error", "outbox.delivery_failed"}:
                recent_errors.append(event.get("event"))
        if len(recent_errors) >= config["event_error_threshold"]:
            found.append(f"Recent event log contains an error storm: {len(recent_errors)} transport/delivery errors in {config['event_error_window_seconds']} seconds.")
    return found

def pending_review() -> bool:
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("source", "").startswith(SOURCE) and job.get("state") in {"queued", "ready", "running"}: return True
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
        from ecosystem.managed_inference import reconcile_dead_callers
        native_recovery = reconcile_dead_callers(cli.ROOT)
        from ecosystem.operator_inference import recover_abandoned_controllers
        operator_recovery = recover_abandoned_controllers(cli.ROOT)
        from ecosystem.executor import recover_abandoned_jobs
        managed_job_recovery = recover_abandoned_jobs()
        repaired_verifications = reconcile_verifications()
        from ecosystem.control_turns import recover_interrupted, observe_head
        control_recovery = recover_interrupted()
        control_head = observe_head()
        from ecosystem.inference_proxy import reconcile_available_capacity
        capacity_reconciliation = reconcile_available_capacity(cli.ROOT)
        from ecosystem.workload_control import worker_lease_health
        lease_health = worker_lease_health(cli.ROOT)
        from ecosystem import outbox
        notification_health = outbox.delivery_health()
        last = datetime.fromisoformat(state["last_review_enqueued_at"]) if state.get("last_review_enqueued_at") else None
        due = not last or (now-last).total_seconds() >= config["steward_review_seconds"]
        issues = findings(config)
        if due and not pending_review() and not (cli.ROOT / "state/PAUSED").exists():
            task_id, task_card, selection_reason = select(config, state, now=now)
            issue_text = "\n".join(f"- {item}" for item in issues) or "- No deterministic warning; perform the scheduled qualitative review."
            task = f"""Perform the periodic ecosystem sanity review.

Selected Steward assignment (`{task_id}`):

{task_card}

Work from `{cli.ROOT}`. Read the last 30 conversational entries
in `{cli.ROOT / "state/conversations"}` without copying secrets into
durable notes. Review recent audit events, failed/running jobs, executor output
tails, model choices and rationales, systemd user-service state, and
the project knowledge tree's current-priority and runtime-truth leaves.

Deterministic findings at enqueue time:
{issue_text}

Look for confusing or dishonest bot replies, missed context, jobs that did not produce what David requested, stalls, notification failures, unsafe behavior, and documentation drift. Implement bounded user-level fixes when evidence is clear; use existing focused checks and direct smoke checks; do not write regression tests during MVP bringup. Update project KT state and next actions when warranted. You may enqueue a focused follow-up job if another role/model is more appropriate. Do not perform approval-required actions. Send David a concise evidence-based handoff."""
            root = cli.ROOT.resolve()
            contract = {
                "objective": task,
                "scope": {"workspace": str(root), "read_paths": [str(root)],
                          "write_paths": [str(root)]},
                "authority_profile": "scheduled_review",
                "requirements": {"required_capabilities": ["reasoning", "tool-calling"],
                                 "minimum_context_tokens": 16384},
                "acceptance": [{"kind": "handoff", "value": "evidence-backed review"}],
                "budget": {"run_seconds": None, "task_seconds": None,
                           "maximum_attempts": None, "maximum_output_bytes": None,
                           "maximum_evidence_items": None, "maximum_children": 1},
                "source_key": f"{SOURCE}:{task_id}", "parent_job_id": None,
                "stop_condition": "Stop after one bounded review or useful partial handoff.",
            }
            job_id = cli.enqueue_task("steward", task, source=f"{SOURCE}:{task_id}",
                                      model=config["review_model"],
                                      model_reason="Optional watchdog preference; central routing remains authoritative.",
                                      task_contract=contract)
            history = state.setdefault("task_last_selected", {}); history[task_id] = now.isoformat()
            state.update(last_review_enqueued_at=now.isoformat(), last_job_id=job_id, last_task_id=task_id, last_task_reason=selection_reason, last_findings=issues, last_verification_repairs=repaired_verifications, last_native_recovery=native_recovery, last_operator_recovery=operator_recovery, last_managed_job_recovery=managed_job_recovery, last_control_turn_recovery=control_recovery, last_control_turn_head=control_head, last_inference_capacity_reconciliation=capacity_reconciliation, last_worker_lease_health=lease_health, last_notification_health=notification_health)
            cli.atomic_json(state_path, state); cli.audit("watchdog.steward_enqueued", job_id=job_id, findings=len(issues), task_id=task_id, selection_reason=selection_reason)
            return f"enqueued {job_id}"
        state.update(last_tick_at=now.isoformat(), last_findings=issues, last_verification_repairs=repaired_verifications, last_native_recovery=native_recovery, last_operator_recovery=operator_recovery, last_managed_job_recovery=managed_job_recovery, last_control_turn_recovery=control_recovery, last_control_turn_head=control_head, last_inference_capacity_reconciliation=capacity_reconciliation, last_worker_lease_health=lease_health, last_notification_health=notification_health)
        cli.atomic_json(state_path, state)
        return "healthy; review not due" if not issues else f"findings={len(issues)}; review already pending"

if __name__ == "__main__": print(tick())
