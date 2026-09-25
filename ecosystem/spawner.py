"""Autonomous agent spawner: keep spare capacity busy with queued and self-directed work.

Each tick spawns at most one background agent when the system is healthy, David is not
using the machine for his own agent work, and fewer than `max_active_agents` agent jobs
are active. Work is chosen from knowledge-tree queues in configured project trees:
urgent items, then queued items (worker), then drafted ideas (manager), then a periodic
project survey (manager), then a periodic maintenance check (steward).
"""
from __future__ import annotations

import fcntl
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ecosystem import cli

CONFIG = cli.ROOT / "config/spawner.json"
STATE = cli.ROOT / "state/spawner.json"
SOURCE = "spawner"
ACTIVE = {"queued", "ready", "claimed", "runner_starting", "running", "awaiting_verification"}
STATUS = re.compile(r"^\s*status:\s*([a-z][a-z ]*?)\s*$", re.IGNORECASE)
QUEUES = (("urgent", "worker", {"queued", "in progress"}),
          ("queued", "worker", {"queued", "in progress"}),
          ("drafted", "manager", {"drafted"}))


def _status(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("\n---", 1)[-1]
    for line in text.splitlines():
        if line.strip():
            match = STATUS.match(line)
            return match.group(1).lower() if match else None
    return None


def _active_jobs() -> list[dict]:
    jobs = []
    for path in (cli.ROOT / "state/jobs").glob("task-*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("kind") == "agent-task" and job.get("state") in ACTIVE:
            jobs.append(job)
    return jobs


def _user_busy(jobs: list[dict]) -> bool:
    if any(job.get("user_directed_origin") in cli.USER_DIRECTED_ORIGINS for job in jobs):
        return True
    from ecosystem.operator_session import active_operator_sessions
    try:
        return bool(active_operator_sessions(cli.ROOT))
    except (OSError, ValueError):
        return False


def _age(state: dict, key: str, now: datetime) -> float:
    stamp = state.get(key)
    return (now - datetime.fromisoformat(stamp)).total_seconds() if stamp else float("inf")


def _candidate(config: dict, state: dict, jobs: list[dict], now: datetime):
    claimed = {job.get("source", "").split(":", 2)[-1] for job in jobs
               if job.get("source", "").startswith(f"{SOURCE}:")}
    projects = [Path(p).expanduser() for p in config["projects"]]
    for branch, role, statuses in QUEUES:
        for project in projects:
            queue = project / ".knowledge/what/is" / branch
            for leaf in sorted(queue.rglob("*.md")) if queue.is_dir() else ():
                key = str(leaf)
                if key in claimed or _age(state.get("items", {}), key, now) < config["item_cooldown_seconds"]:
                    continue
                if _status(leaf) in statuses:
                    return role, project, key, branch
    surveys = state.get("surveys", {})
    due = [p for p in projects if _age(surveys, str(p), now) >= config["survey_interval_seconds"]]
    if due:
        project = min(due, key=lambda p: surveys.get(str(p), ""))
        return "manager", project, None, "survey"
    if _age(state, "last_steward_at", now) >= config["steward_interval_seconds"]:
        return "steward", Path(config["steward_workspace"]).expanduser(), None, "maintenance"
    return None


def _task(role: str, project: Path, item: str | None, kind: str) -> str:
    tree = project / ".knowledge"
    if kind in ("urgent", "queued"):
        return (f"You are a worker on the project at `{project}`.\n\n"
                f"Your work item is the knowledge-tree leaf `{item}`. Read it, carry it out "
                f"in the repository, and update the leaf as your role describes.")
    if kind == "drafted":
        return (f"You are a manager for the project at `{project}`.\n\n"
                f"David drafted the idea in `{item}`. Break it down into queued work items "
                f"under `{tree}/what/is/queued/` as your role describes, and update the idea leaf.")
    if kind == "survey":
        return (f"You are a manager for the project at `{project}`.\n\n"
                f"Survey the project: read its orientation, plan, state and next leaves and its "
                f"queue under `{tree}/what/is/`. Queue the next one to three worthwhile steps, "
                f"close out stale items, and keep plan/state/next current. If the project needs "
                f"nothing right now, say so and stop.")
    from ecosystem.steward_tasks import select
    watchdog = json.loads((cli.ROOT / "config/watchdog.json").read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    card_id, card, _reason = select(watchdog, state)
    state.setdefault("task_last_selected", {})[card_id] = datetime.now(timezone.utc).isoformat()
    cli.atomic_json(STATE, state)
    return f"You are a steward for CointOS.\n\nMaintenance check `{card_id}`:\n\n{card}"


def tick() -> str:
    cli.initialize()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not config.get("enabled", False):
        return "disabled"
    if (cli.ROOT / "state/PAUSED").exists():
        return "dispatch paused"
    from ecosystem.resource_control import dispatch_halted
    if dispatch_halted():
        return "dispatch halted by resource control"
    lock_path = cli.ROOT / "state/spawner.lock"
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "another tick running"
        jobs = _active_jobs()
        if _user_busy(jobs):
            return "David's own agent work is active; standing back"
        if len(jobs) >= config["max_active_agents"]:
            return f"{len(jobs)} agents active; at capacity"
        now = datetime.now(timezone.utc)
        state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        choice = _candidate(config, state, jobs, now)
        if choice is None:
            return "nothing to do"
        role, project, item, kind = choice
        task = _task(role, project, item, kind)
        state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        workspace = str(project.resolve())
        key = f"{SOURCE}:{kind}:{item or workspace}:{now.isoformat()}"
        contract = {
            "objective": task,
            "scope": {"workspace": workspace, "read_paths": [workspace], "write_paths": [workspace]},
            "authority_profile": "ordinary",
            "requirements": {"required_capabilities": ["tool-calling"],
                             "minimum_context_tokens": config["minimum_context_tokens"]},
            "acceptance": [],
            "budget": {"run_seconds": None, "task_seconds": None, "maximum_attempts": None,
                       "maximum_output_bytes": None, "maximum_evidence_items": None,
                       "maximum_children": None},
            "source_key": key, "parent_job_id": None,
            "stop_condition": "Stop after one useful step, recorded in the knowledge tree.",
        }
        job_id = cli.enqueue_task(role, task, source=f"{SOURCE}:{kind}:{item or workspace}", model=config.get("model"),
                                  model_reason="Spawner preference; central routing remains authoritative.",
                                  idempotency_key=key, task_contract=contract)
        if item:
            state.setdefault("items", {})[item] = now.isoformat()
        elif kind == "survey":
            state.setdefault("surveys", {})[str(project)] = now.isoformat()
        else:
            state["last_steward_at"] = now.isoformat()
        state.update(last_spawn_at=now.isoformat(), last_job_id=job_id, last_kind=kind)
        cli.atomic_json(STATE, state)
        cli.audit("spawner.spawned", job_id=job_id, role=role, kind=kind, workspace=workspace, item=item)
        return f"spawned {job_id} ({role}, {kind}) in {workspace}"


if __name__ == "__main__":
    print(tick())
