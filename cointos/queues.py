"""Queue records: the work wanted in each project, and the view of where that work stands.

A record holds what is asked for (brief, dependencies, stage, effort, budget, order, holds) and
one terminal fact written once by the lifecycle: `done`. Everything else about its state is
derived from its tasks by `state`, never stored: a record whose current task failed is blocked;
a failed worker item awaits its one managerial recovery pass. `version` counts revisions of what
is asked; a task made for an older version no longer speaks for the record. All mutations run
under the daemon lock; the runtime tree's queue leaves are a readable projection.
"""
from __future__ import annotations
import copy
import json
import re
from cointos import git, kt, schema
from cointos.config import ROOT
from cointos.state import CONFIG, L, log, now

# Queue item names that would collide with the ids of scheduler-created tasks in a project.
RESERVED = ("garden", "tree-audit")
RESERVED_PREFIXES = ("integrate-", "decompose-", "operator-", "loose-ends-", "test-audit-")


def line(text: str, label: str) -> str | None:
    """The value of a brief's `Label:` line, if it has one."""
    for row in text.splitlines():
        found = re.match(rf"\**{label}:\**\s*(.+)", row.strip(), re.IGNORECASE)
        if found:
            return found[1].strip()
    return None


NO_DEPENDENCY = {"none", "nothing", "n/a", "-"}


def depends(text: str) -> list[str]:
    """The items named on a brief's `Depends on:` line, comma-separated; `none` names nothing."""
    names = []
    for name in (line(text, "Depends on") or "").split(","):
        name = name.strip().strip("`*()[]").strip().rstrip(".;").strip("`*()[]").strip()
        if name and name.lower() not in NO_DEPENDENCY and name not in names:
            names.append(name)
    return names


def relies_on(text: str) -> list[str]:
    """The owner APIs on a brief's `Relies on:` line: function or type names (a `path::name`
    citation or a file path is also accepted), comma-separated."""
    return [n.strip().strip("`") for n in (line(text, "Relies on") or "").split(",") if n.strip().strip("`")]


def require_summary(brief: str) -> None:
    """Agents' worker briefs must explain themselves to the dashboard in one short line."""
    words, (least, most) = len((line(brief, "Summary") or "").split()), CONFIG["summary_words"]
    if not least <= words <= most:
        raise ValueError(f"a worker brief needs a `Summary:` line of {least}-{most} plain words "
                         f"saying what the task is for (it is shown on the dashboard){f'; this one has {words}' if words else ''}")


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def missing_reliances(repo, commit: str, names: list[str]) -> list[str]:
    """The `Relies on:` entries absent at a commit. A name is an identifier found anywhere in the
    tracked tree; a `path::name` entry is checked the same way (the path is only a citation);
    an entry naming a file (containing `/` or `.`) must exist."""
    missing = []
    for name in names:
        symbol = name.partition("::")[2] if "::" in name else name
        if IDENTIFIER.fullmatch(symbol):
            found = git.ok(repo, "grep", "-q", "-w", "-F", "-e", symbol, commit, "--")
        else:
            found = (not symbol.startswith("/") and ".." not in symbol.split("/")
                     and git.blob(repo, commit, symbol) is not None)
        if not found:
            missing.append(name)
    return missing


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def records() -> dict:
    return L["queue"]


def key(record: dict) -> str:
    return f"{record['project']}:{record['item']}"


# ---------------------------------------------------------------- where a record stands

def current(record: dict, kind_name: str | None = None) -> dict | None:
    """The record's task (or its decomposition, given `decompose-`) made for its current version."""
    task_id = f"{record['project']}:{kind_name or ''}{record['item']}"
    task = L["tasks"].get(task_id)
    return task if task and task.get("record_version") == record["version"] else None


