"""The spawner: which task runs next, and admitting runs while there is room.

Waiting tasks resume first, in rank order; then the best new work is created, also by rank
(`what/is/the/architecture/of/cointos.md`, *Autonomy*): integrating reviewed items before new
work, queued items and commands in queue order within project priority, then
the periodic steward, test audit and tree maintenance. Caller holds LOCK throughout.
"""
from __future__ import annotations

import functools
import subprocess
import threading
from copy import deepcopy

from cointos import (capacity, contracts, models, frontier, git, landing, lanes, lifecycle, packets, queues, runs,
                     schema, snapshots, tasks, trees)
from cointos.config import managed_trees
from cointos.state import CONFIG, STOPPING, LOCK, L, alert, log, now

BLOCKED_DEPENDENCY = 'depends on a blocked item'
COMPOSITIONS_TRIED: set[tuple] = set()


def factory_enabled() -> bool:
    return CONFIG.get('factory_enabled', True)


def allowed(task: dict) -> bool:
    """Personal mode admits requested work, never implicit supervision/recovery."""
    if factory_enabled():
        return True
    if task.get('kind') == 'operator' and task.get('place') == 'system':
        return True  # Operators originate at an explicit dispatch/tool boundary.
    return bool(task.get('dispatch_requested')) and task.get('kind') not in ('item', 'breakdown', 'integrate')


def refresh() -> tuple[dict, dict]:
    """Live queue records and dependency readiness, current even while admission is full or
    paused: ({project: its live records}, {project: {item: readiness}})."""
    lifecycle.reconcile()
    projects = tasks.enabled_projects() if factory_enabled() else []
    scanned = {p["name"]: queues.live(p["name"]) for p in projects}
    ready = {p["name"]: queues.readiness(scanned[p["name"]], queues.landed(p["name"])) for p in projects}
    problems = {f"{project}:{item}": state for project, states in ready.items() for item, state in states.items()
                if state not in ("ready", "waiting")}
    for key, problem in problems.items():
        # The blocked item answers for itself; its dependents only have to wait for it.
        if L["dependency_problems"].get(key) != problem and not problem.startswith(BLOCKED_DEPENDENCY):
            alert(f"{key} can never start: {problem}.")
    L["dependency_problems"] = problems
    # Materialize recovery before choosing existing waiting work, so Operator rank
    # applies immediately instead of starving behind a permanent waiting backlog.
    repair_work(scanned)
    retry_compositions(scanned)
    L['work_frontier'] = [row for project in projects for row in frontier.view(project['name'])]
    return scanned, ready


def retry_compositions(scanned: dict) -> None:
    """Restart work refused because its tests would not merge, once they do.

    Nothing else ever would: main or the composer can change with no owner left watching.
    Each exact input is tried once per daemon run, outside LOCK; a real clash stays with its
    recovery owner.
    """
    for project in tasks.enabled_projects():
        rules = project.get('test_policy')
        for record in scanned.get(project['name'], []) if rules and not L['paused'] else []:
            key, task = queues.key(record), queues.current(record)
            failure = task and (task.get('composition_failure')
                                or (task.get('submission_failure') or {}).get('composition'))
            repair = failure and frontier.controller(record)
            if (not failure or queues.state(record)['status'] != 'blocked' or record['held_by']
                    or packets.pending(record) or (repair and tasks.active(repair))):
                continue
            main, commits = git.head(project['path'], project['main_branch']), landing.tests_of(task)
            attempt = (key, record['version'], main, tuple(commits))
            if commits and attempt not in COMPOSITIONS_TRIED:
                COMPOSITIONS_TRIED.add(attempt)
                threading.Thread(target=retry_composition, args=(deepcopy(project), key, attempt, deepcopy(rules), runs.material_baselines(project['name'], commits)), daemon=True).start()


def retry_composition(project: dict, key: str, attempt: tuple, rules: dict, prior=()) -> None:
    try:
        runs.prepare_test_inputs(project, attempt[2], list(attempt[3]), prior)
    except Exception as error:  # still a real clash, or an unusable repository
        log('composition still clashes', item=key, error=str(error)[:300])
        return
    with LOCK:
        record = queues.records().get(key)
        if not record or record['version'] != attempt[1] or queues.state(record)['status'] != 'blocked':
            return
        repair = frontier.controller(record)
        current_project = next((p for p in tasks.enabled_projects() if p['name'] == project['name']), None)
        if (L['paused'] or L['restarting'] or STOPPING.is_set() or record['held_by']
                or packets.pending(record) or (repair and tasks.active(repair))
                or current_project != project):
            COMPOSITIONS_TRIED.discard(attempt)
            return
        task = queues.current(record)
        if git.head(project['path'], project['main_branch']) != attempt[2] or landing.tests_of(task) != list(attempt[3]):
            return
        record.update(version=record['version'] + 1, revised_by='cointos')
        for field in ('composition_failure', 'submission_failure'):
            task.pop(field, None)
        lifecycle.refresh_assignment(key, 'cointos', 'its tests now merge with main', record)
        log('composition retried', item=key, main=attempt[2])


