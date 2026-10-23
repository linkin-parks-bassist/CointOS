"""The landing gate: how reviewed worker code reaches a project's main branch.

An integrator lands the exact commit it reviewed, code and its packet's tests together (`land`),
or reconciles an implementation already present on main (`incorporate`). The daemon checks the
candidate against the worker's receipt and runs the full suite on a fresh checkout, outside the
ledger lock: a test that passes on main and fails on the candidate sends the packet back to its
worker with that test bundled in. Then it fast-forwards main and settles both tasks. One landing at a time per
repository, under a file lock in its Git directory.
"""
from __future__ import annotations

import copy
import re

from cointos import contracts, git, lifecycle, packets, queues, schema, tasks
from cointos.state import CONFIG, LOCK, L, log, save

SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def exact(*commits) -> None:
    if any(not isinstance(c, str) or not SHA.fullmatch(c) for c in commits):
        raise ValueError("landing requires exact commit SHAs")


repository_lock = git.repository_lock


def acceptance_result(worker: dict) -> dict:
    """Return the durable acceptance, including publication kind and measured gate."""
    acceptance = copy.deepcopy(worker['acceptance'])
    return {'ok': True, 'commit': acceptance['commit'], 'acceptance': acceptance}


def tests_of(worker: dict, *, required: bool = False) -> list[str]:
    """A packet's hidden test commits: those of the accepted test-contract items it depends on.
    Caller holds LOCK."""
    depends = queues.records().get(worker["record"] or "", {}).get("depends", [])
    records = (queues.records().get(f"{worker['place']}:{name}") for name in depends)
    commits = list(dict.fromkeys(packets.accepted(packets.current(r)) for r in records
                                if r and r.get("stage") == "test-contract" and (r.get("done") or {}).get("commit")))
    if required:
        require_tests(commits)
    return commits


def require_tests(commits: list[str]) -> None:
    """Tested construction cannot validate an empty independent contract."""
    if not commits:
        raise ValueError('implementation/integration requires an accepted test-contract dependency; '
                         'attach the independently reviewed contract to the assignment. '
                         'Naming a packet in the brief does not bind it; use correct-tests for an invalid contract.')


def check_candidate(repo: str, worker: dict, parent: str, commit: str | None, rules: dict) -> None:
    """Every packet stays intact; None checks the review worktree before commit."""
    if worker["stage"] == "skeleton":
        return
    evidence = worker["receipt"]["evidence"]
    tests = evidence.get("tests", [])
    if worker['stage'] in schema.TESTED:
        tests = submitted_tests(worker)
    if worker["stage"] == "test-contract":
        tests = [evidence["commit"]]
        production = contracts.production(repo, parent, commit, rules)
        if production:
            raise ValueError("a test packet landing changes production code: " + ", ".join(production))
    contracts.packet_unchanged(repo, worker, parent, commit, tests, rules)


def submitted_tests(worker: dict) -> list[str]:
    """The current independent contract, validated by this worker's exact receipt."""
    with LOCK:
        tests = tests_of(worker, required=True)
        if worker['receipt']['evidence'].get('tests') != tests:
            raise ValueError('receipt test-contract commits differ from the current accepted dependencies; '
                             'the worker must validate and submit the current packet before review')
    return tests


def current(integration: dict, run: str | None, submitted: dict, repo: str, main: str,
            parent: str, tree: str, commit: str) -> dict:
    """Validation results have authority only while their entire input remains current.

    Apply this to failures as well as successes, before mutating any task. A user
    hold revokes permission to accept, without discarding the reviewed artifact.
    Caller holds LOCK.
    """
    lifecycle.require_run(integration, run)
    worker = L["tasks"][integration["worker"]]
    packets.require_current(worker)
    if any(t.get("admission_hold") or queues.records().get(t.get("record"), {}).get("held_by")
           for t in (integration, worker)):
        raise ValueError("work is held; release the hold before landing")
    if (worker["status"] != "review" or worker.get("receipt") != submitted["receipt"]
            or worker.get("record_version") != submitted.get("record_version")
            or git.head(tree) != commit or git.head(repo, main) != parent
            or git.head(repo, worker["branch"]) != submitted["receipt"]["evidence"]["commit"]
            or not git.clean(worker["worktree"]) or not git.clean(tree)):
        raise ValueError("task or Git refs changed during validation; review and retry")
    return worker