def blocker(task: dict) -> str:
    """What a failed task leaves for the manager who must decide about it."""
    receipt = task["receipt"] or {}
    report = (f"Assignment: {task['id']}\n\n{task['brief']}\n\n"
              f"Worker receipt: {receipt.get('summary', 'No completion receipt')}\n"
              f"Evidence: {receipt.get('evidence', {})}\n\n"
              f"Task failed: {task['note'] or 'run retries exhausted'}")
    if task.get("recovery_context"):
        report += (f"\n\nThe worker's last evidence before it stopped (branch {task['branch']}, files preserved); "
                   f"treat its claims as leads until verified:\n{task['recovery_context']}")
    return report


def state(record: dict) -> dict:
    """Where a record stands, from its terminal fact and its current tasks:
    {"status": "done" | "replaced" | "blocked" | "queued", "blocker": text or None,
     "decompose": whether a failed worker item awaits its one managerial recovery pass}."""
    if record.get("done"):
        return {"status": "done", "blocker": None, "decompose": False}
    if record.get("replaced_by"):
        return {"status": "replaced", "blocker": None, "decompose": False}
    task = current(record)
    if task is None:
        return {"status": "queued", "blocker": None, "decompose": False}
    if task["kind"] == "breakdown" and task["status"] == "done" and task["receipt"]["disposition"] == "blocked":
        return {"status": "blocked", "blocker": task["receipt"]["summary"], "decompose": False}
    if task["status"] != "failed":
        return {"status": "queued", "blocker": None, "decompose": False}
    if task["kind"] != "item":
        return {"status": "blocked", "blocker": blocker(task), "decompose": False}
    manager = current(record, "decompose-")
    if manager and manager["status"] in schema.SETTLED:
        receipt = manager["receipt"] or {}
        return {"status": "blocked", "decompose": False,
                "blocker": receipt.get("summary") or manager["note"] or "its manager gave up"}
    return {"status": "blocked", "blocker": blocker(task), "decompose": True}


def status(record: dict) -> str:
    return state(record)["status"]


def view() -> dict:
    """The records with where each stands, for the dashboard, CLI and Coin."""
    return {k: {**r, **state(r)} for k, r in records().items()}


def live(project_name: str) -> list[dict]:
    """A project's records still wanted (not done or replaced), in queue order, with positions."""
    mine = sorted((r for r in records().values() if r["project"] == project_name
                   and status(r) not in ("done", "replaced")), key=lambda r: r["priority"])
    return [dict(r, position=i) for i, r in enumerate(mine)]


def landed(project_name: str) -> set[str]:
    return {r["item"] for r in records().values() if r["project"] == project_name and r.get("done")}


def readiness(items: list[dict], done: set[str]) -> dict[str, str]:
    """Each live item's readiness from its dependencies: "ready" once every item it depends on is
    done; "waiting" while any is still wanted; otherwise the problem that keeps it from ever
    becoming ready (an unknown or blocked dependency, or a cycle). A blocked dependency awaiting
    its manager keeps its dependents waiting: the manager replaces it and repoints them."""
    by_name = {item["item"]: item for item in items}

    def stuck(name):
        found = state(by_name[name])
        return found["status"] == "blocked" and not found["decompose"]

    def reaches(start, target, seen):
        for name in by_name[start].get("depends", []):
            if name == target or (name in by_name and name not in seen and reaches(name, target, seen | {name})):
                return True
        return False

    result = {}
    for item in items:
        needed = [name for name in item.get("depends", []) if name not in done]
        unknown = [name for name in needed if name not in by_name]
        if unknown:
            result[item["item"]] = f"depends on unknown {', '.join(unknown)}"
        elif reaches(item["item"], item["item"], {item["item"]}):
            result[item["item"]] = "depends on itself through a cycle"
        elif any(stuck(name) for name in needed):
            result[item["item"]] = "depends on a blocked item: " + ", ".join(name for name in needed if stuck(name))
        else:
            result[item["item"]] = "waiting" if needed else "ready"
    return result


# ---------------------------------------------------------------- changing what is wanted

