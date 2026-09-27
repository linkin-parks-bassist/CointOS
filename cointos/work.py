"""Work: tasks from the knowledge-tree queues, the spawner, and each agent's life.

A daemon thread follows each independent agent unit and settles its task. Daemon-directed
stops settle the task before stopping the unit; externally ended runs are settled when
observed (`what/is/the/architecture/of/cointos.md`, *Agents*).
"""
from __future__ import annotations

import secrets
import subprocess
import threading
import time
from pathlib import Path

from cointos import agents, lanes, queues, trees
from cointos.config import KEYS, STATE, read_json, write_json
from cointos.state import BACKEND, CONFIG, LOCK, L, STOPPING, alert, log, now

KEY_OWNERS: dict[str, tuple[str, str]] = {}  # gateway key -> (agent id, class)
AGENT_KEYS: dict[str, str] = {}  # agent id -> its gateway key


def load_keys() -> None:
    keys = read_json(KEYS, {})
    if "coin" not in keys:
        keys["coin"] = secrets.token_urlsafe(24)
        write_json(KEYS, keys, mode=0o600)
    KEY_OWNERS[keys["coin"]] = ("coin", "coin")


def keep_key(agent_id: str, key: str | None) -> None:
    """Record (or, with None, drop) an agent's gateway key, so an agent that outlives a daemon
    restart is still known by it."""
    keys = read_json(KEYS, {})
    agents_keys = keys.setdefault("agents", {})
    if key is None:
        agents_keys.pop(agent_id, None)
    else:
        agents_keys[agent_id] = key
    write_json(KEYS, keys, mode=0o600)


def project_named(name: str) -> dict:
    for project in CONFIG["projects"]:
        if project["name"].lower() == name.lower():
            return project
    raise ValueError(f"unknown project {name!r}; configured: {[p['name'] for p in CONFIG['projects']]}")


def place(task: dict) -> dict:
    """Where a task works: the tree it gardens, or else its project."""
    configured = CONFIG["trees"] if task["kind"] == "garden" else CONFIG["projects"]
    return next(p for p in configured if p["name"] == task["place"])


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
    keep_key(agent_id, key)
    task.update(status="running", runs=task["runs"] + 1, agent=agent_id, note=None, updated_at=now())
    L["agents"][agent_id] = {
        "id": agent_id, "role": task["role"], "place": task["place"], "task": task_id, "title": task["title"],
        "class": "background", "state": "starting", "pid": None, "url": None, "session": task.get("session"),
        "doing": None, "thoughts": 0, "generated": 0, "repeats": 0, "last_thought": None, "last_activity": now(),
        "started_at": now()}
    log("agent started", agent=agent_id, task=task_id, run=task["runs"])
    threading.Thread(target=agent_thread, args=(agent_id, dict(task), key), daemon=True).start()


def agent_thread(agent_id: str, task: dict | None, key: str | None) -> None:
    """Own one agent from launch (or, with no task, from re-adoption after a daemon restart) to
    the end of its run, and report how it ended. The run itself is a systemd unit outside the
    daemon; this thread follows it."""
    def on_event(kind, value):
        with LOCK:
            agent = L["agents"].get(agent_id)
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
        if task is not None:
            agents.launch(CONFIG, agent_id, task, place(task), key)
        outcome = agents.watch(agent_id, on_event)
    except Ended:
        outcome = None
    except Exception as error:
        outcome = {"finish": None, "code": None, "text": "", "error": f"{type(error).__name__}: {error}"}
    try:
        with LOCK:
            if outcome is not None and agent_id in L["agents"]:
                settle(agent_id, outcome)
    finally:
        agents.stop(agent_id)


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
            alert(f"Gave up on {task['title']} in {task['place']} after {task['runs']} runs: {reason}")
            if task["kind"] == "integrate":  # an item that cannot be integrated has failed too
                end_task(L["tasks"][f"{task['place']}:{task['item']}"], "failed", "could not be integrated")
    finish_agent(agent_id, reason)
    threading.Thread(target=agents.stop, args=(agent_id,), daemon=True).start()


