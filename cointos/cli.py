"""`cointos`: David's and the agents' command line over the daemon.

Reports (`status`, `agents`, `jobs`, `check`, `projects`) are formatted here as text, which
Coin reuses. Agent commands (`finish`, `merge`, `review`, `land`, `return`, `replace`, `queue`,
`attention`) act as the agent run whose environment they run in (`COINTOS_TASK_ID`,
`COINTOS_AGENT`), so the daemon can tell which run submitted what.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from cointos import config as configuration, git, opencode, queues, schema
from cointos.client import Unreachable, call, ledger

CONFIG = configuration.load()
UNITS = ["cointosd.service", "cointos-coin.service"]
LANDING_TIMEOUT = CONFIG["timeouts"]["command_seconds"] + CONFIG["timeouts"]["api_seconds"]
TERMINAL_COMMANDS = frozenset({"finish", "land", "return", "incorporate"})


# ---------------------------------------------------------------- reports

def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds}s" if seconds < 120 else f"{seconds // 60}m" if seconds < 7200 else f"{seconds // 3600}h"


def status_text(state: dict) -> str:
    """Agents first, then the work, then the resources that serve them."""
    now = time.time()
    agents = list(state["agents"].values())
    count = lambda status: sum(t["status"] == status for t in state["tasks"].values())
    lines = [f"CointOS  up {ago(now - state['started_at'])}  {'PAUSED' if state['paused'] else 'running'}  "
             f"{len(agents)} agents  ({sum(a['state'] == 'reading' for a in agents)} reading, "
             f"{sum(a['state'] == 'thinking' for a in agents)} thinking, "
             f"{sum(a['state'] == 'waiting' for a in agents)} waiting, {sum(a['state'] == 'running' for a in agents)} running)",
             f"work     {count('running')} in progress  {count('waiting')} up next  {count('review')} in review  "
             f"{count('done')} done  {count('failed')} gave up"]
    memory, guard = state["memory"], state["guard"]
    if memory:
        lines.append(f"memory   headroom {memory['headroom_gb']} GB  (available {memory['available_gb']} GB)  "
                     f"pressure {memory['psi']}  swap {memory['swap_gb']} GB  "
                     f"snapshots {sum(s['tier'] == 'memory' for s in state['snapshots'].values())} in memory, "
                     f"{sum(s['tier'] != 'memory' for s in state['snapshots'].values())} on disk"
                     + ("  BACKGROUND WAITING FOR MEMORY" if guard["blocked"] else "")
                     + ("  WORK MODEL KILLED" if guard["killed"] else ""))
    for name, model in state["models"].items():
        holders = "  ".join(f"[{lane['index']}] " + (state["thoughts"][lane["holder"]]["agent"]
                                                     if lane["holder"] in state["thoughts"]
                                                     else "free" if lane["up"] else "down")
                            for lane in state["lanes"] if lane["model"] == name)
        health = "up" if model["up"] else "launching" if model["launching"] else "DOWN " + "; ".join(model["problems"])
        lines.append(f"{name:20} {health}  {holders}")
    return "\n".join(lines + ["check    " + checks_summary(state)])


def checks_summary(state: dict) -> str:
    failing = [c for c in state["checks"] if not c["ok"]]
    return "green" if not failing else "RED: " + "; ".join(f"{c['name']}: {c['detail']}" for c in failing)


def agents_text(state: dict) -> str:
    now = time.time()
    lines = []
    for agent in state["agents"].values():
        lines.append(f"{agent['id']:16} {agent['state']:9} {agent['place']}:{agent['title']}  up {ago(now - agent['started_at'])}"
                     f"  {agent['thoughts']} thoughts  last activity {ago(now - agent['last_activity'])} ago")
        if agent.get("doing"):
            lines.append(f"{'':16} {agent['doing'][:140]}")
    return "\n".join(lines) or "no live agents"


def jobs_text(state: dict, limit: int = 30) -> str:
    now = time.time()
    newest = sorted(state["tasks"].values(), key=lambda t: t["updated_at"], reverse=True)[:limit]
    return "\n".join(f"{t['status']:8} {t['id']:45} {t['role']:12} runs {t['runs']}"
                     f"  {ago(now - t['updated_at'])} ago  {t['note'] or ''}" for t in newest) or "no tasks yet"


def checks_text(state: dict) -> tuple[str, bool]:
    """Each self-check and whether everything, including the daemon's own tick, is healthy."""
    lines = [f"{'ok  ' if c['ok'] else 'FAIL'}  {c['name']}{': ' + c['detail'] if c['detail'] else ''}"
             for c in state["checks"]]
    age = time.time() - state["updated_at"]
    if age > 10:
        lines.append(f"FAIL  ledger is {ago(age)} old: the daemon is not ticking")
    return "\n".join(lines), bool(state["checks"]) and all(c["ok"] for c in state["checks"]) and age <= 10


