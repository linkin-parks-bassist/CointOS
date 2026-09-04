"""Deep-control facts and idempotent tool execution."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from ecosystem import cli, conversation, control_turns
from ecosystem.facts import lifecycle
from ecosystem.identity import active_names
from ecosystem.models import snapshot
from ecosystem.roles import list_roles


def status_text() -> str:
    jobs = []
    counts = {}
    now = datetime.now(timezone.utc)
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        state = job.get("state")
        if not isinstance(state, str):
            continue
        counts[state] = counts.get(state, 0) + 1
        if job.get("kind") == "agent-task" and state in {"queued", "ready", "running", "awaiting_verification"}:
            role = job.get("role") or "unassigned"
            line = f"{job['id']}: {job['state']} / {role} / {job.get('model') or 'unspecified'}"
            if job["state"] == "running":
                started = datetime.fromisoformat(job["updated_at"])
                line += f" / {int((now - started).total_seconds() // 60)}m elapsed"
                output = cli.ROOT / job.get("output", "")
                if output.exists():
                    idle = int((now.timestamp() - output.stat().st_mtime) // 60)
                    line += f" / output idle {idle}m"
                    if idle >= 5:
                        line += " (possibly stalled)"
            jobs.append(line)
    active = "\n".join(jobs) if jobs else "No active agent tasks."
    return f"Paused: {(cli.ROOT / 'state/PAUSED').exists()}\nJobs: {counts}\n\nActive work:\n{active}"


def friendly_status() -> str:
    jobs = []
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(job.get("state"), str):
            jobs.append(job)
    active = [job for job in jobs if job.get("kind") == "agent-task" and job.get("state") in {"queued", "ready", "running", "awaiting_verification"}]
    if active:
        opening = "; ".join(
            f"{job.get('agent_name') or 'an older unnamed agent'} is {job['state']} on {job.get('task', 'something')[:120]}"
            for job in active
        ) + "."
    else:
        opening = "nothing's running right now — the machine's ready for whatever's next."
    completed = sum(job.get("kind") == "agent-task" and job.get("state") == "completed" for job in jobs)
    failed = sum(job.get("kind") == "agent-task" and job.get("state") == "failed" for job in jobs)
    history = f" {completed} agent jobs have finished"
    if failed:
        history += f", and {failed} older attempts failed"
    return opening + history + "."


def recent_errors_text(limit: int = 5) -> str:
    events = []
    for path in sorted((cli.ROOT / "logs/runs").glob("*.jsonl"), reverse=True)[:2]:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event", "").endswith(("error", "failed")) or event.get("event") == "telegram.dead_letter":
                events.append(event)
    events.sort(key=lambda item: item.get("at", ""), reverse=True)
    if not events:
        return "I checked the recent event logs; there aren't any recorded errors."
    lines = []
    for event in events[:limit]:
        instant = datetime.fromisoformat(event["at"]).astimezone()
        detail = event.get("error") or event.get("summary") or event["event"]
        lines.append(f"{instant:%-I:%M:%S %p %Z}: {detail}")
    return "yes — the most recent recorded errors are:\n" + "\n".join(lines)


def live_context() -> dict:
    live = snapshot()
    maintenance_path = cli.ROOT / "state/maintenance-status.json"
    maintenance = (json.loads(maintenance_path.read_text(encoding="utf-8"))
                   if maintenance_path.exists() else None)
    live.update(job_status=status_text(), lifecycle_facts=lifecycle(),
                recent_errors=recent_errors_text(), available_roles=list_roles(),
                active_agent_names=sorted(active_names()), active_maintenance=maintenance)
    return live


def _action_key(name: str, arguments: dict) -> str:
    canonical = json.dumps({"name": name, "arguments": arguments}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def execute_tool(identifier: str, name: str, arguments: dict) -> dict:
    key = _action_key(name, arguments)
    previous = control_turns.action_result(identifier, key)
    if previous:
        return previous["result"]
    turn = control_turns.load(identifier)
    user_id = int(turn["user_id"])
    cli.audit("control_turn.tool", turn_id=identifier, user_id=user_id, tool=name)
    if name == "inspect_status":
        refreshed = snapshot()
        result = {"ok": True, "job_status": status_text(), "models": refreshed,
                  "lifecycle_facts": lifecycle()}
    elif name == "inspect_recent_errors":
        result = {"ok": True, "recent_errors": recent_errors_text()}
    elif name == "list_roles":
        result = {"ok": True, "roles": list_roles()}
    elif name in {"queue_task", "amend_pending_task"}:
        role = arguments.get("role")
        model = arguments.get("model")
        task = arguments.get("task")
        available_models = {item["id"] for item in snapshot()["models"]}
        if model is not None and model not in available_models:
            raise ValueError("unavailable model")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("empty task")
        if name == "queue_task":
            job_id = cli.enqueue_task(role, task, source=f"telegram:{user_id}", model=model,
                                      model_reason=arguments.get("model_reason", ""),
                                      agent_name=arguments.get("agent_name"),
                                      idempotency_key=f"{identifier}:{key}")
            job = json.loads((cli.ROOT / "state/jobs" / f"{job_id}.json").read_text())
            result = {"ok": True, "agent_name": job["agent_name"], "role": role,
                      "requested_model_hint": model, "model_selection": "pending", "task": task}
        else:
            job_id = cli.amend_latest_task(f"telegram:{user_id}", role, task, model,
                                           arguments.get("model_reason", ""),
                                           idempotency_key=f"{identifier}:{key}")
            result = {"ok": bool(job_id), "amended": bool(job_id), "task": task}
    elif name == "pause_dispatch":
        (cli.ROOT / "state/PAUSED").touch()
        cli.audit("ecosystem.paused", source="telegram", user_id=user_id)
        result = {"ok": True, "paused": True}
    elif name == "resume_dispatch":
        (cli.ROOT / "state/PAUSED").unlink(missing_ok=True)
        cli.audit("ecosystem.resumed", source="telegram", user_id=user_id)
        result = {"ok": True, "paused": False}
    elif name == "forget_conversation":
        conversation.forget(user_id)
        result = {"ok": True, "forgotten": True}
    else:
        raise ValueError("unsupported control tool")
    control_turns.record_action(identifier, key, name, arguments, result)
    return result