def finish_agent(agent_id: str, reason: str) -> None:
    """Take an agent out of the ledger; its processes are stopped after this. Caller holds LOCK."""
    agent = L["agents"].pop(agent_id)
    L["exiting"][agent_id] = now()
    KEY_OWNERS.pop(AGENT_KEYS.pop(agent_id, ""), None)
    keep_key(agent_id, None)
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
    where = place(task)
    keep_worktree = False
    if task["kind"] == "item":
        # A worker's part ends with its work and its item's new status committed on its branch;
        # the integrator reviews it and lands it, or sends it back.
        branch = (queues.read_item(Path(task["worktree"]), task["item"]) or {}).get("status")
        committed = agents.committed(task)
        finished = branch in ("done", "blocked") and committed
        detail = f"item status {branch} on its branch" + ("" if committed else ", with uncommitted changes")
        keep_worktree = True
    elif task["kind"] == "integrate":
        # Finished once its item has left review: landed (its leaf gone, or blocked, on main) or
        # sent back to its worker.
        worker = L["tasks"][f"{where['name']}:{task['item']}"]
        on_main = (queues.read_item(Path(where["path"]), task["item"]) or {}).get("status")
        if task["item"] in queues.landed(where) or on_main == "blocked":
            agents.discard_worktree(where, worker)
            end_task(worker, "done", "landed" if on_main is None else "landed as blocked", review=None)
            log("task finished", task=worker["id"], detail=worker["note"])
        finished = worker["status"] != "review"
        detail = f"{task['item']} {worker['status']}"
    elif task["kind"] == "breakdown":
        # The idea on the main branch is the truth; `blocked` also counts from the branch, as it
        # can be the very reason the branch could not land.
        landed = (queues.read_item(Path(where["path"]), task["item"]) or {}).get("status")
        branch = (queues.read_item(Path(task["worktree"]), task["item"]) or {}).get("status")
        finished = landed in ("in progress", "done", "blocked") or branch == "blocked"
        detail = f"idea status {landed} on main" + ("" if branch in (None, landed) else f", {branch} on its branch")
    elif task["kind"] == "decompose":
        # Finished once main no longer holds the item as blocked awaiting decomposition: the
        # manager replaced it with smaller children (or rescoped it).
        on_main = queues.read_item(Path(where["path"]), task["item"])
        finished = not (on_main or {}).get("decompose") and outcome.get("finish") == "stop"
        detail = f"{task['item']} " + ("replaced" if on_main is None else f"{on_main['status']} on main")
    elif task["kind"] == "garden":
        # Completion belongs to the assigned batch, not the whole tree. Changes must land.
        health = trees.health(where, CONFIG["timeouts"]["command_seconds"])
        L["trees"][where["name"]] = {**health, "checked_at": now()}
        remaining = set(task["brief"].splitlines()) & set(trees.pending(health))
        merged = agents.git("-C", where["path"], "merge-base", "--is-ancestor", task["branch"],
                            where["main_branch"], check=False).returncode == 0
        finished = outcome.get("finish") == "stop" and merged and agents.committed(task)
        detail = f"run finished with {outcome.get('finish')}; {health['brown']} brown, {health['yellow']} yellow on main"
        if finished and remaining:
            alert(f"Gardener finished with unresolved leaves in {where['name']}: {', '.join(sorted(remaining))}. "
                  "Check its report before further work on that concern.")
    else:
        finished = outcome.get("finish") == "stop"
        detail = f"run finished with {outcome.get('finish')}"
    if outcome.get("error"):
        detail += f"; {outcome['error']}"
    if finished:
        result = (outcome.get("text") or "")[-CONFIG["result_chars"]:]
        if keep_worktree:
            end_task(task, "review", detail, result=result)
        else:
            if task["kind"] == "integrate":
                agents.discard_worktree(where, task)
                merged = True
            else:
                merged = agents.remove_worktree(where, task)
            end_task(task, "done", detail + ("" if merged else "; branch not merged"), result=result)
        log("task finished", task=task["id"], detail=task["note"])
        finish_agent(agent_id, "finished")
    else:
        stop_agent(agent_id, f"run ended unfinished ({detail})", requeue=True)


def send_back(integration: dict, notes: str) -> None:
    """The integrator returns a worker's item with what must change. Caller holds LOCK."""
    worker = L["tasks"][f"{integration['place']}:{integration['item']}"]
    if worker["status"] != "review":
        raise ValueError(f"{worker['id']} is not in review")
    end_task(worker, "waiting", "sent back by the integrator", review=notes)
    log("sent back", task=worker["id"], notes=notes)


# ---------------------------------------------------------------- tasks and the spawner

# Lower runs first. Finished work is landed before new work starts, so branches stay close to
# main. Gardening ranks by how bad its tree is (`trees.rank`).
# Queue members rank by their index position after their kind: urgent work is listed first.
RANKS = {"integrate": [2], "decompose": [3], "queued": [4], "drafted": [5], "survey": [6], "maintenance": [7]}


