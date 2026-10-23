"""Task lifecycle: the only writer of task status, run ownership, receipts and queue settlement.

Every bounded assignment ends through one typed completion receipt tied to its task and run
(`what/is/the/agent/completion/model.md`). The runner reports execution facts only: process
exit, OpenCode finish markers and outward text never decide completion. A receipt's artifacts
are checked as evidence before it is recorded; the functions here alone transition lifecycle
state and write a queue record's one terminal fact, `done`. Callers hold LOCK.

    waiting --start--> running --receipt--> review (complete worker) | done | failed (blocked work)
    running --run ended or stopped without receipt--> waiting (retry) | failed (runs exhausted)
    review  --landed--> done        review --returned--> waiting
"""
from __future__ import annotations

import threading
from pathlib import Path

from cointos import contracts, frontier, git, keys, lanes, opencode, packets, queues, schema, snapshots, tasks, trees
from cointos.state import CONFIG, LOCK, L, alert, log, now, save


def owns(task: dict | None, agent_id: str | None) -> bool:
    """Whether this run is its task's current, unreceipted run."""
    return task is not None and task["agent"] == agent_id and task["status"] == "running"


def require_run(task: dict, run: str | None) -> None:
    """Refuse a lifecycle request from anything but the task's current run (None when it has none)."""
    if task["agent"] != run or not tasks.pending(task):
        raise ValueError(f"{task['id']} is not owned by run {run!r}; only its current run can finish it")


# ---------------------------------------------------------------- receipts

def evidence(task: dict, disposition: str, checked: dict | None = None) -> dict:
    """Check a receipt against the task's artifacts; the evidence to record, or ValueError
    naming what to fix. A branch task leaves nothing uncommitted; a merged one has landed
    before it completes; a test packet changes only tests; tested work has passed its check."""
    found = {}
    if task['kind'] == 'steward' and disposition == 'complete':
        found['scout_result'] = scout_evidence(task, (checked or {}).get('scout_result'))
    if task["role"] == "manager" and disposition == "complete":
        problems = queues.frontier_problems(task["place"], owner=task["id"])
        if problems:
            raise ValueError("queued work cannot continue; fix it before finishing, or finish blocked with the "
                             "unresolved cause:\n" + "\n".join(problems))
    lands = schema.KINDS[task["kind"]]["lands"]
    if task["branch"] is not None:
        if not git.clean(task["worktree"]):
            raise ValueError("commit everything on your branch before finishing; uncommitted now (git status):\n"
                             + uncommitted(task["worktree"]))
        found["commit"] = git.head(task["worktree"])
        where = tasks.place(task)
        if lands == "review":
            if disposition == 'complete':
                contracts.worker_artifact(where['path'], task, found['commit'])
            rules = where.get("test_policy")
            if disposition == "complete" and rules:
                contracts.stage_history(where["path"], task, git.head(where["path"], where["main_branch"]), rules)
            if disposition == "complete" and task.get("stage") == "test-contract" and rules:
                contracts.contracts(where["path"], found["commit"], rules)
                packets.require_changed_tests(task, where['path'], found['commit'], rules)
            if (disposition == "complete" and task.get("stage") in schema.TESTED + ("test-contract",)
                    and where.get("test_policy")):
                if (checked or {}).get("commit") != found["commit"]:
                    raise ValueError("the packet's tests have not run on this commit; run cointos finish again")
                found.update(checked)
        elif lands == "merge" and disposition == "complete" and not git.contains(where["path"], task["branch"],
                                                                                 where["main_branch"]):
            raise ValueError(f"land your committed branch with `cointos merge` before finishing: {task['branch']} "
                             f"is {ahead(where, task)} commit(s) ahead of {where['main_branch']}")
    if task["kind"] == "garden" and disposition == "complete":
        health = garden_health(task)
        if health.get('deferred'):
            raise ValueError('selected leaves have pending canonical knowledge answers or policy: ' +
                             ', '.join(health['deferred']) + '; preserve the owner and finish blocked')
        found.update(health)
    if task.get("repair_origin") and disposition == "complete":
        found.update(repair_evidence(task))
    return found


