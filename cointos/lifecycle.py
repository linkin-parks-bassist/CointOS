"""Task lifecycle: the only writer of task status, run ownership, receipts and queue settlement.

Every bounded assignment ends through one typed completion receipt tied to its task and run
(`what/is/the/agent/completion/model.md`). The runner reports execution facts only: process
exit, OpenCode finish markers and outward text never decide completion. A receipt's artifacts
are checked as evidence before it is recorded; the functions here alone transition lifecycle
state, and queue records are a projection of what they settle. Callers hold LOCK.

    waiting --start--> running --receipt--> review (reviewed kinds) | done | failed (blocked integrator)
    running --run ended or stopped without receipt--> waiting (retry) | failed (runs exhausted)
    review  --landed--> done        review --returned--> waiting
"""
from __future__ import annotations

import threading
from pathlib import Path

from cointos import git, keys, lanes, opencode, queues, schema, snapshots, tasks, trees
from cointos.state import CONFIG, LOCK, L, alert, log, now, save

RETIRE_PER_TICK = 4  # settled tasks whose worktrees one reconcile pass retires (git runs under LOCK)


def owns(task: dict | None, agent_id: str | None) -> bool:
    """Whether this run is its task's current, unreceipted run."""
    return task is not None and task["agent"] == agent_id and task["status"] == "running"


def require_run(task: dict, run: str | None) -> None:
    """Refuse a lifecycle request from anything but the task's current run (None when it has none)."""
    if task["agent"] != run or task["status"] not in ("running", "waiting"):
        raise ValueError(f"{task['id']} is not owned by run {run!r}; only its current run can finish it")


# ---------------------------------------------------------------- receipts

def evidence(task: dict, disposition: str) -> dict:
    """Check a receipt against the task's artifacts; the evidence to record, or ValueError
    naming what to fix. A branch task leaves nothing uncommitted; a reviewed one submits one
    committed report matching its disposition; a merged one has landed before it completes."""
    found = {}
    lands = schema.KINDS[task["kind"]]["lands"]
    if task["branch"] is not None:
        if not git.clean(task["worktree"]):
            raise ValueError("commit everything on your branch before finishing")
        found["commit"] = git.head(task["worktree"])
        where = tasks.place(task)
        if lands == "review":
            expected = "done" if disposition == "complete" else "blocked"
            if queues.status(queues.report(task)) != expected:
                raise ValueError(f"{queues.REPORT} on your branch must declare exactly one `Status: {expected}`")
            found["report"] = expected
        elif lands == "merge" and disposition == "complete" and not git.contains(where["path"], task["branch"],
                                                                                 where["main_branch"]):
            raise ValueError("land your committed branch with `cointos merge` before finishing")
    if task["kind"] == "decompose" and disposition == "complete":
        record = queues.records().get(task["record"])
        revised = record and record["hash"] != task["record_hash"] and (
            record["status"] == "queued" or record.get("replaced_by"))
        if not task.get("replacements") and not revised:
            raise ValueError("revise the failed item or replace it with `cointos replace CHILD...` before finishing")
    if task["kind"] == "garden" and disposition == "complete":
        found.update(garden_health(task))
    return found


def garden_health(task: dict) -> dict:
    """A finished batch's tree as main now has it; still-unresolved selected leaves alert the user
    instead of repeating the batch."""
    where = tasks.place(task)
    health = trees.health(where, CONFIG["timeouts"]["command_seconds"])
    L["trees"][where["name"]] = {**health, "checked_at": now()}
    unresolved = sorted(set(task["brief"].splitlines()) & set(trees.pending(health)))
    if unresolved:
        alert(f"Gardener finished with unresolved leaves in {where['name']}: {', '.join(unresolved)}. "
              "Check its receipt before further work on that concern.")
    return {"brown": health["brown"], "yellow": health["yellow"], "unresolved": unresolved}


def _known(task: dict, run: str | None, disposition: str, summary: str) -> dict | None:
    """The same receipt again (a lost reply) returns the recorded one; a different one is refused."""
    receipt = task["receipt"]
    if receipt is None or receipt["run"] != run:
        return None
    if (receipt["disposition"], receipt["summary"]) != (disposition, summary):
        raise ValueError("this run already submitted a different completion receipt")
    return receipt


