"""The control API: every action the CLI, Coin, agents and the dashboard can ask of the daemon.

`dispatch(action, body)` runs one action. Each is a small function over the domain modules.
Ordinary actions mutate under LOCK and save after releasing it; landing actions validate outside LOCK
(tests can take minutes) and take it only to settle. Actions that change queue records also
republish the readable queue projection.
"""
from __future__ import annotations

import re
from copy import deepcopy

from cointos import contracts, frontier, git, landing, lifecycle, packets, projects, queues, replacement, schema, settings, snapshots, tasks, wakeups
from cointos.config import ROOT
from cointos.state import ACTIVE, CONFIG, LOCK, STOPPING, L, alert, log, now, save


class ApiError(ValueError):
    pass


def caller(body) -> tuple[dict | None, str | None]:
    """The agent run a request comes from, as (its task, its run id), or (None, None) for the
    user. The client names it in `caller` from the run's environment; lifecycle functions and
    `running` decide whether that run may do what it asks."""
    identity = body.get("caller") or {}
    if not identity:
        return None, None
    task = L["tasks"].get(identity.get("task"))
    if task is None:
        raise ApiError(f"unknown calling task {identity.get('task')!r}")
    return task, identity.get("run")


def running(body) -> dict | None:
    """The running task a request is made as, if any; it must be that task's current run."""
    task, run = caller(body)
    if task is not None and not lifecycle.owns(task, run):
        raise ApiError(f"{task['id']} is not running under {run!r}")
    return task


def dispatch(action: str, body: dict):
    # Already-published work must settle before a later hold, cancellation or
    # revision can reinterpret it as unaccepted after a daemon replacement.
    with LOCK:
        recovered = lifecycle.recover_landings()
    if recovered:
        save()
    if action in LANDINGS:
        return landing_action(action, body)
    if action == "finish":
        return finishing(body)
    if action == "check-work":
        return check_work(body)
    if action not in ACTIONS:
        raise ApiError(f"unknown action {action!r}")
    with LOCK:
        result = deepcopy(ACTIONS[action](body))
    save()
    if action in PUBLISHES:
        queues.publish()
    return result


def landing_action(action: str, body: dict):
    with replacement.lease(ROOT, shared=True) as acquired:
        if not acquired:
            raise ApiError('runtime replacement in progress; retry landing after replacement')
        return _landing_action(action, body)


def _landing_action(action: str, body: dict):
    """Mark the tasks being validated, so silence and budget checks leave them alone, and so a
    daemon replacement waits for the validation to finish."""
    with LOCK:
        if STOPPING.is_set():
            raise ApiError("daemon draining; retry landing after replacement")
        integration, run = caller(body)
        target = integration if action == "land" else L["tasks"][body["task"]]
        validating = [target["id"]] + ([target["worker"]] if action == "land" else
                                       [t["id"] for t in [landing.integrating(target)] if t])
        if any(L["tasks"][tid].get("validating") for tid in validating):
            raise ApiError("this landing is already being validated")
        for tid in validating:
            L["tasks"][tid]["validating"] = True
        ACTIVE["landings"] += 1
    try:
        if action == "land":
            result = landing.land(target["id"], body["commit"], run)
        else:
            result = landing.incorporate(target["id"], body["commit"], body["worker_commit"], run)
        queues.publish()
        return result
    finally:
        with LOCK:
            ACTIVE["landings"] -= 1
            for tid in validating:
                L["tasks"][tid].pop("validating", None)
            for agent in L["agents"].values():
                if agent["task"] in validating:
                    agent["last_activity"] = now()


LANDINGS = ("land", "incorporate")


def finishing(body):
    with replacement.lease(ROOT, shared=True) as acquired:
        if not acquired:
            raise ApiError('runtime replacement in progress; retry completion after replacement')
        return _finishing(body)