def scout_evidence(task: dict, result) -> dict:
    """Validate a declared scout result against actual queue authority, never report prose."""
    if not isinstance(result, dict) or set(result) - {'kind', 'handoff', 'checked_projects', 'question'}:
        raise ValueError('complete steward receipts require scout_result with kind no_action, '
                         'manager_handoff or user_decision; use the typed finish tool')
    kind = result.get('kind')
    if kind == 'manager_handoff':
        handoff = result.get('handoff')
        record = queues.records().get(handoff) if isinstance(handoff, str) else None
        if not record or record.get('kind') != 'command' or record.get('proposed_by') != task['id']:
            raise ValueError('queue one checked manager command through cointos_queue, then supply its '
                             'PROJECT:ITEM as scout_result.handoff; a user alert is not a handoff')
        if record.get('held_by') or queues.status(record) not in ('queued', 'done'):
            raise ValueError('the manager handoff is blocked or held; repair it before completing')
        problems = queues.frontier_problems(record['project'], owner=task['id'])
        if problems:
            raise ValueError('repair the manager handoff before completing:\n' + '\n'.join(problems))
        return {'kind': kind, 'handoff': handoff}
    if kind == 'no_action':
        names = result.get('checked_projects')
        required = {p['name'] for p in tasks.enabled_projects()}
        if (not isinstance(names, list) or not all(isinstance(name, str) for name in names)
                or len(names) != len(set(names)) or set(names) != required):
            raise ValueError('no_action requires checked_projects naming every enabled project after '
                             'reading its whole remaining plan: ' + ', '.join(sorted(required)))
        review = task.get('scout_frontier_review') or {}
        frontier = scout_frontiers()
        if (review.get('run') != task['agent'] or review.get('frontier') != frontier
                or any('error' in project for project in frontier)):
            raise ValueError('call cointos_check_work without a draft to review every enabled project\'s '
                             'current accepted plan and queue before no_action; changed or unavailable '
                             'frontiers require a fresh review or a concrete handoff/blocker')
        return {'kind': kind, 'checked_projects': names}
    if kind == 'user_decision':
        question = result.get('question')
        if not isinstance(question, str) or not question.strip():
            raise ValueError('user_decision requires a specific new question needing personal authority; '
                             'managerial judgment about approved work needs manager_handoff')
        return {'kind': kind, 'question': question.strip()}
    raise ValueError('unknown scout_result.kind; choose no_action, manager_handoff or user_decision')


def scout_frontiers(read_plans=False) -> list[dict]:
    """Accepted Git evidence and queue facts, independent of editor branches and report prose."""
    result = []
    for project in sorted(tasks.enabled_projects(), key=lambda p: p['name']):
        rows = [r for r in queues.records().values() if r['project'] == project['name']]
        frontier = {'project': project['name'], 'main_branch': project['main_branch'],
                    'queue': [{'item': r['item'], 'kind': r['kind'], 'stage': r.get('stage'),
                               'version': r['version'], 'status': queues.status(r),
                               'held_by': r.get('held_by'), 'depends': list(r['depends'])}
                              for r in sorted(rows, key=lambda r: r['item'])
                              if not r.get('done') and not r.get('replaced_by')]}
        try:
            repo = Path(project['path'])
            tree = Path(project.get('tree', '.knowledge'))
            if tree.is_absolute():
                tree = tree.relative_to(repo)
            leaf = tree / 'what/is/the/plan.md'
            main = git.head(repo, project['main_branch'])
            frontier.update(main=main, plan_blob=git.run(repo, 'rev-parse', f'{main}:{leaf}').strip())
            if read_plans:
                frontier['plan'] = git.run(repo, 'show', f'{main}:{leaf}')
                accepted = [r for r in rows if isinstance(r.get('done'), dict)]
                frontier['recent_acceptances'] = [
                    {'item': r['item'], 'kind': r['kind'], 'stage': r.get('stage'), 'done': dict(r['done'])}
                    for r in sorted(accepted, key=lambda r: r['done'].get('at', 0))[-5:]]
        except (OSError, ValueError) as error:
            frontier['error'] = str(error)
        result.append(frontier)
    return result


