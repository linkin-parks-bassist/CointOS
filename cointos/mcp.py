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
import subprocess
import sys
import time

from cointos import cli
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


BUDGET = {"generation_seconds": {"type": "number", "description": "override the run's generation-seconds budget"},
          "generation_tokens": {"type": "integer", "description": "override the run's generated-token budget"}}
BUDGET_FLAGS = {"generation_seconds": "--generation-seconds", "generation_tokens": "--generation-tokens"}
WORK = {"stage": choice(cli.schema.STAGES, "construction stage of a worker item"),
        "reasoning_effort": choice(cli.schema.EFFORTS, "deliberate reasoning-effort override")}
WORK_FLAGS = {"stage": "--stage", "reasoning_effort": "--reasoning-effort"}

MANAGERS = ("manager",)
REPAIRERS = MANAGERS + ("operator",)
SCOUTS = ("steward", "test-auditor")
LANDERS = ("manager", "gardener", "tree-auditor", "operator")
SPAWNERS = ("manager", "integrator", "steward", "test-auditor", "gardener", "tree-auditor", "operator")
EVERYONE = None


def finish_args(arguments):
    result = (['finish', '--complete', arguments['complete']] if arguments.get('complete')
              else ['finish', '--blocked', arguments['blocked']])
    if 'scout_result' in arguments:
        result += ['--scout-result-json', json.dumps(arguments['scout_result'])]
    return result