def _finishing(body):
    """`cointos finish`. An implementer's complete receipt first runs its packet's hidden tests,
    outside the ledger lock; a failure goes straight back to the still-running implementer with
    the failing tests revealed. A test writer's complete receipt first finds out whether its
    tests already pass on main."""
    with LOCK:
        task, run = caller(body)
        if task is None:
            raise ApiError("finish is an agent run's own receipt")
        previous = task.get('submission_failure') or {}
        receipt = task.get('receipt') or {}
        replay = (body.get('outcome') == 'complete' and receipt.get('disposition') == 'blocked'
                and receipt.get('run') == run
                and previous.get('blocked_request') == {'run': run, 'detail': body.get('detail', '')})
        replayed = receipt if replay else None
        tested = (not replay and task["kind"] == "item"
                  and task.get("stage") in schema.TESTED + ("test-contract",)
                  and body.get("outcome") == "complete" and lifecycle.owns(task, run)
                  and not task.get("receipt") and git.clean(task["worktree"]))
        if tested:
            if STOPPING.is_set():
                raise ApiError("daemon draining; finish again after replacement")
            if task.get("validating"):
                raise ApiError("this packet's tests are already running")
            where = tasks.place(task)
            rules, commit = where.get("test_policy"), git.head(task["worktree"])
            contracts.worker_artifact(where['path'], task, commit)
            if rules:
                packets.require_changed_tests(task, where['path'], commit, rules)
            main = git.head(where["path"], where["main_branch"])
            tests = landing.tests_of(task)
            bundled = list(task.get("bundled", []))
            submission = {'tree': git.run(where['path'], 'rev-parse', commit + '^{tree}').strip(),
                          'main': main, 'tests': tests, 'bundled': bundled, 'rules': deepcopy(rules),
                          'stage': task['stage'], 'version': task.get('record_version')}
            task["validating"] = True
            ACTIVE["landings"] += 1

    if replay:
        save()
        queues.publish()
        return {'ok': True, 'receipt': replayed}

    def settle(checked):
        with LOCK:
            receipt = lifecycle.submit(task["id"], run, body.get("outcome"), body.get("detail", ""), checked)
            if tested:
                task.pop('submission_failure', None)
        save()
        queues.publish()
        return {"ok": True, "receipt": receipt}

    if tested:
        try:
            checked = {"commit": commit, "tests": tests}
            if rules:
                contracts.stage_history(where['path'], task, main, rules)
                if task['stage'] in schema.TESTED:
                    landing.require_tests(tests)
            if rules and task["stage"] == "test-contract":
                checked = {"commit": commit, "passing": contracts.passing(
                    where["path"], main, [commit], rules, CONFIG["timeouts"]["validation_seconds"],
                    CONFIG["memory"]["agent_limit_gb"])}
            elif rules:
                checked.update(contracts.packet_check(where["path"], main, commit, tests, bundled, rules,
                                                      CONFIG["timeouts"]["validation_seconds"],
                                                      CONFIG["memory"]["agent_limit_gb"]))
        except ValueError as error:
            category = 'execution' if isinstance(error, contracts.ExecutionError) else 'product'
            log('validation execution failed' if category == 'execution' else 'packet tests failed',
                task=task['id'], commit=commit, reason=str(error)[:500])
            changed, blocked = False, None
            with LOCK:
                # A revision, hold, newer candidate or changed main revokes this attempt.
                if (lifecycle.owns(task, run) and task.get('record_version') == submission['version']
                        and task.get('stage') == submission['stage'] and landing.tests_of(task) == tests
                        and task.get('bundled', []) == bundled
                        and tasks.place(task).get('test_policy') == submission['rules']
                        and git.clean(task['worktree']) and git.head(task['worktree']) == commit
                        and git.head(where['path'], where['main_branch']) == main):
                    failure = task.get('submission_failure') or {}
                    same = failure.get('inputs') == submission and failure.get('category', 'product') == category
                    attempts = failure.get('attempts', 0) + 1 if same else 1
                    task['submission_failure'] = {'inputs': submission, 'attempts': attempts,
                                                  'category': category, 'error': str(error)}
                    changed = True
                    if attempts >= 3:
                        reason = (f'Validation infrastructure failed {attempts} unchanged submissions; no assertion evidence: '
                                  if category == 'execution' else f'Unchanged candidate refused {attempts} submissions: ')
                        receipt = lifecycle.submit(task['id'], run, 'blocked',
                                                   reason + str(error))
                        task['submission_failure']['blocked_request'] = {'run': run, 'detail': body.get('detail', '')}
                        blocked = receipt
            if changed:
                save()
            if blocked is not None:
                queues.publish()
                return {'ok': True, 'receipt': blocked}
            raise ApiError(str(error)) from error
        else:
            # Keep both the busy counter and replacement lease until the checked
            # receipt and queue publication are durable, not just until tests end.
            return settle(checked)
        finally:
            with LOCK:
                ACTIVE["landings"] -= 1
                task.pop("validating", None)
                for agent in L["agents"].values():
                    if agent["task"] == task["id"]:
                        agent["last_activity"] = now()
    return settle({'scout_result': body.get('scout_result')})


# ---------------------------------------------------------------- agents' own actions

def receipt_delivered(body):
    task, run = caller(body)
    lifecycle.receipt_delivered(task["id"], run)
    return {"ok": True}


def send_back(body):
    task, run = caller(body)
    lifecycle.returned(task, run, body["notes"])
    return {"ok": True}


