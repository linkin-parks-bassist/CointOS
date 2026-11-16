"""What an agent run is told: its role, its assignment, and how its run ends.

A first run gets shared guidance (except Supervisors), its applicable role/stage and the assignment built
here. A short interruption continues its unfinished turn through the supervisor's resume hook,
or gets the smallest explicit handoff after a completed reply; a long absence gets concise reorientation. Behaviour belongs in the role
files; the assignment carries only this task's facts: where, what, and the exact receipt.
The run supervisor completes pending compaction before selecting recovery's turn boundary.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from cointos import frontier, queues, schema, stations
from cointos.config import ROOT
from cointos.state import CONFIG, L

ROLES = ROOT / "roles"


def system_context(content: str) -> str:
    """Trim known harness boilerplate, retaining explicit project instructions."""
    if content.startswith('Knowledge-tree startup:'):
        return ''  # retrieve the relevant answer instead of preloading whole orientations
    if content.startswith('You are opencode,') and '<env>' in content:
        generic, _, rest = content.partition('<env>')
        # Project instruction blocks, when included here, remain authoritative.
        custom = generic[generic.index('Instructions from:'):] if 'Instructions from:' in generic else ''
        content = (ROLES / '_harness.md').read_text() + '\n' + custom + '<env>' + rest
    content = re.sub(r'<available_skills>.*?</available_skills>', '', content, flags=re.S)
    content = content.replace('Skills provide specialized instructions and workflows for specific tasks.\n'
                              'Use the skill tool to load a skill when a task matches its description.\n', '')
    content = re.sub(r'\s*<server name="knowledgetrees">.*?</server>', '', content, flags=re.S)
    content = re.sub(r'<mcp_instructions>\s*</mcp_instructions>', '', content)
    return content.strip()


def launch_text(task: dict, where: dict, at: float | None = None) -> str:
    """The message a run starts with."""
    if task.get('work_remaining'):
        prefix = shared_launch_prefix(task) + assignment(task, where) + '\n\n' if not task.get('session') else ''
        text = prefix + ('Your assigned files are prepared. Re-read cointos_task for the remaining paths, '
                         'then verify and complete the original behavioral requirements. Prior work is preserved.')
        if task.get('review'):
            text += '\n\nReview findings to address:\n' + task['review']
    elif task.get("review"):
        prefix = shared_launch_prefix(task) + assignment(task, where) + '\n\n' if not task.get('session') else ''
        text = prefix + (f"The integrator sent your work back:\n\n{task['review']}\n\nAddress this in your assigned directory, verify "
                "it with your updated report, then submit it again with the appropriate CointOS tool.")
    elif task.get("session"):
        interrupted = task.get("interrupted_at")
        if interrupted is None or (at if at is not None else time.time()) - interrupted < CONFIG["recovery"]["reorient_after_seconds"]:
            return "Continue."
        text = ("This assignment has been paused for several hours. Re-orient from the current files and "
                "conversation, check whether anything material changed, then continue to its receipt without "
                "repeating finished work.")
    else:
        text = shared_launch_prefix(task) + assignment(task, where)
    return text


def shared_launch_prefix(task: dict) -> str:
    """The task-independent start of a fresh run's user message: shared role guidance ends
    where this task's assignment begins."""
    return shared_launch_tiers(task)[-1]


def shared_launch_tiers(task: dict) -> list[str]:
    """Successively longer starts of a fresh run's user message, each shared by more tasks than
    the next: nothing, file-owned role/stage, then shared guidance.

    Rendering owns the exact token boundaries because chat templates can tokenize a truncated
    message differently. This function owns only the semantic boundaries.
    """
    base = '' if task['role'] == 'supervisor' else (ROLES / "_base.md").read_text() + "\n\n"
    role = role_instructions(task)
    # Role text remains file-owned; identity is explicit without duplicating it in every file.
    title = task['role'].replace('-', ' ').title()
    intro = f"You are an autonomous CointOS {title}.\n\n# Your role\n\n"
    return ["", intro + role + "\n\n", intro + role + "\n\n" + base + "# Your assignment\n\n"]


def role_instructions(task: dict) -> str:
    role_name = 'supervisor-split' if task['role'] == 'supervisor' and task.get('must_split') else task['role']
    role = (ROLES / f"{role_name}.md").read_text()
    if task['role'] == 'worker' and task.get('stage') in ('skeleton', 'test-contract', 'implementation', 'integration'):
        role += '\n' + (ROLES / f"worker-{task['stage']}.md").read_text()
    return role