def submit(task_id: str, run: str | None, disposition: str, summary: str) -> dict:
    """An agent's `cointos finish`: check its evidence, record its receipt, settle its task."""
    task = L["tasks"].get(task_id)
    if task is None:
        raise ValueError(f"unknown task {task_id}")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("a receipt needs a summary: the evidence for complete, or the specific blocker")
    summary = summary.strip()
    known = _known(task, run, disposition, summary)
    if known:
        return known
    if not owns(task, run):
        raise ValueError(f"{task_id} is not running under {run!r}; only its current run can finish it")
    allowed = schema.KINDS[task["kind"]]["receipts"]
    if disposition not in allowed:
        raise ValueError(f"a {task['kind']} task finishes with {' or '.join(allowed)}"
                         + ("; land with `cointos land` or send back with `cointos return`"
                            if task["kind"] == "integrate" else ""))
    return _receive(task, run, disposition, summary, evidence(task, disposition))


def _receive(task: dict, run: str | None, disposition: str, summary: str, found: dict) -> dict:
    """Record a checked receipt and apply its one transition."""
    receipt = {"run": run, "disposition": disposition, "summary": summary, "evidence": found, "at": now()}
    note = f"{disposition}: {summary}"[:CONFIG["result_chars"]]
    if schema.KINDS[task["kind"]]["lands"] == "review":
        _settle(task, "review", note, receipt=receipt, result=summary)
    elif task["kind"] == "integrate" and disposition == "blocked":
        _settle(task, "failed", note, receipt=receipt, result=summary)
        worker = L["tasks"][task["worker"]]
        if worker["status"] == "review":
            _settle(worker, "failed", "could not be integrated: " + summary)
    else:
        _settle(task, "done", note, receipt=receipt, result=summary)
    if disposition == "blocked" and task["role"] not in ("worker", "integrator"):
        alert(f"{task['id']} blocked: {summary}")
    log("receipt", task=task["id"], run=run, disposition=disposition)
    return receipt


def landed(integration: dict | None, run: str | None, worker: dict, acceptance: dict) -> None:
    """A verified landing or incorporation settles the worker and is its integrator's receipt."""
    live = integration is not None and integration["status"] not in ("done", "failed")
    if live:
        require_run(integration, run)
    if worker["status"] != "review":
        raise ValueError(f"{worker['id']} is not in review")
    if worker["receipt"]["evidence"]["commit"] != acceptance["worker_commit"]:
        raise ValueError("the landed worker commit is not the one its receipt submitted")
    _settle(worker, "done", "accepted via " + acceptance["via"], review=None, acceptance=acceptance)
    if live:
        _receive(integration, run, "complete", f"{worker['item']} accepted at {acceptance['commit']}",
                 dict(acceptance))


def returned(integration: dict, run: str | None, notes: str) -> None:
    """The integrator sends a worker's item back; that is the integrator's receipt."""
    if integration["kind"] != "integrate":
        raise ValueError("only an integrator returns work")
    if not isinstance(notes, str) or not notes.strip():
        raise ValueError("say exactly what must change")
    if _known(integration, run, "returned", notes.strip()):
        return
    require_run(integration, run)
    worker = L["tasks"][integration["worker"]]
    if worker["status"] != "review":
        raise ValueError(f"{worker['id']} is not in review")
    _settle(worker, "waiting", "sent back by the integrator", review=notes.strip(), receipt=None)
    worker["rejections"] = worker.get("rejections", 0) + 1
    _receive(integration, run, "returned", notes.strip(), {"worker": worker["id"]})


# ---------------------------------------------------------------- holding and revising queued work

def hold(key: str, by: str) -> None:
    """Keep a queue item from starting while `by` decides about it; a run of it now is stopped,
    uncharged. The hold ends when the item is revised, when it is released, or when the holding
    task settles."""
    record = queues.records()[key]
    if record["status"] == "done":
        raise ValueError(f"{key} is already accepted; queue new work instead")
    if record["held_by"] not in (None, by):
        raise ValueError(f"{key} is already held by {record['held_by']}")
    record["held_by"] = by
    task = L["tasks"].get(key)
    if task and task["status"] == "running":
        stop(task["agent"], f"held by {by}", requeue=True, charge=False)
    log("item held", item=key, by=by)


def unhold(key: str, by: str) -> None:
    record = queues.records()[key]
    if record["held_by"] not in (None, by) and by != "user":
        raise ValueError(f"{key} is held by {record['held_by']}")
    record["held_by"] = None
    log("item released", item=key, by=by)


