"""The agents' MCP server: CointOS controls as typed tools instead of shell commands.

OpenCode starts one per agent run over stdio, in the run's environment (`COINTOS_TASK_ID`,
`COINTOS_AGENT`). Tools share the CLI/API domain implementation without a shell.
Validation returns native structured data and marks failed checks as tool errors.
A run sees only its role's tools. Every result ends with a notice when the
run's task has unread messages from other agents or the user.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import time

from cointos import cli
from cointos.config import ROOT
from cointos.client import Unreachable, call, ledger

PROTOCOL = "2025-06-18"


def text(description: str) -> dict:
    return {"type": "string", "description": description}


def choice(values, description: str) -> dict:
    return {"type": "string", "enum": list(values), "description": description}


def flags(arguments: dict, names: dict) -> list[str]:
    """`--flag value` pairs for the optional arguments present."""
    argv = []
    for key, flag in names.items():
        if arguments.get(key) not in (None, ""):
            argv += [flag, str(arguments[key])]
    return argv


def dispatch_argv(a: dict) -> list[str]:
    """The same tool Coin has. The CLI names this run as the caller, and the daemon decides."""
    station = a.get("station") or {}
    argv = ["agent", "run", a["name"], a["brief"]] + flags({**a, **station}, {
        "project": "--project", "role": "--role", "task": "--task", "stage": "--stage", "directory": "--directory",
        "reasoning_effort": "--reasoning-effort", "generation_seconds": "--generation-seconds",
        "generation_tokens": "--generation-tokens"})
    for ability in a.get("abilities") or []:
        argv += ["--ability", ability]
    for tool in station.get("tools") or []:
        argv += ["--tool", tool]
    return argv + queue_fields(a)


QUEUE_FIELDS = {
    "dependencies": {"type": "array", "items": {"type": "string"},
                     "description": "prerequisite item IDs, optionally PROJECT:ITEM; [] means none"},
    "summary": text("short dashboard description"),
    "relies_on": {"type": "array", "items": {"type": "string"},
                  "description": "existing API names used by test witnesses; required for test-contract work"}}


def queue_fields(arguments: dict) -> list[str]:
    argv = flags(arguments, {"summary": "--summary"})
    for key, flag in (("dependencies", "--dependencies-json"), ("relies_on", "--relies-on-json")):
        if key in arguments:
            argv += [flag, json.dumps(arguments[key])]
    return argv


BUDGET = {"generation_tokens": {"type": "integer", "description": "override the run's generated-token budget"}}
BUDGET_FLAGS = {"generation_seconds": "--generation-seconds", "generation_tokens": "--generation-tokens"}
WORK = {"stage": choice(cli.schema.STAGES, "construction stage of a worker item"),
        "reasoning_effort": choice(cli.schema.EFFORTS, "deliberate reasoning-effort override")}
WORK_FLAGS = {"stage": "--stage", "reasoning_effort": "--reasoning-effort"}

MANAGERS = ("manager",)
REPAIRERS = MANAGERS + ("operator", "first-responder")
SCOUTS = ("steward", "test-auditor")
LANDERS = ("manager", "gardener", "tree-auditor", "operator")
SPAWNERS = ("manager", "integrator", "steward", "test-auditor", "gardener", "tree-auditor", "operator", "first-responder")
EVERYONE = None


def finish_args(arguments):
    result = (['finish', '--complete', arguments['complete']] if arguments.get('complete')
              else ['finish', '--blocked', arguments['blocked']])
    if 'scout_result' in arguments:
        result += ['--scout-result-json', json.dumps(arguments['scout_result'])]
    return result

# name: (roles or EVERYONE, description, properties, required, argv builder)
TOOLS = {
    'handoff': ((*MANAGERS, 'supervisor'), 'Capture and publish the plan while atomically queueing a runnable set of child assignments and '
                'submitting your completion receipt. Use this as soon as the next boundary is clear; '
                'children continue independently. '
                'Invalid graphs create no children. Ends this run.',
                {'summary': text('planning decision and remaining frontier'),
                 'items': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'properties': {
                     'name': text('new item name'), 'brief': text(cli.schema.BRIEF_DESCRIPTION),
                     'kind': choice(cli.schema.QUEUE_KINDS, 'queued, urgent or command'),
                     **WORK, **QUEUE_FIELDS}, 'required': ['name', 'brief', 'summary', 'dependencies']}}},
                ['summary', 'items'], lambda a: ['handoff', a['summary'], '--items-json', json.dumps(a['items'])]),
    "finish": (EVERYONE, "Capture this run's files and submit its completion receipt: exactly one of complete (evidence that the "
               "assigned concern is done) or blocked (the specific blocker). Ends the run.",
               {"complete": text("evidence the assigned concern is complete"),
                "blocked": text("specific blocker requiring intervention")}, [],
               finish_args),
    "task": (EVERYONE, "Inspect the named current assignment. "
             "Recovery IDs resolve their canonical assignment. Request history only for older execution evidence.",
             {"task": text("PROJECT:NAME task id"),
              "history": {"type": "boolean", "description": "include full historical execution narratives"}},
             ["task"], lambda a: ["task", a["task"]] + (["--history"] if a.get("history") else [])),
    "jobs": (EVERYONE, "List unfinished tasks, including held work, and recent queue outcomes. Completed standalone runs require all=true. "
             "Filter by project for current work discovery; use all only for historical investigation. "
             "Use task for the full brief, linked queue, holds and receipts.",
             {"all": {"type": "boolean", "description": "include complete history for historical investigation"},
              "project": text("exact project name; omit to inspect all projects")}, [],
             lambda a: ["jobs"] + (["--all"] if a.get("all") else []) + flags(a, {"project": "--project"})),
    "status": (EVERYONE, "Show the daemon, agents, work counts, memory and models.", {}, [], lambda a: ["status"]),
    "merge": (LANDERS, "Publish this run's scoped maintenance changes. Refuses pending canonical knowledge "
              "answer/policy overlaps; preserve both drafts and report blocked rather than overwriting the owner.",
              {}, [], lambda a: ["merge"]),
    "review": (("integrator",), "Show the worker's submitted change and report for review.", {}, [], lambda a: ["review"]),
    'diagnostic': (('integrator', 'test-auditor', 'first-responder'),
                   'Integrator: list retained worker probes or copy one into scratch. '
                   'Test auditor: name project to prepare accepted files in scratch. '
                   'First Responder: omit arguments to prepare your failed assignment\'s retained files in scratch for reproduction.',
                   {'path': text('integrator: relative diagnostic file; omit to list'),
                    'project': text('test auditor: project whose accepted files to prepare')}, [],
                   lambda a: ['diagnostic'] + flags(a, {'path': '--path', 'project': '--project'})),
    "land": (("integrator",), "Accept the reviewed files. CointOS validates and publishes the exact result. Ends the run.",
             {"summary": text("what landed and the evidence it is correct")}, ["summary"], lambda a: ["land", a["summary"]]),
    "return": (("integrator",), "Send the item back to its worker with actionable notes. Ends the run.",
               {"notes": text("what the worker must change")}, ["notes"], lambda a: ["return", a["notes"]]),
    "incorporate": (("integrator",), "Settle an implementation already present on main. Ends the run.",
                    {"task": text("PROJECT:NAME task in review")}, ["task"],
                    lambda a: ["incorporate", a["task"]]),
    "queue": (EVERYONE, "Add an item to a project's queue. The brief is plain text: "
              "no quoting or escaping is needed.",
              {"project": text("project name"), "name": text("new item name"),
               "brief": text(cli.schema.BRIEF_DESCRIPTION),
               "kind": choice(cli.schema.QUEUE_KINDS, "queued (default), urgent or command"), **WORK, **BUDGET, **QUEUE_FIELDS},
              ["project", "name", "brief", "summary", "dependencies"],
              lambda a: ["queue", a["project"], a["name"], a["brief"]] + flags(a, {"kind": "--kind", **WORK_FLAGS, **BUDGET_FLAGS}) + queue_fields(a)),
    "hold": (EVERYONE, "Hold a queue item so it does not start (and stops a run of it) while you decide; "
             "release=true lifts your hold.",
             {"item": text("PROJECT:ITEM"), "release": {"type": "boolean"}}, ["item"],
             lambda a: ["hold", a["item"]] + (["--release"] if a.get("release") else [])),
    'correct_tests': (EVERYONE, 'Correct an invalid accepted test contract through an independent test worker '
                     'and reviewer. The original stays binding until review accepts the correction; dependent '
                     'implementations then resume automatically with their artifacts preserved. Repeated '
                     'requests for the same contract return its existing correction owner. For a recovery '
                     'controller this also checks and records complete handback atomically, ending its run; '
                     'publish your scoped changes first. Managers and ad-hoc Operators only queue the correction.',
                     {'project': text('project name'), 'packet': text('accepted PROJECT:ITEM test packet'),
                      'name': text('new correction item name'), 'brief': text(cli.schema.BRIEF_DESCRIPTION),
                      'reason': text('contract defect and independently checked evidence'),
                      'summary': text('short description'), 'relies_on': QUEUE_FIELDS['relies_on']},
                     ['project', 'packet', 'name', 'brief', 'reason', 'summary', 'relies_on'],
                     lambda a: ['correct-tests', a['project'], a['packet'], a['name'], a['brief'],
                                '--reason', a['reason'], '--summary', a['summary'],
                                '--relies-on-json', json.dumps(a['relies_on'])]),
    'resume': (EVERYONE, 'Release a repaired infrastructure admission hold in your scope. '
               'Not a retry/restart for failed work: the task must have an infrastructure admission_hold. '
               'For failed work inspect its task and recovery owner. Explicit user holds remain under user authority.',
               {'task': text('PROJECT:TASK')}, ['task'],
               lambda a: ['resume', a['task']]),
    "check_work": (EVERYONE,
                   "Check current work or validate a proposal. A proposal check creates no work; dispatch separately.",
                   {"project": text("project name; defaults to your project"), "name": text("new proposal name"),
                    "brief": text("draft product assignment; omit to check existing queued work"),
                    "kind": choice(cli.schema.QUEUE_KINDS, "queued, urgent or command"),
                    **WORK, **BUDGET, **QUEUE_FIELDS}, [],
                   lambda a: ["check-work"] + flags(a, {"project": "--project", "name": "--name",
                       "brief": "--brief", "kind": "--kind", **WORK_FLAGS, **BUDGET_FLAGS}) + queue_fields(a)),
    "revise": (EVERYONE, "Revise an unaccepted assignment within your authority; no prior hold is required. "
               "A changed assignment starts a fresh conversation; identical input is a no-op. "
               "Omitted stage, effort and budget metadata and explicit user holds remain. "
               "Retain accepted test-contract dependencies; discarding them is refused.",
               {"item": text("PROJECT:ITEM"), "brief": text(cli.schema.BRIEF_DESCRIPTION),
                "reason": text("why the item changes"), **WORK, **BUDGET, **QUEUE_FIELDS},
               ["item", "brief", "reason", "summary", "dependencies"],
               lambda a: ["revise", a["item"], a["brief"], "--reason", a["reason"]] + flags(a, {**WORK_FLAGS, **BUDGET_FLAGS}) + queue_fields(a)),
    "cancel": (EVERYONE, "Withdraw unaccepted queue items for good. Name dependents in the same call.",
               {"items": {"type": "array", "items": {"type": "string"}, "description": "PROJECT:ITEM ids"},
                "reason": text("why")}, ["items", "reason"],
               lambda a: ["cancel", *a["items"], "--reason", a["reason"]]),
    "replace": (("operator", "first-responder"), "Hand this First Responder's origin to existing same-project queue items, "
                "repointing dependents and recording your complete receipt atomically, without duplicating work. "
                "This ends your run; no separate finish call is needed. "
                "Revising another item alone does not establish this handoff.",
                {"children": {"type": "array", "items": {"type": "string"}, "description": "existing item names without project prefixes"}},
                ["children"], lambda a: ["replace", *a["children"]]),
    'metrics': (("first-responder", "manager", "integrator", "operator", "steward", "test-auditor"),
                'Summarize recent pipeline landings, gate returns and recovery spending through CointOS. '
                'Reports retained journal coverage; does not require runtime-file access.',
                {'hours': {'type': 'number', 'description': 'recent window in hours; omit for the CLI default'}}, [],
                lambda a: ['metrics'] + flags(a, {'hours': '--hours'})),
    'source': (("supervisor", "first-responder", "manager", "integrator", "operator", "steward", "test-auditor"),
               'Read accepted project source or assigned task files through CointOS. Name exactly one task or project. '
               'Omit path to list files (task lists changed files); use a relative file to read numbered lines. '
               'A task that never prepared files may have no retained source view; use project for accepted source. '
               'Use log for execution/tool records and knowledge-tree tools for maintained answers.',
               {'task': text('PROJECT:TASK'), 'project': text('project name'),
                'path': text('relative file, or directory ending in /'),
                'start': {'type': 'integer', 'description': 'first line or list entry, starting at 1'},
                'limit': {'type': 'integer', 'description': 'page size; omit for configured default'}}, [],
               lambda a: ['source'] + flags(a, {key: '--' + key for key in ('task', 'project', 'path', 'start', 'limit')})),
    "log": (("supervisor", "first-responder", "manager", "integrator", "operator", "steward", "test-auditor"),
            "Read an assignment's record through CointOS. Supervisors/First Responders can also inspect Coin. With no show: a numbered "
            "index of its thoughts, replies and tool calls, newest last, filtered by kind, turn or grep. With show N or N-M: "
            "those entries in full.",
            {"task": text("PROJECT:TASK, or coin"), "show": text("entry N or range N-M to read in full"),
             "kind": choice(("thought", "reply", "tool", "user", "compaction", "system"), "only this kind"),
             "turn": {"type": "integer", "description": "only this turn"}, "grep": text("only entries containing this text"),
             "last": {"type": "integer", "description": "how many index lines (default 40)"}}, ["task"],
            lambda a: ["log", a["task"]] + flags(a, {"show": "--show", "kind": "--kind", "turn": "--turn", "grep": "--grep", "last": "--last"})),
    "split": (EVERYONE, "This job is too big for one agent: stop an implementer or Operator and hand its work "
              "and files to a manager to cut up much smaller.",
              {"task": text("PROJECT:TASK"), "reason": text("why it is too big and what is worth keeping")}, ["task", "reason"],
              lambda a: ["split", a["task"], "--reason", a["reason"]]),
    "recover": (EVERYONE, "This assignment is malformed: stop its run, preserving its work, and send it to "
                "a First Responder to work out and dispatch the fix.",
                {"task": text("PROJECT:TASK"), "reason": text("what is wrong with the assignment, with evidence")},
                ["task", "reason"], lambda a: ["recover", a["task"], "--reason", a["reason"]]),
    "supersede": (EVERYONE, "Replace failed prerequisites with existing same-project items without accepting them.",
                  {"task": text("PROJECT:FAILED"), "replacements": {"type": "array", "items": {"type": "string"}},
                   "reason": text("evidence")}, ["task", "replacements", "reason"],
                  lambda a: ["supersede", a["task"], *a["replacements"], "--reason", a["reason"]]),
    "budget": (EVERYONE, "Set waiting or undispatched generation limits, or increase a running task's allowance without resetting usage.",
               {"task": text("PROJECT:TASK"), **BUDGET}, ["task"], lambda a: ["budget", a["task"]] + flags(a, BUDGET_FLAGS)),
    "dispatch": (EVERYONE, cli.schema.DISPATCH_DESCRIPTION, cli.schema.DISPATCH_PROPERTIES, ["name", "brief"], dispatch_argv),
}


def run_cli(argv: list[str]) -> tuple[str, bool]:
    """Run one CLI command in-process; its printed output and whether it failed."""
    out, err = io.StringIO(), io.StringIO()
    failed = False
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(argv, acknowledge=False)
        except SystemExit as stop:
            failed = stop.code not in (None, 0)
            if isinstance(stop.code, str):
                print(stop.code, file=err)
        except (Unreachable, ValueError) as error:
            failed = True
            print(str(error), file=err)
    return (out.getvalue() + err.getvalue()).strip() or ("failed" if failed else "done"), failed


# ---------------------------------------------------------------- messages

def summary(brief: str) -> str:
    """A brief's `Summary:` line, else its first line."""
    found = re.search(r"^Summary:\s*(.+)$", brief or "", re.M)
    return (found[1] if found else (brief or "").strip().split("\n")[0])[:160]


