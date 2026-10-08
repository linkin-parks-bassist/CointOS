"""The landing gate: how reviewed worker code reaches a project's main branch.

An integrator lands the exact commit it reviewed, code and its packet's tests together (`land`),
or reconciles an implementation already present on main (`incorporate`). The daemon checks the
candidate against the worker's receipt and runs the full suite on a fresh checkout, outside the
ledger lock: a test that passes on main and fails on the candidate sends the packet back to its
worker with that test bundled in. Then it fast-forwards main and settles both tasks. One landing at a time per
repository, under a file lock in its Git directory.
"""
from __future__ import annotations

import contextlib
import fcntl
import re
from pathlib import Path

from cointos import contracts, git, lifecycle, queues, schema, tasks
from cointos.state import CONFIG, LOCK, L, log, save

SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def exact(*commits) -> None:
    if any(not isinstance(c, str) or not SHA.fullmatch(c) for c in commits):
        raise ValueError("landing requires exact commit SHAs")


@contextlib.contextmanager
def repository_lock(repo: str):
    common = git.run(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    with open(Path(common) / "cointos-land.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def tests_of(worker: dict) -> list[str]:
    """A packet's hidden test commits: those of the accepted test-contract items it depends on.
    Caller holds LOCK."""
    depends = queues.records().get(worker["record"] or "", {}).get("depends", [])
    packets = (queues.records().get(f"{worker['place']}:{name}") for name in depends)
    return [r["done"]["commit"] for r in packets
            if r and r.get("stage") == "test-contract" and (r.get("done") or {}).get("commit")]


def check_candidate(repo: str, worker: dict, parent: str, commit: str, rules: dict) -> None:
    """A ValueError when the candidate breaks its stage's contract outright: an implementer
    touched tests, or the review changed tests beyond the packet's own."""
    if worker["stage"] in ("implementation", "integration"):
        contracts.packet_unchanged(repo, worker, parent, commit, worker["receipt"]["evidence"].get("tests", []), rules)


def land(task_id: str, commit: str, run: str | None) -> dict:
    """Check an immutable candidate, then land it and settle its worker. Never holds LOCK
    while tests run."""
    exact(commit)
    with LOCK:
        integration = L["tasks"][task_id]
        if integration["kind"] != "integrate":
            raise ValueError("only an integrator lands worker code")
        worker = L["tasks"][integration["worker"]]
        if worker["status"] == "done" and (worker.get("acceptance") or {}).get("commit") == commit:
            return {"ok": True, "commit": commit}  # a retry after a lost reply
        if worker["status"] != "review":
            raise ValueError("worker is not in review")
        if worker["stage"] in schema.TESTED and worker["receipt"]["disposition"] != "complete":
            raise ValueError("its worker finished blocked, so its hidden tests never ran against this code; return "
                             "it to the worker to finish complete, or finish blocked for a manager")
        lifecycle.require_run(integration, run)
        where, worker = dict(tasks.place(integration)), dict(worker)
    repo, main, tree = where["path"], where["main_branch"], integration["worktree"]
    rules = where.get("test_policy")
    if not rules:
        raise ValueError("project has no configured test_policy")
    with repository_lock(repo):
        if git.head(tree) != commit or not git.clean(tree):
            raise ValueError("candidate must be the integrator's clean HEAD")
        parent = git.head(repo, main)
        if not git.contains(repo, parent, commit):
            raise ValueError("candidate must contain current main; run cointos review again")
        if git.run(repo, "branch", "--show-current") != main or not git.clean(repo):
            raise ValueError("main checkout must be clean and on its configured branch")
        submitted = worker["receipt"]["evidence"]["commit"]
        if git.head(repo, worker["branch"]) != submitted or not git.clean(worker["worktree"]):
            raise ValueError("worker branch is not the clean commit its completion receipt submitted")
        counts = None
        if parent == commit:  # main already has it: only a landing interrupted after its fast-forward
            if (integration.get("landing") or {}).get("commit") != commit:
                raise ValueError("commit reached main without passing the landing gate")
        else:
            check_candidate(repo, worker, parent, commit, rules)
            counts, caused = contracts.suite(repo, parent, commit, rules, CONFIG["timeouts"]["command_seconds"],
                                             CONFIG["memory"]["agent_limit_gb"])
            if caused:
                bundled = [c for c, _, _ in caused]
                shown = "\n\n".join(f"Failing test: {' '.join(c)}\n{out[-3000:]}\n\nTest source:\n{source}"
                                     for c, out, source in caused)
                reason = (f"Landing {commit} broke tests that pass on main; they are now part of this packet's "
                          f"tests:\n\n{shown}")
                log("landing gate rejected", task=task_id, worker=worker["id"], stage=worker["stage"],
                    commit=commit, reason=reason[:300])
                with LOCK:
                    held = L["tasks"][integration["worker"]]
                    held["bundled"] = held.get("bundled", []) + [c for c in bundled if c not in held.get("bundled", [])]
                    lifecycle.returned(L["tasks"][task_id], run, reason)
                    save()
                raise ValueError(f"{worker['stage']} sent back; integrator should stop: {reason[:2000]}")
        with LOCK:
            integration, worker = L["tasks"][task_id], L["tasks"][integration["worker"]]
            if (worker["status"] != "review" or git.head(tree) != commit or git.head(repo, main) != parent
                    or git.head(repo, worker["branch"]) != submitted
                    or not git.clean(worker["worktree"]) or not git.clean(tree)):
                raise ValueError("task or Git refs changed during validation; review and retry")
            lifecycle.require_run(integration, run)
            integration["landing"] = {"commit": commit, "worker_commit": submitted}
            save()  # recoverable if replacement occurs after the fast-forward but before settlement
            git.run(repo, "merge", "--ff-only", commit)
            lifecycle.landed(integration, run, worker, {"commit": commit, "worker_commit": submitted,
                                                        "via": "landing", "stage": worker["stage"]})
            save()
            log("verified landing", task=task_id, commit=commit, stage=worker["stage"],
                **({"gate": counts} if counts else {}))
    return {"ok": True, "commit": commit}


def incorporate(worker_id: str, commit: str, worker_commit: str, run: str | None) -> dict:
    """Settle an implementation in review whose exact behaviour is already on main, with its
    accepted checks green there."""
    exact(commit, worker_commit)
    acceptance = {"commit": commit, "worker_commit": worker_commit, "via": "incorporation", "stage": "implementation"}
    with LOCK:
        worker = L["tasks"].get(worker_id)
        if worker and worker.get("acceptance") == acceptance:
            return {"ok": True, **acceptance}
        if not worker or worker["kind"] != "item" or worker["stage"] != "implementation" or worker["status"] != "review":
            raise ValueError("incorporate requires an implementation in review")
        if worker["receipt"]["evidence"]["commit"] != worker_commit:
            raise ValueError("the worker commit must be the one its completion receipt submitted")
        integration = integrating(worker)
        if integration is not None:
            lifecycle.require_run(integration, run)
        where, worker = dict(tasks.place(worker)), dict(worker)
    repo, main = where["path"], where["main_branch"]
    with repository_lock(repo):
        if git.head(repo, main) != commit:
            raise ValueError("incorporation requires the current main HEAD, not a historical ancestor")
        if git.head(repo, worker["branch"]) != worker_commit or not git.clean(worker["worktree"]):
            raise ValueError("submitted worker changed or has uncommitted work")
        if worker["receipt"]["disposition"] != "complete":
            raise ValueError("incorporation requires the worker's complete receipt")
        if not contracts.tests_landed(repo, commit, worker["receipt"]["evidence"].get("tests", []), where["test_policy"]):
            raise ValueError("this packet's tests are not on main; land it with cointos land so they land with it")
        contracts.incorporated(repo, worker, commit, where["test_policy"])
        with LOCK:
            worker = L["tasks"][worker_id]
            if (worker["status"] != "review" or not git.clean(worker["worktree"])
                    or git.head(repo, worker["branch"]) != worker_commit or git.head(repo, main) != commit):
                raise ValueError("task or refs changed during incorporation validation")
            lifecycle.landed(integrating(worker), run, worker, acceptance)
            log("incorporation verified", task=worker_id, **acceptance)
            save()
    return {"ok": True, **acceptance}


def integrating(worker: dict) -> dict | None:
    """The unfinished integration of a worker, whose receipt a landing of it is."""
    return next((t for t in L["tasks"].values() if t["kind"] == "integrate" and t["worker"] == worker["id"]
                 and tasks.pending(t)), None)