def new_task(where: dict, kind: str, role: str, item: str | None, brief: str, leaf_hash: str | None, rank: list,
             name: str | None = None) -> str:
    name = name or (Path(item).stem if item else f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}")
    task_id = f"{where['name']}:{item if kind in ('item', 'breakdown') else name}"
    L["tasks"][task_id] = {
        "id": task_id, "place": where["name"], "kind": kind, "role": role, "item": item, "rank": rank,
        "title": Path(item).stem if item else kind, "brief": brief, "leaf_hash": leaf_hash, "status": "waiting", "runs": 0,
        "session": None, "agent": None, "worktree": str(STATE / "worktrees" / where["name"] / name),
        "branch": f"cointos/{name}", "created_at": now(), "updated_at": now(), "note": None,
    }
    log("task created", task=task_id)
    return task_id


def tree_health(tree: dict) -> dict | None:
    """The tree's health, re-read every `garden.check_seconds`; None while it cannot be read
    (David is told once per new reason). Caller holds LOCK."""
    seen = L["trees"].get(tree["name"])
    if seen is None or now() - seen["checked_at"] >= CONFIG["garden"]["check_seconds"]:
        try:
            seen = {**trees.health(tree, CONFIG["timeouts"]["command_seconds"]), "checked_at": now()}
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            if (seen or {}).get("error") != str(error):
                alert(f"Cannot read the {tree['name']} knowledge tree's health: {error}")
            seen = {"error": str(error), "checked_at": now()}
        L["trees"][tree["name"]] = seen
    return None if "error" in seen else seen


def next_task() -> str | None:
    """The next task to run, creating it if needed: begun tasks first, then new work, each in
    rank order (`RANKS`, `trees.rank`). An item runs only once every item it depends on is done
    on main (`queues.readiness`). Caller holds LOCK."""
    tasks = L["tasks"]
    scanned = {project["name"]: queues.scan(project) for project in CONFIG["projects"]}
    ready = {p["name"]: queues.readiness(scanned[p["name"]], queues.landed(p)) for p in CONFIG["projects"]}
    problems = {f"{project}:{item}": state for project, states in ready.items() for item, state in states.items()
                if state not in ("ready", "waiting")}
    for task_id, problem in problems.items():
        if L["dependency_problems"].get(task_id) != problem:
            alert(f"{task_id} can never start: {problem}.")
    L["dependency_problems"] = problems

    def runnable(task):
        return task["kind"] != "item" or ready.get(task["place"], {}).get(task["item"], "ready") == "ready"

    waiting = [t for t in tasks.values() if t["status"] == "waiting" and runnable(t)]
    if waiting:
        return min(waiting, key=lambda t: (t["rank"], t["created_at"]))["id"]
    candidates = []  # (rank, how to create the task)
    for project in CONFIG["projects"]:
        for found in scanned[project["name"]]:
            if ready[project["name"]][found["item"]] != "ready":
                continue
            rank = RANKS[found["kind"]] + [found["position"]]
            if found["decompose"]:  # a worker found it too big: a manager replaces it with smaller children
                name = f"decompose-{Path(found['item']).stem}"
                known = tasks.get(f"{project['name']}:{name}")
                if not (known and (known["status"] in ("running", "waiting") or known["leaf_hash"] == found["hash"])):
                    candidates.append((RANKS["decompose"], lambda p=project, f=found, n=name: new_task(
                        p, "decompose", "manager", f["item"], f["brief"], f["hash"], RANKS["decompose"], n)))
                continue
            known = tasks.get(f"{project['name']}:{found['item']}")
            if known and known["status"] == "waiting":
                known["rank"] = rank  # a manager may have reordered the index
            if known and (known["status"] in ("running", "waiting", "review") or known["leaf_hash"] == found["hash"]):
                continue
            if found["kind"] == "queued" and found["status"] == "queued":
                candidates.append((rank, lambda p=project, f=found, r=rank: new_task(
                    p, "item", "worker", f["item"], f["brief"], f["hash"], r)))
            elif found["kind"] == "drafted" and found["status"] == "drafted":
                candidates.append((rank, lambda p=project, f=found, r=rank: new_task(
                    p, "breakdown", "manager", f["item"], f["brief"], f["hash"], r)))
    for project in CONFIG["projects"]:  # one integration at a time per project, oldest first
        integrating = tasks.get(f"{project['name']}:integrate")
        finished = [t for t in tasks.values() if t["place"] == project["name"] and t["status"] == "review"]
        if finished and not (integrating and integrating["status"] in ("running", "waiting")):
            first = min(finished, key=lambda t: t["updated_at"])
            candidates.append((RANKS["integrate"], lambda p=project, t=first: new_task(
                p, "integrate", "integrator", t["item"], t["brief"], None, RANKS["integrate"], "integrate")))
    for tree in CONFIG["trees"]:
        health = tree_health(tree)
        known = tasks.get(f"{tree['name']}:garden")
        if health is None or any(t["kind"] == "garden" and t["place"] == tree["name"]
                                 and t["status"] in ("running", "waiting") for t in tasks.values()):
            continue
        changed = health["leaves"] and not (known and known["leaf_hash"] == health["hash"])
        if changed or now() - L["last_garden"].get(tree["name"], 0) > CONFIG["garden"]["every_seconds"]:
            def garden(t=tree, h=health):
                L["last_garden"][t["name"]] = now()
                root = trees.root(t)
                leaves = [str(p.relative_to(root)) for p in root.rglob("*.md")]
                selected = trees.select(h, leaves, CONFIG["garden"]["leaves_per_pass"])
                return new_task(t, "garden", "gardener", None, "\n".join(selected), h["hash"], trees.rank(h), "garden")
            candidates.append((trees.rank(health), garden))
        elif now() - L["last_garden"].get(f"{tree['name']}:audit", 0) > CONFIG["garden"]["audit_every_seconds"]:
            def audit(t=tree):
                L["last_garden"][f"{t['name']}:audit"] = now()
                return new_task(t, "garden", "tree-auditor", None, "", None, RANKS["survey"], "garden-audit")
            candidates.append((RANKS["survey"], audit))
    spawner = CONFIG["spawner"]
    for project in CONFIG["projects"]:
        if now() - L["last_survey"].get(project["name"], 0) > spawner["survey_every_seconds"]:
            def survey(p=project):
                L["last_survey"][p["name"]] = now()
                return new_task(p, "survey", "manager", None, "", None, RANKS["survey"])
            candidates.append((RANKS["survey"], survey))
    maintained = [p for p in CONFIG["projects"] if p["name"] == spawner["maintenance_project"]]
    if maintained and now() - L["last_maintenance"] > spawner["maintenance_every_seconds"]:
        def maintenance():
            L["last_maintenance"] = now()
            return new_task(maintained[0], "maintenance", "steward", None, "", None, RANKS["maintenance"])
        candidates.append((RANKS["maintenance"], maintenance))
    return min(candidates, key=lambda c: c[0])[1]() if candidates else None