def repair_work(scanned: dict) -> None:
    """Reconcile one First Responder per unchanged failure, including taskless bad dependencies."""
    if not factory_enabled() or L["paused"]:
        return
    for source in list(L["tasks"].values()):
        if allowed(source) and frontier.reason(source) is not None and not draft_blocked(source):
            tasks.request_repair(source)
    for records in scanned.values():
        for record in records:
            # A split above may have replaced what this earlier scan still shows as failed.
            current = queues.records().get(queues.key(record), record)
            if frontier.reason(current) is not None:
                tasks.request_repair(current)


def spawn() -> None:
    """Start runs while there is room, work and memory."""
    if (STOPPING.is_set() or models.changing() or L["restarting"] or L["paused"] or lanes.blocked()
            or not L["models"][CONFIG["work_model"]]["up"]):
        return
    # User-requested Operators may start while Coin is still answering and the
    # ordinary pool is full. Agent-created helpers keep ordinary admission.
    operators = [t for t in L['tasks'].values() if t.get('kind') == 'operator'
                 and t['status'] == 'waiting' and not t.get('spawned_by') and not t.get('replaced_by')
                 and not any(a['task'] == t['id'] for a in L['agents'].values())]
    if operators:
        _, ready = refresh()
        for task in sorted(operators, key=lambda t: (t['rank'], t['created_at'])):
            if runnable(task, ready) and snapshots.make_room(capacity.agent_gb(task['id']), claim=False):
                runs.start(task)
    if now() - L['user_last_thought'] < CONFIG['spawner']['user_quiet_seconds']:
        return
    # A supervisor takes a slot at once, past max_agents, while memory allows it.
    for task in [t for t in L["tasks"].values() if t["kind"] == "supervise" and t["status"] == "waiting"]:
        if runnable(task, {}) and snapshots.make_room(capacity.agent_gb(task['id']), claim=False):
            runs.start(task)
    while len(L["agents"]) < CONFIG["spawner"]["max_agents"]:
        task = next_task()
        if task is None:
            return
        if not snapshots.make_room(capacity.agent_gb(task['id']), claim=False):
            return
        runs.start(task)


def next_task() -> dict | None:
    """The task to run next: a waiting one first, else the best new one, created now."""
    scanned, ready = refresh()
    reorder(scanned)
    exiting = {agent["task"] for agent in L["agents"].values()}  # a receipt settles before its run exits
    waiting = [t for t in L["tasks"].values() if t["status"] == "waiting" and not t.get("replaced_by")
               and t["id"] not in exiting and runnable(t, ready)]
    best = min(waiting, key=lambda t: (t["rank"], t["created_at"]), default=None)
    options = queued_work(scanned, ready) + integrations() + tree_work() + periodic()
    # A new task outranking every waiting one goes first: an integration drains review and
    # unblocks dependents, so it must not queue behind test authoring for the one slot.
    options = [option for option in options if best is None or option[0] < best["rank"]]
    if not options:
        return best
    created = min(options, key=lambda option: option[0])[1]()
    # A dispatch refused before it ran failed its item; what that changed (its controller
    # is now due) decides the next choice.
    return created if created is not None else next_task()


def held(task: dict) -> bool:
    """Whether its queue item is held while its owner decides about it."""
    return bool(task.get("admission_hold")) or (bool(task["record"]) and
           bool(queues.records().get(task["record"], {}).get("held_by")))


def runnable(task: dict, ready: dict) -> bool:
    if not allowed(task) or held(task) or task.get('split_supervisor') or frontier.obsolete(task):
        return False
    if task.get('repair_origin') and not frontier.runnable(task):
        return False
    if task.get('repair_origin') and not task['runs']:
        source = L['tasks'].get(task['repair_origin']['task'])
        if source and draft_blocked(source):
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
        # Retained reviewers obey the same project serialization as new ones.
        return bool(worker and review_ready(worker, ready.get(worker['place']))
                    and not any(other["kind"] == "integrate" and other["place"] == task["place"]
                                and other["id"] != task["id"] and other["status"] == "running"
                                for other in L["tasks"].values()))
    return True


