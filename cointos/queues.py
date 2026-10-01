"""Daemon-owned scheduler records, published as current answers in the runtime tree.

The ledger is the durable source; the runtime leaves are its readable projection.
Project trees never contain scheduler records. All mutations run under the daemon lock.
"""
from __future__ import annotations
import hashlib
import json
import copy
import re
from pathlib import Path
from cointos import kt, schema
from cointos.config import ROOT
from cointos.state import CONFIG, L, log

REPORT = ".work-report.md"
# Queue item names that would collide with the ids of scheduler-created tasks in a project.
RESERVED = ("garden", "tree-audit")
RESERVED_PREFIXES = ("integrate-", "decompose-", "operator-", "loose-ends-", "test-audit-")

def answer(text: str) -> str:
    """A leaf's answer body, without front matter."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5:]
    return text


def status(text: str) -> str | None:
    """One unambiguous declaration outside quoted examples and fenced code."""
    found_statuses = []
    fence = None
    for line in answer(text).splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is None:
            found = re.fullmatch(r"\**Status:\**\s*([a-z ]+)\**", stripped, re.IGNORECASE)
            if found:
                found_statuses.append(found[1].strip().lower())
    return found_statuses[0] if len(found_statuses) == 1 else None


def depends(text: str) -> list[str]:
    """The items named on the leaf's `Depends on:` line: paths or bare names, comma-separated."""
    for line in answer(text).splitlines():
        found = re.match(r"\**Depends on:\**\s*(.+)", line.strip(), re.IGNORECASE)
        if found:
            return [name.strip(" `*") for name in found[1].split(",") if name.strip(" `*")]
    return []


def readiness(items: list[dict], done: set[str]) -> dict[str, str]:
    """Each item's readiness from its `Depends on:` line: "ready" once every item it depends on
    has landed (`done`, item paths); "waiting" while any is still in the queue; otherwise the
    problem that keeps it from ever becoming ready (an unknown or blocked dependency, or a
    cycle). A blocked dependency awaiting its manager keeps its dependents waiting: a
    manager replaces it with smaller children and repoints them. Pure."""
    paths = {item["item"]: item for item in items}
    stems = {Path(item["item"]).stem: item["item"] for item in items}
    done_stems = {Path(name).stem: name for name in done}

    def resolve(name):
        return name if name in paths else stems.get(Path(name).stem)

    def finished(name):
        return name in done or Path(name).stem in done_stems

    def stuck(name):  # blocked for good; one awaiting decomposition will be replaced
        return paths[name]["status"] == "blocked" and not paths[name].get("decompose")

    def reaches(start, target, seen):
        for name in paths[start].get("depends", []):
            found = resolve(name)
            if found == target or (found and found not in seen and reaches(found, target, seen | {found})):
                return True
        return False

    result = {}
    for item in items:
        needed = [name for name in item.get("depends", []) if not finished(name)]
        unknown = [name for name in needed if resolve(name) is None]
        if unknown:
            result[item["item"]] = f"depends on unknown {', '.join(unknown)}"
        elif reaches(item["item"], item["item"], {item["item"]}):
            result[item["item"]] = "depends on itself through a cycle"
        elif any(stuck(resolve(name)) for name in needed):
            result[item["item"]] = "depends on a blocked item: " + ", ".join(
                resolve(name) for name in needed if stuck(resolve(name)))
        else:
            result[item["item"]] = "waiting" if needed else "ready"
    return result



def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def records() -> dict:
    return L["queue"]


def scan(project: dict) -> list[dict]:
    return [dict(record, position=i) for i, record in enumerate(sorted(records().values(), key=lambda r: r["priority"]))
            if record["project"] == project["name"] and record["status"] != "done"]


def landed(project: dict) -> set[str]:
    return {r["item"] for r in records().values()
            if r["project"] == project["name"] and r["status"] == "done"}