def repair_evidence(task: dict) -> dict:
    """A repair receipt needs a changed origin or a real runnable handoff, not just prose."""
    origin = task["repair_origin"]
    source = L["tasks"].get(origin["task"])
    record = queues.records().get(origin["task"]) or queues.records().get((source or {}).get("record"))
    if source and source.get("record") and record is None:
        return {"repair_origin": origin, "withdrawn_record": source["record"]}
    if record and (source is None or record["version"] != origin["version"]
                   or record.get("done") or record.get("replaced_by")):
        if not record.get("done"):
            items = {item["item"]: item for item in queues.live(record["project"])}
            done = queues.landed(record["project"])
            readiness = queues.readiness(list(items.values()), done)
            names = list(record.get("replaced_by") or [record["item"]])
            seen = set()
            while names:
                name = names.pop()
                if name in seen or name in done:
                    continue
                seen.add(name)
                if name not in items:
                    raise ValueError("repair still has an invalid dependency graph: depends on unknown " + name)
                if items[name].get('held_by'):
                    raise ValueError(f"repair prerequisite {record['project']}:{name} is held")
                condition = readiness.get(name, "")
                status = queues.state(items[name])
                if status["status"] == "blocked" and not status["recoverable"]:
                    raise ValueError(f"repair prerequisite {record['project']}:{name} is terminally blocked: "
                                     + str(status["blocker"]))
                if condition.startswith(("depends on unknown ", "depends on a blocked item:")) or "cycle" in condition:
                    raise ValueError(f"repair dependency {record['project']}:{name} cannot continue: " + condition)
                names.extend(items[name].get("depends", []))
        return {"repair_origin": origin, "repaired_record": queues.key(record), "record_version": record["version"]}
    if source and (source.get("cancelled") or source.get("acceptance") or (source["status"] == "done"
                   and (source.get("receipt") or {}).get("disposition") == "complete")):
        return {"repair_origin": origin, "source_status": source["status"]}
    newer = tasks.newer_attempt(source) if source else None
    if newer and source["kind"] != "garden" and newer["status"] == "done" and (newer.get("receipt") or {}).get("disposition") == "complete":
        return {"repair_origin": origin, "superseding_task": newer["id"], "receipt": newer["receipt"]}
    if source and source.get("launch_failures", 0) == 0 and not source.get("admission_hold")             and source["status"] in ("waiting", "running", "review"):
        return {"repair_origin": origin, "source_status": source["status"]}
    if source and source["kind"] == "garden":
        health = garden_health(source)
        if not health["unresolved"]:
            return {"repair_origin": origin, **health}
    if record:
        for child in frontier.handoffs(record):
            if child.get('correction'):
                return {'repair_origin': origin, 'test_correction': queues.key(child)}
    if source and not source.get("record"):
        for proposed in queues.records().values():
            if proposed.get("proposed_by") != task["id"] or proposed.get("held_by"):
                continue
            current = queues.state(proposed)
            readiness = queues.readiness(queues.live(proposed["project"]), queues.landed(proposed["project"]))
            if current["status"] == "done" or (current["status"] == "queued" and readiness.get(proposed["item"]) == "ready"):
                return {"repair_origin": origin, "continuation": queues.key(proposed)}
    detail = (f"repair has no checked handback for {origin['task']}: revise/replace this blocked assignment, "
              "resolve its infrastructure hold, or establish a runnable continuation before finishing complete.")
    if record:
        detail += (" If existing queue items now own the work, use cointos_replace with their item names to "
                   "replace this origin. Changing another item's brief alone does not hand off this assignment.")
    raise ValueError(detail)