def revise(key: str, by: str, reason: str, brief: str, stage=None, reasoning_effort=None, budget=None) -> None:
    """Change what a queue item asks for. Its task starts afresh on the revised brief: a waiting or
    running one waits for a fresh session, a reviewed one goes back to its worker. The branch keeps
    earlier work, which the revised assignment is told to keep only where it still fits."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("say why the item is revised")
    record = queues.records()[key]
    task = L["tasks"].get(key)
    if record["status"] == "done" or (task and task["status"] == "done"):
        raise ValueError(f"{key} is already accepted; queue new work instead")
    if record.get("replaced_by"):
        raise ValueError(f"{key} was superseded by {', '.join(record['replaced_by'])}")
    if task and task["status"] == "review" and any(
            t["kind"] == "integrate" and t["worker"] == key and t["status"] == "running" for t in L["tasks"].values()):
        raise ValueError(f"{key} is being integrated now; hold it and revise after the integration ends")
    if by != "user" and record["kind"] == "queued":
        queues.require_summary(brief)
    queues.revise(record, brief, stage, reasoning_effort, budget)
    if task and task["status"] in ("waiting", "running", "review", "failed"):
        if task["status"] == "running":
            stop(task["agent"], f"revised by {by}", requeue=True, charge=False)
        task.update(brief=record["brief"], stage=record["stage"], record_hash=record["hash"],
                    reasoning_effort=schema.default_effort(CONFIG, {**task, "reasoning_effort": record["reasoning_effort"]}),
                    budget=schema.budget(CONFIG, record.get("budget")), session=None, runs=0, fresh_retries=0,
                    rejections=0,
                    recovery_note=None, recovery_context=None, revision=f"Revised by {by}: {reason.strip()}")
        _settle(task, "waiting", f"revised by {by}", receipt=None, review=None)
        snapshots.forget_owner(task["id"])  # a new conversation on a new brief
        for integration in L["tasks"].values():
            if (integration["kind"] == "integrate" and integration["worker"] == key
                    and integration["status"] == "waiting" and integration["brief"] != record["brief"]):
                integration.update(brief=record["brief"], session=None, runs=0, fresh_retries=0,
                                   recovery_note=None, recovery_context=None, revision=task["revision"])
                snapshots.forget_owner(integration["id"])
    log("item revised", item=key, by=by, reason=reason.strip())


# ---------------------------------------------------------------- runs

def start(task: dict, agent_id: str) -> None:
    if task.get("admission_hold"):
        raise ValueError(f"task {task['id']} is held; explicitly resume it first")
    if task["status"] != "waiting" or any(a["task"] == task["id"] for a in L["agents"].values()):
        raise ValueError(f"task {task['id']} already has a run")
    task.update(status="running", runs=task["runs"] + 1, agent=agent_id, receipt=None, note=None, updated_at=now())


def engaged(agent_id: str) -> None:
    """Record the first gateway request as the boundary between harness launch and assignment work."""
    agent = L["agents"].get(agent_id)
    if agent is None:
        return
    agent["engaged"] = True
    task = L["tasks"].get(agent["task"])
    if owns(task, agent_id):
        task["launch_failures"] = 0


def ended(agent_id: str, facts: dict) -> None:
    """The runner's report that a run is over. Reconciliation only: a receipted run is released;
    an unreceipted one is retried or failed. Finish markers and exit codes are diagnostics."""
    task = L["tasks"].get(L["agents"][agent_id]["task"])
    if not owns(task, agent_id):
        release(agent_id, "run ended")
        return
    detail = f"finish marker {facts.get('finish')}, exit code {facts.get('code')}"
    if facts.get("error"):
        detail += f"; {facts['error']}"
    agent = L["agents"][agent_id]
    if not agent.get("engaged"):
        failures = task.get("launch_failures", 0) + 1
        task["launch_failures"] = failures
        if failures >= CONFIG["spawner"]["max_launch_failures"]:
            task["admission_hold"] = "repeated infrastructure launch failure"
            alert(f"Held {task['id']} after {failures} runs ended before reaching the model: {detail}")
        stop(agent_id, f"run failed before reaching the model ({detail})", requeue=True, charge=False)
        return
    stop(agent_id, f"run ended without a completion receipt ({detail})", requeue=True)


def kill(agent_id: str) -> dict:
    """the user ends a run and withholds further admission until explicitly released."""
    task = L["tasks"][L["agents"][agent_id]["task"]]
    if owns(task, agent_id):
        task["admission_hold"] = "killed by the user"
    stop(agent_id, "run killed by the user", requeue=True, charge=False)
    return task


def resume_task(task_id: str) -> dict:
    task = L["tasks"].get(task_id)
    if task is None:
        raise ValueError(f"unknown task {task_id}")
    if task["status"] != "waiting":
        raise ValueError("only waiting tasks can be resumed")
    task.pop("admission_hold", None)
    log("task admission released", task=task_id)
    return task


def stop(agent_id: str, reason: str, requeue: bool, charge: bool = True) -> None:
    """End a run now. An unreceipted task waits again, or fails once its runs are exhausted; an
    uncharged stop (the user, the guard, a halt) does not count against them."""
    agent = L["agents"].get(agent_id)
    if agent is None:
        return
    task = L["tasks"].get(agent["task"])
    if owns(task, agent_id):
        task["interrupted_at"] = now()
        if not charge:
            task["runs"] -= 1
        if requeue and task["runs"] < CONFIG["spawner"]["max_runs_per_task"]:
            _settle(task, "waiting", reason)
        else:
            fail(task, reason)
    release(agent_id, reason)
    threading.Thread(target=opencode.stop, args=(agent_id,), daemon=True).start()


def retry_fresh(agent_id: str, reason: str, packet: str) -> None:
    """Budget recovery: restart the task in a new session from a bounded evidence packet, a
    bounded number of times; then fail it."""
    task = L["tasks"][L["agents"][agent_id]["task"]]
    fresh = task.get("fresh_retries", 0)
    if fresh >= CONFIG["recovery"]["fresh_retries"]:
        stop(agent_id, reason + "; fresh retries exhausted", requeue=False)
        return
    task.update(session=None, fresh_retries=fresh + 1, recovery_note=reason, recovery_context=packet)
    snapshots.forget_owner(task["id"])
    log("fresh recovery", task=task["id"], attempt=fresh + 1, reason=reason)
    stop(agent_id, reason, requeue=True)


def fail(task: dict, reason: str) -> None:
    _settle(task, "failed", reason)
    if task["role"] not in ("worker", "integrator"):
        alert(f"Gave up on {task['title']} in {task['place']} after {task['runs']} runs: {reason}")
    if task["kind"] == "integrate" and L["tasks"][task["worker"]]["status"] == "review":
        _settle(L["tasks"][task["worker"]], "failed", "could not be integrated")


def orphaned(task: dict) -> None:
    """A running task whose run did not survive a daemon replacement waits again."""
    interrupted = now()
    task.update(status="waiting", agent=None, note="its agent was gone after a daemon restart",
                interrupted_at=interrupted, updated_at=interrupted)


def release(agent_id: str, reason: str) -> None:
    """Take a run out of the ledger and revoke its gateway key; its processes stop after this.
    A run whose receipt settled its task also leaves no landed worktree behind."""
    agent = L["agents"].pop(agent_id)
    L["exiting"][agent_id] = now()
    keys.revoke(agent_id)
    lanes.cancel_agent(agent_id)
    task = L["tasks"].get(agent["task"])
    if task and (task["receipt"] or {}).get("run") == agent_id and task["status"] == "done":
        clean_up(task)
    if task and not snapshots.live(task["id"]):
        snapshots.forget_owner(task["id"])
    log("agent ended", agent=agent_id, task=agent["task"], reason=reason, thoughts=agent["thoughts"],
        seconds=round(now() - agent["started_at"]))


def clean_up(task: dict) -> None:
    """Retire a settled task's worktree and branch (see `retire`), and an accepted worker's with its
    integrator's."""
    retire(task)
    if task["kind"] == "integrate" and task["status"] == "done":
        retire(L["tasks"][task["worker"]])


