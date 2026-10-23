"""What an agent run is told: its role, its assignment, and how its run ends.

A first run gets `roles/_base.md`, its role file (`roles/<role>.md`) and the assignment built
here. A short interruption continues its unfinished turn through the supervisor's resume hook,
or gets the smallest explicit handoff after a completed reply; a long absence gets concise reorientation. Behaviour belongs in the role
files; the assignment carries only this task's facts: where, what, and the exact receipt.
Every real message ends with the run's daemon-managed budget.
The run supervisor completes pending compaction before selecting recovery's turn boundary.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from cointos import frontier, queues, schema
from cointos.config import ROOT
from cointos.state import CONFIG, L

ROLES = ROOT / "roles"


def launch_text(task: dict, where: dict, at: float | None = None) -> str:
    """The message a run starts with."""
    if task.get("review"):
        text = (f"The integrator sent your work back:\n\n{task['review']}\n\nAddress this on your branch, commit "
                "it with your updated report, then submit it again with `cointos finish`.")
    elif task.get("session"):
        interrupted = task.get("interrupted_at")
        if interrupted is None or (at if at is not None else time.time()) - interrupted < CONFIG["recovery"]["reorient_after_seconds"]:
            return "Continue."
        text = ("This assignment has been paused for several hours. Re-orient from the current branch, files and "
                "conversation, check whether anything material changed, then continue to its receipt without "
                "repeating finished work.")
    else:
        text = shared_launch_prefix(task) + assignment(task, where)
    return text + budget_notice(task)


def shared_launch_prefix(task: dict) -> str:
    """The task-independent start of a fresh run's user message: shared role guidance ends
    where this task's assignment begins."""
    return shared_launch_tiers(task)[-1]


def shared_launch_tiers(task: dict) -> list[str]:
    """Successively longer starts of a fresh run's user message, each shared by more tasks than
    the next: nothing (every task of the project), the guidance all roles share, then this role's.

    Rendering owns the exact token boundaries because chat templates can tokenize a truncated
    message differently. This function owns only the semantic boundaries.
    """
    base = (ROLES / "_base.md").read_text() + "\n\n"
    return ["", base, base + (ROLES / f"{task['role']}.md").read_text() + "\n\n# Your assignment\n\n"]


def assignment(task: dict, where: dict) -> str:
    parts = [location(task, where), identity(task), what(task, where)]
    if authority := queue_authority(task):
        parts.insert(2, authority)
    if task["revision"]:
        parts.append(task["revision"] + "\nThis assignment replaces an earlier brief. Your branch may already hold "
                     "work done for that brief: keep what this brief still needs and remove what it does not.")
    if task.get("recovery_note") and not task.get('repair_origin'):
        parts.append("Fresh recovery: " + task["recovery_note"] +
                     "\nInspect existing branch/files and current main first. Preserve completed work. "
                     "Use the assignment, recovery packet and exact current failures; do not reconstruct prior deliberation. "
                     "Treat packet claims as leads until verified. Then decide where the assignment stands: if its "
                     "work is already complete, commit it and submit your receipt now; if what remains cannot be "
                     "finished within this run's budget, finish blocked stating exactly what is done and what "
                     "remains; otherwise continue from the useful frontier. "
                     "\n\nRecovery packet:\n" + str(task.get("recovery_context") or "No transcript evidence was available.") +
                     "\n\nPrior review feedback: " + str(task.get("review") or "none"))
    proposed = [r for r in queues.records().values() if r.get("proposed_by") == task["id"]]
    if proposed:  # a fresh session has no memory of what earlier runs of this assignment queued
        parts.append("Earlier runs of this assignment already queued the following. Do not queue this work again "
                     "under any name; `cointos revise`, `cointos hold` or `cointos cancel` it instead:\n" +
                     "\n".join(f"- {r['project']}:{r['item']} ({'landed' if queues.status(r) == 'done' else queues.status(r)})"
                               f"{': ' + r['summary'] if r.get('summary') else ''}" for r in proposed))
    parts.append(ending(task, where))
    return "\n\n".join(parts)


def identity(task: dict) -> str:
    """Who the run is, stated so it never has to infer its role from the kind or the code."""
    called = f"Your name is {task['name']}. " if task.get("name") else ""
    return (f"Task: `{task['id']}`, a {task['kind']} task. Your role: {task['role']}. {called}"
            "The `cointos` commands you run act as this task with this role's permissions.\n"
            f"Task start date: {task['prompt_date']} (fixed; run `date` for the current date and time).")


