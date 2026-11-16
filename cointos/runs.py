"""Agent runs: starting one for a waiting task, following it to its end, and adopting the runs
a previous daemon left behind. What a run's end means for its task is decided by
`cointos/lifecycle.py`; this module only reports execution facts to it.
"""
from __future__ import annotations

import secrets
import threading

from cointos import artifacts, contracts, git, landing, keys, lifecycle, opencode, packets, prompts, queues, schema, scheduler, tasks
from cointos.state import CONFIG, LOCK, L, log, now


class Ended(Exception):
    """The run left the ledger while it was still being followed."""


def scheduling_class(task: dict) -> str:
    return 'user' if task['role'] == 'operator' else 'background'


def scheduling_default(task: dict) -> float:
    return scheduler.weight(CONFIG, scheduling_class(task), task['role'])


def start(task: dict) -> str:
    """Reserve and admit one run. LOCK is the follower's admission barrier."""
    with LOCK:
        lifecycle.require_start(task)
        reserved = set(keys.recorded()) | set(keys.ISSUED)
        while True:
            agent_id = f"{task['role']}-{secrets.token_hex(3)}"
            if agent_id in L["agents"] or agent_id in L["exiting"] or agent_id in reserved:
                continue
            try:
                opencode.run_dir(agent_id).mkdir(parents=True)
            except FileExistsError:
                continue
            break
        # The follower cannot launch until this lock is released. Thread/key failure
        # leaves the task untouched; an unregistered follower exits without stopping
        # any unit. Keep the directory reserved, including failed admissions.
        threading.Thread(target=follow, args=(agent_id, dict(task), None), daemon=True).start()
        klass = scheduling_class(task)
        keys.issue(agent_id, klass)
        lifecycle.start(task, agent_id)
        L["agents"][agent_id] = {
            "id": agent_id, "role": task["role"], "place": task["place"], "task": task["id"], "title": task["title"],
            "class": klass, "scheduling_default": scheduling_default(task), "state": "starting", "pid": None, "url": None, "session": task["session"],
            "doing": None, "thoughts": 0, "generated": 0, "engaged": False,
            "repeats": 0, "last_thought": None, "last_activity": now(),
            "started_at": now(), "stage": task["stage"], "reasoning_effort": task["reasoning_effort"]}
        log("agent started", agent=agent_id, task=task["id"], run=task["runs"])
        return agent_id


def follow(agent_id: str, task: dict | None, key: str | None) -> None:
    """Own one run from launch (or, with no task, from adoption after a daemon restart) to its
    end, then report its execution facts. The run is a systemd unit outside the daemon."""
    if task is not None:
        with LOCK:
            current = L["tasks"].get(task["id"])
            if agent_id not in L["agents"] or not lifecycle.owns(current, agent_id):
                return
            task, key = dict(current), keys.ISSUED[agent_id]
    try:
        if task is not None:
            launch(agent_id, task, key)
        facts = opencode.watch(agent_id, lambda kind, value: observed(agent_id, kind, value))
    except contracts.CompositionError as error:
        log('private test preparation failed', task=task['id'], diagnostic=str(error))
        with LOCK:
            current = L["tasks"].get(task["id"])
            if lifecycle.owns(current, agent_id):
                current['composition_failure'] = error.evidence
                lifecycle.refuse_dispatch(current, error.public)
        facts = {"finish": None, "code": None, "error": error.public}
    except Ended:
        facts = None
    except Exception as error:
        if isinstance(error, git.OperationError):
            log('private file operation failed', task=task['id'], diagnostic=str(error))
        facts = {"finish": None, "code": None, "error": error.public if isinstance(error, git.OperationError)
                 else f"{type(error).__name__}: {error}"}
    try:
        with LOCK:
            if facts is not None and agent_id in L["agents"]:
                lifecycle.ended(agent_id, facts)
    finally:
        opencode.stop(agent_id)