def draft_blocked(task: dict) -> bool:
    """Unstarted garden recovery waits for canonical draft owners, not another allowance."""
    if task['kind'] != 'garden':
        return False
    tree = next((tree for tree in managed_trees(CONFIG) if tree['name'] == task['place']), None)
    health = tree_health(tree) if tree else None
    if tree and health is None and tree['name'] not in L['trees']:
        return True  # preserve first-observation ordering without blocking admission on I/O
    return health is not None and bool(set(task['brief'].splitlines()) & set(health.get('deferred', [])))


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
    """New worker or planning tasks for ready records; recovery has already been reconciled.
    Test contracts relying on absent APIs are refused before a worker run."""
    if not factory_enabled():
        return []
    options = []
    for project in tasks.enabled_projects():
        for record in scanned[project["name"]]:
            if record["held_by"]:
                continue
            found = queues.state(record)
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
    task = tasks.create(kind, project, record["item"], record["brief"], rank, item=record["item"],
                        record_version=record["version"], **({"abilities": record["abilities"]} if record.get("abilities") else {}))
    missing = unfounded(project, record) if record.get("stage") == "test-contract" else None
    if not missing:
        return task
    log("brief infeasible", task=task["id"], missing=missing)
    lifecycle.refuse_dispatch(task, f"Dispatch check: the brief relies on {', '.join(missing)}, absent from "
                                    "accepted source. Revise the brief to use existing owner APIs, "
                                    "or queue the prerequisite skeleton it needs first.")
    return None


def unfounded(project: dict, record: dict) -> list[str]:
    """The `Relies on:` names of a brief absent from main (none if the repository is unreadable:
    the run itself reports that)."""
    try:
        head = git.head(project["path"], project.get("main_branch", "main"))
    except ValueError:
        return []
    return queues.missing_reliances(project["path"], head, queues.relies_on(record["brief"]))


def review_ready(worker: dict, ready: dict | None = None) -> bool:
    """A waiting consumer review cannot occupy its pending correction's review slot."""
    if worker['status'] != 'review' or held(worker):
        return False
    if not worker.get('record'):
        return True
    if ready is None:
        ready = queues.readiness(queues.live(worker['place']), queues.landed(worker['place']))
    return ready.get(worker['item']) == 'ready'


def integrations() -> list:
    """One integration at a time per project, of its oldest reviewed item. An integration occupies
    its project only while it can proceed: one that is held, or whose worker is back at work,
    does not keep the project's other reviewed items from being integrated."""
    if not factory_enabled():
        return []
    options = []
    for project in tasks.enabled_projects():
        active = [t for t in L["tasks"].values() if t["kind"] == "integrate" and t["place"] == project["name"]
                  and tasks.pending(t)]
        if any(t["status"] == "running" or (not held(t) and review_ready(L["tasks"][t["worker"]]))
               for t in active):
            continue
        integrated = {t["worker"] for t in active}
        reviewed = [t for t in L["tasks"].values() if t["place"] == project["name"]
                    and review_ready(t) and t["id"] not in integrated]
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
    if not factory_enabled():
        return []
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
            leaves = health.get('inventory', [])
            batch = "\n".join(trees.select(health, leaves, CONFIG["garden"]["leaves_per_pass"]))
            if batch:
                options.append((trees.rank(health), functools.partial(
                    tasks.create, "garden", tree, "garden", batch, trees.rank(health), health_hash=health["hash"])))
        elif now() - tasks.last_created("tree-audit", tree["name"]) > CONFIG["garden"]["audit_every_seconds"]:
            rank = [schema.KINDS["tree-audit"]["rank"]]
            options.append((rank, functools.partial(tasks.create, "tree-audit", tree, "tree-audit", "", rank)))
    return options