def replace(body):
    """Atomically hand recovery to existing children and complete its controller."""
    task, run = caller(body)
    if task is None or not task.get('repair_origin'):
        raise ApiError('only a running recovery controller replaces its origin')
    receipt = task.get('receipt')
    if receipt and receipt['run'] == run:
        if (receipt['disposition'] != 'complete' or 'replacement' not in receipt['evidence']
                or receipt['evidence']['replacement'] != body.get('children')):
            raise ApiError('this run already submitted a different completion receipt')
        return {'ok': True, 'receipt': receipt}
    running(body)
    source = queues.records().get(task['repair_origin']['task'])
    if source is None or not controls_project(task, source['project']):
        raise ApiError('the recovery origin is no longer controllable')
    receipt = lifecycle.replacement_handoff(task, run, source, body.get('children'))
    return {'ok': True, 'receipt': receipt}


# Who may propose queue work: roles, whether they are bound to their own project, and which
# queue kinds they may submit (None: any).
PROPOSERS = {"manager": (True, None), "integrator": (True, ("command",)),
             "steward": (False, ("command",)), "test-auditor": (False, ("command",)), "operator": (True, None)}


def queue(body):
    project = tasks.project_named(body.get("project", ""))
    kind = body.get("kind", "queued")
    by = running(body)
    if by is not None:
        own_project, kinds = PROPOSERS.get(by["role"], (True, ()))
        if (kinds is not None and kind not in kinds) or (own_project and by["place"] != project["name"]
                and not (by["role"] == "operator" and controls_project(by, project["name"]))):
            raise ApiError("queue proposer must be an unfinished same-project manager/integrator, "
                           "or a scout/auditor proposing a command")
        if kind in ("queued", "urgent") and body.get("summary") is None:
            queues.require_summary(body["brief"])
    if by is not None and by["role"] == "operator" and not controls_project(by, project["name"]):
        raise ApiError("queue repair requires a control-enabled Operator in its assigned project")
    item = queues.add(project, kind, body["name"], body["brief"], body.get("stage"),
                      body.get("reasoning_effort"), body.get("budget"),
                      dependency_ids=body.get("dependencies"), summary=body.get("summary"), reliances=body.get("relies_on"))
    if by is not None:
        queues.records()[f"{project['name']}:{item}"].setdefault("proposed_by", by["id"])
    log("queued", project=project["name"], item=item)
    return {"ok": True, "item": item}


def correct_tests(body):
    """Independent correction is a terminal checked handoff for its recovery owner."""
    by, run = caller(body)
    request = {key: body.get(key) for key in ('project', 'packet', 'name', 'brief', 'summary', 'relies_on', 'reason')}
    previous = (by or {}).get('receipt') or {}
    if previous.get('run') == run and by is not None and previous:
        known = previous.get('evidence', {}).get('correction_handoff')
        if previous['disposition'] != 'complete' or not known or known['request'] != request:
            raise ApiError('this run already submitted a different completion receipt')
        return {'ok': True, 'item': known['item'], 'correction': known['correction'], 'receipt': previous}
    project = tasks.project_named(body.get('project', ''))
    running(body)
    if by is not None and not controls_project(by, project['name']):
        raise ApiError('test-contract correction requires the owning manager or recovery controller')
    before = deepcopy(L['queue']) if by and by.get('repair_origin') else None
    try:
        record = packets.propose(project, body['packet'], body['name'], body['brief'],
                                 by=by['id'] if by else 'user', summary=body['summary'],
                                 reliances=body['relies_on'], reason=body['reason'])
        result = {'ok': True, 'item': queues.key(record), 'correction': record['correction']}
        if before is not None:
            receipt = lifecycle.submit(by['id'], run, 'complete',
                                       f"Handed test-contract repair to {queues.key(record)}: {body['reason']}")
            receipt['evidence']['correction_handoff'] = {'request': deepcopy(request),
                                                       'item': result['item'], 'correction': deepcopy(record['correction'])}
            result['receipt'] = receipt
        else:
            result['next_action'] = ('An independent test worker and reviewer own the correction. '
                                     'Acceptance updates dependent assignments automatically; their code is preserved.')
    except Exception:
        if before is not None:
            L['queue'] = before
        raise
    log('test correction requested', item=queues.key(record), correction=record['correction'])
    return result