def uncommitted(worktree, limit: int = 12) -> str:
    lines = git.result(worktree, "status", "--short").stdout.splitlines()
    return "\n".join(lines[:limit] + ([f"... and {len(lines) - limit} more"] if len(lines) > limit else []))


def ahead(where: dict, task: dict) -> str:
    counted = git.result(where["path"], "rev-list", "--count", f"{where['main_branch']}..{task['branch']}")
    return counted.stdout.strip() if counted.returncode == 0 else "some"


def garden_health(task: dict) -> dict:
    """A finished batch's tree as main now has it; still-unresolved selected leaves alert the user
    instead of repeating the batch."""
    where = tasks.place(task)
    health = trees.health(where, CONFIG["timeouts"]["command_seconds"])
    L["trees"][where["name"]] = {**health, "checked_at": now()}
    selected = set(task['brief'].splitlines())
    deferred = sorted(selected & set(health.get('deferred', [])))
    unresolved = sorted(selected & (set(trees.pending(health)) | set(deferred)))
    if unresolved:
        alert(f"Gardener finished with unresolved leaves in {where['name']}: {', '.join(unresolved)}. "
              "Check its receipt before further work on that concern.")
    return {"brown": health["brown"], "yellow": health["yellow"], "unresolved": unresolved, 'deferred': deferred}


def _known(task: dict, run: str | None, disposition: str, summary: str) -> dict | None:
    """The same receipt again (a lost reply) returns the recorded one; a different one is refused."""
    receipt = task["receipt"]
    if receipt is None or receipt["run"] != run:
        return None
    if (receipt["disposition"], receipt["summary"]) != (disposition, summary):
        raise ValueError("this run already submitted a different completion receipt")
    return receipt


def submit(task_id: str, run: str | None, disposition: str, summary: str, checked: dict | None = None) -> dict:
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
    return _receive(task, run, disposition, summary, evidence(task, disposition, checked))


def _receive(task: dict, run: str | None, disposition: str, summary: str, found: dict) -> dict:
    """Record a checked receipt and apply its one transition."""
    receipt = {"run": run, "disposition": disposition, "summary": summary, "evidence": found, "at": now()}
    note = f"{disposition}: {summary}"[:CONFIG["result_chars"]]
    record = queues.records().get(task["record"]) if task["record"] else None
    if task["kind"] == "item" and disposition == "blocked":
        # The recovery controller owns brief repair and verifies the mismatch. An
        # integrator cannot repair it, so spending a review run first adds no
        # authority or artifact to this recovery path.
        _settle(task, "failed", note, receipt=receipt, result=summary)
    elif schema.KINDS[task["kind"]]["lands"] == "review":
        _settle(task, "review", note, receipt=receipt, result=summary)
    elif task["kind"] == "integrate" and disposition == "blocked":
        _settle(task, "failed", note, receipt=receipt, result=summary)
        worker = L["tasks"][task["worker"]]
        if worker["status"] == "review":
            _settle(worker, "failed", "could not be integrated: " + summary)
    else:
        _settle(task, "done", note, receipt=receipt, result=summary)
        if task["kind"] == "breakdown" and disposition == "complete" and record and record["version"] == task["record_version"]:
            queues.finish(record, by=task["id"])
    if disposition == "blocked" and task["role"] not in ("worker", "integrator"):
        alert(f"{task['id']} blocked: {summary}")
    decision = found.get('scout_result') or {}
    if decision.get('kind') == 'user_decision':
        from cointos.state import enqueue_message
        enqueue_message(task['id'], 'user', decision['question'])
    log("receipt", task=task["id"], run=run, disposition=disposition)
    return receipt