def request_role(role: str, body: dict) -> dict:
    """A role the scheduler normally starts, started now by the user. Caller holds LOCK."""
    kind = next(k for k, spec in schema.KINDS.items() if spec["role"] == role)
    if role == "first-responder":
        source = L["tasks"].get(body.get("task", ""))
        known = frontier.controller(source) if source else None
        if known and known["role"] != "first-responder":
            # An Operator left over from before this role gives way; only the user can ask for this.
            for agent_id, agent in list(L["agents"].items()):
                if agent["task"] == known["id"]:
                    lifecycle.stop(agent_id, "replaced by a First Responder", requeue=False)
            if known["status"] not in schema.SETTLED:
                lifecycle.fail(known, "replaced by a First Responder")
            known["former_repair_origin"] = known.pop("repair_origin")
        responder = tasks.request_repair(source)[0] if source else None
        if responder is None:
            if body.get('task'):
                raise ValueError('a first-responder needs an existing task or a standalone runtime diagnostic brief')
            if not body.get('brief', '').strip():
                raise ValueError('a first-responder needs a concrete runtime diagnostic brief')
            existing = next((t for t in L['tasks'].values() if t['kind'] == 'first-response'
                             and t['title'] == body['name'] and tasks.active(t) and not t.get('repair_origin')), None)
            return existing or tasks.create('first-response', tasks.SYSTEM, body['name'], body['brief'],
                                            [schema.KINDS['first-response']['rank']])
        return responder
    if role == "supervisor":
        target = L["tasks"].get(body.get("task", ""))
        if target is None or not tasks.active(target):
            raise ValueError("a supervisor needs task: a live agent's task to look at")
        return tasks.request_supervisor(target, schema.spent(L["agents"][target["agent"]])["generation_tokens"]
                                        if target.get("agent") in L["agents"] else 0)
    effort = {"reasoning_effort": body["reasoning_effort"]} if body.get("reasoning_effort") else {}
    if role in ("steward", "test-auditor"):
        return tasks.create(kind, tasks.SYSTEM, body["name"], body["brief"], [schema.KINDS[kind]["rank"]], budget=body.get("budget"), **effort)
    if role == "integrator":
        worker = L["tasks"].get(body.get("task", ""))
        if worker is None or not review_ready(worker):
            raise ValueError("an integrator needs task: a reviewed worker task ready to land")
        project = tasks.project_named(worker["place"])
        rank = [schema.KINDS[kind]["rank"], project.get("priority", 100)]
        return tasks.create(kind, project, f"integrate-{worker['title']}", worker["brief"], rank, item=worker["item"],
                            worker=worker["id"], budget=body.get("budget"), **effort)
    tree = next((t for t in managed_trees(CONFIG) if t["name"] == body.get("project")), None)
    if tree is None:
        raise ValueError(f"a {role} needs project: one of {', '.join(t['name'] for t in managed_trees(CONFIG))}")
    health = tree_health(tree) or {}
    fields = {"health_hash": health.get("hash")} if kind == "garden" else {}
    return tasks.create(kind, tree, kind, body["brief"], trees.rank(health) if health else [schema.KINDS[kind]["rank"] or 0],
                        budget=body.get("budget"), **effort, **fields)


def periodic() -> list:
    """The system-wide steward, inversely as frequent as the factory is busy (work the user
    killed is not busyness) and once soon after the GPU goes idle, and a retrospective
    test audit after new accepted work."""
    if not factory_enabled():
        return []
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
    """Last completed observation, never subprocess I/O in the admission transaction."""
    seen = L["trees"].get(tree["name"])
    return seen if seen is not None and 'error' not in seen else None


def refresh_trees() -> None:
    """Observe due trees outside LOCK; publish only against the captured configuration/cache.

    One daemon observer calls this. Admission sees completed observations, while
    receipt-time health checks may supersede an observation still in flight.
    """
    with LOCK:
        if not factory_enabled() or STOPPING.is_set() or L['restarting']:
            return
        configured = deepcopy({key: CONFIG[key] for key in ('projects', 'trees')})
        seen = dict(L['trees'])
        interval, timeout = CONFIG['garden']['check_seconds'], CONFIG['timeouts']['command_seconds']
    disabled = {p['name'] for p in configured['projects'] if not p.get('enabled', True)}
    for tree in managed_trees(configured):
        previous = seen.get(tree['name'])
        if (STOPPING.is_set() or tree['name'] in disabled
                or previous is not None and now() - previous['checked_at'] < interval):
            continue
        try:
            fresh = {**trees.health(tree, timeout), "checked_at": now()}
            deferred = sorted(set(trees.pending(fresh)) & set(fresh.get('deferred', [])))
            fresh['deferred_health'] = deferred
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            fresh = {'error': str(error), 'checked_at': now()}
        with LOCK:
            if (STOPPING.is_set() or L['restarting']
                    or configured != {key: CONFIG[key] for key in ('projects', 'trees')}
                    or L['trees'].get(tree['name']) is not previous):
                continue
            if fresh.get('deferred_health') and fresh['deferred_health'] != (previous or {}).get('deferred_health', []):
                alert(f"Cannot garden pending or absent canonical answers in {tree['name']}: " +
                      ', '.join(fresh['deferred_health']) + '. Preserve and reconcile their owning answers before maintenance.')
            if 'error' in fresh and fresh['error'] != (previous or {}).get('error'):
                alert(f"Cannot read the {tree['name']} knowledge tree's health: {fresh['error']}")
            L['trees'][tree['name']] = fresh