def handoff(body):
    """Publish a manager's runnable children and its checked handoff in one transaction."""
    task, run = caller(body)
    if task is None or task['role'] != 'manager':
        raise ApiError('handoff is a manager completion with runnable child assignments')
    previous = task.get('receipt') or {}
    if previous.get('run') == run and previous.get('disposition') == 'complete':
        if (previous.get('summary') != body.get('summary')
                or previous.get('evidence', {}).get('handoff') != body.get('items')):
            raise ApiError('this run already submitted a different handoff')
        return {'ok': True, 'receipt': previous}
    running(body)
    items = body.get('items')
    if not isinstance(items, list) or not items or any(not isinstance(item, dict) for item in items):
        raise ApiError('handoff needs a nonempty array of child assignments')
    project = tasks.project_named(task['place'])
    before = deepcopy(L['queue'])
    try:
        created = []
        for item in items:
            if item.get('summary') is None or not isinstance(item.get('dependencies'), list):
                raise ApiError('every handoff child needs summary and dependencies')
            name = queues.add(project, item.get('kind', 'queued'), item.get('name', ''), item.get('brief', ''),
                              item.get('stage'), item.get('reasoning_effort'), item.get('budget'),
                              dependency_ids=item['dependencies'], summary=item['summary'],
                              reliances=item.get('relies_on'))
            record = queues.records()[f"{project['name']}:{name}"]
            if record.get('proposed_by') not in (None, task['id']):
                raise ApiError('handoff child already belongs to another proposer')
            record['proposed_by'] = task['id']
            created.append(queues.key(record))
        receipt = lifecycle.submit(task['id'], run, 'complete', body.get('summary', ''))
        receipt['evidence']['handoff'] = deepcopy(items)
    except Exception:
        L['queue'] = before
        raise
    log('handoff accepted', task=task['id'], children=created)
    return {'ok': True, 'children': created, 'receipt': receipt}


def check_work(body):
    """Preflight without mutation, except a successful scout frontier review."""
    with LOCK:
        result, persist = _check_work(body)
        result = deepcopy(result)
    if persist:
        save()
    return result


def _check_work(body):
    """Return the checked result and whether its frontier review needs persistence."""
    by = running(body)
    if by and by['role'] in ('steward', 'test-auditor') and 'brief' not in body:
        if body.get('project'):
            tasks.project_named(body['project'])  # refuse a typo instead of silently ignoring it
        frontiers = lifecycle.scout_frontiers(read_plans=True)
        problems = [p['project'] + ': ' + p['error'] for p in frontiers if 'error' in p]
        if not problems:
            by['scout_frontier_review'] = {'run': by['agent'],
                'frontier': [{k: v for k, v in p.items() if k not in ('plan', 'recent_acceptances')}
                             for p in frontiers]}
        return {'ok': not problems, 'problems': problems, 'projects': frontiers,
                'completion_receipt_required': True,
                'next_action': 'Read every remaining accepted plan and compare it with actual queue/acceptance facts. '
                               'Manager reports, hidden test acceptance and passing old prototype commands do not '
                               'establish implementation of the promised new path. Queue one checked manager '
                               'handoff for approved unowned work. no_action requires this frontier to remain current.'}, not problems
    project = tasks.project_named(body.get("project") or (by or {}).get("place", ""))
    if "brief" not in body:
        problems = queues.frontier_problems(project["name"], owner=by["id"] if by else None)
        if by and by['role'] == 'worker':
            try:
                contracts.worker_artifact(project['path'], by, git.head(by['worktree']))
            except ValueError as error:
                problems.append(str(error))
        if by and by["kind"] == "item" and project.get("test_policy"):
            try:
                contracts.stage_history(project["path"], by,
                    git.head(project["path"], project["main_branch"]), project["test_policy"])
            except ValueError as error:
                problems.append(str(error))
            if by['stage'] in schema.TESTED:
                try:
                    landing.tests_of(by, required=True)
                except ValueError as error:
                    problems.append(str(error))
        if by and by['kind'] == 'integrate' and project.get('test_policy'):
            worker = L['tasks'].get(by['worker'])
            if worker and (worker.get('receipt') or {}).get('disposition') == 'complete':
                parent = git.head(project['path'], project['main_branch'])
                rules = project['test_policy']
                try:
                    landing.check_candidate(by['worktree'], worker, parent, None, rules)
                except ValueError as error:
                    problems.append(str(error))
        result = {"problems": problems}
        if by:
            result['binding_tests'] = frontier.inspect(by['id'], L)['binding_tests']
        if by and by['role'] == 'worker' and project.get('test_policy'):
            paths = contracts.working_stage_changes(by['worktree'], by['stage'], project['test_policy'])
            result['out_of_scope_paths'] = paths
            if paths:
                problems.append('uncommitted files outside the assigned ' + by['stage'] + ' stage: ' +
                                ', '.join(paths) + '; preserve diagnostic work separately and restore these '
                                'files before committing the scoped artifact')
        if by and schema.KINDS[by['kind']]['lands'] == 'merge':
            try:
                where = tasks.place(by)
                contracts.maintenance_history(where, by, git.head(where['path'], where['main_branch']),
                                              include_worktree=True)
            except ValueError as error:
                problems.append(str(error))
        if by and by['role'] in ('worker', 'manager', 'integrator'):
            result['worktree_clean'] = git.clean(by['worktree'])
            if not result['worktree_clean']:
                status = git.result(by['worktree'], 'status', '--short')
                result['worktree_status'] = (status.stdout or status.stderr)[:4000]
            if by['role'] != 'integrator' and not result['worktree_clean']:
                problems.append('the assigned worktree has uncommitted or untracked changes; inspect and preserve them, then commit the completed scoped artifact before submitting it')
            result.update(task=by['id'], completion_receipt_required=True,
                          worktree=by['worktree'], branch=by['branch'], main_branch=project['main_branch'],
                          next_action='Fix the reported problems and continue, or submit the role\'s checked completion/blocked receipt. A green preflight is not semantic acceptance; final prose cannot settle this task.')
        return {"ok": not problems, **result}, False
    try:
        return queues.preview(project, body.get("kind", "queued"), body.get("name", ""), body["brief"],
                              body.get("stage"), body.get("reasoning_effort"), body.get("budget"),
                              dependency_ids=body.get("dependencies"), summary=body.get("summary"),
                              reliances=body.get("relies_on")), False
    except ValueError as error:
        return {"ok": False, "problems": [str(error)]}, False


