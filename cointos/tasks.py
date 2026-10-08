"""Tasks and the places they work in.

A task record is plain data in the ledger (`L["tasks"]`), created only by `create` and moved
through its lifecycle only by `cointos/lifecycle.py`. Its fields:

    id, kind, role, place, title        identity; `place` is a project, a tree, or "system"
    item, brief                          what to do; `item` names its queue item, if any
    record, record_version               its daemon queue record and the record version it was made for
    health_hash                          a garden's tree-health identity when it was made
    worker                               an integration's worker task
    rank, created_at, updated_at         admission order and times
    status, runs, agent, session, note   lifecycle: waiting | running | review | done | failed
    receipt, result, acceptance          how it ended (see what/is/the/agent/completion/model.md)
    worktree, branch, base_commit        where it works; system tasks have no branch
    stage, reasoning_effort, budget      pinned metadata; `stage` only for items
    prompt_date, system_context          fixed system-prefix identity (content is deduplicated in the ledger)
    abilities, spawned_by                an operator's permissions; the task whose run started it
    replacements                         a decomposition's replacement children
    revision                             why and by whom its item was last revised
    review, rejections                   the integrator's latest return notes and their count
    fresh_retries, recovery_note, recovery_context   budget recovery state
    replaced_by, replacement_reason      set when the user supersedes failed work
    landing                              an integration's validated candidate, while it lands
    validating                           a landing check is in flight (not persisted)
    admission_hold                       the user's durable kill hold; explicit resume releases it
    interrupted_at                      when an existing session last lost its run
    launch_failures                     consecutive runs that never reached the model
    retired                             how its worktree and branch were retired once settled
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from cointos import names, queues, schema
from cointos.config import ROOT, managed_trees
from cointos.state import CONFIG, L, log, now

SYSTEM = {"name": "system", "path": str(ROOT)}


# ---------------------------------------------------------------- places

def enabled_projects() -> list[dict]:
    return [p for p in CONFIG["projects"] if p.get("enabled", True)]


def project_named(name: str, require_enabled: bool = True) -> dict:
    for project in CONFIG["projects"]:
        if project["name"].lower() == name.lower():
            if require_enabled and not project.get("enabled", True):
                raise ValueError(f"project {project['name']!r} is disabled")
            return project
    raise ValueError(f"unknown project {name!r}; configured: {[p['name'] for p in CONFIG['projects']]}")


def place(task: dict) -> dict:
    """The project, tree or system a task works in."""
    if task["place"] == "system":
        return SYSTEM
    places = managed_trees(CONFIG) if schema.KINDS[task["kind"]]["scope"] == "tree" else CONFIG["projects"]
    return next(p for p in places if p["name"] == task["place"])


def active(task: dict) -> bool:
    """Unfinished: waiting, running or in review."""
    return task["status"] in schema.ACTIVE


def pending(task: dict) -> bool:
    """Waiting for or holding a run (not yet in review or settled)."""
    return task["status"] in schema.PENDING


def settled(task: dict) -> bool:
    """Done or failed: its lifecycle has ended."""
    return task["status"] in schema.SETTLED


# ---------------------------------------------------------------- creating tasks

def create(kind: str, where: dict, name: str, brief: str, rank: list, *, item: str | None = None,
           record_version: int | None = None, worker: str | None = None, reasoning_effort: str | None = None,
           budget: dict | None = None, **fields) -> dict:
    """A new waiting task of `kind` in `where`. A queue-backed task is named by its item, so its
    id is its record's key; any other is numbered (`garden-3`), so ids never repeat. Caller holds LOCK."""
    spec = schema.KINDS[kind]
    title = Path(item).stem if item else name
    if not spec["record"]:
        name = numbered(where["name"], name)
    system = where["name"] == "system"
    record = queues.records().get(f"{where['name']}:{item}") if spec["record"] else None
    created = now()
    task = {
        "id": f"{where['name']}:{name}", "kind": kind, "role": spec["role"], "place": where["name"],
        "name": names.invent({t["name"] for t in L["tasks"].values() if t.get("name")}),
        "title": title, "item": item, "brief": brief,
        "record": f"{where['name']}:{item}" if spec["record"] else None, "record_version": record_version,
        "worker": worker, "rank": rank, "created_at": created, "updated_at": created,
        "status": "waiting", "runs": 0, "agent": None, "session": None, "note": None,
        "receipt": None, "result": None, "revision": None,
        "worktree": str(ROOT) if system else str(Path(where["path"]).parent / ".worktrees" / Path(where["path"]).name / name),
        "branch": None if system else f"work/{name}",
        "stage": record["stage"] if kind == "item" else None,
        "prompt_date": time.strftime("%a %b %d %Y", time.localtime(created)),
        **fields,
    }
    # Recovery is a new managerial assignment, not another run of the failed worker.
    # Its record supplies evidence/identity, but the worker's limits cannot govern it.
    metadata = record if kind != "decompose" else None
    task["reasoning_effort"] = schema.default_effort(CONFIG, {
        **task, "reasoning_effort": schema.effort(reasoning_effort) or (metadata or {}).get("reasoning_effort")},
        reviewed=L["tasks"].get(worker))
    task["budget"] = schema.budget(CONFIG, budget if budget is not None else (metadata or {}).get("budget"))
    L["tasks"][task["id"]] = task
    L["cadence"][f"{kind}:{where['name']}"] = created
    log("task created", task=task["id"])
    return task