def assignment(task: dict, where: dict) -> str:
    if task['role'] == 'supervisor':
        parts = [identity(task), task['brief']]
        subject = L['tasks'].get(task.get('supervises'))
        if subject:
            used = frontier.usage(subject, L, time.time())
            parts.append(f"Subject's current run: {used['gpu_seconds'] / 60:.1f} GPU minutes; "
                         f"{used['generated_tokens']:,} generated tokens. Read its task for current counters.")
        parts.append(ending(task, where))
        return '\n\n'.join(parts)
    parts = [location(task, where), identity(task), what(task, where)]
    parts.append(ending(task, where))
    return "\n\n".join(parts)


PLANNERS = ('manager', 'steward', 'first-responder', 'operator', 'supervisor')


def unbound_tests(project_name: str, limit: int = 40) -> list[dict]:
    """Accepted test packets nothing depends on: a planner that can't see them writes them again."""
    mine = [r for r in queues.records().values() if r['project'] == project_name]
    wanted = {name for r in mine if not r.get('replaced_by') for name in r.get('depends', [])}
    # Accepted via tests: held off main as hidden tests until an implementation depends on them.
    unbound = [r for r in mine if r.get('stage') == 'test-contract' and (r.get('done') or {}).get('via') == 'tests'
               and not r.get('correction') and r['item'] not in wanted]
    return sorted(unbound, key=lambda r: -r['done'].get('at', 0))[:limit]


def identity(task: dict) -> str:
    """Who the run is, stated so it never has to infer its role from the kind or the code."""
    called = f"Your name is {task['name']}. " if task.get("name") else ""
    return (f"Task: `{task['id']}` ({task['role']}). {called}"
            f"Task start date: {task['prompt_date']} (fixed; run `date` for the current date and time).")


def location(task: dict, where: dict) -> str:
    granted = stations.of(task)["tools"]
    reach = f"\nStation tools beyond the standard set: {', '.join(granted)}." if granted else ""
    return place_text(task, where) + reach


def place_text(task: dict, where: dict) -> str:
    if stations.stationed(task):
        return (f"Station: {task['worktree']}. This is your working directory; your writes are confined to it, "
                "Check what is already there before changing it.")
    if task["branch"] is None:
        if task['role'] != 'operator':
            text = (f"Working directory: {task['worktree']} (private scratch). This is a system task. Inspect assignments and projects "
                    "through cointos_task, cointos_log and cointos_source. Use knowledge-tree tools for maintained answers.")
            if task['role'] == 'test-auditor':
                text += ' Prepare accepted project files with cointos_diagnostic before running suites.'
            return text
        return (f"Scope: the installed CointOS runtime ({task['worktree']}) and the explicitly named accessible paths. "
                "This is a system task.")
    return f"Working directory: {task['worktree']}. Project: {where['name']}."


def what(task: dict, where: dict) -> str:
    kind = task["kind"]
    if kind in ("item", "integrate", "breakdown"):
        job = {'item': 'Carry out', 'integrate': 'Review', 'breakdown': 'Plan'}[kind]
        return f"{job} this task. Read cointos_task {task['id']} for its current brief and contract."
    if kind == "garden":
        return f"Verify only these selected root-relative leaves (brown first when present):\n\n{task['brief']}"
    if kind == "first-response":
        if not task.get("repair_origin"):
            return task["brief"]
        return recovery_assignment(task)
    if kind == "operator":
        if task.get('repair_origin'):
            return ('Recover this current assignment with the declared Operator controls. '
                    'Use cointos_task for full evidence; old repair briefs carry no authority.\n\n' +
                    recovery_assignment(task))
        return f"Ad-hoc operator assignment. Abilities: {', '.join(task['abilities'])}.\n\n{task['brief']}"
    return task["brief"] or "Choose one concern as your role describes."


def recovery_assignment(task: dict) -> str:
    """A recovery starts from a pointer, not a replay of the failed investigation."""
    origin = task['repair_origin']['task']
    return (schema.RECOVERY_GOAL.format(task=origin) +
            f" Read cointos_task {task['id']} for the current assignment and failure evidence.")



def ending(task: dict, where: dict) -> str:
    return "Finish with the appropriate CointOS tool."