def landed(integration: dict | None, run: str | None, worker: dict, acceptance: dict) -> None:
    """A verified landing or incorporation settles the worker and is its integrator's receipt."""
    live = integration is not None and not tasks.settled(integration)
    if live:
        require_run(integration, run)
    if worker["status"] != "review":
        raise ValueError(f"{worker['id']} is not in review")
    if worker["receipt"]["evidence"]["commit"] != acceptance["worker_commit"]:
        raise ValueError("the landed worker commit is not the one its receipt submitted")
    accept_worker(worker, acceptance)
    if live:
        _receive(integration, run, "complete", f"{worker['item']} accepted at {acceptance['commit']}",
                 dict(acceptance))


def accept_worker(worker: dict, acceptance: dict) -> None:
    """Persist the same acceptance evidence for normal and recovered publication."""
    _settle(worker, "done", "accepted via " + acceptance["via"], review=None, acceptance=acceptance)
    if worker["record"] in queues.records():
        record = queues.records()[worker["record"]]
        queues.finish(record, commit=acceptance["commit"], via=acceptance["via"],
                      **({'gate': acceptance['gate']} if 'gate' in acceptance else {}))
        activate_correction(record, worker['id'])


def activate_correction(record: dict, by: str) -> None:
    for key in packets.activate(record):
        revised = queues.records()[key]
        revised['revised_by'] = by
        refresh_assignment(key, by, 'independently reviewed test-contract correction', revised)


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
    uncharged. A task's hold ends on its own revision, release or settlement. User holds
    require explicit release and survive revisions."""
    record = queues.records()[key]
    if record.get("done"):
        raise ValueError(f"{key} is already accepted; queue new work instead")
    if record["held_by"] not in (None, by):
        raise ValueError(f"{key} is already held by {record['held_by']}")
    record["held_by"] = by
    for task in list(L["tasks"].values()):
        if (task["id"] != by and task["status"] == "running" and
                (task.get("record") == key or task.get("worker") == key
                 or (task.get('repair_origin') or {}).get('task') == key)):
            stop(task["agent"], f"held by {by}", requeue=True, charge=False)
    log("item held", item=key, by=by)


def unhold(key: str, by: str) -> None:
    record = queues.records()[key]
    if record["held_by"] not in (None, by) and by != "user":
        raise ValueError(f"{key} is held by {record['held_by']}")
    record["held_by"] = None
    log("item released", item=key, by=by)


def revise(key: str, by: str, reason: str, brief: str, stage=None, reasoning_effort=None, budget=None, **metadata) -> None:
    """Change what a queue item asks for. Its task starts afresh on the revised brief: a waiting or
    running one waits for a fresh session, a reviewed one goes back to its worker. The branch keeps
    earlier work, which the revised assignment is told to keep only where it still fits."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("say why the item is revised")
    record = queues.records()[key]
    task = L["tasks"].get(key)
    if record.get("done") or (task and task.get("acceptance")):
        raise ValueError(f"{key} is already accepted; queue new work instead")
    if record.get("replaced_by"):
        raise ValueError(f"{key} was superseded by {', '.join(record['replaced_by'])}")
    if task and task["status"] == "review" and any(
            t["kind"] == "integrate" and t["worker"] == key and t["status"] == "running" for t in L["tasks"].values()):
        raise ValueError(f"{key} is being integrated now; hold it and revise after the integration ends")
    if by != "user" and record["kind"] == "queued" and metadata.get("summary") is None:
        queues.require_summary(brief)
    if not queues.revise(record, brief, stage, reasoning_effort, budget,
                         preserve_packets=by != "user", **metadata):
        return
    if record["held_by"] == by and by != "user":
        record["held_by"] = None
    record["revised_by"] = by
    refresh_assignment(key, by, reason, record)
    log("item revised", item=key, by=by, reason=reason.strip())