def queue_key(name: str) -> str | None:
    """The queue record a control names. Every control takes a task id; an item task's id is
    its queue key, and any other task reaches its record through its `record` link."""
    current = queues.records()
    if name in current:
        return name
    task = L["tasks"].get(name)
    if task:
        key = task.get('record') or (task.get('repair_origin') or {}).get('task')
        return key if key in current else None
    return None


def controls_project(task: dict, project: str) -> bool:
    """Queue repair authority preserves project scope and the user's explicit holds."""
    if task["role"] == "manager":
        return task["place"] == project
    if task["role"] != "operator" or "control" not in task.get("abilities", []):
        return False
    if task["place"] not in (project, "system"):
        return False
    if origin := task.get("repair_origin"):
        source = L["tasks"].get(origin["task"])
        record = queues.records().get(origin["task"]) or queues.records().get((source or {}).get("record"))
        if (source is None and record is None) or (source and (source.get("cancelled")
                or (source.get("record") and record is None))):
            return False
        if record and record.get("held_by") not in (None, task["id"]):
            return False
        if source and source.get("admission_hold") not in (None, "repeated infrastructure launch failure"):
            return False
    return True


def require_operator_release(task: dict | None, record: dict) -> None:
    if task and task["role"] == "operator" and record.get("held_by") not in (None, task["id"]):
        raise ApiError("work is explicitly held by another owner; an Operator cannot release or revise that hold")


def decider(body) -> tuple[str, str]:
    """The queue item a hold or revision is about, and who decides about it: the user, or the
    running manager of the item's own project."""
    name = body.get("item", "")
    key = queue_key(name)
    if key is None:
        raise ApiError(f"{name!r} has no queue item; only queued work can be held, revised or moved")
    record = queues.records()[key]
    by = running(body)
    if by is None:
        return key, "user"
    if not controls_project(by, record["project"]):
        raise ApiError("only the owning project's running manager, or the user, holds or revises queued work")
    require_operator_release(by, record)
    return key, by["id"]


def hold(body):
    lifecycle.hold(*decider(body))
    return {"ok": True}


def unhold(body):
    lifecycle.unhold(*decider(body))
    return {"ok": True}


def revise(body):
    key, by = decider(body)
    lifecycle.revise(key, by, body.get("reason", ""), body.get("brief", ""), body.get("stage"),
                     body.get("reasoning_effort"), body.get("budget"), dependency_ids=body.get("dependencies"),
                     summary=body.get("summary"), reliances=body.get("relies_on"))
    return {"ok": True, "item": key}


def cancel(body):
    """End named tasks for good. A task with a queue record withdraws that record (and every run
    working on it); a live task without one, such as a garden or an audit, just ends."""
    names = body.get("items") or []
    if not isinstance(names, list) or not names or not all(isinstance(i, str) for i in names):
        raise ApiError("name the tasks to cancel as PROJECT:NAME")
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise ApiError("say why the work is cancelled")
    keys, alone = [], []
    for name in dict.fromkeys(names):
        task = L["tasks"].get(name)
        key = None if task and task.get('repair_origin') and not task.get('record') else queue_key(name)
        if key is not None:
            keys.append(key)
        elif task is not None and not tasks.settled(task):
            alone.append(task)
        else:
            raise ApiError(f"{name!r} is not a live task or queue item")
    by = running(body)
    if by is not None and alone and all(t.get('repair_origin') for t in alone):
        origins = ', '.join(dict.fromkeys(t['repair_origin']['task'] for t in alone))
        raise ApiError('these are derived recovery tasks, not queued assignments; to withdraw obsolete '
                       'work, cancel its originating queue ID: ' + origins)
    if by is not None and (alone or any(
            not controls_project(by, queues.records()[k]["project"]) for k in keys)):
        raise ApiError("only the owning project's running manager, or the user, cancels queued work")
    for key in keys:
        require_operator_release(by, queues.records()[key])
    who = "user" if by is None else by["id"]
    for task in alone:
        lifecycle.cancel_task(task, who, reason)
    return {"ok": True, "cancelled": [t["id"] for t in alone] + (lifecycle.cancel(list(dict.fromkeys(keys)), who, reason) if keys else [])}