def add(project: dict, kind: str, name: str, brief: str, stage=None, reasoning_effort=None, budget=None) -> str:
    """A new queued record, or the same one again for a retried identical proposal."""
    if kind not in schema.QUEUE_KINDS:
        raise ValueError("kind must be urgent, queued or command")
    if not name.strip():
        raise ValueError("name must not be empty")
    item = slug(name)
    if item in RESERVED or item.startswith(RESERVED_PREFIXES):
        raise ValueError("name is reserved for scheduler tasks")
    record_kind = "command" if kind == "command" else "queued"
    priorities = [r["priority"] for r in records().values()]
    record = {"project": project["name"], "item": item, "kind": record_kind, "held_by": None, "version": 1,
              "priority": min(priorities, default=0) - 1 if kind == "urgent" else max(priorities, default=0) + 1,
              **contents(record_kind, brief, stage, reasoning_effort, budget)}
    existing = records().get(key(record))
    if existing:
        if all(existing.get(k) == record.get(k) for k in ("kind", "brief", "stage", "reasoning_effort", "budget")):
            return item  # retry after a lost API response
        raise ValueError(f"{key(record)} already exists; choose another name")
    records()[key(record)] = record
    return item


def contents(kind: str, brief: str, stage=None, reasoning_effort=None, budget=None) -> dict:
    """What a record asks for, validated: its brief and the metadata derived from or pinned to it."""
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("brief must not be empty")
    if budget is not None:
        schema.budget(CONFIG, budget)
    stage = schema.stage("implementation" if stage is None else stage) if kind == "queued" else None
    if stage == "test-contract" and not relies_on(brief):
        raise ValueError("a test-contract brief needs a `Relies on: name, ...` line naming the existing "
                         "functions and types its witnesses and assertions use; they are checked against main at dispatch")
    fields = {"brief": brief.strip(), "summary": line(brief, "Summary"), "depends": depends(brief), "stage": stage,
              "reasoning_effort": schema.effort(reasoning_effort)}
    if budget is not None:
        fields["budget"] = dict(budget)
    return fields


def revise(record: dict, brief: str, stage=None, reasoning_effort=None, budget=None) -> None:
    """Replace what a record asks for: a new version, queued afresh. Omitted metadata is
    retained; supplied budget fields merge."""
    if budget is not None:
        schema.budget(CONFIG, budget)
        budget = {**record.get("budget", {}), **budget}
    else:
        budget = record.get("budget")
    revised = contents(record["kind"], brief,
                       record["stage"] if stage is None else stage,
                       record["reasoning_effort"] if reasoning_effort is None else reasoning_effort,
                       budget)
    record.pop("budget", None)
    record.update(held_by=None, version=record["version"] + 1, **revised)


def finish(record: dict, **facts) -> None:
    """The terminal fact: this record's work is done. Written once, by the lifecycle."""
    record["done"] = {"at": now(), **facts}


def replace(record: dict, replacements: list[str], reason: str) -> None:
    """Replace a record with existing same-project records: dependents of it depend on the
    replacements instead, except a replacement that depended on it, which inherits its
    dependencies. Nothing changes if that would leave a new cycle."""
    if not isinstance(replacements, list) or not replacements or not all(isinstance(n, str) for n in replacements):
        raise ValueError("name the replacement items")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("say why it is replaced")
    replacements = list(dict.fromkeys(replacements))
    project, item = record["project"], record["item"]
    current_records = records()
    for name in replacements:
        other = current_records.get(f"{project}:{name}")
        if name == item or other is None or status(other) in ("replaced", "blocked"):
            raise ValueError(f"invalid same-project replacement: {name}")
    revised = copy.deepcopy(current_records)
    for other in revised.values():
        if other["project"] == project and item in other["depends"]:
            instead = record["depends"] if other["item"] in replacements else replacements
            other["depends"] = list(dict.fromkeys(n for dep in other["depends"]
                                                  for n in (instead if dep == item else [dep])))

    def cycles(view_of):
        mine = [r for r in view_of.values() if r["project"] == project and not r.get("done")]
        return {n for n, s in readiness(mine, landed(project)).items() if "cycle" in s}
    if cycles(revised) - cycles(current_records):
        raise ValueError("replacement would leave a dependency cycle; no records changed")
    for k, other in revised.items():
        current_records[k]["depends"] = other["depends"]
    record.update(replaced_by=replacements, replacement_reason=reason.strip())
    log("item replaced", item=key(record), replacements=replacements, reason=reason.strip())


