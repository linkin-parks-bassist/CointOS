"""Agent runs: starting one for a waiting task, following it to its end, and adopting the runs
a previous daemon left behind. What a run's end means for its task is decided by
`cointos/lifecycle.py`; this module only reports execution facts to it.
"""
from __future__ import annotations

import secrets
import threading

from cointos import git, keys, lifecycle, opencode, prompts, tasks
from cointos.state import CONFIG, LOCK, L, log, now


class Ended(Exception):
    """The run left the ledger while it was still being followed."""


def start(task: dict) -> str:
    """Start an agent run for a waiting task. Caller holds LOCK."""
    agent_id = f"{task['role']}-{secrets.token_hex(3)}"
    lifecycle.start(task, agent_id)
    key = keys.issue(agent_id, "background")
    L["agents"][agent_id] = {
        "id": agent_id, "role": task["role"], "place": task["place"], "task": task["id"], "title": task["title"],
        "class": "background", "state": "starting", "pid": None, "url": None, "session": task["session"],
        "doing": None, "thoughts": 0, "generated": 0, "engaged": False,
        "repeats": 0, "last_thought": None, "last_activity": now(),
        "started_at": now(), "stage": task["stage"], "reasoning_effort": task["reasoning_effort"]}
    log("agent started", agent=agent_id, task=task["id"], run=task["runs"])
    threading.Thread(target=follow, args=(agent_id, dict(task), key), daemon=True).start()
    return agent_id


def follow(agent_id: str, task: dict | None, key: str | None) -> None:
    """Own one run from launch (or, with no task, from adoption after a daemon restart) to its
    end, then report its execution facts. The run is a systemd unit outside the daemon."""
    try:
        if task is not None:
            launch(agent_id, task, key)
        facts = opencode.watch(agent_id, lambda kind, value: observed(agent_id, kind, value))
    except Ended:
        facts = None
    except Exception as error:
        facts = {"finish": None, "code": None, "error": f"{type(error).__name__}: {error}"}
    try:
        with LOCK:
            if facts is not None and agent_id in L["agents"]:
                lifecycle.ended(agent_id, facts)
    finally:
        opencode.stop(agent_id)


def launch(agent_id: str, task: dict, key: str) -> None:
    """Prepare the task's worktree and start its run's unit. Runs outside LOCK."""
    where = tasks.place(task)
    if task["branch"] is not None:
        git.add_worktree(where["path"], task["worktree"], task["branch"], where["main_branch"])
    if task["kind"] == "item" and not task.get("base_commit"):
        base = git.run(task["worktree"], "merge-base", "HEAD", where["main_branch"])
        with LOCK:
            L["tasks"][task["id"]]["base_commit"] = task["base_commit"] = base
    opencode.launch(CONFIG, agent_id, task, key, prompts.launch_text(task, where), protected(task, where))


def protected(task: dict, where: dict) -> list[str]:
    """Paths an implementation run may not edit: its project's test contracts and harness."""
    rules = where.get("test_policy")
    if task["kind"] != "item" or task["stage"] != "implementation" or not rules:
        return []
    patterns = [rules["manifest"], *rules["protected"]]
    return patterns + [f"{task['worktree']}/{pattern}" for pattern in patterns]


def observed(agent_id: str, kind: str, value) -> None:
    """An event from a followed run: its server, its session, what it is doing."""
    with LOCK:
        agent = L["agents"].get(agent_id)
        if agent is None:
            raise Ended
        if kind == "server":
            agent.update(pid=value[0], url=value[1], state="running")
        elif kind == "session" and agent["session"] != value:
            agent["session"] = value
            task = L["tasks"].get(agent["task"])
            if lifecycle.owns(task, agent_id):
                task["session"] = value
        elif kind == "activity" and value:
            agent["doing"] = value
        agent["last_activity"] = now()


def adopt(previous: dict) -> None:
    """On daemon start: follow again the runs of the previous daemon (systemd units that
    outlived it), stop agent processes nobody owns, and let running tasks whose run is gone wait
    again. Caller holds LOCK."""
    recorded = keys.recorded()
    for agent_id, agent in (previous.get("agents") or {}).items():
        task = L["tasks"].get(agent["task"])
        if (agent_id not in recorded or task is None or task["agent"] != agent_id
                or not opencode.active(agent_id)):
            continue
        L["agents"][agent_id] = {**agent,
                                 "engaged": agent.get("engaged", bool(agent.get("thoughts") or agent.get("generated"))),
                                 "last_activity": now()}
        keys.adopt(agent_id, agent["class"], recorded[agent_id])
        log("agent adopted", agent=agent_id, task=agent["task"])
        threading.Thread(target=follow, args=(agent_id, None, None), daemon=True).start()
    for agent_id, pids in opencode.find_processes().items():
        if agent_id not in L["agents"]:
            for pid in pids:
                try:
                    opencode.stop_group(pid, grace=CONFIG["timeouts"]["leftover_stop_grace_seconds"])
                except PermissionError:
                    pass
    for task in L["tasks"].values():
        if task["status"] == "running" and task["agent"] not in L["agents"]:
            lifecycle.orphaned(task)
