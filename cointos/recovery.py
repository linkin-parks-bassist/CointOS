"""Run budgets, recovery evidence and incident packets.

Each run is charged only for generation: lane waiting, prefill and tool time are free. A run
past its budget ends; its assignment continues in a fresh session from its branch/files and a
bounded evidence packet, a bounded number of times (`lifecycle.retry_fresh`). Once a run has spent `recovery.warning_fraction` of either limit it
gets one message saying so, to wrap up while it still can. Long silent stretches before writing
are normal for the work model, so nothing stops a run before its budget. Caller holds LOCK.
"""
from __future__ import annotations

from pathlib import Path

from cointos import git, lifecycle, opencode, schema
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
        exhausted = (spent_seconds >= task["budget"]["generation_seconds"]
                     or spent_tokens >= task["budget"]["generation_tokens"])
        if not lifecycle.owns(task, agent_id):
            if exhausted:  # only finishing its reply after its receipt
                lifecycle.stop(agent_id, "generation budget reached after its receipt", requeue=False)
            continue
        if not exhausted and not agent.get("budget_warned") and warned(task, spent_seconds, spent_tokens):
            agent["budget_warned"] = True
            warn(task, spent_seconds, spent_tokens)
        if exhausted:
            reason = f"generation budget reached ({spent_seconds:.0f}s, {spent_tokens} tokens); branch and files preserved"
            lifecycle.retry_fresh(agent_id, reason, packet(agent_id, task, agent))


def warned(task: dict, spent_seconds: float, spent_tokens: int) -> bool:
    share = CONFIG["recovery"]["warning_fraction"]
    return (spent_seconds >= share * task["budget"]["generation_seconds"]
            or spent_tokens >= share * task["budget"]["generation_tokens"])


def warn(task: dict, spent_seconds: float, spent_tokens: int) -> None:
    """One message into the run's session: its budget is nearly spent."""
    limits = task["budget"]
    text = (f"Budget warning: this run has used {spent_seconds / 60:.0f} of its {limits['generation_seconds'] / 60:.0f} "
            f"generation minutes ({spent_tokens:,} of {limits['generation_tokens']:,} tokens). Commit your work now. "
            "If the assignment is done, finish --complete. If what remains will not fit in one more run, write "
            "exactly what is done and what remains in your report and finish --blocked. At the limit this run ends "
            "and a fresh run of this assignment continues from your branch and files.")
    L["messages"] = L["messages"] + [{"at": now(), "from": "cointos", "to": task["id"], "text": text, "read": False}]
    log("budget warning", task=task["id"], seconds=round(spent_seconds), tokens=spent_tokens)


def packet(agent_id: str, task: dict, agent: dict) -> str:
    """Bounded outward evidence for a fresh run; never hidden reasoning."""
    sections = [f"Previous run: {agent.get('generation_tokens', 0)} generated tokens, "
                f"{agent.get('generation_seconds', 0):.0f} generation seconds. "
                "This packet contains outward text and tool evidence only; verify it against the branch."]
    worktree = task["worktree"]
    if task["branch"] is not None and Path(worktree).is_dir():
        status = git.result(worktree, "status", "--short").stdout.strip()
        commits = git.result(worktree, "log", "--oneline", f"{task.get('base_commit') or 'HEAD'}..HEAD").stdout.strip()
        sections += ["Git status:\n" + (status or "clean"), "Commits since start:\n" + (commits or "none")]
    sections += list(reversed(opencode.evidence(agent_id, limit=7)))
    return "\n\n".join(sections)[:CONFIG["recovery"]["handoff_chars"]]
