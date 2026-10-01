"""The control API: every action the CLI, Coin, agents and the dashboard can ask of the daemon.

`dispatch(action, body)` runs one action. Each is a small function over the domain modules.
Ordinary actions run under LOCK and save the ledger; landing actions validate outside LOCK
(tests can take minutes) and take it only to settle. Actions that change queue records also
republish the readable queue projection.
"""
from __future__ import annotations

from cointos import landing, lifecycle, projects, queues, settings, snapshots, tasks
from cointos.state import ACTIVE, CONFIG, LOCK, STOPPING, L, alert, log, now, save


class ApiError(ValueError):
    pass


def dispatch(action: str, body: dict):
    if action in LANDINGS:
        return landing_action(action, body)
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
        target = L["tasks"][body["task"]]
        validating = [target["id"]] + ([target["worker"]] if action == "land" else
                                       [t["id"] for t in [landing.integrating(target)] if t])
        if any(L["tasks"][tid].get("validating") for tid in validating):
            raise ApiError("this landing is already being validated")
        for tid in validating:
            L["tasks"][tid]["validating"] = True
        ACTIVE["landings"] += 1
    try:
        if action == "land":
            result = landing.land(body["task"], body["commit"], body.get("run"))
        else:
            result = landing.incorporate(body["task"], body["commit"], body["worker_commit"], body.get("run"))
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


# ---------------------------------------------------------------- agents' own actions

def finish(body):
    return {"ok": True, "receipt": lifecycle.submit(body["task"], body.get("run"), body.get("outcome"),
                                                    body.get("detail", ""))}


def receipt_delivered(body):
    lifecycle.receipt_delivered(body["task"], body["run"])
    return {"ok": True}


def send_back(body):
    lifecycle.returned(L["tasks"][body["task"]], body.get("run"), body["notes"])
    return {"ok": True}


def replace(body):
    """A decomposition manager repoints the dependents of its oversized item to its children;
    its receipt later retires the item."""
    task = L["tasks"][body["task"]]
    if task["kind"] != "decompose" or not lifecycle.owns(task, body.get("run")):
        raise ApiError("only a running decomposition manager replaces its item")
    children = body["children"]
    if not children or not isinstance(children, list):
        raise ApiError("children must list existing replacement item names")
    records = queues.records()
    if any(child == task["item"] or f"{task['place']}:{child}" not in records for child in children):
        raise ApiError("replacement children must exist and exclude the parent")
    for record in records.values():
        if record["project"] == task["place"] and task["item"] in record["depends"]:
            record["depends"] = list(dict.fromkeys(name for dep in record["depends"]
                                                   for name in (children if dep == task["item"] else [dep])))
    task["replacements"] = list(dict.fromkeys(children))
    log("item replaced", task=task["id"], children=task["replacements"])
    return {"ok": True}


# Who may propose queue work: roles, whether they are bound to their own project, and which
# queue kinds they may submit (None: any).
PROPOSERS = {"manager": (True, None), "integrator": (True, ("command",)),
             "steward": (False, ("command",)), "test-auditor": (False, ("command",))}


def proposer(body) -> dict | None:
    """The running task a request is made as, if any; it must be that task's current run."""
    if not body.get("proposed_by"):
        return None
    task = L["tasks"].get(body["proposed_by"])
    if task is None or not lifecycle.owns(task, body.get("run")):
        raise ApiError("a proposal must come from the proposing task's current run")
    return task


def queue(body):
    project = tasks.project_named(body.get("project", ""))
    kind = body.get("kind", "queued")
    by = proposer(body)
    if by is not None:
        own_project, kinds = PROPOSERS.get(by["role"], (True, ()))
        if (kinds is not None and kind not in kinds) or (own_project and by["place"] != project["name"]):
            raise ApiError("queue proposer must be an unfinished same-project manager/integrator, "
                           "or a scout/auditor proposing a command")
    item = queues.add(project, kind, body["name"], body["brief"], body.get("stage"),
                      body.get("reasoning_effort"), body.get("budget"))
    if by is not None:
        queues.records()[f"{project['name']}:{item}"].setdefault("proposed_by", by["id"])
    log("queued", project=project["name"], item=item)
    return {"ok": True, "item": item}


def decider(body) -> tuple[str, str]:
    """The queue item a hold or revision is about, and who decides about it: the user, or the
    running manager of the item's own project."""
    key = body.get("item", "")
    record = queues.records().get(key)
    if record is None:
        raise ApiError(f"unknown queue item {key!r}; name it PROJECT:ITEM")
    by = proposer(body)
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


def attention(body):
    by = proposer(body)
    message = body.get("message", "").strip()
    if by is None or by["role"] not in ("steward", "test-auditor"):
        raise ApiError("attention may only be sent by a running scout or test auditor")
    if not message:
        raise ApiError("attention message is required")
    alert(f"{by['role']} needs the user: {message}")
    return {"ok": True}


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
    if body.get("quiesce") and not L["quiescing"]:
        L["quiescing"] = True
        log("restart quiescing")
    return {"ok": True, "ready": ACTIVE["chats"] == 0 and ACTIVE["landings"] == 0 and not L["thoughts"],
            "active_requests": ACTIVE["chats"]}


def cancel_restart(body):
    L["restarting"] = False
    L["quiescing"] = False
    LOCK.notify_all()
    for agent in L["agents"].values():
        agent["last_activity"] = now()
    return {"ok": True}


def run_agent(body):
    task = tasks.request_operator(body["name"], body["brief"], body.get("project"), body.get("abilities"),
                                  body.get("reasoning_effort"), body.get("budget"))
    log("operator requested", task=task["id"], abilities=task["abilities"])
    return {"ok": True, "task": task["id"]}


def scout(body):
    task, created = tasks.request_steward()
    log("scout requested", task=task["id"], created=created)
    return {"ok": True, "task": task["id"], "created": created}


def supersede(body):
    return queues.supersede(body["task"], body["replacements"], body["reason"])


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
    protected |= {L["tasks"][tid]["worker"] for tid in list(protected) if L["tasks"][tid]["worker"]}
    removed = [tid for tid, task in L["tasks"].items() if task["status"] in ("done", "failed") and tid not in protected]
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
    if any(r["project"].lower() == name and r["status"] == "queued" for r in queues.records().values()):
        raise ApiError("cannot remove a project with queued records")
    project = projects.remove(CONFIG, body["project"])
    log("project removed", project=project["name"])
    return {"ok": True, "project": project}


ACTIONS = {
    "finish": finish, "receipt-delivered": receipt_delivered, "return": send_back, "replace": replace,
    "queue": queue, "attention": attention,
    "hold": hold, "unhold": unhold, "revise": revise,
    "stop": pause, "go": resume, "halt": halt, "kill-agent": kill_agent, "resume-task": resume_task,
    "prepare-restart": prepare_restart, "cancel-restart": cancel_restart,
    "run-agent": run_agent, "scout": scout, "supersede": supersede, "clear-review": clear_review,
    "reasoning": reasoning, "budget": budget, "forget-task": forget_task, "clear-task-history": clear_task_history,
    "viewers": viewers, "scheduler": scheduler,
    "project-list": project_list, "project-new": project_new, "project-add": project_add,
    "project-set": project_set, "project-remove": project_remove,
}
PUBLISHES = {"finish", "return", "replace", "queue", "hold", "unhold", "revise", "supersede", "reasoning", "budget",
             "clear-task-history"}