def changed_files(task: dict) -> str:
    """Ask the artifact owner for a file summary; agents never open peer repositories."""
    try:
        return call('workspace-changes', {'task': task['id']})['changes']
    except (ValueError, Unreachable):
        return ''


def peers() -> tuple[str, bool]:
    """Every other live run: what it is for, what it is doing now and what it has changed."""
    me = identity()["task"]
    try:
        state = ledger()
    except Unreachable as error:
        return str(error), True
    sections = []
    for agent in state["agents"].values():
        task = state["tasks"].get(agent["task"]) or {}
        if agent["task"] == me or not task:
            continue
        called = f"{task['name']}, " if task.get("name") else ""
        lines = [f"{called}{task['id']} ({task['role']}, {agent['state']}): {summary(task.get('brief', ''))}"]
        if agent.get("doing"):
            lines.append(f"  now: {agent['doing'][:160]}")
        files = changed_files(task)
        lines.append("  changed:\n" + "\n".join("    " + line for line in files.splitlines()) if files else "  changed: nothing yet")
        sections.append("\n".join(lines))
    return ("\n\n".join(sections) or "no other agents are running"), False


MESSAGE_TOOLS = {
    "peers": ("See every other live agent run: its task id, role, what it is for, what it is doing now and which "
              "files it has changed. Check it before changing shared files or interfaces.", {}, []),
    "send": ("Send a short message to another active task (PROJECT:NAME, as `jobs` shows), a local external mailbox "
             "('mailbox:NAME', without phone alerts), or to the user ('user'). "
             "Use it to ask or tell, not to hand off work: queued work still goes through the queue.",
             {"to": text("PROJECT:NAME task id, 'mailbox:NAME', or 'user'"), "text": text("the message")}, ["to", "text"]),
    "inbox": ("Read this task's unread messages; reading marks them read. wait=true blocks until a message "
              "arrives (5 minutes, or wait_minutes up to 9) instead of returning empty: use it to wait instead of sleeping.",
              {"wait": {"type": "boolean", "description": "block until a message arrives"},
               "wait_minutes": {"type": "number", "description": "how long to wait, at most 9"}}, []),
}