def move(body):
    key = queue_key(body.get("item", ""))
    if key is None:
        raise ApiError(f"{body.get('item', '')!r} has no queue item; only queued work can be moved")
    return {"ok": True, "position": queues.move(key, body.get("to", ""))}


# ---------------------------------------------------------------- messages between tasks and the user



def mailbox(name: str) -> str:
    """A local, polled endpoint, without a managed task or Coin notification."""
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", name):
        raise ApiError("mailbox names use letters, digits, underscores and hyphens")
    return "mailbox:" + name


def sender(body) -> str:
    """'user' for the user's own CLI, else the active task whose current run is asking."""
    task = running(body)
    if body.get("mailbox") is not None:
        if task is not None:
            raise ApiError("only the user's local client may use an external mailbox identity")
        return mailbox(body["mailbox"])
    return "user" if task is None else task["id"]


def send(body):
    """One message to an active task's inbox, or durably queued for Coin delivery."""
    origin, target, text = sender(body), (body.get("to") or "").strip(), (body.get("text") or "").strip()
    if not text:
        raise ApiError("a message needs text")
    if target == "user":
        alert(f"Message from {origin}: {text}")
    elif target.startswith("mailbox:"):
        mailbox(target.removeprefix("mailbox:"))
    elif not (target in L["tasks"] and tasks.active(L["tasks"][target])):
        raise ApiError(f"{target!r} is not an active task; use jobs for task ids, 'mailbox:NAME', or 'user'")
    from cointos.state import enqueue_message
    enqueue_message(origin, target, text)
    return {"ok": True, "to": target, "delivery": "queued" if target == "user" else "inbox"}


def message_delivered(body):
    """Coin acknowledges transport acceptance; ordinary inbox reads are not delivery."""
    if running(body) is not None:
        raise ApiError('only the local delivery client may acknowledge user messages')
    for message in L['messages']:
        if message['to'] == 'user' and message['from'] == body['from'] and message['at'] == body['at']:
            message['read'] = True
    return {'ok': True}


def inbox(body):
    """The asker's unread messages, marked read."""
    reader = sender(body)
    unread = [m for m in L["messages"] if m["to"] == reader and not m["read"]]
    for message in unread:
        if reader != 'user':
            message["read"] = True
    return {"messages": [{"from": m["from"], "at": m["at"], "text": m["text"]} for m in unread]}


# ---------------------------------------------------------------- the user's controls

def stop_agents(reason: str, project: str | None = None) -> None:
    for agent_id, agent in list(L["agents"].items()):
        if project is None or agent["place"] == project:
            lifecycle.stop(agent_id, reason, requeue=True, charge=False)


def pause(body):
    L["paused"] = True
    stop_agents("stopped by the user")
    log("paused")
    return {"ok": True, "paused": True}


def resume(body):
    L["paused"] = False
    log("resumed")
    return {"ok": True, "paused": False}


def coin(body):
    """Coin reports what it is doing, for its dashboard card: busy with a turn, and on what.
    Its last words stay on the card until the next turn starts."""
    state, busy = L["coin"], bool(body.get("busy"))
    pid = body.get("pid")
    if type(pid) is int and pid > 0:
        process = wakeups.process(pid)
        if process is not None:
            state["process"] = {"pid": pid, "start_ticks": process["start_ticks"], "boot_id": wakeups.boot_id()}
    if busy != state["busy"]:
        state.update(busy=busy, since=now())
        if busy:
            state["live"] = {}
            state["gpu_seconds"] = 0
        else:
            state["last_turn_at"] = now()
    doing = body.get("doing") if busy else None
    if state.get("doing") != doing:
        state["doing_since"] = now()
    state["doing"] = doing
    return {"ok": True}


def halt(body):
    STOPPING.set()
    stop_agents("system halted")
    log("halt requested")
    LOCK.notify_all()
    return {"ok": True}


def kill_agent(body):
    """Kill one run, not its task: preserve artifacts and return unfinished work to waiting."""
    if body.get("agent") not in L["agents"]:
        raise ApiError(f"no live agent {body.get('agent')!r}")
    task = lifecycle.kill(body["agent"])
    return {"ok": True, "task": task["id"], "held": bool(task.get("admission_hold"))}


def resume_task(body):
    by = running(body)
    target = L["tasks"].get(body["task"])
    if by is not None:
        if target is None or not controls_project(by, target["place"]) or by["role"] != "operator":
            raise ApiError("resuming infrastructure repair requires a control-enabled Operator in scope")
        if target.get("admission_hold") != "repeated infrastructure launch failure":
            raise ApiError("explicit user holds require the user's own resume control")
    task = lifecycle.resume_task(body["task"])
    return {"ok": True, "task": task["id"]}