# name: (roles or EVERYONE, description, properties, required, argv builder)
TOOLS = {
    'handoff': (MANAGERS, 'Finish planning by atomically queueing a runnable set of child assignments and '
                'submitting your completion receipt. Use this as soon as the next boundary is clear; '
                'children continue independently. Requires a clean published planning branch. '
                'Invalid graphs create no children. Ends this run.',
                {'summary': text('planning decision and remaining frontier'),
                 'items': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'properties': {
                     'name': text('new item name'), 'brief': text('behavior, scope and acceptance'),
                     'kind': choice(cli.schema.QUEUE_KINDS, 'queued, urgent or command'),
                     **WORK, **QUEUE_FIELDS}, 'required': ['name', 'brief', 'summary', 'dependencies']}}},
                ['summary', 'items'], lambda a: ['handoff', a['summary'], '--items-json', json.dumps(a['items'])]),
    "finish": (EVERYONE, "Submit this run's one completion receipt: exactly one of complete (evidence that the "
               "assigned concern is done) or blocked (the specific blocker). Ends the run.",
               {"complete": text("evidence the assigned concern is complete"),
                "blocked": text("specific blocker requiring intervention")}, [],
               finish_args),
    "task": (EVERYONE, "Show current work, binding accepted tests, actual correction owners and receipts. "
             "Recovery IDs resolve their canonical assignment. Request history only for older execution evidence.",
             {"task": text("PROJECT:NAME task id"),
              "history": {"type": "boolean", "description": "include full historical execution narratives"}},
             ["task"], lambda a: ["task", a["task"]] + (["--history"] if a.get("history") else [])),
    "jobs": (EVERYONE, "List every unfinished task, including held work, plus recent terminal history. "
             "Filter by project for current work discovery; use all only for historical investigation. "
             "Use task for the full brief, linked queue, holds and receipts.",
             {"all": {"type": "boolean", "description": "include complete history for historical investigation"},
              "project": text("exact project name; omit to inspect all projects")}, [],
             lambda a: ["jobs"] + (["--all"] if a.get("all") else []) + flags(a, {"project": "--project"})),
    "status": (EVERYONE, "Show the daemon, agents, work counts, memory and models.", {}, [], lambda a: ["status"]),
    "merge": (LANDERS, "Land this run's committed maintenance branch on main. Refuses pending canonical knowledge "
              "answer/policy overlaps; preserve both drafts and report blocked rather than overwriting the owner.",
              {}, [], lambda a: ["merge"]),
    "review": (("integrator",), "Show the worker's submitted change and report for review.", {}, [], lambda a: ["review"]),
    "land": (("integrator",), "Land the reviewed worker item through the daemon's exact-candidate gate. Ends the run.",
             {"summary": text("what landed and the evidence it is correct")}, ["summary"], lambda a: ["land", a["summary"]]),
    "return": (("integrator",), "Send the item back to its worker with actionable notes. Ends the run.",
               {"notes": text("what the worker must change")}, ["notes"], lambda a: ["return", a["notes"]]),
    "incorporate": (("integrator",), "Settle an implementation already present on main. Ends the run.",
                    {"task": text("PROJECT:NAME task in review"), "commit": text("exact current main commit SHA"),
                     "worker_commit": text("exact submitted worker commit SHA")}, ["task", "commit", "worker_commit"],
                    lambda a: ["incorporate", a["task"], "--commit", a["commit"], "--worker-commit", a["worker_commit"]]),
    "queue": (REPAIRERS + SCOUTS + ("integrator",), "Add an item to a project's queue. The brief is plain text: "
              "no quoting or escaping is needed.",
              {"project": text("project name"), "name": text("new item name"),
               "brief": text("product behavior, scope and acceptance in plain prose; metadata uses separate fields"),
               "kind": choice(cli.schema.QUEUE_KINDS, "queued (default), urgent or command"), **WORK, **BUDGET, **QUEUE_FIELDS},
              ["project", "name", "brief", "summary", "dependencies"],
              lambda a: ["queue", a["project"], a["name"], a["brief"]] + flags(a, {"kind": "--kind", **WORK_FLAGS, **BUDGET_FLAGS}) + queue_fields(a)),
    "hold": (REPAIRERS, "Hold a queue item so it does not start (and stops a run of it) while you decide; "
             "release=true lifts your hold.",
             {"item": text("PROJECT:ITEM"), "release": {"type": "boolean"}}, ["item"],
             lambda a: ["hold", a["item"]] + (["--release"] if a.get("release") else [])),
    'correct_tests': (REPAIRERS, 'Correct an invalid accepted test contract through an independent test worker '
                     'and reviewer. The original stays binding until review accepts the correction; dependent '
                     'implementations then resume automatically with their artifacts preserved. Repeated '
                     'requests for the same contract return its existing correction owner. For a recovery '
                     'controller this also checks and records complete handback atomically, ending its run; '
                     'commit and merge your changes first. Managers and ad-hoc Operators only queue the correction.',
                     {'project': text('project name'), 'packet': text('accepted PROJECT:ITEM test packet'),
                      'name': text('new correction item name'), 'brief': text('correct behavior and assertions'),
                      'reason': text('contract defect and independently checked evidence'),
                      'summary': text('short description'), 'relies_on': QUEUE_FIELDS['relies_on']},
                     ['project', 'packet', 'name', 'brief', 'reason', 'summary', 'relies_on'],
                     lambda a: ['correct-tests', a['project'], a['packet'], a['name'], a['brief'],
                                '--reason', a['reason'], '--summary', a['summary'],
                                '--relies-on-json', json.dumps(a['relies_on'])]),
    'resume': (('operator',), 'Release a repaired infrastructure admission hold in your scope. '
               'Explicit user holds remain under user authority.', {'task': text('PROJECT:TASK')}, ['task'],
               lambda a: ['resume', a['task']]),
    "check_work": (REPAIRERS + SCOUTS + ("integrator", "worker"),
                   "Validate before handoff: omit brief to inspect your queued frontier. For scouts this supplies "
                   "every enabled project's accepted plan, current queue and recent acceptances; a fresh "
                   "review is required before no_action. Supply a draft to "
                   "check metadata, dependency IDs, unknown prerequisites, cycles and declared APIs without "
                   "queueing it. Existing-work checks also report uncommitted work and the required native "
                   "receipt, uncommitted files outside a worker's stage, staged/unstaged review candidate integrity "
                   "including untracked protected files, and production edits in test-packet reviews. Preserve out-of-scope diagnostics "
                   "separately and restore those files before committing. "
                   "Maintenance checks include forbidden staged, unstaged and untracked paths as well as committed history. "
                   "Pending canonical knowledge answer/policy overlaps also refuse; lifecycle stamps alone do not. "
                   "Allowed integrator staging is valid. Green preflight is not semantic acceptance. "
                   "Ordinary dependency waits are valid. Returns exact problems to fix.",
                   {"project": text("project name; defaults to your project"), "name": text("new proposal name"),
                    "brief": text("draft product assignment; omit to check existing queued work"),
                    "kind": choice(cli.schema.QUEUE_KINDS, "queued, urgent or command"),
                    **WORK, **BUDGET, **QUEUE_FIELDS}, [],
                   lambda a: ["check-work"] + flags(a, {"project": "--project", "name": "--name",
                       "brief": "--brief", "kind": "--kind", **WORK_FLAGS, **BUDGET_FLAGS}) + queue_fields(a)),
    "revise": (REPAIRERS, "Replace a held item's brief; omitted stage, effort and budget are retained. "
               "Retain accepted test-contract dependencies on implementation/integration work; discarding them is refused.",
               {"item": text("PROJECT:ITEM"), "brief": text("the complete revised brief"),
                "reason": text("why the item changes"), **WORK, **BUDGET, **QUEUE_FIELDS},
               ["item", "brief", "reason", "summary", "dependencies"],
               lambda a: ["revise", a["item"], a["brief"], "--reason", a["reason"]] + flags(a, {**WORK_FLAGS, **BUDGET_FLAGS}) + queue_fields(a)),
    "cancel": (REPAIRERS, "Withdraw unaccepted queue items for good. Name dependents in the same call.",
               {"items": {"type": "array", "items": {"type": "string"}, "description": "PROJECT:ITEM ids"},
                "reason": text("why")}, ["items", "reason"],
               lambda a: ["cancel", *a["items"], "--reason", a["reason"]]),
    "replace": (("operator",), "Hand this recovery controller's origin to existing same-project queue items, "
                "repointing dependents and recording your complete receipt atomically, without duplicating work. "
                "Commit and merge your own changes first. This ends your run; no separate finish call is needed. "
                "Revising another item alone does not establish this handoff.",
                {"children": {"type": "array", "items": {"type": "string"}, "description": "existing item names without project prefixes"}},
                ["children"], lambda a: ["replace", *a["children"]]),
    "supersede": (REPAIRERS, "Replace failed prerequisites with existing same-project items without accepting them.",
                  {"task": text("PROJECT:FAILED"), "replacements": {"type": "array", "items": {"type": "string"}},
                   "reason": text("evidence")}, ["task", "replacements", "reason"],
                  lambda a: ["supersede", a["task"], *a["replacements"], "--reason", a["reason"]]),
    "budget": (REPAIRERS, "Set waiting or undispatched generation limits, or increase a running task's allowance without resetting usage.",
               {"task": text("PROJECT:TASK"), **BUDGET}, ["task"], lambda a: ["budget", a["task"]] + flags(a, BUDGET_FLAGS)),
    "operator": (SPAWNERS, "Start an operator: a general agent for work the pipeline has no route for. Its budget "
                 "comes out of what this run has left, and it gets no ability this run lacks.",
                 {"name": text("short operator name"), "brief": text("its complete assignment"),
                  "project": text("project it works in; omit for system scope"), **BUDGET},
                 ["name", "brief", "generation_tokens", "generation_seconds"],
                 lambda a: ["agent", "run", a["name"], a["brief"]] + flags(a, {"project": "--project", **BUDGET_FLAGS})),
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
    """What a run's worktree has changed since its base commit, committed or not."""
    worktree, base = task.get("worktree"), task.get("base_commit")
    if not (worktree and base and os.path.isdir(worktree) and task.get("branch")):
        return ""
    result = subprocess.run(["git", "-C", worktree, "diff", "--stat=120", base], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


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
              "files its branch has changed. Check it before changing shared files or interfaces.", {}, []),
    "send": ("Send a short message to another active task (PROJECT:NAME, as `jobs` shows), a local external mailbox "
             "('mailbox:NAME', without phone alerts), or to the user ('user'). "
             "Use it to ask or tell, not to hand off work: queued work still goes through the queue.",
             {"to": text("PROJECT:NAME task id, 'mailbox:NAME', or 'user'"), "text": text("the message")}, ["to", "text"]),
    "inbox": ("Read this task's unread messages; reading marks them read. wait=true blocks until a message "
              "arrives (up to 5 minutes) instead of returning empty: use it to wait for a reply instead of sleeping.",
              {"wait": {"type": "boolean", "description": "block until a message arrives"}}, []),
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
        messages = call("inbox", identity())["messages"]
        deadline = time.monotonic() + 300
        while arguments.get("wait") and not messages and time.monotonic() < deadline:
            time.sleep(2)
            messages = call("inbox", identity())["messages"]
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