def identity() -> dict:
    return {"task": os.environ.get("COINTOS_TASK_ID"), "run": os.environ.get("COINTOS_AGENT")}


def message_tool(name: str, arguments: dict) -> tuple[str, bool]:
    if name == "peers":
        return peers()
    try:
        if name == "send":
            result = call("send", {**identity(), "to": arguments["to"], "text": arguments["text"]})
            return f"sent to {result['to']}", False
        deadline = time.monotonic() + 60 * max(0, min(float(arguments.get("wait_minutes") or 5), 9))
        while True:
            try:
                messages, missed = call("inbox", identity())["messages"], None
            except Unreachable as error:
                # A wait rides through a slow or replaced daemon; only lasting absence is an error.
                if not arguments.get("wait"):
                    raise
                messages, missed = [], error
            if not arguments.get("wait") or messages or time.monotonic() >= deadline:
                break
            time.sleep(2)
        if missed is not None:
            raise missed
        return ("\n\n".join(f"From {m['from']}:\n{m['text']}" for m in messages) or "no unread messages"), False
    except (Unreachable, ValueError, KeyError) as error:
        return str(error), True


def unread_notice() -> str:
    task = identity()["task"]
    try:
        count = sum(1 for m in ledger().get("messages", []) if m["to"] == task and not m["read"])
    except Unreachable:
        return ""
    return f"\n\n[{count} unread message{'s' if count != 1 else ''}: call inbox]" if count else ""