def refresh_assignment(key: str, by: str, reason: str, record: dict) -> None:
    """Refresh an existing task from its revised record; preserve branches and explicit holds."""
    for related in list(L['tasks'].values()):
        if tasks.active(related) and frontier.obsolete(related):
            cancel_task(related, by, 'origin assignment revised by another owner')
    task = L["tasks"].get(key)
    if task and task["status"] in ("waiting", "running", "review", "failed"):
        if task["status"] == "running":
            stop(task["agent"], f"revised by {by}", requeue=True, charge=False)
        task.update(brief=record["brief"], stage=record["stage"], record_version=record["version"],
                    reasoning_effort=schema.default_effort(CONFIG, {**task, "reasoning_effort": record["reasoning_effort"]}),
                    budget=schema.budget(CONFIG, record.get("budget"), role=task["role"]), session=None, runs=0, fresh_retries=0,
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


def replace(record: dict, replacements: list[str], by: str, reason: str) -> None:
    """Repoint live dependencies and their assignments as one validated graph change."""
    def preflight(changed):
        for key in changed:
            task = L["tasks"].get(key)
            if task and (task.get("validating") or task.get("acceptance")):
                raise ValueError(f"{key} is being validated or already accepted; no records changed")
            if any(t["kind"] == "integrate" and t["worker"] == key
                   and t["status"] == "running" for t in L["tasks"].values()):
                raise ValueError(f"{key} is being integrated; no records changed")
    changed = queues.replace(record, replacements, reason, preflight=preflight)
    for key in changed:
        queues.records()[key]["revised_by"] = by
        refresh_assignment(key, by, reason, queues.records()[key])


def replacement_handoff(task: dict, run: str, record: dict, children: list[str]) -> dict:
    """Check the complete proposed handoff before repointing work and receipting its owner.

    The API holds LOCK and persists both facts together. The preview has no run, task,
    snapshot or journal effects; all graph/artifact/active-review refusals precede changes.
    """
    require_run(task, run)
    reason = 'replaced by ' + task['id']
    proposed, _ = queues.replacement(record, children, reason)
    current = L['queue']
    try:
        L['queue'] = proposed
        found = evidence(task, 'complete')
    finally:
        L['queue'] = current
    replace(record, children, task['id'], reason)
    task['replacements'] = list(record['replaced_by'])
    found['replacement'] = list(children)
    summary = f"Handed {queues.key(record)} to " + ', '.join(f"{record['project']}:{n}" for n in record['replaced_by'])
    return _receive(task, run, 'complete', summary, found)


# ---------------------------------------------------------------- runs

def require_start(task: dict, agent_id: str | None = None) -> None:
    """Validate admission before allocating execution or changing ownership."""
    if task.get("admission_hold"):
        raise ValueError(f"task {task['id']} is held; explicitly resume it first")
    if task["status"] != "waiting" or any(a["task"] == task["id"] for a in L["agents"].values()):
        raise ValueError(f"task {task['id']} already has a run")
    if agent_id is not None and (agent_id in L["agents"] or agent_id in L["exiting"]):
        raise ValueError(f"run {agent_id} already has an owner or is still exiting")


def start(task: dict, agent_id: str) -> None:
    require_start(task, agent_id)
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


def cancel(items: list[str], by: str, reason: str) -> list[str]:
    """Withdraw unaccepted queue items for good: end every run and task working on them (their
    integrations too), drop their records and retire their branches. Controllers lose queue
    authority and can close with checked withdrawal evidence. Live
    work that depends on an item must be cancelled with it or revised first."""
    current = queues.records()
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("say why the work is cancelled")
    for key in items:
        if key not in current:
            raise ValueError(f"unknown queue item {key!r}; name it PROJECT:ITEM")
        if current[key].get("done"):
            raise ValueError(f"{key} is already accepted; it cannot be cancelled")
    cancelled = {(current[k]["project"], current[k]["item"]) for k in items}
    dependents = sorted(k for k, r in current.items() if k not in items and not r.get("done")
                        and not r.get("replaced_by") and any((r["project"], d) in cancelled for d in r["depends"]))
    if dependents:
        raise ValueError(f"{', '.join(dependents)} still depend on it; cancel them too or revise their Depends on")
    note = f"cancelled by {by}: {reason.strip()}"
    for key in items:
        affected = [t for t in L["tasks"].values() if not tasks.settled(t)
                    and (t["id"] == key or t.get("record") == key or (t["kind"] == "integrate" and t.get("worker") == key))]
        for agent in [a for a in L["agents"].values() if a["task"] in {t["id"] for t in affected}]:
            release(agent["id"], note)
            threading.Thread(target=opencode.stop, args=(agent["id"],), daemon=True).start()
        for task in affected:
            task.pop("admission_hold", None)
            snapshots.forget_owner(task["id"])
            task.update(status="failed", agent=None, note=note, cancelled=reason.strip(), updated_at=now())
            task.pop("retired", None)
        if key in L["tasks"] and L["tasks"][key]["status"] == "failed":
            L["tasks"][key]["cancelled"] = reason.strip()
        del current[key]
        log("queue item cancelled", item=key, by=by, reason=reason.strip())
    for task in L["tasks"].values():
        if task.get("cancelled") and task["status"] == "failed":
            retire(task)
    return list(items)


def cancel_task(task: dict, by: str, reason: str) -> None:
    """End one task without withdrawing its queue record; the caller owns queue disposition."""
    note = f"cancelled by {by}: {reason}"
    for agent in [a for a in L["agents"].values() if a["task"] == task["id"]]:
        release(agent["id"], note)
        threading.Thread(target=opencode.stop, args=(agent["id"],), daemon=True).start()
    task.pop("admission_hold", None)
    snapshots.forget_owner(task["id"])
    task.update(status="failed", agent=None, note=note, cancelled=reason, updated_at=now())
    log("task cancelled", task=task["id"], by=by, reason=reason)


def kill(agent_id: str) -> dict:
    """the user ends a run and withholds further admission until explicitly released."""
    task = L["tasks"][L["agents"][agent_id]["task"]]
    if owns(task, agent_id):
        task["admission_hold"] = "paused by the user"
    stop(agent_id, "paused by the user", requeue=True, charge=False)
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
    """A run spent its budget. That ends the run, never the assignment: its work stays on the
    branch and files, and the task continues in a new session (with a bounded evidence packet)
    whose first job is to establish where that work stands. Only that session can submit what
    the last one finished, or report what remains as a blocker. After the role's fresh retry limit
    such sessions the task fails; a failed assignment reaches its recovery controller with the packet."""
    task = L["tasks"][L["agents"][agent_id]["task"]]
    fresh = task.get("fresh_retries", 0)
    if fresh >= schema.fresh_limit(CONFIG, task):
        task.update(recovery_note=reason, recovery_context=packet)  # the controller's preserved evidence
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
        role=(task or {}).get('role', agent.get('role', 'unknown')),
        generation_seconds=round(agent.get('generation_seconds', 0), 3),
        generation_tokens=agent.get('generation_tokens', 0),
        speculation=agent.get('speculation'),
        seconds=round(now() - agent["started_at"]))