def spawn() -> None:
    """Start agents while there is room, work and memory. Caller holds LOCK."""
    if (STOPPING.is_set() or L["paused"] or lanes.blocked() or not L["models"][CONFIG["work_model"]]["up"]
            or now() - L["user_last_thought"] < CONFIG["spawner"]["user_quiet_seconds"]):
        return
    headroom = L["memory"].get("headroom_gb", 0.0)
    while len(L["agents"]) < CONFIG["spawner"]["max_agents"] and headroom >= CONFIG["memory"]["agent_memory_gb"]:
        task_id = next_task()
        if task_id is None:
            return
        start_agent(task_id)
        headroom -= CONFIG["memory"]["agent_memory_gb"]


def adopt(previous: dict) -> None:
    """On daemon start: take back the agents of the previous daemon. Their runs are systemd units
    that outlived it; each gets its thread again, which follows the run from its files (and, for
    a run that ended meanwhile, settles it at once). Agent processes of no known agent are
    stopped, and running tasks without an agent wait again. Caller holds LOCK."""
    keys = read_json(KEYS, {}).get("agents", {})
    for agent_id, agent in (previous.get("agents") or {}).items():
        if agent_id not in keys or agent["task"] not in L["tasks"]:
            continue
        L["agents"][agent_id] = {**agent, "state": "running" if agent["state"] != "starting" else "starting"}
        KEY_OWNERS[keys[agent_id]] = (agent_id, agent["class"])
        AGENT_KEYS[agent_id] = keys[agent_id]
        log("agent adopted", agent=agent_id, task=agent["task"])
        threading.Thread(target=agent_thread, args=(agent_id, None, None), daemon=True).start()
    for agent_id, pids in agents.find_processes().items():
        if agent_id not in L["agents"]:
            for pid in pids:
                try:
                    agents.stop_group(pid, grace=CONFIG["timeouts"]["leftover_stop_grace_seconds"])
                except PermissionError:
                    pass
    for task in L["tasks"].values():
        if task["status"] == "running" and task["agent"] not in L["agents"]:
            task.update(status="waiting", agent=None, note="its agent was gone after a daemon restart", updated_at=now())