def catalogue(for_role: str | None) -> list[dict]:
    tools = [{"name": name, "description": description,
              "inputSchema": {"type": "object", "properties": properties, "required": required}}
             for name, (roles, description, properties, required, _) in TOOLS.items()
             if roles is EVERYONE or for_role in roles]
    if for_role == 'steward':
        finish = next(tool for tool in tools if tool['name'] == 'finish')
        finish['inputSchema']['properties'] = {**finish['inputSchema']['properties'], 'scout_result': {
            'type': 'object', 'additionalProperties': False,
            'description': 'Required for complete. Approved unfinished work needs manager_handoff, not user_decision. '
                           'A local user alert is not a manager handoff or Telegram delivery.',
            'properties': {
                'kind': {'type': 'string', 'enum': ['no_action', 'manager_handoff', 'user_decision']},
                'handoff': text('exact PROJECT:ITEM command queued by this steward; required for manager_handoff'),
                'checked_projects': {'type': 'array', 'items': {'type': 'string'},
                                     'description': 'all enabled projects whose remaining plans were checked; required for no_action'},
                'question': text('specific new decision requiring personal user authority; required for user_decision')},
            'required': ['kind']}}
    tools += [{"name": name, "description": description,
               "inputSchema": {"type": "object", "properties": properties, "required": required}}
              for name, (description, properties, required) in MESSAGE_TOOLS.items()]
    return tools


def missing(required: list[str], arguments: dict) -> str | None:
    absent = [key for key in required if arguments.get(key) in (None, "")]
    return f"missing required argument(s): {', '.join(absent)}" if absent else None


def invoke(name: str, arguments: dict, for_role: str | None) -> tuple[str, bool]:
    if problem := unexpected_arguments(name, arguments, for_role):
        return problem, True
    if name in MESSAGE_TOOLS:
        if problem := missing(MESSAGE_TOOLS[name][2], arguments):
            return problem, True
        result, failed = message_tool(name, arguments)
    elif name in TOOLS and (TOOLS[name][0] is EVERYONE or for_role in TOOLS[name][0]):
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
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "cointos", "version": "1"}}
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
        elif params.get('name') == 'check_work' and for_role in TOOLS['check_work'][0]:
            body = {key: arguments[key] for key in ('project', 'name', 'brief', 'kind', 'stage',
                    'reasoning_effort', 'dependencies', 'relies_on', 'summary')
                    if arguments.get(key) is not None}
            budget = {key: arguments[key] for key in cli.schema.BUDGET_KEYS if arguments.get(key) is not None}
            if budget:
                body['budget'] = budget
            try:
                checked = call('check-work', body)
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