MOVES = ("top", "up", "down", "bottom")


def move(record_key: str, where: str) -> int:
    """Move one live queue item among the project's live items; the spawner admits by this order.
    Returns the item's new position. Caller holds LOCK."""
    record = records().get(record_key)
    if record is None or record.get("done"):
        raise ValueError(f"no live queue item {record_key!r}")
    if where not in MOVES:
        raise ValueError(f"move must be one of {', '.join(MOVES)}")
    mine = sorted((r for r in records().values() if r["project"] == record["project"] and not r.get("done")),
                  key=lambda r: r["priority"])
    index = mine.index(record)
    if where in ("top", "bottom"):
        others = [r["priority"] for r in records().values() if r is not record]
        record["priority"] = (min(others, default=0) - 1) if where == "top" else (max(others, default=0) + 1)
    else:
        neighbour = index - 1 if where == "up" else index + 1
        if 0 <= neighbour < len(mine):
            record["priority"], mine[neighbour]["priority"] = mine[neighbour]["priority"], record["priority"]
    log("queue item moved", item=record_key, to=where)
    return sorted((r for r in records().values() if r["project"] == record["project"] and not r.get("done")),
                  key=lambda r: r["priority"]).index(record)


# ---------------------------------------------------------------- history

def history_frontier(active_tasks: set[str]) -> set[str]:
    """Queue identities still needed by unfinished work, including transitive prerequisites."""
    current_records = records()
    protected = set()
    for record_key, record in current_records.items():
        found = state(record)
        if (found["status"] == "queued" or found["decompose"] or record_key in active_tasks
                or record.get("proposed_by") in active_tasks):
            protected.add(record_key)
    pending = list(protected)
    while pending:
        record = current_records[pending.pop()]
        for name in (*record.get("depends", []), *record.get("replaced_by", [])):
            other = f"{record['project']}:{name}"
            if other in current_records and other not in protected:
                protected.add(other)
                pending.append(other)
    return protected


def clear_history(active_tasks: set[str]) -> list[str]:
    """Remove settled queue records that no live frontier still references. Caller holds LOCK."""
    protected = history_frontier(active_tasks)
    removed = [k for k in records() if k not in protected]
    for record_key in removed:
        del records()[record_key]
    return removed


PUBLISHED: dict[tuple[str, str], str] = {}  # the answer each runtime queue leaf last received


def publish() -> None:
    """Refresh the derived runtime queue answers when they change; called only by the daemon."""
    for kind, question in (("queued", "what is queued"), ("command", "what is the command queue")):
        body = "The daemon alone owns this queue. Submit changes through its API.\n"
        for r in sorted(records().values(), key=lambda r: r["priority"]):
            found = state(r)
            if r["kind"] != kind or found["status"] in ("done", "replaced"):
                continue
            body += (f"\n## {key(r)}\n\nStatus: {found['status']}\n"
                     f"Stage: {r['stage'] or 'manager command'}\nReasoning effort: {r['reasoning_effort'] or 'stage default'}\n\n{r['brief']}\n")
            body += "\nCurrent dependencies: " + (", ".join(r["depends"]) or "none") + "\n"
            body += "Run budget metadata: " + json.dumps(r.get("budget", {})) + " (omitted limits use daemon defaults)\n"
            if r["held_by"]:
                body += f"Held by {r['held_by']}: it will not start until revised or released.\n"
            if found["blocker"]:
                body += f"\nCurrent blocker: {found['blocker']}\n"
        if "\n## " not in body:
            body += "\nThe queue is empty.\n"
        if PUBLISHED.get((str(ROOT), question)) != body:
            kt.write(ROOT, question, body)
            PUBLISHED[(str(ROOT), question)] = body