def land(task_id: str, commit: str, run: str | None) -> dict:
    """Check an immutable candidate, then land it and settle its worker. Never holds LOCK
    while tests run."""
    exact(commit)
    with LOCK:
        recovered = lifecycle.recover_landings()
    if recovered:
        save()
    with LOCK:
        integration = L["tasks"][task_id]
        if integration["kind"] != "integrate":
            raise ValueError("only an integrator lands worker code")
        worker = L["tasks"][integration["worker"]]
        replay = worker["status"] == "done" and (worker.get("acceptance") or {}).get("commit") == commit
        if not replay and (worker.get("receipt") or {}).get("disposition") == "blocked":
            raise ValueError("its worker finished blocked, so completion checks have not passed; return "
                             "a manager must revise or replace its assignment before its worker submits complete")
        if not replay and worker["status"] != "review":
            raise ValueError("worker is not in review")
        if not replay and worker["receipt"]["disposition"] != "complete":
            raise ValueError("landing requires a complete worker receipt")
        if not replay:
            lifecycle.require_run(integration, run)
        where, worker = dict(tasks.place(integration)), copy.deepcopy(worker)
    if replay:
        save()  # retry durability before acknowledging a previously settled result
        return acceptance_result(worker)
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
        submitted = worker["receipt"]["evidence"]["commit"]
        if git.head(repo, worker["branch"]) != submitted or not git.clean(worker["worktree"]):
            raise ValueError("worker branch is not the clean commit its completion receipt submitted")
        with LOCK:
            current(L["tasks"][task_id], run, worker, repo, main, parent, tree, commit)
        counts = None
        if parent == commit:  # main already has it: only a landing interrupted after its fast-forward
            intent = integration.get("landing") or {}
            if (intent.get("commit") != commit or intent.get("worker_commit") != submitted
                    or intent.get("receipt_run") != worker["receipt"]["run"]
                    or intent.get("record_version") != worker.get("record_version")
                    or intent.get("run") != run):
                raise ValueError("commit reached main without passing the landing gate")
        else:
            check_candidate(repo, worker, parent, commit, rules)
            counts, caused = contracts.suite(repo, parent, commit, rules, CONFIG["timeouts"]["validation_seconds"],
                                             CONFIG["memory"]["agent_limit_gb"])
            if worker["stage"] == "test-contract" and (caused or counts["red_on_main"]):
                # Review is the authority for the contract, even while its implementation is
                # missing. Only completed exact-candidate execution reaches this point;
                # execution errors propagate. Keep the reviewed packet off main until code
                # passes it. The single ledger save accepts it and its integrator together.
                with LOCK:
                    integration = L["tasks"][task_id]
                    held = current(integration, run, worker, repo, main, parent, tree, commit)
                    lifecycle.landed(integration, run, held, {"commit": commit, "worker_commit": submitted,
                                                           "via": "tests", "stage": "test-contract", "gate": counts})
                    log("reviewed test packet", task=task_id, commit=commit, gate=counts)
                    result = acceptance_result(held)
                save()
                return result
            if caused:
                bundled = [c for c, _, _ in caused]
                shown = "\n\n".join(f"Failing test: {' '.join(c)}\n{out[-3000:]}\n\nTest source:\n{source}"
                                     for c, out, source in caused)
                reason = (f"Landing {commit} broke tests that pass on main; they are now part of this packet's "
                          f"tests:\n\n{shown}")
                with LOCK:
                    held = current(L["tasks"][task_id], run, worker, repo, main, parent, tree, commit)
                    log("landing gate rejected", task=task_id, worker=worker["id"], stage=worker["stage"],
                        commit=commit, reason=reason[:300])
                    held["bundled"] = held.get("bundled", []) + [c for c in bundled if c not in held.get("bundled", [])]
                    lifecycle.returned(L["tasks"][task_id], run, reason)
                save()
                raise ValueError(f"{worker['stage']} sent back; integrator should stop: {reason[:2000]}")
        with LOCK:
            integration = L["tasks"][task_id]
            held = current(integration, run, worker, repo, main, parent, tree, commit)
            integration["landing"] = {"commit": commit, "worker_commit": submitted,
                                      "receipt_run": worker["receipt"]["run"],
                                      "record_version": worker.get("record_version"), "run": run}
            if counts is not None:
                integration['landing']['gate'] = counts
            elif 'gate' in intent:
                integration['landing']['gate'] = intent['gate']
            saved_intent = copy.deepcopy(integration['landing'])
        save()  # the verified intent must be durable before Git publication
        with LOCK:
            integration = L['tasks'][task_id]
            held = current(integration, run, worker, repo, main, parent, tree, commit)
            if integration.get('landing') != saved_intent:
                raise ValueError('landing intent changed during persistence; review and retry')
            publication = git.publish(repo, main, commit, parent)
            lifecycle.landed(integration, run, held, {"commit": commit, "worker_commit": submitted,
                                                        "via": "landing", "stage": worker["stage"],
                                                        **({'gate': integration['landing']['gate']}
                                                           if 'gate' in integration['landing'] else {})})
            log("verified landing", task=task_id, commit=commit, stage=worker["stage"],
                **({"gate": counts} if counts else {}))
            if publication.get("draft"):
                log("workspace preserved", project=where["name"], **publication)
            result = acceptance_result(held)
        save()
    return result


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
        where, worker = dict(tasks.place(worker)), copy.deepcopy(worker)
    repo, main = where["path"], where["main_branch"]
    with repository_lock(repo):
        if git.head(repo, main) != commit:
            raise ValueError("incorporation requires the current main HEAD, not a historical ancestor")
        if git.head(repo, worker["branch"]) != worker_commit or not git.clean(worker["worktree"]):
            raise ValueError("submitted worker changed or has uncommitted work")
        if worker["receipt"]["disposition"] != "complete":
            raise ValueError("incorporation requires the worker's complete receipt")
        tests = submitted_tests(worker)
        if not contracts.tests_landed(repo, commit, tests, where["test_policy"]):
            raise ValueError("this packet's tests are not on main; land it with cointos land so they land with it")
        contracts.incorporated(repo, worker, commit, where["test_policy"])
        with LOCK:
            if integrating(worker) is not integration:
                raise ValueError("integration changed during incorporation validation; retry")
            if integration:
                lifecycle.require_run(integration, run)
                if integration.get("admission_hold"):
                    raise ValueError("integration is held")
            held = L["tasks"][worker_id]
            if (held["status"] != "review" or held.get("receipt") != worker["receipt"]
                    or held.get("record_version") != worker.get("record_version")
                    or held.get("admission_hold")
                    or queues.records().get(held.get("record"), {}).get("held_by")
                    or not git.clean(held["worktree"])
                    or git.head(repo, held["branch"]) != worker_commit or git.head(repo, main) != commit):
                raise ValueError("task, hold or refs changed during incorporation validation")
            lifecycle.landed(integration, run, held, acceptance)
            log("incorporation verified", task=worker_id, **acceptance)
        save()
    return {"ok": True, **acceptance}


def integrating(worker: dict) -> dict | None:
    """The unfinished integration of a worker, whose receipt a landing of it is."""
    return next((t for t in L["tasks"].values() if t["kind"] == "integrate" and t["worker"] == worker["id"]
                 and tasks.pending(t)), None)
