"""What an agent run is told: its role, its assignment, and how its run ends.

A first run gets `roles/_base.md`, its role file (`roles/<role>.md`) and the assignment built
here. A short interruption continues its existing session with the smallest explicit handoff
OpenCode accepts; after a long absence it gets one concise reorientation. Behaviour belongs in the role
files; the assignment carries only this task's facts: where, what, and the exact receipt.
Every real message ends with the run's daemon-managed budget.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from cointos import queues, schema
from cointos.config import ROOT
from cointos.state import CONFIG

ROLES = ROOT / "roles"
REORIENT_AFTER_SECONDS = 3 * 60 * 60


def launch_text(task: dict, where: dict, at: float | None = None) -> str:
    """The message a run starts with."""
    if task.get("review"):
        text = (f"The integrator sent your work back:\n\n{task['review']}\n\nAddress this on your branch, commit "
                "it with your updated report, then submit it again with `cointos finish`.")
    elif task.get("session"):
        interrupted = task.get("interrupted_at")
        if interrupted is None or (at if at is not None else time.time()) - interrupted < REORIENT_AFTER_SECONDS:
            return "Continue."
        text = ("This assignment has been paused for several hours. Re-orient from the current branch, files and "
                "conversation, check whether anything material changed, then continue to its receipt without "
                "repeating finished work.")
    else:
        text = shared_launch_prefix(task) + assignment(task, where)
    return text + budget_notice(task)


def shared_launch_prefix(task: dict) -> str:
    """The task-independent start of a fresh run's user message.

    Rendering owns the exact token boundary because chat templates can tokenize a truncated
    message differently. This function owns only the semantic boundary: shared role guidance
    ends where this task's assignment begins.
    """
    role = (ROLES / "_base.md").read_text() + "\n\n" + (ROLES / f"{task['role']}.md").read_text()
    return role + "\n\n# Your assignment\n\n"


def assignment(task: dict, where: dict) -> str:
    parts = [location(task, where), identity(task), what(task, where)]
    if task["revision"]:
        parts.append(task["revision"] + "\nThis assignment replaces an earlier brief. Your branch may already hold "
                     "work done for that brief: keep what this brief still needs and remove what it does not.")
    if task.get("recovery_note"):
        parts.append("Fresh recovery: " + task["recovery_note"] +
                     "\nInspect existing branch/files and current main first. Preserve completed work. "
                     "Use the assignment, recovery packet and exact current failures; do not reconstruct prior deliberation. "
                     "Treat packet claims as leads until verified, then continue from the useful frontier. "
                     "\n\nRecovery packet:\n" + str(task.get("recovery_context") or "No transcript evidence was available.") +
                     "\n\nPrior review feedback: " + str(task.get("review") or "none"))
    proposed = [r for r in queues.records().values() if r.get("proposed_by") == task["id"]]
    if proposed:  # a fresh session has no memory of what earlier runs of this assignment queued
        parts.append("Earlier runs of this assignment already queued the following. Do not queue this work again "
                     "under any name; `cointos revise`, `cointos hold` or `cointos cancel` it instead:\n" +
                     "\n".join(f"- {r['project']}:{r['item']} ({'landed' if r['status'] == 'done' else r['status']})"
                               f"{': ' + r['summary'] if r.get('summary') else ''}" for r in proposed))
    parts.append(ending(task, where))
    return "\n\n".join(parts)


def identity(task: dict) -> str:
    """Who the run is, stated so it never has to infer its role from the kind or the code."""
    return (f"Task: `{task['id']}`, a {task['kind']} task. Your role: {task['role']}. "
            "The `cointos` commands you run act as this task with this role's permissions.")


def location(task: dict, where: dict) -> str:
    if task["branch"] is None:
        return (f"Scope: the installed CointOS runtime ({task['worktree']}) and the explicitly named accessible paths. "
                "This is a system task with no project, branch or worktree.")
    repository = f"repository {where['path']}, main branch `{where['main_branch']}`"
    if schema.KINDS[task["kind"]]["scope"] == "tree":
        return (f"Tree: {where['name']}, the knowledge root `{where['tree']}` of {repository}.\n"
                f"Your worktree: {task['worktree']}, on branch `{task['branch']}`; your copy of the tree is "
                f"`{Path(task['worktree']) / where['tree']}`.")
    return f"Project: {where['name']}, {repository}.\nYour worktree: {task['worktree']}, on branch `{task['branch']}`."


def what(task: dict, where: dict) -> str:
    kind = task["kind"]
    if kind == "item":
        text = (f"Stage: {task['stage']}. Reasoning effort: {task['reasoning_effort']}.\n"
                f"Your task: {task['item']}\n\n{task['brief']}")
        if where.get("test_policy"):
            text += "\n\nProject test policy: " + json.dumps(where["test_policy"])
        return text
    if kind == "integrate":
        return f"Review task {task['item']} (worker task {task['worker']}):\n\n{task['brief']}"
    if kind in ("breakdown", "decompose"):
        return f"{'Decompose' if kind == 'decompose' else 'Command'} {task['item']}:\n\n{task['brief']}"
    if kind == "garden":
        return f"Verify only these selected root-relative leaves (brown first when present):\n\n{task['brief']}"
    if kind == "operator":
        return f"Ad-hoc operator assignment. Abilities: {', '.join(task['abilities'])}.\n\n{task['brief']}"
    return task["brief"] or "Choose one concern as your role describes."


def ending(task: dict, where: dict) -> str:
    """How this run lands its work and which receipt ends it."""
    lands = schema.KINDS[task["kind"]]["lands"] if task["branch"] else None
    text = ""
    if lands == "merge":
        text = ("When your work is committed, land it with `cointos merge` in your worktree: it brings your branch "
                f"up to date with `{where['main_branch']}` and lands it. Never run `git merge`, `git rebase` or "
                "`git stash` yourself. If it reports conflicts, resolve them as it says and run it again. Only what "
                "lands counts: commit nothing after that.\n\n")
    if lands == "gate":
        return text + ("Your run ends with exactly one receipt: a verified `cointos land` or `cointos incorporate`, "
                       "`cointos return \"NOTES\"`, or, if you can do neither, `cointos finish --blocked \"REASON\"`. "
                       "A successful terminal command delivers the receipt and ends this managed run automatically.")
    if lands == "review":
        text += ("Commit your work and `.work-report.md` on this branch; the matching receipt is `--complete` for "
                 "`Status: done` and `--blocked` for `Status: blocked`.\n\n")
    return text + ("Your run ends with exactly one receipt: `cointos finish --complete \"EVIDENCE\"` when this bounded "
                   "assignment is done, or `cointos finish --blocked \"SPECIFIC BLOCKER\"`. The daemon checks it against "
                   "your artifacts and refuses it with the reason if they do not match; fix that and finish again. "
                   "A successful terminal command delivers the receipt and ends this managed run automatically.")


def budget_notice(task: dict) -> str:
    limits = task["budget"]
    effort = task["reasoning_effort"]
    return (f"\n\nFYI — daemon-managed budget for this run: {limits['generation_tokens']:,} generated tokens "
            f"or {limits['generation_seconds']:g} seconds of generation, whichever comes first. "
            f"Each uninterrupted reasoning block is limited to {CONFIG['reasoning']['budgets'][effort]:,} tokens at "
            f"{effort} effort; decide succinctly, then use a tool or answer before the daemon closes reasoning for you. "
            "Reasoning, answer text and tool-call output tokens count; prompt prefill, lane waiting and tool execution "
            "do not. Finish the bounded assignment and submit its receipt within this budget. "
            "Act once evidence is sufficient: do not narrate plans, reopen settled choices, or repeatedly reread the "
            "same evidence. Worker items must leave a durable branch artifact by the checkpoint stated in the base "
            "instructions. On exhaustion the daemon preserves branch/files and a bounded evidence packet for a fresh "
            "retry; do not expand scope.")
