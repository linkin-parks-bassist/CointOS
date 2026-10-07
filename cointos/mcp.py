"""The agents' MCP server: CointOS controls as typed tools instead of shell commands.

OpenCode starts one per agent run over stdio, in the run's environment (`COINTOS_TASK_ID`,
`COINTOS_AGENT`). Each tool builds an argument vector for the same `cli` command a person
would type, so arguments never pass through a shell and both surfaces share one
implementation. A run sees only its role's tools. Every result ends with a notice when the
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


BUDGET = {"generation_seconds": {"type": "number", "description": "override the run's generation-seconds budget"},
          "generation_tokens": {"type": "integer", "description": "override the run's generated-token budget"}}
BUDGET_FLAGS = {"generation_seconds": "--generation-seconds", "generation_tokens": "--generation-tokens"}
WORK = {"stage": choice(cli.schema.STAGES, "construction stage of a worker item"),
        "reasoning_effort": choice(cli.schema.EFFORTS, "deliberate reasoning-effort override")}
WORK_FLAGS = {"stage": "--stage", "reasoning_effort": "--reasoning-effort"}

MANAGERS = ("manager",)
SCOUTS = ("steward", "test-auditor")
LANDERS = ("manager", "gardener", "tree-auditor", "operator")
EVERYONE = None

# name: (roles or EVERYONE, description, properties, required, argv builder)
TOOLS = {
    "finish": (EVERYONE, "Submit this run's one completion receipt: exactly one of complete (evidence that the "
               "assigned concern is done) or blocked (the specific blocker). Ends the run.",
               {"complete": text("evidence the assigned concern is complete"),
                "blocked": text("specific blocker requiring intervention")}, [],
               lambda a: ["finish", "--complete", a["complete"]] if a.get("complete") else ["finish", "--blocked", a["blocked"]]),
    "task": (EVERYONE, "Show one exact task and its queue record, receipts and dependencies.",
             {"task": text("PROJECT:NAME task id")}, ["task"], lambda a: ["task", a["task"]]),
    "jobs": (EVERYONE, "List recent and active tasks with their states.",
             {"all": {"type": "boolean", "description": "include all history"}}, [],
             lambda a: ["jobs"] + (["--all"] if a.get("all") else [])),
    "status": (EVERYONE, "Show the daemon, agents, work counts, memory and models.", {}, [], lambda a: ["status"]),
    "merge": (LANDERS, "Land this run's committed branch on its project's main branch.", {}, [], lambda a: ["merge"]),
    "review": (("integrator",), "Show the worker's submitted change and report for review.", {}, [], lambda a: ["review"]),
    "land": (("integrator",), "Land the reviewed worker item through the daemon's exact-candidate gate. Ends the run.",
             {"summary": text("what landed and the evidence it is correct")}, ["summary"], lambda a: ["land", a["summary"]]),
    "return": (("integrator",), "Send the item back to its worker with actionable notes. Ends the run.",
               {"notes": text("what the worker must change")}, ["notes"], lambda a: ["return", a["notes"]]),
    "incorporate": (("integrator",), "Settle an implementation already present on main. Ends the run.",
                    {"task": text("PROJECT:NAME task in review"), "commit": text("exact current main commit SHA"),
                     "worker_commit": text("exact submitted worker commit SHA")}, ["task", "commit", "worker_commit"],
                    lambda a: ["incorporate", a["task"], "--commit", a["commit"], "--worker-commit", a["worker_commit"]]),
    "queue": (MANAGERS + SCOUTS + ("integrator",), "Add an item to a project's queue. The brief is plain text: "
              "no quoting or escaping is needed.",
              {"project": text("project name"), "name": text("new item name"),
               "brief": text("the complete brief, including Summary:, Depends on: and Relies on: lines as required"),
               "kind": choice(cli.schema.QUEUE_KINDS, "queued (default), urgent or command"), **WORK, **BUDGET},
              ["project", "name", "brief"],
              lambda a: ["queue", a["project"], a["name"], a["brief"]] + flags(a, {"kind": "--kind", **WORK_FLAGS, **BUDGET_FLAGS})),
    "hold": (MANAGERS, "Hold a queue item so it does not start (and stops a run of it) while you decide; "
             "release=true lifts your hold.",
             {"item": text("PROJECT:ITEM"), "release": {"type": "boolean"}}, ["item"],
             lambda a: ["hold", a["item"]] + (["--release"] if a.get("release") else [])),
    "revise": (MANAGERS, "Replace a held item's brief; omitted stage, effort and budget are retained.",
               {"item": text("PROJECT:ITEM"), "brief": text("the complete revised brief"),
                "reason": text("why the item changes"), **WORK, **BUDGET}, ["item", "brief", "reason"],
               lambda a: ["revise", a["item"], a["brief"], "--reason", a["reason"]] + flags(a, {**WORK_FLAGS, **BUDGET_FLAGS})),
    "cancel": (MANAGERS, "Withdraw unaccepted queue items for good. Name dependents in the same call.",
               {"items": {"type": "array", "items": {"type": "string"}, "description": "PROJECT:ITEM ids"},
                "reason": text("why")}, ["items", "reason"],
               lambda a: ["cancel", *a["items"], "--reason", a["reason"]]),
    "replace": (MANAGERS, "Replace this task's failed item with already-queued children, repointing dependents.",
                {"children": {"type": "array", "items": {"type": "string"}, "description": "child item names"}},
                ["children"], lambda a: ["replace", *a["children"]]),
    "supersede": (MANAGERS, "Replace failed prerequisites with existing same-project items without accepting them.",
                  {"task": text("PROJECT:FAILED"), "replacements": {"type": "array", "items": {"type": "string"}},
                   "reason": text("evidence")}, ["task", "replacements", "reason"],
                  lambda a: ["supersede", a["task"], *a["replacements"], "--reason", a["reason"]]),
    "budget": (MANAGERS, "Set generation limits on waiting or undispatched work.",
               {"task": text("PROJECT:TASK"), **BUDGET}, ["task"], lambda a: ["budget", a["task"]] + flags(a, BUDGET_FLAGS)),
    "attention": (SCOUTS, "Send one bounded issue to the user through Coin.",
                  {"message": text("the issue and what the user must decide or do")}, ["message"],
                  lambda a: ["attention", a["message"]]),
}


def run_cli(argv: list[str]) -> tuple[str, bool]:
    """Run one CLI command in-process; its printed output and whether it failed."""
    out, err = io.StringIO(), io.StringIO()
    failed = False
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(argv)
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
    tools += [{"name": name, "description": description,
               "inputSchema": {"type": "object", "properties": properties, "required": required}}
              for name, (description, properties, required) in MESSAGE_TOOLS.items()]
    return tools


def missing(required: list[str], arguments: dict) -> str | None:
    absent = [key for key in required if arguments.get(key) in (None, "", [])]
    return f"missing required argument(s): {', '.join(absent)}" if absent else None


def invoke(name: str, arguments: dict, for_role: str | None) -> tuple[str, bool]:
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
        output, failed = invoke(params.get("name", ""), params.get("arguments") or {}, for_role)
        result = {"content": [{"type": "text", "text": output}], "isError": failed}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


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
            protocol.write(json.dumps(reply) + "\n")
            protocol.flush()


if __name__ == "__main__":
    main()
