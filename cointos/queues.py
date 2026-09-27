"""Work queues in each project's knowledge tree.

`what/is/queued.md` answers what is queued: its endpoints in priority order. Each endpoint,
`what/is/the/queued/<name>.md`, describes one item: its status line, an optional `Depends on:`
line naming other endpoints, and its brief. Drafted ideas have the same shape under `drafted`.
Urgent work is simply listed first."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

KINDS = ("queued", "drafted")  # work for workers; ideas for managers to break down
STATUSES = ("queued", "in progress", "blocked", "done", "drafted")


def index_leaf(kind: str) -> str:
    """The leaf answering what is <kind>: its members in priority order, first first."""
    return f"what/is/{kind}.md"


def endpoint(kind: str, name: str) -> str:
    """The leaf describing one member: what is the <kind> <name>."""
    return f"what/is/the/{kind}/{name}.md"


def entries(text: str, kind: str) -> list[str]:
    """The endpoints an index names, in its order (its priority). Pure."""
    found = re.findall(rf"what/is/the/{kind}/[A-Za-z0-9._-]+\.md", answer(text))
    return list(dict.fromkeys(found))


EMPTY = re.compile(r"^Nothing is (queued|drafted)\.$")  # an index's line while it lists nothing


def with_entry(text: str, item: str, first: bool) -> str:
    """The index text with `item` listed first or last. Front matter and prose stay. Pure."""
    lines = [line for line in text.rstrip("\n").split("\n") if not EMPTY.match(line.strip())]
    listed = [i for i, line in enumerate(lines) if re.search(r"what/is/the/[a-z]+/[A-Za-z0-9._-]+\.md", line)]
    at = (listed[0] if first else listed[-1] + 1) if listed else len(lines)
    return "\n".join(lines[:at] + [f"- `{item}`"] + lines[at:]) + "\n"


def without_entry(text: str, item: str) -> str:
    """The index text without the lines naming `item`; says it is empty once nothing is left. Pure."""
    kind = Path(item).parent.name
    left = "".join(line for line in text.splitlines(keepends=True) if item not in line)
    return left if entries(left, kind) else left.rstrip("\n") + f"\n\nNothing is {kind}.\n"


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


def landed(project: dict) -> set[str]:
    """The items landed on the project's main branch. A landed item's leaf is gone (a leaf is an
    answer, never a log); its landing commit names it in a `Landed:` trailer, so git keeps the
    history. A trailer counts only once its item's leaf has left main: any commit can carry one,
    such as a manager's that queues the items it names."""
    git = ["git", "-C", project["path"]]
    trailers = subprocess.run(git + ["log", project["main_branch"], "--format=%(trailers:key=Landed,valueonly)"],
                              capture_output=True, text=True).stdout
    named = {item.strip() for line in trailers.splitlines() for item in line.split(",") if item.strip()}
    present = subprocess.run(git + ["ls-tree", "-r", "--name-only", project["main_branch"], "--", ".knowledge"],
                             capture_output=True, text=True).stdout.splitlines()
    return named - {path.removeprefix(".knowledge/") for path in present}


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


def read_item(root: Path, item: str) -> dict | None:
    """The item at `.knowledge/<item>` under `root`, or None."""
    try:
        text = (root / ".knowledge" / item).read_text(encoding="utf-8")
    except OSError:
        return None
    body = answer(text).strip()
    return {"item": item, "status": status(text), "depends": depends(text), "brief": body,
            "decompose": needs_decomposition(text), "hash": hashlib.sha256(body.encode()).hexdigest()[:16]}


def scan(project: dict) -> list[dict]:
    """Every member of the project's queue and drafted indexes, in priority order, as
    {item, kind, position, status, depends, decompose, brief, hash}. An entry whose endpoint
    is missing is skipped."""
    root = Path(project["path"])
    items = []
    for kind in KINDS:
        try:
            text = (root / ".knowledge" / index_leaf(kind)).read_text(encoding="utf-8")
        except OSError:
            continue
        for position, item in enumerate(entries(text, kind)):
            found = read_item(root, item)
            if found:
                items.append({**found, "kind": kind, "position": position})
    return items


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


INDEX_ANSWERS = {
    "queued": "Work queued for workers, highest priority first. Each entry names the endpoint leaf that "
              "describes it; managers add and reorder entries, and landing removes a finished endpoint "
              "with its entry.\n\nNothing is queued.\n",
    "drafted": "Ideas drafted for managers to break down, highest priority first. Each entry names the "
               "endpoint leaf that describes it.\n\nNothing is drafted.\n",
}


def add(project: dict, kind: str, name: str, brief: str) -> str:
    """Write a new endpoint leaf with kt, list it in its index (first for urgent work, else last),
    and commit both on the project's main branch.

    Committing matters: agents work in worktrees made from the main branch, and a merge
    cannot land over an untracked copy of the same leaf.
    """
    if kind not in ("urgent", *KINDS):
        raise ValueError(f"kind must be one of urgent, {', '.join(KINDS)}")
    first, kind = kind == "urgent", "queued" if kind == "urgent" else kind
    item = endpoint(kind, slug(name))
    path = Path(project["path"])
    if (path / ".knowledge" / item).exists():
        raise ValueError(f"{item} already exists in {project['name']}")
    status_line = "Status: drafted" if kind == "drafted" else "Status: queued"
    index = path / ".knowledge" / index_leaf(kind)

    def capture(question, text):
        subprocess.run(["kt", "capture", "--local", question, text], cwd=path, check=True,
                       capture_output=True, text=True)

    capture(f"what is the {kind} {slug(name)}", f"{status_line}\n\n{brief.strip()}\n")
    if not index.exists():
        capture(f"what is {kind}", INDEX_ANSWERS[kind])
    index.write_text(with_entry(index.read_text(encoding="utf-8"), item, first), encoding="utf-8")
    branch = subprocess.run(["git", "-C", str(path), "branch", "--show-current"],
                            capture_output=True, text=True).stdout.strip()
    if branch == project["main_branch"]:
        leaves = [f".knowledge/{item}", f".knowledge/{index_leaf(kind)}"]
        subprocess.run(["git", "-C", str(path), "add", "--", *leaves], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", f"Queue {item}", "--", *leaves],
                       check=True, capture_output=True)
    return item