def revivable(task: dict) -> bool:
    """Whether `cointos revise` could still restart this task on its branch: a failed item whose
    queue record is live, unaccepted and not superseded."""
    record = queues.records().get(task["record"]) if task["record"] else None
    return (task["status"] == "failed" and record is not None and record["status"] != "done"
            and not record.get("replaced_by") and not task.get("replaced_by"))


def retire(task: dict) -> bool:
    """Leave nothing behind for a settled task with no run: remove its checkout, delete its branch
    once main contains it, and archive a dead unlanded branch under `git.ARCHIVE`. A revivable
    task keeps its branch; a checkout with uncommitted work is kept for inspection.
    Returns whether the task was considered (it is then marked `retired`)."""
    if (task["branch"] is None or task["status"] not in ("done", "failed") or task.get("retired")
            or any(agent["task"] == task["id"] for agent in L["agents"].values())):
        return False
    try:
        where = tasks.place(task)
    except StopIteration:  # its project is no longer configured: nothing safe to act on
        task["retired"] = "kept: place no longer configured"
        return True
    if Path(task["worktree"]).is_dir():
        if not git.clean(task["worktree"]):
            task["retired"] = "kept: uncommitted work"
            log("worktree kept: uncommitted work", task=task["id"])
            return True
        git.remove_worktree(where["path"], task["worktree"])
    outcome = git.retire_branch(where["path"], task["branch"], where["main_branch"], keep=revivable(task))
    task["retired"] = outcome
    log("task retired", task=task["id"], branch=outcome)
    return True


