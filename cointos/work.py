"""Work: tasks from the knowledge-tree queues, the spawner, and each agent's life.

An agent's thread owns its OpenCode processes and alone reports how its run ended. Every
end follows one order: the agent leaves the ledger with its task settled, then its process
group is stopped (`what/is/the/architecture/of/cointos.md`, *Agents*).
"""
from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

from cointos import agents, lanes, queues
from cointos.config import KEYS, STATE, read_json, write_json
from cointos.state import BACKEND, CONFIG, LOCK, L, alert, log, now

KEY_OWNERS: dict[str, tuple[str, str]] = {}  # gateway key -> (agent id, class)
AGENT_KEYS: dict[str, str] = {}  # agent id -> its gateway key


def load_keys() -> None:
    keys = read_json(KEYS, {})
    if "coin" not in keys:
        keys["coin"] = secrets.token_urlsafe(24)
        write_json(KEYS, keys, mode=0o600)
    KEY_OWNERS[keys["coin"]] = ("coin", "coin")


def project_named(name: str) -> dict:
    for project in CONFIG["projects"]:
        if project["name"].lower() == name.lower():
            return project
    raise ValueError(f"unknown project {name!r}; configured: {[p['name'] for p in CONFIG['projects']]}")


# ---------------------------------------------------------------- an agent's life

class Ended(Exception):
    """The agent left the ledger while its run was still going."""


def start_agent(task_id: str) -> None:
    """Start an agent on a task. Caller holds LOCK."""
    task = L["tasks"][task_id]
    agent_id = f"{task['role']}-{secrets.token_hex(3)}"
    key = secrets.token_urlsafe(24)
    KEY_OWNERS[key] = (agent_id, "background")
    AGENT_KEYS[agent_id] = key
    task.update(status="running", runs=task["runs"] + 1, agent=agent_id, note=None, updated_at=now())
    L["agents"][agent_id] = {
        "id": agent_id, "role": task["role"], "project": task["project"], "task": task_id, "title": task["title"],
        "class": "background", "state": "starting", "pid": None, "url": None, "session": task.get("session"),
        "doing": None, "thoughts": 0, "repeats": 0, "last_thought": None, "last_activity": now(),
        "started_at": now()}
    log("agent started", agent=agent_id, task=task_id, run=task["runs"])
    threading.Thread(target=agent_thread, args=(agent_id, dict(task), key), daemon=True).start()


def agent_thread(agent_id: str, task: dict, key: str) -> None:
    """Own one agent's processes from launch to exit, and report how its run ended."""
    group = []

    def on_event(kind, value):
        with LOCK:
            agent = L["agents"].get(agent_id)
            if kind == "server":
                group.append(value[0])
            if agent is None:
                raise Ended
            if kind == "server":
                agent.update(pid=value[0], url=value[1], state="running")
            elif kind == "session" and agent["session"] != value:
                agent["session"] = value
                L["tasks"][agent["task"]]["session"] = value
            elif kind == "activity" and value:
                agent["doing"] = value
            agent["last_activity"] = now()
    try:
        outcome = agents.run(CONFIG, {"id": agent_id}, task, project_named(task["project"]), key, on_event)
    except Ended:
        outcome = None
    except Exception as error:
        outcome = {"finish": None, "code": None, "text": "", "error": f"{type(error).__name__}: {error}"}
    try:
        with LOCK:
            if outcome is not None and agent_id in L["agents"]:
                settle(agent_id, outcome)
    finally:
        if group:
            agents.stop_group(group[0])


def stop_agent(agent_id: str, reason: str, requeue: bool, charge: bool = True) -> None:
    """End an agent now and settle its task. An uncharged stop (David, the guard, a halt)
    does not count against the task's runs. Caller holds LOCK."""
    agent = L["agents"].get(agent_id)
    if agent is None:
        return
    task = L["tasks"].get(agent["task"])
    if task is not None:
        if not charge:
            task["runs"] -= 1
        exhausted = task["runs"] >= CONFIG["spawner"]["max_runs_per_task"]
        end_task(task, "waiting" if requeue and not exhausted else "failed", reason)
        if task["status"] == "failed":
            alert(f"Gave up on {task['title']} in {task['project']} after {task['runs']} runs: {reason}")
    finish_agent(agent_id, reason)
    if agent["pid"]:
        threading.Thread(target=agents.stop_group, args=(agent["pid"],), daemon=True).start()


def finish_agent(agent_id: str, reason: str) -> None:
    """Take an agent out of the ledger; its processes are stopped after this. Caller holds LOCK."""
    agent = L["agents"].pop(agent_id)
    L["exiting"][agent_id] = now()
    KEY_OWNERS.pop(AGENT_KEYS.pop(agent_id, ""), None)
    lanes.cancel_agent(agent_id)
    log("agent ended", agent=agent_id, task=agent["task"], reason=reason, thoughts=agent["thoughts"],
        seconds=round(now() - agent["started_at"]))