def launch(agent_id: str, task: dict, key: str) -> None:
    """Prepare the task's worktree and start its run's unit. Runs outside LOCK."""
    where = tasks.place(task)
    preflight_bindings(task, where)
    correction = (queues.records().get(task.get('record')) or {}).get('correction')
    inherited = (queues.records().get(task.get('record')) or {}).get('preserved_artifact')
    if task["branch"] is not None:
        if correction:
            packets.require_current(task)
        git.add_worktree(where["path"], task["worktree"], task["branch"],
                         inherited['commit'] if inherited else correction['commit'] if correction else where["main_branch"])
        if inherited and not git.contains(task['worktree'], inherited['commit'], 'HEAD'):
            raise ValueError('assigned files do not contain the prepared work; preserve them for recovery')
        # Reusing a checkout/branch preserves work, but does not prove it still
        # contains the accepted packet (another run may have moved its ref).
        if correction and not git.contains(task['worktree'], correction['commit'], 'HEAD'):
            raise ValueError('prepared work does not contain accepted packet contents; '
                             'preserve the files and request current preparation before resuming')
    author = task['kind'] in ('item', 'breakdown', 'operator', 'garden', 'tree-audit') and task.get('branch')
    material = artifacts.materials(task, where) if author else []
    if author and not task.get("base_commit"):
        base = inherited['base'] if inherited else correction['commit'] if correction else git.run(task["worktree"], "merge-base", "HEAD", where["main_branch"])
        if material:
            base = git.run(where['path'], 'merge-base', '--octopus', base, *(artifact['base'] for artifact in material))
        with LOCK:
            L["tasks"][task["id"]]["base_commit"] = task["base_commit"] = base
    if task.get('branch'):
        if author:
            remaining = artifacts.prepare_assignment(task, where, material)
            with LOCK:
                if not lifecycle.owns(L['tasks'].get(task['id']), agent_id):
                    raise Ended
                L['tasks'][task['id']]['work_remaining'] = task['work_remaining'] = remaining
        git.insulate(task['worktree'])
    elif opencode.observer(task):
        directory = opencode.agent_data(task) / 'workspace'
        if directory.is_symlink():
            raise ValueError('the private working directory is a link; preserve it for recovery')
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with LOCK:
            if not lifecycle.owns(L['tasks'].get(task['id']), agent_id):
                raise Ended
            L['tasks'][task['id']]['worktree'] = task['worktree'] = str(directory)
    store = opencode.launch(CONFIG, agent_id, task, key, prompts.launch_text(task, where), protected(task, where))
    if store:
        with LOCK:
            current = L['tasks'].get(task['id'])
            if lifecycle.owns(current, agent_id):
                current['session_store'] = store


def preflight_bindings(task: dict, project: dict) -> None:
    """Compose the complete current contract before model launch, outside LOCK.

    No tests execute and no worker checkout is touched. Acceptance remains the
    authority for changed bindings/main after this early feasibility check.
    """
    rules = project.get('test_policy')
    if task['kind'] != 'item' or task['stage'] not in schema.TESTED or not rules:
        return
    with LOCK:
        if not lifecycle.owns(L['tasks'].get(task['id']), task['agent']):
            raise Ended
        commits = landing.tests_of(task, required=True)
        prior = material_baselines(task['place'], commits)
    main = git.head(project['path'], project['main_branch'])
    prepare_test_inputs(project, main, commits, prior)
    with LOCK:
        current = L["tasks"].get(task["id"])
        if not lifecycle.owns(current, task["agent"]):
            raise Ended
        current.pop("composition_failure", None)


def material_baselines(place: str, commits: list[str]) -> list[str]:
    """Verified historical baselines for exact inputs; caller holds LOCK."""
    return [t['base_commit'] for t in L['tasks'].values()
                 if t.get('place') == place and t.get('base_commit')
                 and (t.get('acceptance') or {}).get('via') == 'landing'
                 and (t.get('receipt') or {}).get('disposition') == 'complete'
                 and (t['receipt'].get('evidence') or {}).get('tests') == commits
                 and t['acceptance'].get('worker_commit') == t['receipt']['evidence'].get('commit')]


