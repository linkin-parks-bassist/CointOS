"""The spawner: which task runs next, and admitting runs while there is room.

Waiting tasks resume first, in rank order; then the best new work is created, also by rank
(`what/is/the/architecture/of/cointos.md`, *Autonomy*): integrating reviewed items before new
work, decompositions, queued items and commands in queue order within project priority, then
the periodic steward, test audit and tree maintenance. Caller holds LOCK throughout.
"""
from __future__ import annotations

import functools
import subprocess
from pathlib import Path

from cointos import lanes, lifecycle, queues, runs, schema, tasks, trees
from cointos.config import managed_trees
from cointos.state import CONFIG, STOPPING, L, alert, now


def refresh() -> tuple[dict, dict, bool]:
    """Queue projection and dependency readiness, current even while admission is full or
    paused: ({project: its unfinished records}, {project: {item: readiness}}, queue changed)."""
    changed = lifecycle.reconcile()
    projects = tasks.enabled_projects()
    scanned = {p["name"]: queues.scan(p) for p in projects}
    ready = {p["name"]: queues.readiness(scanned[p["name"]], queues.landed(p)) for p in projects}
    problems = {f"{project}:{item}": state for project, states in ready.items() for item, state in states.items()
                if state not in ("ready", "waiting")}
    for key, problem in problems.items():
        if L["dependency_problems"].get(key) != problem:
            alert(f"{key} can never start: {problem}.")
    L["dependency_problems"] = problems
    return scanned, ready, changed


def spawn() -> None:
    """Start runs while there is room, work and memory."""
    if (STOPPING.is_set() or L["restarting"] or L["paused"] or lanes.blocked()
            or not L["models"][CONFIG["work_model"]]["up"]
            or now() - L["user_last_thought"] < CONFIG["spawner"]["user_quiet_seconds"]):
        return
    headroom = L["memory"].get("headroom_gb", 0.0)
    while len(L["agents"]) < CONFIG["spawner"]["max_agents"] and headroom >= CONFIG["memory"]["agent_memory_gb"]:
        task = next_task()
        if task is None:
            return
        runs.start(task)
        headroom -= CONFIG["memory"]["agent_memory_gb"]


def next_task() -> dict | None:
    """The task to run next: a waiting one first, else the best new one, created now."""
    scanned, ready, _ = refresh()
    reorder(scanned)
    exiting = {agent["task"] for agent in L["agents"].values()}  # a receipt settles before its run exits
    waiting = [t for t in L["tasks"].values() if t["status"] == "waiting" and not t.get("replaced_by")
               and t["id"] not in exiting and runnable(t, ready)]
    if waiting:
        return min(waiting, key=lambda t: (t["rank"], t["created_at"]))
    options = queued_work(scanned, ready) + integrations() + tree_work() + periodic()
    return min(options, key=lambda option: option[0])[1]() if options else None


def held(task: dict) -> bool:
    """Whether its queue item is held while its owner decides about it."""
    return bool(task.get("admission_hold")) or (bool(task["record"]) and
           bool(queues.records().get(task["record"], {}).get("held_by")))


def runnable(task: dict, ready: dict) -> bool:
    if held(task):
        return False
    scope = schema.KINDS[task["kind"]]["scope"]
    if scope in ("project", "either") and task["place"] != "system":
        project = next((p for p in CONFIG["projects"] if p["name"] == task["place"]), None)
        if project is None or not project.get("enabled", True):
            return False
    if task["kind"] in ("item", "breakdown"):
        return ready.get(task["place"], {}).get(task["item"]) == "ready"
    return True


def queue_rank(kind: str, project: dict, position: int) -> list:
    return [schema.KINDS[kind]["rank"], project.get("priority", 100), position]


def reorder(scanned: dict) -> None:
    """Waiting queue tasks take their record's current position: David and managers reorder."""
    for project in tasks.enabled_projects():
        for record in scanned[project["name"]]:
            task = L["tasks"].get(f"{project['name']}:{record['item']}")
            if task and task["status"] == "waiting":
                task["rank"] = queue_rank(task["kind"], project, record["position"])


def queued_work(scanned: dict, ready: dict) -> list:
    """New tasks for ready queue records: a worker item or command, or a decomposition manager
    for an item a worker returned as too big."""
    options = []
    for project in tasks.enabled_projects():
        for record in scanned[project["name"]]:
            if record.get("replaced_by") or record["held_by"] or ready[project["name"]][record["item"]] != "ready":
                continue
            if record["decompose"]:
                name = f"decompose-{Path(record['item']).stem}"
                known = L["tasks"].get(f"{project['name']}:{name}")
                if not (known and (known["status"] in ("running", "waiting") or known["record_hash"] == record["hash"])):
                    rank = [schema.KINDS["decompose"]["rank"], project.get("priority", 100)]
                    options.append((rank, functools.partial(
                        tasks.create, "decompose", project, name, record.get("report", record["brief"]), rank,
                        item=record["item"], record_hash=record["hash"])))
                continue
            known = L["tasks"].get(f"{project['name']}:{record['item']}")
            if record["status"] != "queued" or (known and (tasks.active(known) or known["record_hash"] == record["hash"])):
                continue
            kind = schema.QUEUE_KINDS[record["kind"]]
            rank = queue_rank(kind, project, record["position"])
            options.append((rank, functools.partial(tasks.create, kind, project, record["item"], record["brief"], rank,
                                                    item=record["item"], record_hash=record["hash"])))
    return options