# ---------------------------------------------------------------- protocol

def role() -> str | None:
    task = identity()["task"]
    try:
        return (ledger()["tasks"].get(task) or {}).get("role") if task else None
    except Unreachable:
        return None


GRANTS = {"log": "logs"}  # a tool an agent also gets when whoever dispatched it gave it that ability


def granted(name: str) -> bool:
    task = identity()["task"]
    if name not in GRANTS or not task:
        return False
    try:
        return GRANTS[name] in ((ledger()["tasks"].get(task) or {}).get("abilities") or [])
    except Unreachable:
        return False


def catalogue(for_role: str | None) -> list[dict]:
    tools = [{"name": name, "description": description,
              "inputSchema": {"type": "object", "properties": properties, "required": required,
                              "additionalProperties": False}}
             for name, (roles, description, properties, required, _) in TOOLS.items()
             if roles is EVERYONE or for_role in roles or granted(name)]
    if for_role == 'worker':
        tools = [tool for tool in tools if tool['name'] in
                 ('finish', 'task', 'check_work', 'inbox', 'send', 'peers', 'split', 'recover', 'status')]
        check = next(tool for tool in tools if tool['name'] == 'check_work')
        check['inputSchema'] = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
        task = next(tool for tool in tools if tool['name'] == 'task')
        task['description'] = 'Read the named current assignment.'
        task['inputSchema'] = {'type': 'object', 'properties': {'task': text('task ID')}, 'required': ['task'],
                               'additionalProperties': False}
    if for_role == 'supervisor':
        for tool in tools:
            if tool['name'] in ('task', 'log'):
                tool['description'] += ' Omit task to inspect your declared subject.'
                tool['inputSchema']['required'] = [key for key in tool['inputSchema']['required'] if key != 'task']
        handoff = next(tool for tool in tools if tool['name'] == 'handoff')
        handoff['description'] = ('Complete a mandatory second-Supervisor split by creating exactly two fresh '
            'worker jobs, roughly half the remaining work each. Replaces the stopped job and ends your run. '
            'No separate maintenance publication is required. First Supervisors do not use this tool.')
        properties = dict(handoff['inputSchema']['properties'])
        properties['items'] = {**properties['items'], 'minItems': 2, 'maxItems': 2}
        handoff['inputSchema']['properties'] = properties
    if for_role == 'steward':
        finish = next(tool for tool in tools if tool['name'] == 'finish')
        finish['inputSchema']['properties'] = {**finish['inputSchema']['properties'], 'scout_result': {
            'type': 'object', 'additionalProperties': False,
            'description': 'Required for complete. Approved unfinished work needs manager_handoff, not user_decision. '
                           'A local user alert is not a manager handoff or Telegram delivery.',
            'properties': {
                'kind': {'type': 'string', 'enum': ['no_action', 'manager_handoff', 'recovery_handoff', 'user_decision']},
                'handoff': text('exact command queued by this steward for manager_handoff, or First Responder task for recovery_handoff'),
                'checked_projects': {'type': 'array', 'items': {'type': 'string'},
                                     'description': 'all enabled projects whose remaining plans were checked; required for no_action'},
                'question': text('specific new decision requiring personal user authority; required for user_decision')},
            'required': ['kind']}}
    tools += [{"name": name, "description": description,
               "inputSchema": {"type": "object", "properties": properties, "required": required,
                               "additionalProperties": False}}
              for name, (description, properties, required) in MESSAGE_TOOLS.items()]
    return tools


