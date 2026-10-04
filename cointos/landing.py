"""The landing gate: how reviewed worker code reaches a project's main branch.

An integrator lands the exact commit it reviewed (`land`), or reconciles an implementation
already present on main (`incorporate`). The daemon checks the candidate against the worker's
receipt and the project's accepted test contracts on a fresh checkout, outside the ledger lock,
then fast-forwards main and settles both tasks through the lifecycle. One landing at a time per
repository, under a file lock in its Git directory.
"""
from __future__ import annotations

import contextlib
import fcntl
import re
from pathlib import Path

from cointos import contracts, git, lifecycle, queues, tasks
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


def checks(repo: str, worker: dict, parent: str, commit: str, rules: dict) -> list[list[str]]:
    """The accepted checks a candidate must pass for its worker's construction stage; a
    ValueError when the candidate breaks the stage's contract outright."""
    stage = worker["stage"]
    if stage == "implementation":
        return contracts.implementation_checks(repo, worker, parent, commit, rules)
    if stage == "test-contract":
        production = contracts.affected(repo, parent, commit, rules)
        if production:
            raise ValueError("test-contract commits cannot change production code: " + ", ".join(sorted(production)))
        contracts.contracts(repo, commit, rules)
        return []
    if stage == "integration":
        # Integration is not a way around implementation checks: carried production changes
        # must pass contracts already accepted on main, plus any contracts it adds.
        added = contracts.integration_tests(repo, parent, commit, rules)
        commands = contracts.affected_checks(repo, parent, commit, parent, rules)
        return commands + [c for c in added if c not in commands]
    return []  # a skeleton is accepted on the integrator's review


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
        red = None
        if parent == commit:  # main already has it: only a landing interrupted after its fast-forward
            if (integration.get("landing") or {}).get("commit") != commit:
                raise ValueError("commit reached main without passing the landing gate")
        else:
            try:
                commands = checks(repo, worker, parent, commit, rules)
                if worker["stage"] == "implementation":
                    red = contracts.implementation_gate(repo, parent, commit, commands,
                                                        CONFIG["timeouts"]["command_seconds"],
                                                        CONFIG["memory"]["agent_limit_gb"])
                else:
                    contracts.verify(repo, commit, commands, CONFIG["timeouts"]["command_seconds"],
                                     CONFIG["memory"]["agent_limit_gb"])
                if worker["stage"] == "test-contract":
                    red = contracts.red_gate(repo, parent, commit, git.show(repo, submitted, queues.REPORT), rules,
                                             CONFIG["timeouts"]["command_seconds"], CONFIG["memory"]["agent_limit_gb"])
            except ValueError as error:
                if worker["stage"] not in ("implementation", "test-contract"):
                    raise
                log("landing gate rejected", task=task_id, worker=worker["id"], stage=worker["stage"],
                    commit=commit, reason=str(error)[:300])
                with LOCK:
                    lifecycle.returned(L["tasks"][task_id], run, f"Landing {commit} failed validation: {error}")
                    save()
                raise ValueError(f"{worker['stage']} sent back; integrator should stop: {error}") from error
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
                **({"gate": red} if red else {}))
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
        if queues.status(queues.report(worker)) != "done":
            raise ValueError("incorporation requires a done worker report")
        commands = contracts.incorporated(repo, worker, commit, where["test_policy"])
        contracts.verify(repo, commit, commands, CONFIG["timeouts"]["command_seconds"], CONFIG["memory"]["agent_limit_gb"])
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
                 and t["status"] in ("waiting", "running")), None)