def clean_up(task: dict) -> None:
    """Retire a settled task's worktree and branch (see `retire`), and an accepted worker's with its
    integrator's."""
    retire(task)
    if task["kind"] == "integrate" and task["status"] == "done":
        retire(L["tasks"][task["worker"]])


def revivable(task: dict) -> bool:
    """Whether `cointos revise` could still restart this task on its branch: a failed item whose
    queue record is live, unaccepted and not replaced."""
    record = queues.records().get(task["record"]) if task["record"] else None
    return task["status"] == "failed" and record is not None and queues.status(record) == "blocked"


def retire(task: dict) -> bool:
    """Leave nothing behind for a settled task with no run: remove its checkout, delete its branch
    once main contains it, and archive a dead unlanded branch under `git.ARCHIVE`. A revivable
    task keeps its branch; a checkout with uncommitted work is kept for inspection.
    Returns whether the task was considered (it is then marked `retired`)."""
    if (task["branch"] is None or not tasks.settled(task) or task.get("retired")
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
    if status in schema.SETTLED:
        for record in queues.records().values():  # a settled task no longer decides about anything it held
            if record["held_by"] == task["id"]:
                record["held_by"] = None


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
        stopped = False
        with LOCK:
            if agent_id in L["agents"]:
                stop(agent_id, "completion receipt delivered", requeue=False, charge=False)
                stopped = True
        if stopped:
            save()

    threading.Thread(target=retire, daemon=True).start()


def refuse_dispatch(task: dict, reason: str) -> None:
    """A new task whose brief cannot be carried out as written fails before any run: its record
    goes to its recovery controller like any other failed item."""
    _settle(task, "failed", reason)


def recover_landings() -> int:
    """Finish published, verified intents after process loss; no model or worktree needed.

    Publication is the acceptance point. The intent pins the validated receipt and
    assignment epoch; merely finding arbitrary code on main is never sufficient.
    Call under LOCK before admission or user controls; the caller persists the
    resulting ledger outside LOCK before acknowledging it. Do not acquire the repository
    lock here: publishers acquire that lock before LOCK.
    """
    recovered = 0
    for integration in list(L["tasks"].values()):
        intent = integration.get("landing")
        if (not intent or integration["kind"] != "integrate" or not tasks.pending(integration)
                or not {"commit", "worker_commit", "receipt_run", "record_version", "run"} <= intent.keys()):
            continue
        worker = L["tasks"].get(integration["worker"])
        receipt = (worker or {}).get("receipt") or {}
        if (not worker or worker["status"] != "review" or receipt.get("disposition") != "complete"
                or intent.get("receipt_run") != receipt.get("run")
                or intent.get("record_version") != worker.get("record_version")
                or intent.get("worker_commit") != receipt.get("evidence", {}).get("commit")
                or "run" not in intent):
            continue
        where = tasks.place(worker)
        record = queues.records().get(worker.get("record"))
        if record and (record["version"] != intent["record_version"] or record.get("done")):
            continue
        if not git.contains(where["path"], intent["commit"], where["main_branch"]):
            continue
        acceptance = {"commit": intent["commit"], "worker_commit": intent["worker_commit"],
                      "via": "landing", "stage": worker["stage"],
                      **({'gate': intent['gate']} if 'gate' in intent else {})}
        accept_worker(worker, acceptance)
        _receive(integration, intent["run"], "complete",
                 f"{worker['item']} accepted at {intent['commit']}", dict(acceptance))
        recovered += 1
        log("landing recovered", task=integration["id"], **acceptance)
    return recovered


def reconcile() -> None:
    """Retire caches whose conversations have ended and settled work's worktrees."""
    recover_landings()
    for task in list(L["tasks"].values()):
        if tasks.active(task) and frontier.obsolete(task):
            cancel_task(task, 'cointos', 'origin assignment revised by another owner')
        if task.get("repair_origin") and task["status"] == "waiting" and not task["runs"]:
            origin = task["repair_origin"]
            source = L["tasks"].get(origin["task"])
            record = queues.records().get(origin["task"]) or queues.records().get((source or {}).get("record"))
            obsolete = bool(record is not None and (record["version"] != origin["version"]
                        or record.get("done") or record.get("replaced_by")))
            obsolete |= (source is None and record is None) or bool((source or {}).get("cancelled"))
            obsolete |= bool(source and tasks.newer_attempt(source))
            if obsolete:
                cancel_task(task, "cointos", "repair origin progressed or was withdrawn before admission")
    snapshots.forget_orphans()
    swept = 0
    for task in list(L["tasks"].values()):  # retire settled work a bounded few at a time under LOCK
        if swept >= CONFIG["recovery"]["retire_per_tick"]:  # git runs under LOCK, so a few per pass
            break
        try:
            swept += retire(task)
        except ValueError as error:
            task["retired"] = f"failed: {error}"
            log("retire failed", task=task["id"], error=str(error))