def missing(required: list[str], arguments: dict) -> str | None:
    absent = [key for key in required if arguments.get(key) in (None, "")]
    return f"missing required argument(s): {', '.join(absent)}" if absent else None


def invoke(name: str, arguments: dict, for_role: str | None) -> tuple[str, bool]:
    if problem := unexpected_arguments(name, arguments, for_role):
        return problem, True
    if for_role == 'supervisor' and name in ('task', 'log') and 'task' not in arguments:
        try:
            own = ledger()['tasks'].get(identity()['task']) or {}
        except Unreachable as error:
            return str(error), True
        if not own.get('supervises'):
            return 'this run has no declared subject; provide task explicitly', True
        arguments = {**arguments, 'task': own['supervises']}
    if name in MESSAGE_TOOLS:
        if problem := missing(MESSAGE_TOOLS[name][2], arguments):
            return problem, True
        result, failed = message_tool(name, arguments)
    elif name in TOOLS and (TOOLS[name][0] is EVERYONE or for_role in TOOLS[name][0] or granted(name)):
        if name == "finish" and bool(arguments.get("complete")) == bool(arguments.get("blocked")):
            return "give exactly one of complete or blocked", True
        if problem := missing(TOOLS[name][3], arguments):
            return problem, True
        result, failed = run_cli(TOOLS[name][4](arguments))
    else:
        return f"unknown tool {name!r} for this role", True
    return result + ("" if name == "inbox" else unread_notice()), failed