def add(project: dict, kind: str, name: str, brief: str, stage=None, reasoning_effort=None, budget=None) -> str:
    """A new queued record, or the same one again for a retried identical proposal."""
    if kind not in schema.QUEUE_KINDS:
        raise ValueError("kind must be urgent, queued or command")
    if not name.strip():
        raise ValueError("name must not be empty")
    item = slug(name)
    if item in RESERVED or item.startswith(RESERVED_PREFIXES):
        raise ValueError("name is reserved for scheduler tasks")
    record = {"project": project["name"], "item": item, "kind": record_kind(kind),
              "status": "queued", "decompose": False, "held_by": None,
              "priority": (min((r["priority"] for r in records().values()), default=0) - 1 if kind == "urgent"
                           else max((r["priority"] for r in records().values()), default=0) + 1),
              **contents(record_kind(kind), brief, stage, reasoning_effort, budget)}
    key = f"{project['name']}:{item}"
    if key in records():
        if all(records()[key].get(k) == record.get(k) for k in ("kind", "brief", "stage", "reasoning_effort", "budget")):
            return item  # retry after a lost API response
        raise ValueError(f"{key} already exists; choose another name")
    records()[key] = record
    return item


def record_kind(queue_kind: str) -> str:
    return "command" if queue_kind == "command" else "queued"


def contents(kind: str, brief: str, stage=None, reasoning_effort=None, budget=None) -> dict:
    """What a record asks for, validated: its brief and the metadata derived from or pinned to it."""
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("brief must not be empty")
    if budget is not None:
        schema.budget(CONFIG, budget)
    fields = {"brief": brief.strip(), "depends": depends(brief),
              "stage": schema.stage("implementation" if stage is None else stage) if kind == "queued" else None,
              "reasoning_effort": schema.effort(reasoning_effort),
              "hash": hashlib.sha256(brief.strip().encode()).hexdigest()[:16]}
    if budget is not None:
        fields["budget"] = dict(budget)
    return fields


def revise(record: dict, brief: str, stage=None, reasoning_effort=None, budget=None) -> None:
    """Replace what a record asks for. It queues again: an earlier blocker or decomposition request
    described the previous brief. Omitted metadata is retained; supplied budget fields merge."""
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
    record.pop("report", None)
    record.update(status="queued", decompose=False, held_by=None, **revised)


def update(project: str, item: str, status_value: str, report: str = "", *, decompose: bool = False) -> None:
    record = records()[f"{project}:{item}"]
    record.update(status=status_value, decompose=decompose)
    if report:
        record["report"] = report
    record["hash"] = hashlib.sha256(repr(record).encode()).hexdigest()[:16]


def accepted(project: str, item: str, commit: str) -> None:
    """Make verified acceptance the terminal authority for one queue record.

    Worker reports describe the submitted attempt. Once the daemon records a verified
    landing receipt they can no longer keep scheduling state blocked.
    """
    record = records()[f"{project}:{item}"]
    record.update(status="done", decompose=False, commit=commit)
    record.pop("report", None)
    record["hash"] = hashlib.sha256(repr(record).encode()).hexdigest()[:16]


def report(task: dict) -> str:
    try:
        return (Path(task["worktree"]) / REPORT).read_text()
    except OSError:
        return ""


def history_frontier(active_tasks: set[str]) -> set[str]:
    """Queue identities still needed by unfinished work, including transitive prerequisites."""
    current = records()
    protected = {key for key, record in current.items()
                 if record["status"] == "queued" or (record["status"] == "blocked" and record.get("decompose"))
                 or key in active_tasks or record.get("proposed_by") in active_tasks}

    def key_for(project: str, name: str) -> str | None:
        direct = f"{project}:{name}"
        if direct in current:
            return direct
        stem = Path(name).stem
        return next((key for key, record in current.items()
                     if record["project"] == project and Path(record["item"]).stem == stem), None)

    pending = list(protected)
    while pending:
        record = current[pending.pop()]
        for name in (*record.get("depends", []), *record.get("replaced_by", [])):
            key = key_for(record["project"], name)
            if key is not None and key not in protected:
                protected.add(key)
                pending.append(key)

    return protected


def clear_history(active_tasks: set[str]) -> list[str]:
    """Remove terminal queue history that no live frontier still references. Caller holds LOCK."""
    current = records()
    protected = history_frontier(active_tasks)

    removed = [key for key, record in current.items()
               if key not in protected and record["status"] in ("done", "blocked")]
    for key in removed:
        del current[key]
    return removed


