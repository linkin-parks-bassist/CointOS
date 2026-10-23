"""Queue records: the work wanted in each project, and the view of where that work stands.

A record holds what is asked for (brief, dependencies, stage, effort, budget, order, holds) and
one terminal fact written once by the lifecycle: `done`. Everything else about its state is
derived from its tasks by `state`, never stored: a record whose current task failed is blocked;
a failed assignment has one recovery controller. `version` counts revisions of what
is asked; a task made for an older version no longer speaks for the record. All mutations run
under the daemon lock; the runtime tree's queue leaves are a readable projection.
"""
from __future__ import annotations
import copy
import json
import re
import threading
from cointos import dependencies, frontier, git, kt, packets, schema
from cointos.dependencies import line, depends, dependency_brief, slug, NO_DEPENDENCY
from cointos.config import ROOT
from cointos.state import CONFIG, LOCK, L, log, now

# Queue item names that would collide with the ids of scheduler-created tasks in a project.
RESERVED = ("garden", "tree-audit")
RESERVED_PREFIXES = ("integrate-", "decompose-", "operator-", "loose-ends-", "test-audit-")



def relies_on(text: str) -> list[str]:
    """The owner APIs on a brief's `Relies on:` line: function or type names (a `path::name`
    citation or a file path is also accepted), comma-separated."""
    # The line is prose: sentence punctuation outside a quoted citation is not its name.
    names = [n.strip().rstrip(".;").strip().strip("`")
             for n in (line(text, "Relies on") or "").split(",")]
    return [name for name in names if name]


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



def records() -> dict:
    return L["queue"]


def key(record: dict) -> str:
    return f"{record['project']}:{record['item']}"


# ---------------------------------------------------------------- where a record stands

def current(record: dict) -> dict | None:
    """The execution task made for this assignment version."""
    task = L["tasks"].get(key(record))
    return task if task and task.get("record_version") == record["version"] else None


def blocker(task: dict) -> str:
    """The original evidence for the assignment's recovery controller."""
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
    """Desired work is settled, executable, or blocked with one recovery owner."""
    if record.get('done'):
        return {'status': 'done', 'blocker': None, 'recoverable': False}
    if record.get('replaced_by'):
        return {'status': 'replaced', 'blocker': None, 'recoverable': False}
    task = current(record)
    if task is None or (task['status'] != 'failed' and
                        (task.get('receipt') or {}).get('disposition') != 'blocked'):
        return {'status': 'queued', 'blocker': None, 'recoverable': False}
    repair = frontier.controller(record)
    failure = repair if repair and repair['status'] in schema.SETTLED else task
    return {'status': 'blocked', 'blocker': (failure.get('receipt') or {}).get('summary') or
            (failure.get('note') if failure is repair else blocker(task)),
            'recoverable': repair is None or repair['status'] in schema.PENDING}


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


def frontier_problems(project_name: str, *, owner=None, items=None) -> list[str]:
    """Concrete dead edges only; ordinary dependency waits are valid handoffs."""
    items = live(project_name) if items is None else items
    ready = readiness(items, landed(project_name))
    selected = {r["item"] for r in items if owner is None or owner in (r.get("proposed_by"), r.get("revised_by"))}
    by_name = {r["item"]: r for r in items}
    pending = list(selected)
    while pending:
        for name in by_name[pending.pop()].get("depends", []):
            if name in by_name and name not in selected:
                selected.add(name)
                pending.append(name)
    return [f"{project_name}:{r['item']}: {ready[r['item']]}" for r in items
            if r["item"] in selected and
            ready[r["item"]] not in ("ready", "waiting")]


def preview(project: dict, kind: str, name: str, brief: str, stage=None,
            reasoning_effort=None, budget=None, **metadata) -> dict:
    """Validate a proposal and its graph without writing a record or starting a run."""
    if kind not in schema.QUEUE_KINDS:
        raise ValueError("kind must be urgent, queued or command")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must not be empty")
    item = slug(name)
    if item in RESERVED or item.startswith(RESERVED_PREFIXES):
        raise ValueError("name is reserved for scheduler tasks")
    if f"{project['name']}:{item}" in records() or f"{project['name']}:{item}" in L["tasks"]:
        raise ValueError("item already exists; hold/revise it instead of queueing a duplicate")
    record_kind = "command" if kind == "command" else "queued"
    candidate = {"project": project["name"], "item": item, "kind": record_kind, "version": 1,
                 **contents(record_kind, brief, stage, reasoning_effort, budget, project=project["name"], **metadata)}
    candidate["proposed_by"] = "preview"
    items = live(project["name"]) + [candidate]
    problems = frontier_problems(project["name"], items=items, owner="preview")
    if candidate["stage"] == "test-contract":
        head = git.head(project["path"], project.get("main_branch", "main"))
        missing = missing_reliances(project["path"], head, relies_on(candidate["brief"]))
        if missing:
            problems.append(f"{key(candidate)}: declared APIs absent on main: {', '.join(missing)}")
    return {"ok": not problems, "problems": problems, "item": item,
            "readiness": readiness(items, landed(project["name"]))[item]}


