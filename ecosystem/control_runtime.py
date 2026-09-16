"""Deep-control facts and idempotent tool execution."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from ecosystem import cli, conversation, control_turns
from ecosystem.facts import lifecycle
from ecosystem.identity import active_names
from ecosystem.models import snapshot
from ecosystem.roles import list_roles, safe_role_label
from ecosystem.task_contracts import accepted_workspace_policy


def _prompt_lifecycle_facts() -> dict:
    facts = lifecycle()
    recent = []
    for fact in facts.get("recent_agents", []):
        projected = dict(fact)
        projected["role"] = safe_role_label(projected.get("role"))
        recent.append(projected)
    latest = {}
    for raw_role, fact in facts.get("latest_by_role", {}).items():
        role = safe_role_label(raw_role)
        if role is None:
            continue
        projected = dict(fact)
        projected["role"] = role
        latest[role] = projected
    return {**facts, "latest_by_role": latest, "recent_agents": recent}


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
            role = safe_role_label(job.get("role")) or "unassigned"
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
    live.update(job_status=status_text(), lifecycle_facts=_prompt_lifecycle_facts(),
                recent_errors=recent_errors_text(), available_roles=list_roles(),
                active_agent_names=sorted(active_names()), active_maintenance=maintenance)
    return live


def _action_key(name: str, arguments: dict) -> str:
    canonical = json.dumps({"name": name, "arguments": arguments}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def _contact_task_contract(identifier: str, key: str, task: str,
                           workspace_selector: object = None) -> dict:
    """Convert an authenticated control turn into accepted executable authority."""
    try:
        policy = accepted_workspace_policy(cli.ROOT)
    except ValueError:
        policy = {"workspaces": []}
    active = [item for item in policy["workspaces"] if item.get("mode") == "active"]
    if workspace_selector is None:
        root = active[0]["path"] if active else str(cli.ROOT.resolve())
    elif isinstance(workspace_selector, str) and workspace_selector.strip():
        selector = workspace_selector.strip()
        workspace = next(
            (item for item in active if selector in {item["id"], item["path"]}), None
        )
        root = workspace["path"] if workspace is not None else str(Path(selector).expanduser().resolve())
    else:
        raise ValueError("workspace must be a non-empty id or path")
    return {
        "objective": task,
        "scope": {"workspace": root, "read_paths": [root], "write_paths": [root]},
        "authority_profile": "contact_requested",
        "requirements": {
            "required_capabilities": ["tool-calling"],
            "minimum_context_tokens": 16384,
        },
        "acceptance": [],
        "budget": {
            "run_seconds": None,
            "task_seconds": None,
            "maximum_attempts": None,
            "maximum_output_bytes": None,
            "maximum_evidence_items": None,
            "maximum_children": 0,
        },
        "source_key": f"{identifier}:{key}",
        "parent_job_id": None,
        "stop_condition": "Stop when the requested task is complete or requires David's decision.",
    }


def _task_progress(user_id: int, agent_name: object = None) -> dict:
    records = []
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(job, dict) and job.get("kind") == "agent-task" \
                and job.get("source") == f"telegram:{user_id}":
            records.append(job)
    if agent_name is not None:
        if not isinstance(agent_name, str) or not agent_name:
            return {"ok": True, "found": False}
        records = [job for job in records if job.get("agent_name") == agent_name]
    else:
        active = [job for job in records
                  if job.get("state") in {"queued", "ready", "running", "awaiting_verification"}]
        records = active if active else records
    if not records:
        return {"ok": True, "found": False}

    def updated(job):
        value = job.get("updated_at")
        return value if isinstance(value, str) else ""

    selected = max(records, key=updated)
    progress = {key: selected[key] for key in
                ("agent_name", "state", "task", "role", "model", "updated_at", "attempts",
                 "logical_run_state", "runner_phase", "last_preemption_reason", "failure_reason")
                if key in selected}
    output = selected.get("output")
    if isinstance(output, str) and output:
        root = cli.ROOT.resolve()
        candidate = (root / output).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            stat = candidate.stat()
            progress["output_bytes"] = stat.st_size
            progress["output_updated_at"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    return {"ok": True, "found": True, "progress": progress}


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
                  "lifecycle_facts": _prompt_lifecycle_facts()}
    elif name == "inspect_task_progress":
        result = _task_progress(user_id, arguments.get("agent_name"))
    elif name == "cancel_task":
        result = cli.request_task_cancellation(f"telegram:{user_id}", arguments.get("agent_name"))
    elif name == "inspect_recent_errors":
        result = {"ok": True, "recent_errors": recent_errors_text()}
    elif name == "list_roles":
        result = {"ok": True, "roles": list_roles()}
    elif name in {"queue_task", "amend_pending_task"}:
        task = arguments.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("empty task")
        task = task.strip()
        role = arguments.get("role")
        model = arguments.get("model")
        contract = _contact_task_contract(identifier, key, task, arguments.get("workspace"))
        if name == "queue_task":
            job_id = cli.enqueue_task(
                role, task, source=f"telegram:{user_id}", model=model,
                model_reason=arguments.get("model_reason", ""),
                agent_name=arguments.get("agent_name"),
                idempotency_key=f"{identifier}:{key}", task_contract=contract,
            )
            job = json.loads((cli.ROOT / "state/jobs" / f"{job_id}.json").read_text())
            result = {
                "ok": True, "agent_name": job["agent_name"],
                "role": safe_role_label(role), "requested_model_hint": model,
                "model_selection": "pending", "task": task,
            }
        else:
            job_id = cli.amend_latest_task(
                f"telegram:{user_id}", role, task, model,
                arguments.get("model_reason", ""),
                idempotency_key=f"{identifier}:{key}", task_contract=contract,
            )
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
