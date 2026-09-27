"""Daemon-owned scheduler records, published as current answers in the runtime tree.

The ledger is the durable source; the runtime leaves are its readable projection.
Project trees never contain scheduler records. All mutations run under the daemon lock.
"""
from __future__ import annotations
import hashlib
import re
import subprocess
from pathlib import Path
from cointos.config import ROOT

REPORT = ".work-report.md"

def needs_decomposition(text: str) -> bool:
    return status(text) == "blocked" and "needs decomposition:" in answer(text).lower()


def answer(text: str) -> str:
    """A leaf's answer body, without front matter."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5:]
    return text


def status(text: str) -> str | None:
    for line in answer(text).splitlines():
        if line.strip():
            found = re.match(r"\**Status:\**\s*([a-z ]+)", line.strip(), re.IGNORECASE)
            return found[1].strip().lower() if found else None
    return None


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
    cycle). A dependency blocked with `Needs decomposition:` keeps its dependents waiting: a
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
    from cointos.state import L
    return L.setdefault("queue", {})


def scan(project: dict) -> list[dict]:
    return [dict(record, position=i) for i, record in enumerate(sorted(records().values(), key=lambda r: r["priority"]))
            if record["project"] == project["name"] and record["status"] != "done"]


def landed(project: dict) -> set[str]:
    return {r["item"] for r in records().values()
            if r["project"] == project["name"] and r["status"] == "done"}


def add(project: dict, kind: str, name: str, brief: str) -> str:
    if kind not in ("urgent", "queued", "command"):
        raise ValueError("kind must be urgent, queued or command")
    if not name.strip() or not brief.strip():
        raise ValueError("name and brief must not be empty")
    item = slug(name)
    if item in ("integrate", "garden", "garden-audit") or item.startswith(("decompose-", "survey-", "maintenance-")):
        raise ValueError("name is reserved for scheduler tasks")
    key = f"{project['name']}:{item}"
    record = {"project": project["name"], "item": item,
              "kind": "queued" if kind == "urgent" else kind, "status": "queued",
              "brief": brief.strip(), "depends": depends(brief), "decompose": False,
              "hash": hashlib.sha256(brief.strip().encode()).hexdigest()[:16],
              "priority": (min((r["priority"] for r in records().values()), default=0) - 1 if kind == "urgent"
                           else max((r["priority"] for r in records().values()), default=0) + 1)}
    if key in records():
        if all(records()[key][k] == record[k] for k in ("project", "item", "kind", "brief")):
            return item  # retry after lost API response
        raise ValueError(f"{key} already exists; choose another name")
    records()[key] = record
    return item


def update(project: str, item: str, status_value: str, report: str = "") -> None:
    record = records()[f"{project}:{item}"]
    record.update(status=status_value, decompose=needs_decomposition(report))
    if report:
        record["report"] = report
    record["hash"] = hashlib.sha256(repr(record).encode()).hexdigest()[:16]


def report(task: dict) -> str:
    try:
        return (Path(task["worktree"]) / REPORT).read_text()
    except OSError:
        return ""


def publish() -> None:
    """Refresh the derived runtime queue answers through kt; called only by the daemon."""
    for kind, question in (("queued", "what is queued"), ("command", "what is the command queue")):
        body = "The daemon alone owns this queue. Submit changes through its API.\n"
        for r in sorted(records().values(), key=lambda r: r["priority"]):
            if r["kind"] == kind and r["status"] != "done":
                body += f"\n## {r['project']}:{r['item']}\n\nStatus: {r['status']}\n\n{r['brief']}\n"
                if r.get("report"):
                    body += f"\nCurrent blocker: {r['report']}\n"
        if "\n## " not in body:
            body += "\nThe queue is empty.\n"
        address = "local:" + question.replace(" ", "/") + ".md"
        result = subprocess.run(["kt", "--lean", "open", address], cwd=ROOT, capture_output=True, text=True)
        if result.returncode == 0:
            text = result.stdout
            revision = re.search(r"Revision: ([0-9a-f]{64})", result.stderr)
            if revision is None:
                raise RuntimeError("kt did not return a queue leaf revision")
            if text.strip() == body.strip():
                continue
            command = ["kt", "rewrite", address, revision[1], body]
        else:
            command = ["kt", "add", "--local", question, body]
        subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
