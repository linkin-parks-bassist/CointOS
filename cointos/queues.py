"""Work queues: item leaves in each project's knowledge tree."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

KINDS = ("urgent", "queued", "drafted")
STATUSES = ("queued", "in progress", "blocked", "done", "drafted")


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


def read_item(root: Path, item: str) -> dict | None:
    """The item at `.knowledge/<item>` under `root`, or None."""
    try:
        text = (root / ".knowledge" / item).read_text(encoding="utf-8")
    except OSError:
        return None
    body = answer(text).strip()
    return {"item": item, "status": status(text), "brief": body,
            "hash": hashlib.sha256(body.encode()).hexdigest()[:16]}


def scan(project: dict) -> list[dict]:
    """Every item leaf in the project's queues, as {item, kind, status, brief, hash}."""
    items = []
    for kind in KINDS:
        directory = Path(project["path"]) / ".knowledge/what/is" / kind
        for path in sorted(directory.glob("*.md")):
            found = read_item(Path(project["path"]), f"what/is/{kind}/{path.name}")
            if found:
                items.append({**found, "kind": kind})
    return items


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def add(project: dict, kind: str, name: str, brief: str) -> str:
    """Write a new item leaf with kt and commit it on the project's main branch.

    Committing matters: agents work in worktrees made from the main branch, and a merge
    cannot land over an untracked copy of the same leaf.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    first = "Status: drafted" if kind == "drafted" else "Status: queued"
    item = f"what/is/{kind}/{slug(name)}.md"
    path = Path(project["path"])
    if (path / ".knowledge" / item).exists():
        raise ValueError(f"{item} already exists in {project['name']}")
    subprocess.run(["kt", "capture", "--local", f"what is {kind} {slug(name)}", f"{first}\n\n{brief.strip()}\n"],
                   cwd=path, check=True, capture_output=True, text=True)
    branch = subprocess.run(["git", "-C", str(path), "branch", "--show-current"],
                            capture_output=True, text=True).stdout.strip()
    if branch == project["main_branch"]:
        subprocess.run(["git", "-C", str(path), "add", "--", f".knowledge/{item}"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", f"Queue {item}", "--", f".knowledge/{item}"],
                       check=True, capture_output=True)
    return item
