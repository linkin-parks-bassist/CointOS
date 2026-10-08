"""The spawner: which task runs next, and admitting runs while there is room.

Waiting tasks resume first, in rank order; then the best new work is created, also by rank
(`what/is/the/architecture/of/cointos.md`, *Autonomy*): integrating reviewed items before new
work, decompositions, queued items and commands in queue order within project priority, then
the periodic steward, test audit and tree maintenance. Caller holds LOCK throughout.
"""
from __future__ import annotations

import functools
import subprocess

from cointos import git, lanes, lifecycle, queues, runs, schema, tasks, trees
from cointos.config import managed_trees
from cointos.state import CONFIG, STOPPING, L, alert, log, now


def refresh() -> tuple[dict, dict]:
    """Live queue records and dependency readiness, current even while admission is full or
    paused: ({project: its live records}, {project: {item: readiness}})."""
    lifecycle.reconcile()
    projects = tasks.enabled_projects()
    scanned = {p["name"]: queues.live(p["name"]) for p in projects}
    ready = {p["name"]: queues.readiness(scanned[p["name"]], queues.landed(p["name"])) for p in projects}
    problems = {f"{project}:{item}": state for project, states in ready.items() for item, state in states.items()
                if state not in ("ready", "waiting")}
    for key, problem in problems.items():
        if L["dependency_problems"].get(key) != problem:
            alert(f"{key} can never start: {problem}.")
    L["dependency_problems"] = problems
    return scanned, ready


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
    scanned, ready = refresh()
    reorder(scanned)
    exiting = {agent["task"] for agent in L["agents"].values()}  # a receipt settles before its run exits
    waiting = [t for t in L["tasks"].values() if t["status"] == "waiting" and not t.get("replaced_by")
               and t["id"] not in exiting and runnable(t, ready)]
    if waiting:
        return min(waiting, key=lambda t: (t["rank"], t["created_at"]))
    options = queued_work(scanned, ready) + integrations() + tree_work() + periodic()
    if not options:
        return None
    created = min(options, key=lambda option: option[0])[1]()
    # A dispatch refused before it ran failed its item for good; what that changed (its manager
    # is now due) decides the next choice.
    return created if created is not None else next_task()


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
    if task["kind"] == "integrate":
        worker = L["tasks"].get(task["worker"])
        return bool(worker and worker["status"] == "review" and not held(worker))
    return True


def queue_rank(kind: str, project: dict, position: int) -> list:
    return [schema.KINDS[kind]["rank"], project.get("priority", 100), position]


def reorder(scanned: dict) -> None:
    """Waiting queue tasks take their record's current position: the user and managers reorder."""
    for project in tasks.enabled_projects():
        for record in scanned[project["name"]]:
            task = L["tasks"].get(f"{project['name']}:{record['item']}")
            if task and task["status"] == "waiting":
                task["rank"] = queue_rank(task["kind"], project, record["position"])


def queued_work(scanned: dict, ready: dict) -> list:
    """New tasks for ready queue records: a worker item or command, or a decomposition manager
    for a failed worker item awaiting managerial recovery. A test-contract brief relying on APIs
    main lacks is refused before any run and goes to that recovery pass."""
    options = []
    for project in tasks.enabled_projects():
        for record in scanned[project["name"]]:
            if record["held_by"]:
                continue
            found = queues.state(record)
            if found["decompose"]:
                name = f"decompose-{record['item']}"
                known = L["tasks"].get(f"{project['name']}:{name}")
                if not (known and (tasks.active(known) or known["record_version"] == record["version"])):
                    rank = [schema.KINDS["decompose"]["rank"], project.get("priority", 100)]
                    options.append((rank, functools.partial(
                        tasks.create, "decompose", project, name, found["blocker"], rank,
                        item=record["item"], record_version=record["version"])))
                continue
            if found["status"] != "queued" or ready[project["name"]][record["item"]] != "ready":
                continue
            known = L["tasks"].get(f"{project['name']}:{record['item']}")
            if known and (tasks.active(known) or known["record_version"] == record["version"]):
                continue
            kind = schema.QUEUE_KINDS[record["kind"]]
            rank = queue_rank(kind, project, record["position"])
            options.append((rank, functools.partial(dispatch, kind, project, record, rank)))
    return options


def dispatch(kind: str, project: dict, record: dict, rank: list) -> dict | None:
    """Create a queue record's task. A test-contract brief whose `Relies on:` APIs are absent
    from main is refused at once (None), before any worker spends generation on it."""
    task = tasks.create(kind, project, record["item"], record["brief"], rank,
                        item=record["item"], record_version=record["version"])
    missing = unfounded(project, record) if record.get("stage") == "test-contract" else None
    if not missing:
        return task
    log("brief infeasible", task=task["id"], missing=missing)
    lifecycle.refuse_dispatch(task, f"Dispatch check: the brief relies on {', '.join(missing)}, absent on "
                                    f"{project.get('main_branch', 'main')}. Correct the brief to the owner APIs "
                                    f"that exist (hold/revise), or queue the prerequisite skeleton it needs first.")
    return None


def unfounded(project: dict, record: dict) -> list[str]:
    """The `Relies on:` names of a brief absent from main (none if the repository is unreadable:
    the run itself reports that)."""
    try:
        head = git.head(project["path"], project.get("main_branch", "main"))
    except ValueError:
        return []
    return queues.missing_reliances(project["path"], head, queues.relies_on(record["brief"]))