def projects_text(projects: list[dict]) -> str:
    return "\n".join(f"{p['priority']:>4}  {p['name']:<20} {'enabled' if p['enabled'] else 'disabled':<8} "
                     f"{p['main_branch']:<12} {p['path']}  ({p.get('test_policy', {}).get('manifest', 'no test manifest')})"
                     for p in projects) or "No projects registered."


# ---------------------------------------------------------------- the system's services

def systemctl(*args) -> int:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True).returncode


def up() -> str:
    systemctl("start", *UNITS)
    return "starting: cointosd loads the models, then agents start as work is available"


def halt(keep_coin: bool) -> str:
    """Stop everything: the daemon settles interrupted work first, then services, agent units
    and models stop."""
    try:
        call("halt")
        settled = ""
    except Unreachable:
        settled = "daemon unreachable: interrupted work could not be settled. "
    systemctl("stop", *(UNITS[:1] if keep_coin else UNITS))
    systemctl("stop", "cointos-agent-*")  # agents' runs are units of their own
    backend = importlib.import_module(CONFIG["backend"])
    problems = []
    for name in CONFIG["models"]:
        try:
            backend.kill(CONFIG, name)
        except Exception as error:
            problems.append(f"could not kill {name}: {error}")
    for pids in opencode.find_processes().values():
        for pid in pids:
            opencode.stop_group(pid, grace=CONFIG["timeouts"]["leftover_stop_grace_seconds"])
    return "\n".join([settled + "halted: daemon" + ("" if keep_coin else " and Coin") +
                      " stopped, agents stopped, models killed", *problems, "bring it back with: cointos up"])


def restart() -> str:
    """Drain complete HTTP replies, then replace only the daemon; agents and models stay."""
    deadline = time.monotonic() + CONFIG["timeouts"]["command_seconds"]
    try:
        while not call("prepare-restart")["ready"]:
            if time.monotonic() >= deadline:
                raise SystemExit("restart cancelled: replies did not drain in time; no processes stopped")
            time.sleep(CONFIG["tick_seconds"])
        if systemctl("restart", "cointosd.service") != 0:
            raise SystemExit("daemon restart failed; check cointosd.service")
    except BaseException:
        try:
            call("cancel-restart")
        except (ValueError, Unreachable):
            pass
        raise
    return "daemon restarted; existing agents are adopted and continue their sessions"


# ---------------------------------------------------------------- agent commands

def run_here() -> tuple[dict, str]:
    """The task and run identity of the agent run this command runs in."""
    task_id, run = os.environ.get("COINTOS_TASK_ID"), os.environ.get("COINTOS_AGENT")
    if not task_id or not run:
        raise SystemExit("this is not a CointOS agent run (COINTOS_TASK_ID and COINTOS_AGENT are unset)")
    task = ledger()["tasks"].get(task_id)
    if task is None:
        raise SystemExit(f"task {task_id} is no longer in the ledger")
    return task, run


def main_branch(task: dict) -> str:
    places = configuration.managed_trees(CONFIG) if schema.KINDS[task["kind"]]["scope"] == "tree" else CONFIG["projects"]
    return next(p for p in places if p["name"] == task["place"])["main_branch"]


def here(*args) -> subprocess.CompletedProcess:
    return git.result(".", *args)


def conflicted() -> list[str]:
    return here("diff", "--name-only", "--diff-filter=U").stdout.split()


def resolve(files: list[str], then: str) -> None:
    raise SystemExit(
        "These files have changes from both sides:\n  " + "\n  ".join(files) + "\n"
        "Nothing has landed. Open each file, keep what both sides meant (main's changes are other "
        "agents' finished work; do not drop them) and remove the <<<<<<< ======= >>>>>>> markers. "
        f"Then `git add` those files and {then}.")