def unexpected_arguments(name: str, arguments: dict, for_role: str | None) -> str | None:
    """Never silently discard a purported target or operation absent from the contract."""
    declaration = next((t for t in catalogue(for_role) if t['name'] == name), None)
    if declaration:
        unknown = sorted(set(arguments) - set(declaration['inputSchema'].get('properties', {})))
        if unknown:
            return 'unsupported argument(s): ' + ', '.join(unknown) + '; use the declared tool fields. '


def respond(request: dict, for_role: str | None) -> dict | None:
    method, ident = request.get("method"), request.get("id")
    if ident is None:
        return None  # a notification
    if method == "initialize":
        result = {"protocolVersion": request.get("params", {}).get("protocolVersion", PROTOCOL),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "cointos", "version": "1"},
                  "instructions": (ROOT / 'roles/_workflow.md').read_text().strip()}
    elif method == "tools/list":
        result = {"tools": catalogue(for_role)}
    elif method == "tools/call":
        params = request.get("params", {})
        arguments = params.get('arguments')
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            result = {'content':[{'type':'text','text':'tool arguments must be an object'}], 'isError':True}
        elif problem := unexpected_arguments(params.get('name', ''), arguments, for_role):
            result = {'content':[{'type':'text','text':problem}], 'isError':True}
        elif params.get('name') == 'check_work':
            body = {key: arguments[key] for key in ('project', 'name', 'brief', 'kind', 'stage',
                    'reasoning_effort', 'dependencies', 'relies_on', 'summary')
                    if arguments.get(key) is not None}
            budget = {key: arguments[key] for key in cli.schema.BUDGET_KEYS if arguments.get(key) is not None}
            if budget:
                body['budget'] = budget
            try:
                checked = cli.frontier.file_view(call('check-work', body))
                result = {'content': [{'type': 'text', 'text': json.dumps(checked)}],
                          'structuredContent': checked, 'isError': not checked['ok']}
                if notice := unread_notice():
                    result['content'].append({'type':'text', 'text':notice})
            except (ValueError, Unreachable) as error:
                result = {'content':[{'type':'text', 'text':str(error)}], 'isError':True}
        else:
            output, failed = invoke(params.get("name", ""), arguments, for_role)
            result = {"content": [{"type": "text", "text": output}], "isError": failed}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def write_reply(protocol, request: dict, reply: dict) -> None:
    """A terminal result must leave MCP's output buffer before its run is retired."""
    protocol.write(json.dumps(reply) + '\n')
    protocol.flush()
    if (request.get('method') == 'tools/call'
            and request.get('params', {}).get('name', '').replace('_', '-') in cli.TERMINAL_COMMANDS
            and cli.has_receipt_here()):
        cli.deliver_receipt()


def main() -> None:
    # Protocol messages own the real stdout; anything else written to file descriptor 1, such as
    # a subprocess a command runs, goes to stderr instead of corrupting the stream.
    protocol = os.fdopen(os.dup(1), "w")
    os.dup2(2, 1)
    for_role = role()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        reply = respond(request, for_role)
        if reply is not None:
            write_reply(protocol, request, reply)


if __name__ == "__main__":
    main()
