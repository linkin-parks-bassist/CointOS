"""The control API: every action the CLI, Coin, agents and the dashboard can ask of the daemon.

`dispatch(action, body)` runs one action. Each is a small function over the domain modules.
Ordinary actions run under LOCK and save the ledger; landing actions validate outside LOCK
(tests can take minutes) and take it only to settle. Actions that change queue records also
republish the readable queue projection.
"""
from __future__ import annotations

import re

from cointos import contracts, git, landing, lifecycle, projects, queues, schema, settings, snapshots, tasks
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
    if action in LANDINGS:
        return landing_action(action, body)
    if action == "finish":
        return finishing(body)
    if action not in ACTIONS:
        raise ApiError(f"unknown action {action!r}")
    with LOCK:
        result = ACTIONS[action](body)
        save()
        if action in PUBLISHES:
            queues.publish()
        return result


def landing_action(action: str, body: dict):
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
    """`cointos finish`. An implementer's complete receipt first runs its packet's hidden tests,
    outside the ledger lock; a failure goes straight back to the still-running implementer with
    the failing tests revealed. A test writer's complete receipt first finds out whether its
    tests already pass on main."""
    with LOCK:
        task, run = caller(body)
        if task is None:
            raise ApiError("finish is an agent run's own receipt")
        tested = (task["kind"] == "item"
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
            main, tests = git.head(where["path"], where["main_branch"]), landing.tests_of(task)
            bundled = list(task.get("bundled", []))
            task["validating"] = True
            ACTIVE["landings"] += 1
    if tested:
        try:
            checked = {"commit": commit, "tests": tests}
            if rules and task["stage"] == "test-contract":
                checked = {"commit": commit, "passing": contracts.passing(
                    where["path"], main, [commit], rules, CONFIG["timeouts"]["command_seconds"],
                    CONFIG["memory"]["agent_limit_gb"])}
            elif rules:
                checked.update(contracts.packet_check(where["path"], main, commit, tests, bundled, rules,
                                                      CONFIG["timeouts"]["command_seconds"],
                                                      CONFIG["memory"]["agent_limit_gb"]))
        except ValueError as error:
            log("packet tests failed", task=task["id"], commit=commit)
            raise ApiError(str(error)) from error
        finally:
            with LOCK:
                ACTIVE["landings"] -= 1
                task.pop("validating", None)
                for agent in L["agents"].values():
                    if agent["task"] == task["id"]:
                        agent["last_activity"] = now()
    with LOCK:
        receipt = lifecycle.submit(task["id"], run, body.get("outcome"), body.get("detail", ""),
                                   checked if tested else None)
        save()
        queues.publish()
    return {"ok": True, "receipt": receipt}


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
    """A decomposition manager replaces its failed item with already-queued children: the item's
    dependents depend on the children instead."""
    task = running(body)
    if task is None or task["kind"] != "decompose":
        raise ApiError("only a running decomposition manager replaces its item")
    queues.replace(queues.records()[task["record"]], body.get("children"), "replaced by " + task["id"])
    task["replacements"] = list(dict.fromkeys(body["children"]))
    return {"ok": True}


# Who may propose queue work: roles, whether they are bound to their own project, and which
# queue kinds they may submit (None: any).
PROPOSERS = {"manager": (True, None), "integrator": (True, ("command",)),
             "steward": (False, ("command",)), "test-auditor": (False, ("command",))}


def queue(body):
    project = tasks.project_named(body.get("project", ""))
    kind = body.get("kind", "queued")
    by = running(body)
    if by is not None:
        own_project, kinds = PROPOSERS.get(by["role"], (True, ()))
        if (kinds is not None and kind not in kinds) or (own_project and by["place"] != project["name"]):
            raise ApiError("queue proposer must be an unfinished same-project manager/integrator, "
                           "or a scout/auditor proposing a command")
        if kind in ("queued", "urgent"):
            queues.require_summary(body["brief"])
    item = queues.add(project, kind, body["name"], body["brief"], body.get("stage"),
                      body.get("reasoning_effort"), body.get("budget"))
    if by is not None:
        queues.records()[f"{project['name']}:{item}"].setdefault("proposed_by", by["id"])
    log("queued", project=project["name"], item=item)
    return {"ok": True, "item": item}


def queue_key(name: str) -> str | None:
    """The queue record a control names. Every control takes a task id; an item task's id is
    its queue key, and any other task reaches its record through its `record` link."""
    current = queues.records()
    if name in current:
        return name
    task = L["tasks"].get(name)
    return task["record"] if task and task.get("record") in current else None


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
    if by["role"] != "manager" or by["place"] != record["project"]:
        raise ApiError("only the owning project's running manager, or the user, holds or revises queued work")
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
                     body.get("reasoning_effort"), body.get("budget"))
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
        key = queue_key(name)
        task = L["tasks"].get(name)
        if key is not None:
            keys.append(key)
        elif task is not None and task["status"] not in ("done", "failed"):
            alone.append(task)
        else:
            raise ApiError(f"{name!r} is not a live task or queue item")
    by = running(body)
    if by is not None and (by["role"] != "manager" or alone or any(
            queues.records()[k]["project"] != by["place"] for k in keys)):
        raise ApiError("only the owning project's running manager, or the user, cancels queued work")
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