def prepare_test_inputs(project: dict, main: str, commits: list[str], prior=()) -> None:
    """Prepare exact accepted tests outside LOCK without changing worker files."""
    rules = project['test_policy']
    if not contracts.materialized(project['path'], main, commits, rules):
        # Legacy published artifacts did not retain test-input ancestry. Recompute
        # from their pinned baseline; only an exact protected-tree match is reusable.
        for baseline in dict.fromkeys(prior):
            if not git.ok(project['path'], 'cat-file', '-e', baseline + '^{commit}'):
                continue
            try:
                with contracts.combined(project['path'], baseline, commits, rules, non_code='ours'):
                    pass
            except contracts.CompositionError:
                continue
            if contracts.materialized(project['path'], main, commits, rules):
                break
    with contracts.combined(project['path'], main, commits, rules, non_code="ours"):
        pass


def protected(task: dict, where: dict) -> list[str]:
    """Paths an implementation run may not edit: its project's test contracts and harness."""
    rules = where.get("test_policy")
    if task["kind"] != "item" or task["stage"] != "implementation" or not rules:
        return []
    patterns = [rules["manifest"], *rules.get("protected", [])]
    return patterns + [f"{task['worktree']}/{pattern}" for pattern in patterns]


def observed(agent_id: str, kind: str, value) -> None:
    """An event from a followed run: its server, its session, what it is doing."""
    with LOCK:
        agent = L["agents"].get(agent_id)
        if agent is None:
            raise Ended
        if kind == "server":
            agent.update(pid=value[0], url=value[1], state="running")
        elif kind == "session" and agent["session"] != value:
            agent["session"] = value
            task = L["tasks"].get(agent["task"])
            if lifecycle.owns(task, agent_id):
                task["session"] = value
        elif kind == "activity" and value:
            if agent.get("doing") != value:
                agent["doing_since"] = now()
            agent["doing"] = value
        agent["last_activity"] = now()


def adopt(previous: dict) -> None:
    """On daemon start: follow again the runs of the previous daemon (systemd units that
    outlived it), stop agent processes nobody owns, and send missing unreceipted runs to
    First Responder diagnosis. Caller holds LOCK."""
    recorded = keys.recorded()
    for agent_id, agent in (previous.get("agents") or {}).items():
        task = L["tasks"].get(agent["task"])
        if (agent_id not in recorded or task is None
                or (task["agent"] != agent_id and (task.get("receipt") or {}).get("run") != agent_id)
                or not opencode.active(agent_id)):
            continue
        L["agents"][agent_id] = {**agent,
                                 "gpu_since": None,
                                 "class": scheduling_class(task),
                                 "scheduling_default": scheduling_default(task),
                                 "engaged": agent.get("engaged", bool(agent.get("thoughts") or agent.get("generated"))),
                                 "last_activity": now()}
        keys.adopt(agent_id, L["agents"][agent_id]["class"], recorded[agent_id])
        opencode.thaw_capture(agent_id)
        log("agent adopted", agent=agent_id, task=agent["task"])
        threading.Thread(target=follow, args=(agent_id, None, None), daemon=True).start()
    for agent_id, pids in opencode.find_processes().items():
        if agent_id not in L["agents"]:
            for pid in pids:
                try:
                    opencode.stop_group(pid, grace=CONFIG["timeouts"]["leftover_stop_grace_seconds"])
                except PermissionError:
                    pass
    for task in L["tasks"].values():
        agent = L["agents"].get(task["agent"])
        if task["status"] == "running" and (agent is None or agent["task"] != task["id"]):
            lifecycle.orphaned(task)