def readiness(items: list[dict], done: set[str]) -> dict[str, str]:
    """Each live item's readiness from its dependencies: "ready" once every item it depends on is
    done; "waiting" while any is still wanted; otherwise the problem that keeps it from ever
    becoming ready (an unknown or blocked dependency, or a cycle). A blocked dependency awaiting
    its recovery controller keeps dependents waiting while that controller repairs the assignment.
    Pending test corrections are admission prerequisites; the old acceptance stays immutable."""
    by_name = {item["item"]: item for item in items}
    edges = {item['item']: list(dict.fromkeys([*item.get('depends', []),
             *(r['item'] for r in packets.pending(item, items))])) for item in items}

    def stuck(name):
        found = state(by_name[name])
        return found["status"] == "blocked" and not found["recoverable"]

    def reaches(start, target, seen):
        for name in edges[start]:
            if name == target or (name in by_name and name not in seen and reaches(name, target, seen | {name})):
                return True
        return False

    result = {}
    for item in items:
        needed = [name for name in edges[item['item']] if name not in done]
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

def add(project: dict, kind: str, name: str, brief: str, stage=None, reasoning_effort=None, budget=None, **metadata) -> str:
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
              **contents(record_kind, brief, stage, reasoning_effort, budget, project=project["name"], **metadata)}
    existing = records().get(key(record))
    if existing:
        if all(existing.get(k) == record.get(k) for k in ("kind", "brief", "stage", "reasoning_effort", "budget")):
            return item  # retry after a lost API response
        raise ValueError(f"{key(record)} already exists; choose another name")
    if key(record) in L["tasks"]:
        raise ValueError(f"{key(record)} already names a task; choose another name")
    records()[key(record)] = record
    return item


def contents(kind: str, brief: str, stage=None, reasoning_effort=None, budget=None, *, project: str,
             dependency_ids=None, summary=None, reliances=None) -> dict:
    """What a record asks for, validated: its brief and the metadata derived from or pinned to it."""
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("brief must not be empty")
    for label, values in (("dependencies", dependency_ids), ("relies_on", reliances)):
        if values is not None and (not isinstance(values, list) or
                any(not isinstance(v, str) or not v.strip() for v in values)):
            raise ValueError(f"{label} must be an array of nonempty strings")
    if summary is not None:
        if not isinstance(summary, str) or not summary.strip() or '\n' in summary or '\r' in summary:
            raise ValueError("summary must be a nonempty single-line string")
        brief = dependencies.metadata_brief(brief, "Summary", summary.strip())
    if reliances is not None:
        brief = dependencies.metadata_brief(brief, "Relies on", ", ".join(reliances))
    if budget is not None:
        schema.budget(CONFIG, budget)
    stage = schema.stage("implementation" if stage is None else stage) if kind == "queued" else None
    if stage == "test-contract" and not relies_on(brief):
        raise ValueError("a test-contract brief needs a `Relies on: name, ...` line naming the existing "
                         "functions and types its witnesses and assertions use; they are checked against main at dispatch")
    names = depends(brief) if dependency_ids is None else dependency_ids
    canonical = dependencies.canonical(project, names)
    if any(name != slug(name) for name in canonical):
        raise ValueError("Depends on must contain only item IDs separated by commas; "
                         "put explanations on a separate line, not inside dependency names")
    if canonical != names or dependency_ids is not None:
        brief = dependency_brief(brief, canonical)
    fields = {"brief": brief.strip(), "summary": line(brief, "Summary"), "depends": canonical, "stage": stage,
              "reasoning_effort": schema.effort(reasoning_effort)}
    if budget is not None:
        fields["budget"] = dict(budget)
    return fields


def revise(record: dict, brief: str, stage=None, reasoning_effort=None, budget=None, *,
           preserve_packets=False, **metadata) -> bool:
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
                       budget, project=record["project"], **metadata)
    if preserve_packets and record.get("stage") in ("implementation", "integration"):
        removed = [name for name in record.get("depends", []) if name not in revised["depends"]
                   and (packet := records().get(f"{record['project']}:{name}"))
                   and packet.get("stage") == "test-contract" and packet.get("done")]
        if removed:
            raise ValueError("revision would discard accepted test packets: " + ", ".join(removed) +
                             "; retain these dependencies while repairing the assignment. "
                             "Use correct-tests for an invalid accepted contract; an independent author and reviewer "
                             "activate the corrected packet and update dependent assignments. "
                             "repairing a build blocker does not withdraw acceptance tests.")
    if all(record.get(k) == revised.get(k) for k in
           ("brief", "stage", "reasoning_effort", "budget", "depends")):
        return False  # replaying the same request cannot refill a failed assignment's budget
    record.pop("budget", None)
    record.update(version=record["version"] + 1, **revised)
    return True