def prepare_restart(body):
    if not L["restarting"]:
        L["restarting"] = True
        log("restart draining")
    ready = ACTIVE["chats"] == 0 and ACTIVE["landings"] == 0 and not L["thoughts"]
    return {"ok": True, "ready": ready, "active_requests": ACTIVE["chats"]}


def cancel_restart(body):
    L["restarting"] = False
    LOCK.notify_all()
    for agent in L["agents"].values():
        agent["last_activity"] = now()
    return {"ok": True}


def run_agent(body):
    task, run = caller(body)
    spawner = (running(body), L["agents"][run]) if task is not None else None
    task = tasks.request_operator(body["name"], body["brief"], body.get("project"), body.get("abilities"),
                                  body.get("reasoning_effort"), body.get("budget"), spawner)
    log("operator requested", task=task["id"], abilities=task["abilities"], spawned_by=task.get("spawned_by"))
    return {"ok": True, "task": task["id"]}


def scout(body):
    task, created = tasks.request_steward()
    log("scout requested", task=task["id"], created=created)
    return {"ok": True, "task": task["id"], "created": created}


def supersede(body):
    """The user replaces failed or blocked work with existing items, without accepting it."""
    record = queues.records().get(body.get("task", ""))
    by = running(body)
    if by is not None and (record is None or not controls_project(by, record["project"])):
        raise ApiError("replacement requires the owning manager or a control-enabled Operator")
    if record is not None:
        require_operator_release(by, record)
    if record is not None and record.get("replaced_by"):
        if (record["replaced_by"], record.get("replacement_reason")) != (body.get("replacements"), body.get("reason", "").strip()):
            raise ApiError("it already has a different replacement")
        return {"ok": True, "replaced_by": record["replaced_by"]}  # a retry after a lost reply
    if record is None or queues.status(record) != "blocked":
        raise ApiError("only blocked work can be superseded; stop or cancel active work first")
    lifecycle.replace(record, body.get("replacements"), "user" if by is None else by["id"], body.get("reason", ""))
    if record["item"] and f"{record['project']}:{record['item']}" in L["tasks"]:
        L["tasks"][f"{record['project']}:{record['item']}"]["replaced_by"] = record["replaced_by"]
    return {"ok": True, "replaced_by": record["replaced_by"]}


def clear_review(body):
    task = L["tasks"][body["task"]]
    if task["status"] != "waiting" or not task.get("review") or not body.get("reason", "").strip():
        raise ApiError("clear-review requires inactive waiting work with rejection feedback and a reason")
    log("review feedback withdrawn", task=task["id"], reason=body["reason"])
    task.update(review=None, session=None, recovery_note="Infrastructure rejection withdrawn: " + body["reason"])
    snapshots.forget_owner(task["id"])
    return {"ok": True, "applies": "fresh session on next run"}


def reasoning(body):
    tasks.set_reasoning(body["task"], body["effort"])
    return {"ok": True, "applies": "next reply"}


def budget(body):
    by = running(body)
    key = queue_key(body["task"])
    target = L["tasks"].get(body["task"])
    project = queues.records()[key]["project"] if key else (target or {}).get("place")
    if by is not None and not controls_project(by, project):
        raise ApiError("budget changes require the owning manager or a control-enabled Operator")
    return tasks.set_budget(body["task"], body["budget"])


def forget(task_id: str) -> None:
    """Remove one task record and everything the daemon keeps for its conversation."""
    snapshots.forget_owner(task_id)
    for lane in L["lanes"]:
        if lane["resident"] == task_id:
            lane["resident"] = None  # a later graceful stop must not save this owner again
    del L["tasks"][task_id]


def forget_task(body):
    """Operator cleanup of one paused task; its Git and OpenCode artifacts are removed separately."""
    if not L["paused"] or L["agents"] or ACTIVE["landings"]:
        raise ApiError("pause and stop all agents before forgetting work")
    if body["task"] in L["tasks"]:
        forget(body["task"])
        log("task forgotten", task=body["task"])
    return {"ok": True}


