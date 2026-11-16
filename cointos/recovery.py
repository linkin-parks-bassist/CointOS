"""Token budgets and evidence-driven supervision.

Elapsed time never terminates a run. Generated-token exhaustion retains the existing
recovery policy; periodic token/GPU-service milestones request a progress decision.
Caller holds LOCK.
"""
from __future__ import annotations

from pathlib import Path

from cointos import contracts, frontier, lifecycle, opencode, schema, tasks
from cointos.state import CONFIG, L, log, now


def enforce() -> None:
    if L["restarting"]:
        return
    for agent_id, agent in list(L["agents"].items()):
        task = L["tasks"][agent["task"]]
        if task.get("validating"):
            continue
        used = schema.spent(agent)
        spent_seconds, spent_tokens = used["generation_seconds"], used["generation_tokens"]
        exhausted = (task["role"] != "supervisor" and spent_tokens >= task["budget"]["generation_tokens"])
        if not lifecycle.owns(task, agent_id):
            if exhausted:  # only finishing its reply after its receipt
                lifecycle.stop(agent_id, "generation budget reached after its receipt", requeue=False)
            continue
        if not exhausted and not agent.get("budget_warned") and warned(task, spent_seconds, spent_tokens):
            agent["budget_warned"] = True
            warn(task, spent_seconds, spent_tokens)
        if not exhausted:
            supervise(task, agent, spent_tokens)
        if exhausted:
            reason = f"generation budget reached ({spent_seconds:.0f}s, {spent_tokens} tokens); files preserved"
            lifecycle.retry_fresh(agent_id, reason, packet(agent_id, task, agent))


UNSUPERVISED = ("supervisor",)  # no recursive supervision


def supervise(task: dict, agent: dict, spent_tokens: int) -> None:
    """A run that has generated this many tokens gets someone watching what it's actually doing.
    GPU service and generated tokens are observations, not proof of useful progress."""
    if not CONFIG.get('factory_enabled', True):
        return  # Only explicit Coin/user/timer dispatch may request another agent.
    every = CONFIG["recovery"].get("supervise_every_tokens")
    if not every or task["role"] in UNSUPERVISED:
        return
    accounted = agent.get('supervision_accounted_tokens', 0)
    task['supervision_tokens'] = task.get('supervision_tokens', 0) + max(0, spent_tokens - accounted)
    agent['supervision_accounted_tokens'] = spent_tokens
    if task.get('split_supervisor'):
        return
    if (task['role'] == 'worker' and task.get('stage') == 'implementation' and task.get('record')
            and task['supervision_tokens'] >= CONFIG['recovery'].get('split_after_tokens', 40000)):
        tasks.request_supervisor(task, task['supervision_tokens'], must_split=True)
        return
    # A token watermark survives restarts and cadence changes. Coalesce overdue
    # intervals into one inspection rather than launching a backlog of watchers.
    last = task.get('supervision_checked_tokens', 0)
    gpu = frontier.usage(task, L, now())['gpu_seconds']
    interval = CONFIG['recovery'].get('supervise_every_gpu_seconds', float('inf'))
    gpu_due = gpu // interval > agent.get('supervision_checked_gpu_seconds', 0) // interval
    if task['supervision_tokens'] // every <= last // every and not gpu_due:
        return
    if any(t['kind'] == 'supervise' and t.get('supervises') == task['id'] and tasks.pending(t)
           for t in L['tasks'].values()):
        return
    tasks.request_supervisor(task, task['supervision_tokens'])
    task['supervision_checked_tokens'] = task['supervision_tokens']
    agent['supervision_checked_gpu_seconds'] = gpu


def warned(task: dict, spent_seconds: float, spent_tokens: int) -> bool:
    share = CONFIG["recovery"]["warning_fraction"]
    return task['role'] != 'supervisor' and spent_tokens >= share * task['budget']['generation_tokens']


def warn(task: dict, spent_seconds: float, spent_tokens: int) -> None:
    """One message into the run's session: its budget is nearly spent."""
    limits = task["budget"]
    token_limit = "no token cap" if task["role"] == "supervisor" else format(limits["generation_tokens"], ",")
    text = (f"Budget warning: this run has generated {spent_tokens:,} of {token_limit} tokens. "
            "Preserve your work and submit the completed result or exact blocker. There is no automatic time limit.")
    L["messages"] = L["messages"] + [{"at": now(), "from": "cointos", "to": task["id"], "text": text, "read": False}]
    log("budget warning", task=task["id"], seconds=round(spent_seconds), tokens=spent_tokens)


def packet(agent_id: str, task: dict, agent: dict) -> str:
    """Bounded outward evidence for a fresh run; never hidden reasoning."""
    sections = [f"Previous run: {agent.get('generation_tokens', 0)} generated tokens, "
                f"{agent.get('generation_seconds', 0):.0f} generation seconds. "
                "This packet contains outward text and tool evidence only; verify it against the prepared files."]
    worktree = task["worktree"]
    if task["branch"] is not None and Path(worktree).is_dir():
        changed = contracts.working_paths(worktree, task.get('base_commit') or 'HEAD')
        sections += ["Changed files:\n" + ('\n'.join(changed) or 'none')]
    sections += list(reversed(opencode.evidence(agent_id, limit=7)))
    return "\n\n".join(sections)[:CONFIG["recovery"]["handoff_chars"]]