def finish(record: dict, **facts) -> None:
    """The terminal fact: this record's work is done. Written once, by the lifecycle."""
    record["done"] = {"at": now(), **facts}


def replacement(record: dict, replacements: list[str], reason: str) -> tuple[dict, list[str]]:
    """Replace a record with existing same-project records: dependents of it depend on the
    replacements instead, except a replacement that depended on it, which inherits its
    dependencies. Changed assignments get a new version and matching dependency metadata.
    Return the proposed queue and changed keys without
    mutating records, tasks, runs or the journal."""
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
        if (other["project"] == project and item in other["depends"]
                and status(current_records[key(other)]) not in ("done", "replaced")):
            instead = record["depends"] if other["item"] in replacements else replacements
            other["depends"] = list(dict.fromkeys(n for dep in other["depends"]
                                                  for n in (instead if dep == item else [dep])))

    def cycles(view_of):
        mine = [r for r in view_of.values() if r["project"] == project and not r.get("done")]
        return {n for n, s in readiness(mine, landed(project)).items() if "cycle" in s}
    if cycles(revised) - cycles(current_records):
        raise ValueError("replacement would leave a dependency cycle; no records changed")
    changed = [k for k, other in revised.items() if current_records[k]["depends"] != other["depends"]]
    for k in changed:
        other = revised[k]
        other.update(brief=dependency_brief(other["brief"], other["depends"]),
                     version=other["version"] + 1)
    revised[key(record)].update(replaced_by=replacements, replacement_reason=reason.strip())
    return revised, changed


def replace(record: dict, replacements: list[str], reason: str, preflight=None) -> list[str]:
    """Apply a valid replacement, preserving record identities. Preflight precedes mutation."""
    revised, changed = replacement(record, replacements, reason)
    if preflight:
        preflight(changed)
    for k in [*changed, key(record)]:
        records()[k].update(revised[k])
    log("item replaced", item=key(record), replacements=record['replaced_by'], reason=reason.strip())
    return changed


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
        if (found["status"] == "queued" or found["recoverable"] or record_key in active_tasks
                or record.get("proposed_by") in active_tasks):
            protected.add(record_key)
    pending = list(protected)
    while pending:
        record = current_records[pending.pop()]
        related = [f"{record['project']}:{name}" for name in
                   (*record.get('depends', []), *record.get('replaced_by', []))]
        related += [record.get('corrected_by'), (record.get('correction') or {}).get('packet')]
        for other in related:
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
PUBLISH_LOCK = threading.Lock()  # acquire outside LOCK; serializes derived file writes


def publish() -> None:
    """Capture under LOCK, then publish ordered derived answers without retaining it."""
    with PUBLISH_LOCK:
        with LOCK:
            projections = [(question, projection(kind)) for kind, question in
                           (("queued", "what is queued"), ("command", "what is the command queue"))]
        for question, body in projections:
            if PUBLISHED.get((str(ROOT), question)) != body:
                kt.write(ROOT, question, body)
                PUBLISHED[(str(ROOT), question)] = body


def projection(kind: str) -> str:
    """One queue answer from the caller's locked ledger view."""
    body = "The daemon alone owns this queue. Submit changes through its API.\n"
    for r in sorted(records().values(), key=lambda r: r["priority"]):
        found = state(r)
        if r["kind"] != kind or found["status"] in ("done", "replaced"):
            continue
        body += (f"\n## {key(r)}\n\nStatus: {found['status']}\n"
                 f"Stage: {r['stage'] or 'manager command'}\nReasoning effort: {r['reasoning_effort'] or 'stage default'}\n\n{r['brief']}\n")
        body += "\nCurrent dependencies: " + (", ".join(r["depends"]) or "none") + "\n"
        if corrections := packets.pending(r):
            body += "Waiting for independently reviewed test correction: " + ", ".join(key(c) for c in corrections) + ".\n"
        body += "Run budget metadata: " + json.dumps(r.get("budget", {})) + " (omitted limits use daemon defaults)\n"
        if r["held_by"]:
            body += f"Held by {r['held_by']}: it will not start until revised or released.\n"
        if found["blocker"]:
            body += f"\nCurrent blocker: {found['blocker']}\n"
    if "\n## " not in body:
        body += "\nThe queue is empty.\n"
    return body