def integrations() -> list:
    """One integration at a time per project, of its oldest reviewed item."""
    options = []
    for project in tasks.enabled_projects():
        if any(t["kind"] == "integrate" and t["place"] == project["name"] and t["status"] in ("running", "waiting")
               for t in L["tasks"].values()):
            continue
        reviewed = [t for t in L["tasks"].values()
                    if t["place"] == project["name"] and t["status"] == "review" and not held(t)]
        if reviewed:
            worker = min(reviewed, key=lambda t: t["updated_at"])
            rank = [schema.KINDS["integrate"]["rank"], project.get("priority", 100)]
            options.append((rank, functools.partial(tasks.create, "integrate", project, f"integrate-{worker['title']}",
                                                    worker["brief"], rank,
                                                    item=worker["item"], worker=worker["id"])))
    return options


def tree_work() -> list:
    """Per owned tree, at most one maintenance task: a gardening batch when its health changed or
    its routine interval passed, else a structural audit when that interval passed."""
    options = []
    for tree in managed_trees(CONFIG):
        health = tree_health(tree)
        if health is None or any(t["place"] == tree["name"] and schema.KINDS[t["kind"]]["scope"] == "tree"
                                 and t["status"] in ("running", "waiting") for t in L["tasks"].values()):
            continue
        gardens = [t for t in L["tasks"].values() if t["kind"] == "garden" and t["place"] == tree["name"]]
        latest = max(gardens, key=lambda t: t["created_at"], default=None)
        changed = health["leaves"] and not (latest and latest["record_hash"] == health["hash"])
        if changed or now() - tasks.last_created("garden", tree["name"]) > CONFIG["garden"]["every_seconds"]:
            leaves = [str(p.relative_to(trees.root(tree))) for p in trees.root(tree).rglob("*.md")]
            batch = "\n".join(trees.select(health, leaves, CONFIG["garden"]["leaves_per_pass"]))
            options.append((trees.rank(health), functools.partial(
                tasks.create, "garden", tree, "garden", batch, trees.rank(health), record_hash=health["hash"])))
        elif now() - tasks.last_created("tree-audit", tree["name"]) > CONFIG["garden"]["audit_every_seconds"]:
            rank = [schema.KINDS["tree-audit"]["rank"]]
            options.append((rank, functools.partial(tasks.create, "tree-audit", tree, "tree-audit", "", rank)))
    return options


def periodic() -> list:
    """The system-wide steward, inversely as frequent as the factory is busy, and a
    retrospective test audit after new accepted work."""
    options = []
    projects = tasks.enabled_projects()
    spawner = CONFIG["spawner"]
    concerns = {t["id"] for t in L["tasks"].values() if tasks.active(t) and t["kind"] != "steward"}
    concerns |= {key for key, record in queues.records().items() if record["status"] == "queued"
                 and not (key in L["tasks"] and L["tasks"][key]["record_hash"] == record["hash"]
                          and L["tasks"][key]["status"] in ("done", "failed"))}
    interval = spawner["steward_every_seconds"] * (1 + len(concerns))
    if (projects and now() - tasks.last_created("steward", "system") > interval
            and not any(t["kind"] == "steward" and t["status"] in ("running", "waiting") for t in L["tasks"].values())):
        options.append(([schema.KINDS["steward"]["rank"]], lambda: tasks.request_steward()[0]))
    audited = tasks.last_created("test-audit", "system")
    names = {project["name"] for project in projects}
    recent = sorted((t for t in L["tasks"].values() if t["place"] in names and t["kind"] in ("item", "integrate")
                     and t["status"] == "done" and t["updated_at"] > audited), key=lambda t: t["updated_at"])
    if (recent and now() - audited > spawner["test_auditor_every_seconds"]
            and not any(t["kind"] == "test-audit" and t["status"] in ("running", "waiting")
                        for t in L["tasks"].values())):
        options.append(([schema.KINDS["test-audit"]["rank"]], lambda: tasks.request_test_auditor(recent)[0]))
    return options


def tree_health(tree: dict) -> dict | None:
    """The tree's health, re-read every `garden.check_seconds`; None while it cannot be read
    (David is told once per new reason)."""
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