# ---------------------------------------------------------------- settlement and its projection

def _settle(task: dict, status: str, note: str, **fields) -> None:
    """The one task-status write. Settlement does not end a run or its conversation."""
    task.update(status=status, agent=None, note=note, updated_at=now(), **fields)
    task.pop("retired", None)  # a task that settles again is retired again
    if status in ("done", "failed"):
        for record in queues.records().values():  # a settled task no longer decides about anything it held
            if record["held_by"] == task["id"]:
                record["held_by"] = None
    project(task)


def receipt_delivered(task_id: str, agent_id: str) -> None:
    """Retire the managed run after its terminal command has printed and flushed its receipt.

    The acknowledgement is idempotent.  Process termination runs after the API action returns;
    the command that acknowledged delivery is inside the unit being stopped.
    """
    task = L["tasks"].get(task_id)
    receipt = task.get("receipt") if task else None
    if receipt is None or receipt.get("run") != agent_id:
        raise ValueError(f"{task_id} has no completion receipt from run {agent_id!r}")
    agent = L["agents"].get(agent_id)
    if agent is None:
        return
    if agent["task"] != task_id:
        raise ValueError(f"run {agent_id!r} does not belong to {task_id}")

    def retire() -> None:
        with LOCK:
            if agent_id in L["agents"]:
                stop(agent_id, "completion receipt delivered", requeue=False, charge=False)
                save()

    threading.Thread(target=retire, daemon=True).start()


def project(task: dict) -> bool:
    """Make the task's queue record show what its settlement says. Idempotent; True on change."""
    record = queues.records().get(task["record"]) if task["record"] else None
    if record is None:
        return False
    receipt, acceptance = task["receipt"] or {}, task.get("acceptance")
    if task["kind"] == "item" and acceptance:
        if (record["status"], record.get("commit")) == ("done", acceptance["commit"]) and not (
                record.get("report") is not None or record.get("decompose")):
            return False
        queues.accepted(record["project"], record["item"], acceptance["commit"])
    elif task["kind"] in ("item", "breakdown", "decompose") and task["status"] == "failed":
        if task["record_hash"] != record["hash"] or (record["status"] != "queued" and task["kind"] != "decompose"):
            return False
        report = (f"Assignment: {task['id']}\n\n{task['brief']}\n\n"
                  f"Worker receipt: {receipt.get('summary', 'No completion receipt')}\n"
                  f"Evidence: {receipt.get('evidence', {})}\n\n"
                  f"Task failed: {task['note'] or 'run retries exhausted'}")
        queues.update(record["project"], record["item"], "blocked",
                      report, decompose=task["kind"] == "item")
    elif task["kind"] == "breakdown" and receipt and record["status"] == "queued":
        blocked = receipt["disposition"] == "blocked"
        queues.update(record["project"], record["item"], "blocked" if blocked else "done",
                      receipt["summary"] if blocked else "")
    elif (task["kind"] == "decompose" and receipt.get("disposition") == "complete"
          and task["record_hash"] == record["hash"] and record["status"] != "done"):
        queues.update(record["project"], record["item"], "done")
    elif task["kind"] == "decompose" and receipt.get("disposition") == "blocked" and task["record_hash"] == record["hash"]:
        queues.update(record["project"], record["item"], "blocked", receipt["summary"])
    else:
        return False
    return True


def reconcile() -> bool:
    """Re-project settled tasks and retire caches whose conversations have ended."""
    snapshots.forget_orphans()
    changed = False
    for task in L["tasks"].values():
        if project(task):
            log("queue record reconciled", task=task["id"])
            changed = True
    swept = 0
    for task in list(L["tasks"].values()):  # retire settled work a bounded few at a time under LOCK
        if swept >= RETIRE_PER_TICK:
            break
        try:
            swept += retire(task)
        except ValueError as error:
            task["retired"] = f"failed: {error}"
            log("retire failed", task=task["id"], error=str(error))
    return changed