def supersede(task_id: str, replacements: list[str], reason: str) -> dict:
    """Replace failed/blocked prerequisites without declaring their work accepted. Caller holds LOCK."""
    records_now = records()
    old = records_now.get(task_id)
    if (old is None or not isinstance(reason, str) or not reason.strip() or not isinstance(replacements, list)
            or not replacements or not all(isinstance(n, str) for n in replacements)):
        raise ValueError("supersede requires a queued task ID, existing bare replacement names and a reason")
    replacements = list(dict.fromkeys(replacements))
    if old.get("replaced_by"):
        if old["replaced_by"] != replacements or old.get("replacement_reason") != reason.strip():
            raise ValueError("task already has a different replacement")
        return {"ok": True, "replaced_by": replacements}
    task = L["tasks"].get(task_id, {})
    if (task.get("status") not in ("failed", "done", None)
            or (old["status"] != "blocked" and task.get("status") != "failed")):
        raise ValueError("only failed or blocked work can be superseded; stop active work first")
    project, item = old["project"], old["item"]
    for name in replacements:
        record = records_now.get(f"{project}:{name}")
        if (name == item or record is None or record.get("replaced_by") or record["status"] == "blocked"
                or L["tasks"].get(f"{project}:{name}", {}).get("status") == "failed"):
            raise ValueError(f"invalid same-project replacement: {name}")
    revised = copy.deepcopy(records_now)
    def same_item(name):
        return name == item or Path(name).stem == Path(item).stem
    for r in revised.values():
        if r["project"] == project:
            if any(same_item(n) for n in r["depends"]):
                r["depends"] = list(dict.fromkeys(n for dep in r["depends"]
                                                 for n in (replacements if same_item(dep) else [dep])))
    graph = [r for r in revised.values() if r["project"] == project and r["status"] != "done"]
    done = {r["item"] for r in revised.values() if r["project"] == project and r["status"] == "done"}
    before = readiness([r for r in records_now.values() if r["project"] == project and r["status"] != "done"], done)
    if any("cycle" in s and "cycle" not in before.get(n, "") for n, s in readiness(graph, done).items()):
        raise ValueError("replacement would leave a dependency cycle; no records changed")
    # Keep existing dict identities: callers may hold records under the same lock.
    for key, record in revised.items():
        records_now[key].update(record)
    old.update(status="blocked", decompose=False, replaced_by=replacements, replacement_reason=reason.strip())
    if task:
        task.update(replaced_by=replacements, replacement_reason=reason.strip())
    log("prerequisite superseded", task=task_id, replacements=replacements, reason=reason.strip())
    return {"ok": True, "replaced_by": replacements}


def publish() -> None:
    """Refresh the derived runtime queue answers; called only by the daemon."""
    for kind, question in (("queued", "what is queued"), ("command", "what is the command queue")):
        body = "The daemon alone owns this queue. Submit changes through its API.\n"
        for r in sorted(records().values(), key=lambda r: r["priority"]):
            if r["kind"] == kind and r["status"] != "done":
                body += (f"\n## {r['project']}:{r['item']}\n\nStatus: {r['status']}\n"
                         f"Stage: {r['stage'] or 'manager command'}\nReasoning effort: {r['reasoning_effort'] or 'stage default'}\n\n{r['brief']}\n")
                body += "\nCurrent dependencies: " + (", ".join(r["depends"]) or "none") + "\n"
                body += "Run budget metadata: " + json.dumps(r.get("budget", {})) + " (omitted limits use daemon defaults)\n"
                if r["held_by"]:
                    body += f"Held by {r['held_by']}: it will not start until revised or released.\n"
                if r.get("replaced_by"):
                    body += f"\nReplaced by: {', '.join(r['replaced_by'])}\nReason: {r['replacement_reason']}\n"
                if r.get("report"):
                    body += f"\nCurrent blocker: {r['report']}\n"
        if "\n## " not in body:
            body += "\nThe queue is empty.\n"
        kt.write(ROOT, question, body)