def clear_task_history(body):
    """Remove finished task records and terminal queue history that live work no longer needs."""
    protected = {agent["task"] for agent in L["agents"].values()}
    protected |= {tid for tid, task in L["tasks"].items() if tasks.active(task)}
    protected |= {task["worker"] for tid, task in L["tasks"].items() if tid in protected and task["worker"]}
    protected |= {task["record"] for tid, task in L["tasks"].items() if tid in protected and task["record"]}
    for tid, task in L["tasks"].items():
        if not (origin := task.get("repair_origin")):
            continue
        source = L["tasks"].get(origin["task"])
        record = queues.records().get(origin["task"]) or queues.records().get((source or {}).get("record"))
        current = (record is not None and record["version"] == origin["version"]
                   and not record.get("done") and not record.get("replaced_by"))
        current |= bool(source and source.get("record_version") == origin["version"]
                        and not source.get("cancelled") and (source["status"] == "failed" or source.get("admission_hold")
                        or (source.get("receipt") or {}).get("disposition") == "blocked"))
        if tid in protected or current:
            protected.add(tid)
            protected.add(origin["task"])
            if source and source.get("record"):
                protected.add(source["record"])
    frontier = queues.history_frontier(protected)
    removed = [tid for tid, task in L["tasks"].items()
               if tasks.settled(task) and tid not in protected
               and tid not in frontier and task["record"] not in frontier]
    for task_id in removed:
        forget(task_id)
    queue_removed = queues.clear_history(protected)
    log("task history cleared", task_records=len(removed), queue_records=len(queue_removed))
    return {"ok": True, "removed": len(removed) + len(queue_removed),
            "task_records": len(removed), "queue_records": len(queue_removed)}


def viewers(body):
    L["viewers_showing"] = bool(body.get("show"))
    log("viewers", showing=L["viewers_showing"])
    return {"ok": True, "showing": L["viewers_showing"]}


def scheduler(body):
    return settings.set_scheduler(body)


# ---------------------------------------------------------------- projects

def merge(body):
    """Publish maintenance through current daemon-owned run and role authority."""
    task = running(body)
    if task is None or schema.KINDS[task['kind']]['lands'] != 'merge' or not task.get('branch'):
        raise ApiError('maintenance merge requires a running maintenance/planning assignment')
    where = tasks.place(task)
    commit = body.get('commit')
    if not isinstance(commit, str) or commit != git.head(task['worktree']) or commit != git.head(where['path'], task['branch']):
        raise ApiError('maintenance candidate must be the current assigned branch HEAD')
    if not git.clean(task['worktree']):
        raise ApiError('commit the scoped worktree changes before maintenance merge')
    with git.repository_lock(where['path']):
        main = git.head(where['path'], where['main_branch'])
        contracts.maintenance_history(where, task, main)
        result = git.publish(where['path'], where['main_branch'], commit, main)
    log('maintenance merged', task=task['id'], agent=task['agent'], commit=commit)
    return {'ok': True, **result}


def project_list(body):
    return {"ok": True, "projects": CONFIG["projects"]}


def project_new(body):
    project = projects.create(CONFIG, body)
    log("project created", project=project["name"], path=project["path"])
    return {"ok": True, "project": project}


def project_add(body):
    project = projects.add(CONFIG, body)
    log("project added", project=project["name"], path=project["path"])
    return {"ok": True, "project": project}


def project_set(body):
    changes = body.get("settings")
    if not isinstance(changes, dict) or not changes:
        raise ApiError("project-set requires one or more settings")
    project = projects.update(CONFIG, body["project"], changes)
    if not project["enabled"]:
        stop_agents("project disabled", project["name"])
    log("project changed", project=project["name"], settings=changes)
    return {"ok": True, "project": project}


def project_remove(body):
    name = body["project"].lower()
    if any(t["place"].lower() == name and tasks.active(t) for t in L["tasks"].values()):
        raise ApiError("cannot remove a project with waiting, running or review work; disable it first and settle the work")
    if any(r["project"].lower() == name and queues.status(r) == "queued" for r in queues.records().values()):
        raise ApiError("cannot remove a project with queued records")
    project = projects.remove(CONFIG, body["project"])
    log("project removed", project=project["name"])
    return {"ok": True, "project": project}


ACTIONS = {
    "message-delivered": message_delivered,
    "merge": merge,
    "receipt-delivered": receipt_delivered, "return": send_back, "replace": replace,
    "queue": queue, "handoff": handoff, "correct-tests": correct_tests, "check-work": check_work, "send": send, "inbox": inbox,
    "hold": hold, "unhold": unhold, "revise": revise,
    "stop": pause, "go": resume, "coin": coin, "halt": halt, "kill-agent": kill_agent, "resume-task": resume_task,
    "prepare-restart": prepare_restart, "cancel-restart": cancel_restart,
    "run-agent": run_agent, "scout": scout, "supersede": supersede, "cancel": cancel, "move": move, "clear-review": clear_review,
    "reasoning": reasoning, "budget": budget, "forget-task": forget_task, "clear-task-history": clear_task_history,
    "viewers": viewers, "scheduler": scheduler,
    "project-list": project_list, "project-new": project_new, "project-add": project_add,
    "project-set": project_set, "project-remove": project_remove,
}
PUBLISHES = {"finish", "return", "replace", "queue", "handoff", "correct-tests", "hold", "unhold", "revise", "supersede", "cancel", "move", "reasoning", "budget",
             "clear-task-history"}