def end_task(task: dict, status: str, note: str, **fields) -> None:
    """Set how a task stands after a run. A task whose conversation is over (done or failed)
    has its context snapshots forgotten. Caller holds LOCK."""
    task.update(status=status, agent=None, note=note, updated_at=now(), **fields)
    if status in ("done", "failed"):
        lanes.forget_owner(task["id"])


def settle(agent_id: str, outcome: dict) -> None:
    """An agent's run ended by itself: decide whether its task is finished. Caller holds LOCK."""
    agent = L["agents"][agent_id]
    task = L["tasks"][agent["task"]]
    project = project_named(task["project"])
    if task["kind"] in ("item", "breakdown"):
        found = queues.read_item(Path(task["worktree"]), task["item"]) or queues.read_item(Path(project["path"]), task["item"])
        status = found["status"] if found else None
        finished = status in (("done", "blocked") if task["kind"] == "item" else ("in progress", "done", "blocked"))
        detail = f"item status {status}"
    else:
        finished = outcome.get("finish") == "stop"
        detail = f"run finished with {outcome.get('finish')}"
    if outcome.get("error"):
        detail += f"; {outcome['error']}"
    if finished:
        merged = agents.remove_worktree(project, task)
        end_task(task, "done", detail + ("" if merged else "; branch not merged"),
                 result=(outcome.get("text") or "")[-2000:])
        log("task finished", task=task["id"], detail=task["note"])
        finish_agent(agent_id, "finished")
    else:
        stop_agent(agent_id, f"run ended unfinished ({detail})", requeue=True)


# ---------------------------------------------------------------- tasks and the spawner

def new_task(project: dict, kind: str, role: str, item: str | None, brief: str, leaf_hash: str | None) -> str:
    name = Path(item).stem if item else f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    task_id = f"{project['name']}:{item or name}"
    L["tasks"][task_id] = {
        "id": task_id, "project": project["name"], "kind": kind, "role": role, "item": item,
        "title": name if item else kind, "brief": brief, "leaf_hash": leaf_hash, "status": "waiting", "runs": 0,
        "session": None, "agent": None, "worktree": str(STATE / "worktrees" / project["name"] / name),
        "branch": f"cointos/{name}", "created_at": now(), "updated_at": now(), "note": None,
    }
    log("task created", task=task_id)
    return task_id


def next_task() -> str | None:
    """The next task to run, creating it from the queues if needed. Caller holds LOCK."""
    tasks = L["tasks"]
    waiting = sorted((t for t in tasks.values() if t["status"] == "waiting"), key=lambda t: t["created_at"])
    if waiting:
        return waiting[0]["id"]
    candidates = []
    for project in CONFIG["projects"]:
        for found in queues.scan(project):
            known = tasks.get(f"{project['name']}:{found['item']}")
            if known and (known["status"] in ("running", "waiting") or known["leaf_hash"] == found["hash"]):
                continue
            if found["kind"] in ("urgent", "queued") and found["status"] == "queued":
                candidates.append((0 if found["kind"] == "urgent" else 1, "item", "worker", project, found))
            elif found["kind"] == "drafted" and found["status"] == "drafted":
                candidates.append((2, "breakdown", "manager", project, found))
    if candidates:
        _, kind, role, project, found = min(candidates, key=lambda c: c[0])
        return new_task(project, kind, role, found["item"], found["brief"], found["hash"])
    spawner = CONFIG["spawner"]
    for project in CONFIG["projects"]:
        if now() - L["last_survey"].get(project["name"], 0) > spawner["survey_every_seconds"]:
            L["last_survey"][project["name"]] = now()
            return new_task(project, "survey", "manager", None, "", None)
    maintained = [p for p in CONFIG["projects"] if p["name"] == spawner["maintenance_project"]]
    if maintained and now() - L["last_maintenance"] > spawner["maintenance_every_seconds"]:
        L["last_maintenance"] = now()
        return new_task(maintained[0], "maintenance", "steward", None, "", None)
    return None


def spawn() -> None:
    """Start agents while there is room, work and memory. Caller holds LOCK."""
    if (L["paused"] or lanes.blocked() or not L["models"][CONFIG["work_model"]]["up"]
            or now() - L["user_last_thought"] < CONFIG["spawner"]["user_quiet_seconds"]):
        return
    headroom = L["memory"].get("headroom_gb", 0.0)
    while len(L["agents"]) < CONFIG["spawner"]["max_agents"] and headroom >= CONFIG["memory"]["agent_memory_gb"]:
        task_id = next_task()
        if task_id is None:
            return
        start_agent(task_id)
        headroom -= CONFIG["memory"]["agent_memory_gb"]


def recover_leftovers() -> None:
    """Stop agent processes left by an earlier daemon and requeue their tasks."""
    for pids in agents.find_processes().values():
        for pid in pids:
            try:
                agents.stop_group(pid, grace=2)
            except PermissionError:
                pass
    for task in L["tasks"].values():
        if task["status"] == "running":
            task.update(status="waiting", agent=None, note="daemon restarted", updated_at=now())
