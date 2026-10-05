"""Run budgets, recovery evidence and incident packets.

Each run is charged only for generation: lane waiting, prefill and tool time are free. A run
past its budget restarts fresh from a bounded evidence packet a bounded number of times
(`lifecycle.retry_fresh`). Long silent stretches before writing are normal for the work
model, so no earlier checkpoint stops a run. Caller holds LOCK.
"""
from __future__ import annotations

from pathlib import Path

from cointos import git, lifecycle, opencode, queues
from cointos.state import CONFIG, L


def enforce() -> None:
    if L["restarting"]:
        return
    for agent_id, agent in list(L["agents"].items()):
        task = L["tasks"][agent["task"]]
        if task.get("validating"):
            continue
        spent_seconds, spent_tokens = agent.get("generation_seconds", 0), agent.get("generation_tokens", 0)
        exhausted = (spent_seconds >= task["budget"]["generation_seconds"]
                     or spent_tokens >= task["budget"]["generation_tokens"])
        if not lifecycle.owns(task, agent_id):
            if exhausted:  # only finishing its reply after its receipt
                lifecycle.stop(agent_id, "generation budget reached after its receipt", requeue=False)
            continue
        if exhausted:
            reason = f"generation budget reached ({spent_seconds:.0f}s, {spent_tokens} tokens); branch and files preserved"
            lifecycle.retry_fresh(agent_id, reason, packet(agent_id, task, agent))


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


def incidents() -> list[dict]:
    """One stable, bounded packet per mechanical problem; no model diagnosis here."""
    packets = [{"task": key, "reason": reason} for key, reason in sorted(L["dependency_problems"].items())]
    for task in L["tasks"].values():
        if task.get("replaced_by") or task["status"] == "done":
            continue
        if task["status"] == "failed":
            packets.append({"task": task["id"], "reason": task["note"] or "run retries exhausted"})
        elif task["status"] == "review" and task["stage"] == "implementation":
            if (queues.records().get(task["record"]) or {}).get("commit"):
                packets.append({"task": task["id"], "reason": "queue has a commit but task remains in review"})
        if task.get("rejections", 0) >= CONFIG["recovery"]["repeated_rejections"]:
            packets.append({"task": task["id"], "reason": "repeated landing rejection",
                            "evidence": (task.get("review") or "")[:1000]})
    return packets
