"""Shared test fixtures: a fresh ledger, real Git repositories, and tasks made the way the daemon
makes them (`tasks.create`, `lifecycle.start`), so tests exercise the real record shapes."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path
from unittest.mock import patch

from cointos import git, lifecycle, opencode, queues, state, tasks


def fresh_ledger(test, previous: dict | None = None) -> dict:
    """An empty daemon ledger for this test; the previous one comes back afterwards."""
    saved, stopping = copy.deepcopy(state.L), state.STOPPING.is_set()
    test.addCleanup(lambda: (state.L.clear(), state.L.update(saved),
                             state.STOPPING.set() if stopping else state.STOPPING.clear()))
    state.STOPPING.clear()
    state.L.clear()
    state.L.update(state.fresh(previous or {}))
    return state.L


def quiet(test) -> None:
    """No systemd, no background threads, no kt: runs and publication stay in the ledger."""
    test.enterContext(patch.object(opencode, "stop"))
    test.enterContext(patch.object(lifecycle.threading, "Thread"))
    test.enterContext(patch.object(queues, "publish"))


def repository(test, name: str = "project") -> Path:
    """A Git repository with one commit on `main`."""
    root = Path(test.enterContext(tempfile.TemporaryDirectory()))
    repo = root / name
    repo.mkdir()
    git.run(repo, "init", "-q", "-b", "main")
    git.run(repo, "config", "user.name", "Test")
    git.run(repo, "config", "user.email", "test@example.invalid")
    git.run(repo, "commit", "-q", "--allow-empty", "-m", "initial")
    return repo


def project(test, repo: Path, name: str = "p", **settings) -> dict:
    """Register `repo` as the only configured project."""
    registered = {"name": name, "path": str(repo), "main_branch": "main", "priority": 100, "enabled": True, **settings}
    test.enterContext(patch.dict(state.CONFIG, projects=[registered], trees=[]))
    return registered


def commit(worktree, message: str = "change") -> str:
    git.run(worktree, "add", "-A")
    git.run(worktree, "commit", "-q", "--allow-empty", "-m", message)
    return git.head(worktree)


def queued(where: dict, name: str, brief: str = "Do it", kind: str = "queued", **options) -> dict:
    """A task for a new queue record, as the spawner creates it."""
    item = queues.add(where, kind, name, brief, **options)
    record = queues.records()[f"{where['name']}:{item}"]
    task_kind = "breakdown" if kind == "command" else "item"
    return tasks.create(task_kind, where, item, record["brief"], [4], item=item, record_hash=record["hash"])


def running(task: dict, agent_id: str = "run-1", worktree: bool = True) -> dict:
    """Start a run of a waiting task in the ledger (its worktree created, no processes)."""
    if worktree and task["branch"] is not None:
        where = tasks.place(task)
        git.add_worktree(where["path"], task["worktree"], task["branch"], where["main_branch"])
    lifecycle.start(task, agent_id)
    state.L["agents"][agent_id] = {
        "id": agent_id, "role": task["role"], "place": task["place"], "task": task["id"], "title": task["title"],
        "class": "background", "state": "running", "session": None, "thoughts": 1, "generated": 0, "repeats": 0,
        "engaged": True, "last_thought": None, "last_activity": state.now(), "started_at": state.now()}
    return task


def reviewed(task: dict, agent_id: str = "run-1", status: str = "done") -> dict:
    """A worker run that committed its report and submitted it for review."""
    running(task, agent_id)
    (Path(task["worktree"]) / queues.REPORT).write_text(f"Status: {status}\n\nDone.\n")
    commit(task["worktree"], "work")
    lifecycle.submit(task["id"], agent_id, "complete" if status == "done" else "blocked", "Done")
    lifecycle.release(agent_id, "run ended")
    return task