def integrations() -> list:
    """One integration at a time per project, of its oldest reviewed item. An integration occupies
    its project only while it can proceed: one that is held, or whose worker is back at work,
    does not keep the project's other reviewed items from being integrated."""
    options = []
    for project in tasks.enabled_projects():
        active = [t for t in L["tasks"].values() if t["kind"] == "integrate" and t["place"] == project["name"]
                  and tasks.pending(t)]
        if any(t["status"] == "running" or (not held(t) and L["tasks"][t["worker"]]["status"] == "review")
               for t in active):
            continue
        integrated = {t["worker"] for t in active}
        reviewed = [t for t in L["tasks"].values() if t["place"] == project["name"] and t["status"] == "review"
                    and not held(t) and t["id"] not in integrated]
        if reviewed:
            worker = min(reviewed, key=lambda t: t["updated_at"])
            rank = [schema.KINDS["integrate"]["rank"], project.get("priority", 100)]
            options.append((rank, functools.partial(tasks.create, "integrate", project, f"integrate-{worker['title']}",
                                                    worker["brief"], rank,
                                                    item=worker["item"], worker=worker["id"])))
    return options


def idle_seconds() -> float:
    """How long every work-model lane has been free (0 while any is held or kept for an agent)."""
    work = [lane for lane in L["lanes"] if lane["model"] == CONFIG["work_model"] and lane["up"]]
    if not work or any(lane["holder"] is not None for lane in work):
        return 0
    return now() - max(max(lane.get("free_since", 0), lane.get("held_until", 0)) for lane in work)


def tree_work() -> list:
    """Per owned tree, at most one maintenance task: a gardening batch when its health changed or
    its routine interval passed, else a structural audit when that interval passed. A disabled
    project's tree is left alone."""
    options = []
    disabled = {p["name"] for p in CONFIG["projects"] if not p.get("enabled", True)}
    for tree in managed_trees(CONFIG):
        if tree["name"] in disabled:
            continue
        health = tree_health(tree)
        if health is None or any(t["place"] == tree["name"] and schema.KINDS[t["kind"]]["scope"] == "tree"
                                 and tasks.pending(t) for t in L["tasks"].values()):
            continue
        gardens = [t for t in L["tasks"].values() if t["kind"] == "garden" and t["place"] == tree["name"]]
        latest = max(gardens, key=lambda t: t["created_at"], default=None)
        changed = health["leaves"] and not (latest and latest.get("health_hash") == health["hash"])
        if changed or now() - tasks.last_created("garden", tree["name"]) > CONFIG["garden"]["every_seconds"]:
            leaves = [str(p.relative_to(trees.root(tree))) for p in trees.root(tree).rglob("*.md")]
            batch = "\n".join(trees.select(health, leaves, CONFIG["garden"]["leaves_per_pass"]))
            options.append((trees.rank(health), functools.partial(
                tasks.create, "garden", tree, "garden", batch, trees.rank(health), health_hash=health["hash"])))
        elif now() - tasks.last_created("tree-audit", tree["name"]) > CONFIG["garden"]["audit_every_seconds"]:
            rank = [schema.KINDS["tree-audit"]["rank"]]
            options.append((rank, functools.partial(tasks.create, "tree-audit", tree, "tree-audit", "", rank)))
    return options


def periodic() -> list:
    """The system-wide steward, inversely as frequent as the factory is busy (work the user
    killed is not busyness) and once soon after the GPU goes idle, and a retrospective
    test audit after new accepted work."""
    options = []
    projects = tasks.enabled_projects()
    spawner = CONFIG["spawner"]
    concerns = {t["id"] for t in L["tasks"].values()
                if tasks.active(t) and t["kind"] != "steward" and not t.get("admission_hold")}
    concerns |= {key for key, record in queues.records().items() if queues.status(record) == "queued"}
    interval = spawner["steward_every_seconds"] * (1 + len(concerns))
    names = {project["name"] for project in projects}
    stewarded = tasks.last_created("steward", "system")
    settled = max((t["updated_at"] for t in L["tasks"].values()
                   if t["place"] in names and tasks.settled(t)), default=0)
    # An idle GPU gets one scout per stretch of settled project work: a scout that finds nothing
    # leaves the GPU idle again but settles no project work, so it does not summon another.
    stalled = (settled > stewarded and idle_seconds() > spawner["idle_steward_seconds"])
    if (projects and (stalled or now() - stewarded > interval)
            and not any(t["kind"] == "steward" and tasks.pending(t) for t in L["tasks"].values())):
        options.append(([schema.KINDS["steward"]["rank"]], lambda: tasks.request_steward()[0]))
    audited = tasks.last_created("test-audit", "system")
    recent = sorted((t for t in L["tasks"].values() if t["place"] in names and t["kind"] in ("item", "integrate")
                     and t["status"] == "done" and t["updated_at"] > audited), key=lambda t: t["updated_at"])
    if (recent and now() - audited > spawner["test_auditor_every_seconds"]
            and not any(t["kind"] == "test-audit" and tasks.pending(t)
                        for t in L["tasks"].values())):
        options.append(([schema.KINDS["test-audit"]["rank"]], lambda: tasks.request_test_auditor(recent)[0]))
    return options


def tree_health(tree: dict) -> dict | None:
    """The tree's health, re-read every `garden.check_seconds`; None while it cannot be read
    (the user is told once per new reason)."""
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