def merge() -> str:
    """Land this run's branch: bring it up to date with main, then fast-forward main to it (an
    integrator's candidate goes through the daemon's landing gate instead). A conflict is left
    in the worktree with plain instructions; nothing lands until it is resolved."""
    task, run = run_here()
    lands = schema.KINDS[task["kind"]]["lands"]
    if lands == "review":
        raise SystemExit("Workers do not land their work. Commit everything on your branch with .work-report.md, "
                         "then submit it with `cointos finish`: the integrator reviews and lands it.")
    if task["branch"] is None:
        raise SystemExit("this system task has no branch to land")
    main = main_branch(task)
    again = "`git commit --no-edit`, and run `cointos merge` again"
    if here("branch", "--show-current").stdout.strip() != task["branch"]:
        raise SystemExit("run this in your task worktree, on your task branch")
    if conflicted():
        resolve(conflicted(), again)
    if not git.clean("."):
        raise SystemExit("your worktree has uncommitted changes; commit them first, then run `cointos merge` again")
    if here("cat-file", "-e", f"HEAD:{queues.REPORT}").returncode == 0:
        raise SystemExit(f"{queues.REPORT} is a worker-to-integrator artifact and may never land from a {task['kind']} "
                         "task; remove it, commit that removal, and run `cointos merge` again")
    if here("merge", "--no-edit", main).returncode != 0:
        if conflicted():
            resolve(conflicted(), again)
        here("merge", "--abort")
        raise SystemExit(f"bringing your branch up to date with {main} failed; nothing has landed")
    if lands == "gate":
        result = call("land", {"task": task["id"], "commit": git.head("."), "run": run}, timeout=LANDING_TIMEOUT)
        return f"verified and landed {result['commit']} on {main}; this is your receipt."
    checkout = Path(git.run(".", "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    if git.result(checkout, "branch", "--show-current").stdout.strip() != main:
        raise SystemExit(f"the main checkout {checkout} is not on {main} right now; nothing has landed. "
                         "Try `cointos merge` again later.")
    landed = git.result(checkout, "merge", "--ff-only", task["branch"])
    if landed.returncode:
        raise SystemExit("main could not take your branch; nothing has landed. If main moved meanwhile, run "
                         "`cointos merge` again. Otherwise the main checkout has someone's uncommitted edits "
                         "in the same files; try again later.\n" + landed.stderr.strip())
    return f"landed {task['branch']} on {main}"


def integration() -> tuple[dict, dict, str]:
    """In an integrator's run: its task, the worker's task it integrates, and its run."""
    task, run = run_here()
    if task["kind"] != "integrate":
        raise SystemExit("only the integrator reviews and lands a worker's item")
    return task, ledger()["tasks"][task["worker"]], run


def review() -> str:
    """Stage the worker's submitted commit for review; its branch-local report is shown, not staged."""
    task, worker, run = integration()
    main = main_branch(task)
    submitted = worker["receipt"]["evidence"]["commit"]
    account = git.show(".", submitted, queues.REPORT)
    if not (here("diff", "--cached", "--quiet").returncode or conflicted()):
        if not git.clean("."):
            raise SystemExit("commit or resolve existing review edits before staging another worker")
        if here("merge", "--ff-only", main).returncode:
            raise SystemExit("review branch cannot fast-forward to current main; preserve your edits and resolve before review")
        squashed = here("merge", "--squash", submitted)
        if squashed.returncode and not conflicted():
            raise SystemExit(squashed.stderr.strip())
        here("rm", "-q", "-f", "--ignore-unmatch", "--", queues.REPORT)
    lines = [f"Worker report for {task['item']}:\n\n{account}\n", here("diff", "--cached", "--stat").stdout]
    if conflicted():
        resolve(conflicted(), "carry on with review; cointos land commits it")
    return "\n".join(lines + ['Check the diff and tests, maintain the project tree and plan, then cointos land "summary", '
                              'or cointos return "what must change".'])


def land(summary: str) -> str:
    """Commit the review with the worker's account, then land it through the daemon's gate.
    Retrying after a lost reply resends the same landing."""
    task, worker, run = integration()
    if conflicted():
        resolve(conflicted(), "run cointos land again")
    account = git.show(".", worker["receipt"]["evidence"]["commit"], queues.REPORT).strip()
    message = f"{summary.strip()}\n\n{account}"
    here("rm", "-q", "-f", "--ignore-unmatch", "--", queues.REPORT)
    here("add", "-A")
    if here("diff", "--cached", "--quiet").returncode:
        committed = here("commit", "-q", "-m", message)
        if committed.returncode:
            raise SystemExit(committed.stderr.strip() or committed.stdout.strip())
    elif not account or here("log", "-1", "--format=%B").stdout.strip() != message:
        raise SystemExit("nothing reviewed to land; run cointos review first")
    return merge()


def send_back(notes: str) -> str:
    task, worker, run = integration()
    call("return", {"task": task["id"], "run": run, "notes": notes})
    return f"sent {task['item']} back to its worker; this is your receipt."


def finish(outcome: str, detail: str) -> str:
    task, run = run_here()
    call("finish", {"task": task["id"], "run": run, "outcome": outcome, "detail": detail})
    return f"receipt accepted: {task['id']} {outcome}."


def replace(children: list[str]) -> str:
    task, run = run_here()
    call("replace", {"task": task["id"], "run": run, "children": children})
    return f"dependents of {task['item']} now depend on {', '.join(children)}; finish when your plan has landed"


def proposal(body: dict) -> dict:
    """A request made as this agent run, when it runs in one."""
    if os.environ.get("COINTOS_TASK_ID"):
        body.update(proposed_by=os.environ["COINTOS_TASK_ID"], run=os.environ.get("COINTOS_AGENT"))
    return body


# ---------------------------------------------------------------- live views

def watch(agent_id: str | None) -> None:
    """Open OpenCode's live view of an agent's session (the first live agent if none is named)."""
    live = ledger()["agents"]
    if not live:
        raise SystemExit("no live agents")
    agent = live.get(agent_id) if agent_id else next(iter(live.values()))
    if agent is None:
        raise SystemExit(f"no live agent {agent_id!r}; live: {', '.join(live)}")
    if not agent.get("url") or not agent.get("session"):
        raise SystemExit(f"{agent['id']} is still starting; try again in a moment")
    command = opencode.attach(agent)
    os.execv(command[0], command)


def view(slot: int) -> None:
    """A viewer window: show, live, whichever agent the daemon gives slot `slot`; idle between agents."""
    def title(text):
        sys.stdout.write(f"\033]0;{text}\007")
        sys.stdout.flush()

    def assigned():
        try:
            state = ledger()
        except (Unreachable, ValueError):
            return None
        agent = state["agents"].get(state["viewers"].get(str(slot)))
        return agent if agent and agent.get("url") and agent.get("session") else None

    idle_shown = False
    while True:
        agent = assigned()
        if agent is None:
            if not idle_shown:
                title(f"CointOS viewer {slot}: idle")
                print(f"\033[2J\033[H\n  CointOS viewer {slot}\n\n  idle: the next agent to start appears here.")
                idle_shown = True
            time.sleep(CONFIG["viewers"]["poll_seconds"])
            continue
        idle_shown = False
        title(f"CointOS {slot}: {agent['id']} on {agent['place']}: {agent['title']}")
        child = subprocess.Popen(opencode.attach(agent))
        while child.poll() is None:
            time.sleep(CONFIG["viewers"]["poll_seconds"])
            current = assigned()
            if current is None or current["id"] != agent["id"]:
                child.terminate()
                try:
                    child.wait(timeout=CONFIG["viewers"]["detach_seconds"])
                except subprocess.TimeoutExpired:
                    child.kill()
        subprocess.run(["stty", "sane"], check=False)  # the TUI may leave the terminal in raw mode


# ---------------------------------------------------------------- projects and limits

def test_policy(args) -> dict | None:
    if not args.test_manifest:
        return None
    return {"manifest": args.test_manifest, "protected": args.protect, "non_code": args.non_code}


def limits(args) -> dict | None:
    chosen = {key: getattr(args, key) for key in schema.BUDGET_KEYS if getattr(args, key) is not None}
    return chosen or None


def project_command(args) -> str:
    if args.project_command == "list":
        return projects_text(call("project-list")["projects"])
    if args.project_command == "remove":
        return json.dumps(call("project-remove", {"project": args.name})["project"], indent=2)
    if args.project_command == "set":
        changes = {key: getattr(args, key) for key in ("main_branch", "priority") if getattr(args, key) is not None}
        if args.enable or args.disable:
            changes["enabled"] = args.enable
        if test_policy(args) is not None:
            changes["test_policy"] = test_policy(args)
        if not changes:
            raise SystemExit("project set needs a setting")
        return json.dumps(call("project-set", {"project": args.name, "settings": changes})["project"], indent=2)
    if args.project_command == "add":
        path = Path(args.path).expanduser().resolve()
        body = {"name": args.name or path.name, "path": str(path), "main_branch": args.main_branch}
    else:
        body = {"name": args.name, "path": args.path, "main_branch": args.main_branch}
    body.update(priority=args.priority, enabled=not args.disabled, test_policy=test_policy(args))
    return json.dumps(call(f"project-{args.project_command}", body)["project"], indent=2)


# ---------------------------------------------------------------- the command line

def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="cointos", description="Control CointOS.")
    sub = top.add_subparsers(dest="command", required=True)
    for name in ("status", "agents", "check", "go", "up", "restart", "merge", "review"):
        sub.add_parser(name)
    sub.add_parser("jobs").add_argument("--all", action="store_true")
    sub.add_parser("task", help="show one exact task and queue record, including receipts and dependencies").add_argument("task")
    sub.add_parser("halt").add_argument("--keep-coin", action="store_true")
    sub.add_parser("stop", help="pause autonomous agents and return their unfinished work to waiting")
    sub.add_parser("kill", help="kill one run and hold unfinished work until explicitly resumed").add_argument("agent")
    sub.add_parser("resume", help="release a killed task for scheduling").add_argument("task")
    sub.add_parser("watch", help="watch an agent live in OpenCode").add_argument("agent", nargs="?")
    viewing = sub.add_parser("view", help="show agents live in pop-up windows: --all to open them, --off to stop")
    viewing.add_argument("slot", type=int, nargs="?", help="be viewer window N (the daemon opens these)")
    viewing.add_argument("--all", action="store_true", help="open a viewer for every active agent, and for new ones")
    viewing.add_argument("--off", action="store_true", help="open no more viewers (open ones still show new agents)")

    finishing = sub.add_parser("finish", help="agent: submit this run's one completion receipt")
    disposition = finishing.add_mutually_exclusive_group(required=True)
    disposition.add_argument("--complete", help="evidence the assigned concern is complete")
    disposition.add_argument("--blocked", help="specific blocker requiring intervention")
    sub.add_parser("land", help="integrator: land the reviewed item").add_argument("summary")
    sub.add_parser("return", help="integrator: send the item back to its worker").add_argument("notes")
    sub.add_parser("replace", help="manager: replace an oversized item with queued children").add_argument("children", nargs="+")
    incorporated = sub.add_parser("incorporate", help="integrator: settle an implementation already present on main")
    incorporated.add_argument("task", help="project:task in review")
    incorporated.add_argument("--commit", required=True, help="exact current main commit SHA")
    incorporated.add_argument("--worker-commit", required=True, help="exact submitted worker commit SHA")
    sub.add_parser("attention", help="scout/auditor: send a bounded issue to David through Coin").add_argument("message")

    queue = sub.add_parser("queue", help="add an item to a project's queue")
    queue.add_argument("project")
    queue.add_argument("name")
    queue.add_argument("brief")
    queue.add_argument("--kind", default="queued", choices=tuple(schema.QUEUE_KINDS))
    queue.add_argument("--stage", choices=schema.STAGES, help="construction stage (default: implementation)")
    queue.add_argument("--reasoning-effort", choices=schema.EFFORTS, help="override the stage's reasoning effort")
    budget_options(queue)
    holding = sub.add_parser("hold", help="keep a queue item from starting while you decide about it")
    holding.add_argument("item", help="PROJECT:ITEM")
    holding.add_argument("--release", action="store_true", help="release your hold without revising")
    revising = sub.add_parser("revise", help="change what a queue item asks for; its task restarts on the new brief")
    revising.add_argument("item", help="PROJECT:ITEM")
    revising.add_argument("brief", help="the complete revised brief, including any Depends on: line")
    revising.add_argument("--reason", required=True, help="why the item changes")
    revising.add_argument("--stage", choices=schema.STAGES)
    revising.add_argument("--reasoning-effort", choices=schema.EFFORTS)
    budget_options(revising)
    supersede = sub.add_parser("supersede", help="replace failed/blocked prerequisites without accepting the failed work")
    supersede.add_argument("task", help="project:task")
    supersede.add_argument("replacements", nargs="+", help="existing same-project bare item names")
    supersede.add_argument("--reason", required=True)
    withdrawn = sub.add_parser("clear-review", help="withdraw infrastructure rejection from an inactive task")
    withdrawn.add_argument("task")
    withdrawn.add_argument("--reason", required=True)
    reasoning = sub.add_parser("reasoning", help="set a task's reasoning effort for its next reply")
    reasoning.add_argument("task", help="project:task ID")
    reasoning.add_argument("effort", choices=schema.EFFORTS)
    budget = sub.add_parser("budget", help="set generation limits on waiting/undispatched work")
    budget.add_argument("task", help="project:task ID")
    budget_options(budget)

    project = sub.add_parser("project", help="create and manage registered projects")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_sub.add_parser("list", help="list projects in scheduling order")
    for name in ("add", "new"):
        command = project_sub.add_parser(name, help=("register an existing Git repository" if name == "add" else
                                                      "create a Git repository and project knowledge tree, then register it"))
        if name == "add":
            command.add_argument("path")
            command.add_argument("--name")
        else:
            command.add_argument("name")
            command.add_argument("--path")
        command.add_argument("--main-branch")
        command.add_argument("--priority", type=int, default=100, help="lower values run first within a lifecycle class")
        command.add_argument("--disabled", action="store_true")
        policy_options(command)
    project_set = project_sub.add_parser("set", help="change project scheduling and policy options")
    project_set.add_argument("name")
    project_set.add_argument("--main-branch")
    project_set.add_argument("--priority", type=int)
    enabled = project_set.add_mutually_exclusive_group()
    enabled.add_argument("--enable", action="store_true")
    enabled.add_argument("--disable", action="store_true")
    policy_options(project_set)
    project_sub.add_parser("remove", help="remove an idle project from CointOS (the repository remains)").add_argument("name")

    agent = sub.add_parser("agent", help="run one ad-hoc operator with explicit scope and abilities")
    agent_run = agent.add_subparsers(dest="agent_command", required=True).add_parser("run")
    agent_run.add_argument("name")
    agent_run.add_argument("brief")
    scope = agent_run.add_mutually_exclusive_group()
    scope.add_argument("--project")
    scope.add_argument("--system", action="store_true", help="run from the installed CointOS runtime (default)")
    agent_run.add_argument("--ability", action="append", choices=schema.ABILITIES, default=[])
    agent_run.add_argument("--reasoning-effort", choices=schema.EFFORTS)
    budget_options(agent_run)
    return top


def budget_options(command) -> None:
    command.add_argument("--generation-seconds", type=float, help="daemon-enforced generation seconds per run")
    command.add_argument("--generation-tokens", type=int, help="daemon-enforced generated tokens per run, including reasoning")


def policy_options(command) -> None:
    command.add_argument("--test-manifest")
    command.add_argument("--protect", action="append", default=[])
    command.add_argument("--non-code", action="append", default=[])


def show_check() -> str:
    text, healthy = checks_text(ledger())
    if not healthy:
        raise SystemExit(text)
    return text


def show_task(task_id: str) -> str:
    state = ledger()
    task, record = state["tasks"].get(task_id), state["queue"].get(task_id)
    if task is None and record is None:
        raise SystemExit(f"unknown task {task_id!r}; use cointos jobs --all for existing IDs")
    return json.dumps({"task": task, "queue": record}, indent=2)


def hold_command(args) -> str:
    if args.release:
        call("unhold", proposal({"item": args.item}))
        return f"released {args.item}"
    call("hold", proposal({"item": args.item}))
    return f"held {args.item}: it will not start until you revise or release it"


def resume() -> str:
    call("go")
    return "resumed: agents will start as work is available"


def stop_command(args) -> str:
    call("stop")
    return "paused: running agents stopped and requeued, no new agents until `cointos go`"


def kill_command(agent: str) -> str:
    result = call("kill-agent", {"agent": agent})
    return (f"killed run {agent}; task {result['task']} is held; resume with `cointos resume {result['task']}`"
            if result["held"] else f"killed run {agent}; its task was already settled")


def view_command(args) -> str | None:
    if args.slot is not None:
        return view(args.slot)
    if not (args.all or args.off):
        raise SystemExit("usage: cointos view --all | --off")
    call("viewers", {"show": args.all})
    return "viewers: opening windows for active agents" if args.all else "viewers: no new windows"


COMMANDS = {
    "status": lambda args: status_text(ledger()),
    "agents": lambda args: agents_text(ledger()),
    "jobs": lambda args: jobs_text(ledger(), limit=10_000 if args.all else 30),
    "check": lambda args: show_check(),
    "task": lambda args: show_task(args.task),
    "go": lambda args: resume(),
    "stop": stop_command,
    "kill": lambda args: kill_command(args.agent),
    "resume": lambda args: (call("resume-task", {"task": args.task}) and f"released {args.task} for scheduling"),
    "up": lambda args: up(),
    "halt": lambda args: halt(args.keep_coin),
    "restart": lambda args: restart(),
    "watch": lambda args: watch(args.agent),
    "view": view_command,
    "finish": lambda args: finish(*(("complete", args.complete) if args.complete is not None else ("blocked", args.blocked))),
    "merge": lambda args: merge(),
    "review": lambda args: review(),
    "land": lambda args: land(args.summary),
    "return": lambda args: send_back(args.notes),
    "replace": lambda args: replace(args.children),
    "incorporate": lambda args: json.dumps(call("incorporate", {"task": args.task, "commit": args.commit,
                                                                "worker_commit": args.worker_commit,
                                                                "run": os.environ.get("COINTOS_AGENT")},
                                                timeout=LANDING_TIMEOUT)),
    "attention": lambda args: json.dumps(call("attention", proposal({"message": args.message}))),
    "queue": lambda args: call("queue", proposal({
        "project": args.project, "name": args.name, "brief": args.brief, "kind": args.kind, "stage": args.stage,
        "reasoning_effort": args.reasoning_effort, "budget": limits(args)}))["item"],
    "hold": hold_command,
    "revise": lambda args: call("revise", proposal({
        "item": args.item, "brief": args.brief, "reason": args.reason, "stage": args.stage,
        "reasoning_effort": args.reasoning_effort, "budget": limits(args)}))["item"] + " revised",
    "supersede": lambda args: json.dumps(call("supersede", {"task": args.task, "replacements": args.replacements,
                                                            "reason": args.reason})),
    "clear-review": lambda args: json.dumps(call("clear-review", {"task": args.task, "reason": args.reason})),
    "reasoning": lambda args: json.dumps(call("reasoning", {"task": args.task, "effort": args.effort})),
    "budget": lambda args: json.dumps(call("budget", {"task": args.task, "budget": limits(args) or {}})),
    "project": project_command,
    "agent": lambda args: call("run-agent", {"name": args.name, "brief": args.brief, "project": args.project,
                                             "abilities": args.ability or ["standard"],
                                             "reasoning_effort": args.reasoning_effort, "budget": limits(args)})["task"],
}


def deliver_receipt() -> None:
    """Acknowledge that this managed run's terminal receipt is visible outside its unit."""
    task_id, run = os.environ.get("COINTOS_TASK_ID"), os.environ.get("COINTOS_AGENT")
    if not task_id or not run:
        raise SystemExit("terminal CointOS commands require a managed agent run")
    # The daemon stops this exact unit.  This acknowledgement call may be cut off with it.
    call("receipt-delivered", {"task": task_id, "run": run})


def has_receipt_here() -> bool:
    """Whether a nominally failed terminal command actually recorded this run's receipt.

    An implementation landing can return its worker and then report validation failure.  That
    error is still a terminal receipt and must end the integrator instead of inviting another
    model turn.
    """
    task_id, run = os.environ.get("COINTOS_TASK_ID"), os.environ.get("COINTOS_AGENT")
    if not task_id or not run:
        return False
    receipt = (ledger()["tasks"].get(task_id) or {}).get("receipt") or {}
    return receipt.get("run") == run


def main(argv=None) -> None:
    args = parser().parse_args(argv)
    try:
        output = COMMANDS[args.command](args)
    except ValueError as error:
        if args.command in TERMINAL_COMMANDS and has_receipt_here():
            print(str(error), file=sys.stderr, flush=True)
            deliver_receipt()
            return
        raise SystemExit(str(error))
    except Unreachable as error:
        raise SystemExit(str(error))
    if output:
        print(output, flush=args.command in TERMINAL_COMMANDS)
    if args.command in TERMINAL_COMMANDS:
        deliver_receipt()


if __name__ == "__main__":
    main()