def numbered(place_name: str, base: str) -> str:
    prefix = f"{place_name}:{base}-"
    taken = [int(tid[len(prefix):]) for tid in L["tasks"] if tid.startswith(prefix) and tid[len(prefix):].isdigit()]
    return f"{base}-{max(taken, default=0) + 1}"


def last_created(kind: str, place_name: str) -> float:
    return L["cadence"].get(f"{kind}:{place_name}", 0)


def request_operator(name: str, brief: str, project: str | None, abilities, reasoning_effort, budget,
                     spawner: tuple[dict, dict] | None = None) -> dict:
    """One explicitly requested ad-hoc operator task. Caller holds LOCK.

    An agent run may start one too, as (its task, its agent). A worker may not: its work is
    reviewed, and an operator would land it unreviewed. The operator gets no ability its
    spawner lacks, and its budget comes out of the spawner's run."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("operator name must use letters, numbers, dot, underscore or dash")
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("operator brief is required")
    abilities = schema.abilities(abilities)
    if spawner:
        task, agent = spawner
        if task["role"] == "worker":
            raise ValueError("a worker does not start operators: an operator would land its work unreviewed; "
                             "finish blocked with the evidence instead")
        if set(abilities) - set(task.get("abilities") or ["standard"]):
            raise ValueError("an operator gets no ability its spawner lacks")
        used = schema.spent(agent)
        left = {key: task["budget"][key] - used[key] for key in schema.BUDGET_KEYS}
        if not budget or set(budget) != set(schema.BUDGET_KEYS):
            raise ValueError(f"give the operator both budget limits from what this run has left: "
                             f"{left['generation_tokens']:,} tokens and {left['generation_seconds']:.0f} seconds")
        schema.budget(CONFIG, budget)
        if any(budget[key] > left[key] for key in schema.BUDGET_KEYS):
            raise ValueError(f"this run has only {left['generation_tokens']:,} tokens and "
                             f"{left['generation_seconds']:.0f} seconds left to give")
    where = project_named(project) if project else SYSTEM
    known = next((t for t in L["tasks"].values() if t["kind"] == "operator" and t["place"] == where["name"]
                  and t["title"] == f"operator-{name}" and active(t)), None)
    if known:
        raise ValueError(f"operator task {known['id']} is already active")
    operator = create("operator", where, f"operator-{name}", brief, [schema.KINDS["operator"]["rank"], where.get("priority", 0)],
                      abilities=abilities, reasoning_effort=reasoning_effort, budget=budget,
                      spawned_by=spawner[0]["id"] if spawner else None)
    if spawner:
        granted = spawner[1].setdefault("granted", {})
        for key in schema.BUDGET_KEYS:
            granted[key] = granted.get(key, 0) + budget[key]
    return operator


def request_steward() -> tuple[dict, bool]:
    """The one system-wide loose-end scout: the live one, or a new one now."""
    existing = [t for t in L["tasks"].values() if t["kind"] == "steward" and pending(t)]
    if existing:
        return min(existing, key=lambda task: task["created_at"]), False
    projects = enabled_projects()
    if not projects:
        raise ValueError("a scout requires at least one configured project")
    allowed = ", ".join(project["name"] for project in projects)
    brief = ("Inspect the CointOS runtime and all configured projects (" + allowed + ") plus their "
             "accessible knowledge trees for concrete loose ends, dangling work, stale recorded state, "
             "or a valuable unfinished frontier. Choose the single most useful bounded concern. Do not "
             "implement product work. If managerial judgment is warranted, enqueue exactly one command "
             "in the project that owns it. If the concern is project enrollment itself, perform at most one "
             "cointos project action instead. Otherwise report that no actionable loose end was found.")
    return create("steward", SYSTEM, "loose-ends", brief, [schema.KINDS["steward"]["rank"]]), True


def request_test_auditor(recent: list[dict]) -> tuple[dict, bool]:
    """One global retrospective test audit of recently accepted work, deduplicated."""
    existing = [t for t in L["tasks"].values() if t["kind"] == "test-audit" and pending(t)]
    if existing:
        return min(existing, key=lambda task: task["created_at"]), False
    evidence = "\n".join(f"- {task['place']}: {task.get('item') or task['title']} ({task['id']})" for task in recent[-8:])
    brief = ("Recent accepted product work to sample:\n" + evidence + "\n\nChoose one landing. Read the "
             "project's specification and test-contract guidance, inspect the implementation and actual tests, and "
             "run the relevant suite. Green tests are not sufficient: check that the suite would reject plausible "
             "shortcuts and covers boundaries, invalid inputs, state transitions, ordering, rollback, and invariants "
             "required by the spec. Queue at most one manager command, in the owning project, only for a concrete gap.")
    return create("test-audit", SYSTEM, "test-audit", brief, [schema.KINDS["test-audit"]["rank"]]), True


# ---------------------------------------------------------------- metadata changes

def set_reasoning(task_id: str, effort: str) -> None:
    """Change future replies; already rendered thoughts keep their effort. Caller holds LOCK."""
    if effort not in schema.EFFORTS:
        raise ValueError("reasoning effort must be low, medium or xhigh")
    task, record = L["tasks"].get(task_id), queues.records().get(task_id)
    if task is None and record is None:
        raise ValueError(f"unknown task {task_id}")
    for holder in (task, record, *(a for a in L["agents"].values() if a["task"] == task_id)):
        if holder is not None:
            holder["reasoning_effort"] = effort
    log("reasoning changed", task=task_id, effort=effort)


def set_budget(task_id: str, changes) -> dict:
    """Change only undispatched or waiting work; never surprise an active run. Caller holds LOCK."""
    task, record = L["tasks"].get(task_id), queues.records().get(task_id)
    if task and (task["status"] != "waiting" or task.get("validating")):
        raise ValueError("budget changes require an inactive waiting task")
    if not task and (not record or queues.status(record) != "queued"):
        raise ValueError("budget changes require a waiting task or undispatched queue item")
    if not changes:
        raise ValueError("budget changes must contain at least one limit")
    schema.budget(CONFIG, changes)  # validate the request before any mutation
    effective = schema.budget(CONFIG, {**(task or record).get("budget", {}), **changes})
    for holder in (task, record):
        if holder is not None:
            holder["budget"] = effective
    log("task budget changed", task=task_id, budget=effective)
    return {"ok": True, "budget": effective}