def location(task: dict, where: dict) -> str:
    if task["branch"] is None:
        return (f"Scope: the installed CointOS runtime ({task['worktree']}) and the explicitly named accessible paths. "
                "This is a system task with no project, branch or worktree.")
    repository = f"repository {where['path']}, main branch `{where['main_branch']}`"
    if schema.KINDS[task["kind"]]["scope"] == "tree":
        return (f"Tree: {where['name']}, the knowledge root `{where['tree']}` of {repository}.\n"
                f"Your worktree: {task['worktree']}, on branch `{task['branch']}`; your copy of the tree is "
                f"`{Path(task['worktree']) / where['tree']}`.")
    return (f"Project: {where['name']}. Your active checkout for product reads, edits and commands: "
            f"{task['worktree']}, on branch `{task['branch']}`.\n"
            f"Shared Git metadata and accepted refs: {repository}. Its editor files may be stale or dirty; "
            f"inspect accepted code with `git show {where['main_branch']}:PATH` from your worktree, "
            "not by reading that editor checkout. Relative product paths refer to your active checkout.")


def what(task: dict, where: dict) -> str:
    kind = task["kind"]
    if kind == "item":
        text = (f"Stage: {task['stage']}. Reasoning effort: {task['reasoning_effort']}.\n"
                f"Your task: {task['item']}\n\n{task['brief']}")
        if where.get("test_policy"):
            text += "\n\nProject test policy: " + json.dumps(where["test_policy"])
        correction = (queues.records().get(task.get('record')) or {}).get('correction')
        if correction:
            text += ('\n\nYour branch starts at the accepted packet. Verify the reported contract defect, '
                     'correct its assertions while preserving valid coverage, and submit normally. '
                     'Independent review activates the replacement and resumes dependent implementations. '
                     'Do not change production code or attempt to revise dependent assignments yourself.')
        return text
    if kind == "integrate":
        return f"Review task {task['item']} (worker task {task['worker']}):\n\n{task['brief']}"
    if kind == 'breakdown':
        return f"Command {task['item']}:\n\n{task['brief']}"
    if kind == "garden":
        return f"Verify only these selected root-relative leaves (brown first when present):\n\n{task['brief']}"
    if kind == "operator":
        if task.get('repair_origin'):
            current = frontier.inspect(task['id'], L)
            current.pop('task')
            return ('Recover this current assignment with the declared Operator controls. '
                    'Old execution evidence is retained separately; do not treat old repair briefs as authority.\n\n' +
                    json.dumps(current, indent=2))
        return f"Ad-hoc operator assignment. Abilities: {', '.join(task['abilities'])}.\n\n{task['brief']}"
    return task["brief"] or "Choose one concern as your role describes."


def queue_authority(task: dict) -> str:
    """The same current contract facts for planners, authors and reviewers."""
    if task['kind'] not in ('item', 'breakdown', 'integrate'):
        return ''
    owned = frontier.record(task)
    if owned is None:
        return ''
    current = frontier.inspect(queues.key(owned), L)
    authority = {'assignment': queues.key(owned), 'version': owned['version'],
                 'depends': owned['depends'], 'binding_tests': current['binding_tests']}
    text = ('Current queue authority: use these bindings when interpreting packet references in the brief. '
            'Only independent acceptance of a typed correction changes a binding test contract.\n')
    if owned.get('correction'):
        authority['correction'] = owned['correction']
        text += ('This assignment owns the pending correction below. Acceptance of another packet does not '
                 'complete this correction; independent review of this assignment activates its replacement.\n')
    return text + json.dumps(authority, indent=2)


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
        text += "Commit your work on this branch; your receipt is your account of it for the integrator.\n\n"
    if task['role'] == 'manager':
        text += 'Use `cointos handoff` to queue children and submit your complete receipt atomically.\n\n'
    if task.get('repair_origin'):
        text += ('Use `cointos replace` to hand this origin to existing items, or `cointos correct-tests` '
                 'to request independent contract correction. Both check your handback and submit the complete '
                 'receipt atomically, ending your recovery run without a separate finish call.\n\n')
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
            "do not. Finish the bounded assignment and submit its receipt within this budget; a message warns you "
            f"once {CONFIG['recovery']['warning_fraction']:.0%} of either limit is spent. "
            "Act once evidence is sufficient: do not narrate plans, reopen settled choices, or repeatedly reread the "
            "same evidence. On exhaustion this run ends; its branch/files and a bounded evidence packet are "
            f"preserved. This role permits {schema.fresh_limit(CONFIG, task)} fresh budget retries; "
            "after those, unresolved work stays blocked unless an eligible canonical recovery or corrective handoff can advance it. "
            "Exhausted recovery Operators receive no recursive repair; do not expand scope.")