MESSAGES_KEPT = 200


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
    """One short message to an active task's inbox, or to the user through Coin."""
    origin, target, text = sender(body), (body.get("to") or "").strip(), (body.get("text") or "").strip()
    if not text:
        raise ApiError("a message needs text")
    if target == "user":
        alert(f"Message from {origin}: {text}")
    elif target.startswith("mailbox:"):
        mailbox(target.removeprefix("mailbox:"))
    elif not (target in L["tasks"] and tasks.active(L["tasks"][target])):
        raise ApiError(f"{target!r} is not an active task; use jobs for task ids, 'mailbox:NAME', or 'user'")
    L["messages"] = (L["messages"] + [{"at": now(), "from": origin, "to": target, "text": text,
                                       "read": target == "user"}])[-MESSAGES_KEPT:]
    log("message", sender=origin, to=target)
    return {"ok": True, "to": target}


def inbox(body):
    """The asker's unread messages, marked read."""
    reader = sender(body)
    unread = [m for m in L["messages"] if m["to"] == reader and not m["read"]]
    for message in unread:
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
    if record is not None and record.get("replaced_by"):
        if (record["replaced_by"], record.get("replacement_reason")) != (body.get("replacements"), body.get("reason", "").strip()):
            raise ApiError("it already has a different replacement")
        return {"ok": True, "replaced_by": record["replaced_by"]}  # a retry after a lost reply
    if record is None or queues.status(record) != "blocked":
        raise ApiError("only blocked work can be superseded; stop or cancel active work first")
    queues.replace(record, body.get("replacements"), body.get("reason", ""))
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
    frontier = queues.history_frontier(protected)
    removed = [tid for tid, task in L["tasks"].items()
               if task["status"] in ("done", "failed") and tid not in protected
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
    "receipt-delivered": receipt_delivered, "return": send_back, "replace": replace,
    "queue": queue, "send": send, "inbox": inbox,
    "hold": hold, "unhold": unhold, "revise": revise,
    "stop": pause, "go": resume, "halt": halt, "kill-agent": kill_agent, "resume-task": resume_task,
    "prepare-restart": prepare_restart, "cancel-restart": cancel_restart,
    "run-agent": run_agent, "scout": scout, "supersede": supersede, "cancel": cancel, "move": move, "clear-review": clear_review,
    "reasoning": reasoning, "budget": budget, "forget-task": forget_task, "clear-task-history": clear_task_history,
    "viewers": viewers, "scheduler": scheduler,
    "project-list": project_list, "project-new": project_new, "project-add": project_add,
    "project-set": project_set, "project-remove": project_remove,
}
PUBLISHES = {"finish", "return", "replace", "queue", "hold", "unhold", "revise", "supersede", "cancel", "move", "reasoning", "budget",
             "clear-task-history"}
