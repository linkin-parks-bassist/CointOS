"""`cointos`: one control surface over the daemon's ledger."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cointos import agents, config as configuration, queues

CONFIG = configuration.load()
BACKEND = importlib.import_module(CONFIG["backend"])
UNITS = ["cointosd.service", "cointos-coin.service"]


def call(action: str | None = None, body: dict | None = None, timeout: float = CONFIG["timeouts"]["api_seconds"]):
    """GET the ledger, or POST an action."""
    url = configuration.api_url(CONFIG) + ("/api/ledger" if action is None else f"/api/{action}")
    data = None if action is None else json.dumps(body or {}).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(json.loads(error.read() or b"{}").get("error", str(error)))


def ledger() -> dict:
    try:
        return call()
    except (urllib.error.URLError, OSError):
        raise SystemExit("cointosd is not running (start it with: cointos up)")


def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds}s" if seconds < 120 else f"{seconds // 60}m" if seconds < 7200 else f"{seconds // 3600}h"


def show_status(state: dict) -> None:
    """Agents first, then the work, then the resources that serve them."""
    now = time.time()
    agents = list(state["agents"].values())
    count = lambda status: sum(t["status"] == status for t in state["tasks"].values())
    print(f"CointOS  up {ago(now - state['started_at'])}  {'PAUSED' if state['paused'] else 'running'}  "
          f"{len(agents)} agents  ({sum(a['state'] == 'reading' for a in agents)} reading, "
          f"{sum(a['state'] == 'thinking' for a in agents)} thinking, "
          f"{sum(a['state'] == 'waiting' for a in agents)} waiting, {sum(a['state'] == 'running' for a in agents)} running)")
    print(f"work     {count('running')} in progress  {count('waiting')} up next  {count('done')} done  {count('failed')} gave up")
    m, guard = state["memory"], state["guard"]
    if m:
        print(f"memory   headroom {m['headroom_gb']} GB  (available {m['available_gb']} GB)  pressure {m['psi']}  "
              f"swap {m['swap_gb']} GB  snapshots {sum(s['tier'] == 'memory' for s in state['snapshots'].values())} in memory, "
              f"{sum(s['tier'] != 'memory' for s in state['snapshots'].values())} on disk"
              + ("  BACKGROUND WAITING FOR MEMORY" if guard["blocked"] else "") + ("  WORK MODEL KILLED" if guard["killed"] else ""))
    for name, model in state["models"].items():
        lanes = [lane for lane in state["lanes"] if lane["model"] == name]
        holders = "  ".join(f"[{lane['index']}] " + (state["thoughts"][lane["holder"]]["agent"] if lane["holder"] in state["thoughts"]
                                                     else "free" if lane["up"] else "down") for lane in lanes)
        print(f"{name:20} {'up' if model['up'] else 'launching' if model['launching'] else 'DOWN ' + '; '.join(model['problems'])}  {holders}")
    failing = [c for c in state["checks"] if not c["ok"]]
    print("check    " + ("green" if not failing else "RED: " + "; ".join(f"{c['name']}: {c['detail']}" for c in failing)))


def show_agents(state: dict) -> None:
    now = time.time()
    if not state["agents"]:
        print("no live agents")
    for agent in state["agents"].values():
        print(f"{agent['id']:16} {agent['state']:9} {agent['place']}:{agent['title']}  up {ago(now - agent['started_at'])}"
              f"  {agent['thoughts']} thoughts  last activity {ago(now - agent['last_activity'])} ago")
        if agent.get("doing"):
            print(f"{'':16} {agent['doing'][:140]}")


def show_jobs(state: dict, limit: int = 30) -> None:
    now = time.time()
    tasks = sorted(state["tasks"].values(), key=lambda t: t["updated_at"], reverse=True)[:limit]
    if not tasks:
        print("no tasks yet")
    for task in tasks:
        print(f"{task['status']:8} {task['place']}:{task['title']:36} {task['role']:8} runs {task['runs']}"
              f"  {ago(now - task['updated_at'])} ago  {task.get('note') or ''}")


def systemctl(*args) -> int:
    return subprocess.run(["systemctl", "--user", *args]).returncode


def halt(keep_coin: bool) -> None:
    try:
        call("halt")  # the ledger owner settles interrupted work before any unit is killed
    except urllib.error.URLError:
        print("daemon unreachable: stopping remaining services and models")
    units = UNITS[:1] if keep_coin else UNITS
    systemctl("stop", *units)
    systemctl("stop", "cointos-agent-*")  # agents' runs are units of their own
    for name in CONFIG["models"]:
        try:
            BACKEND.kill(CONFIG, name)
        except Exception as error:
            print(f"could not kill {name}: {error}")
    for pids in agents.find_processes().values():
        for pid in pids:
            agents.stop_group(pid, grace=CONFIG["timeouts"]["leftover_stop_grace_seconds"])
    print("halted: daemon" + ("" if keep_coin else " and Coin") + " stopped, agents stopped, models killed"
          "\nbring it back with: cointos up")


def git(*args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def task_here() -> tuple[dict, str, Path]:
    """The task whose worktree this is, its place's main branch, and the main checkout."""
    here = Path(git("rev-parse", "--show-toplevel").stdout.strip() or ".").resolve()
    checkout = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()).parent
    task = next((t for t in ledger()["tasks"].values() if Path(t["worktree"]).resolve() == here), None)
    if task is None:
        raise SystemExit(f"{here} is not a CointOS task's worktree")
    main = next(p for p in CONFIG["trees" if task["kind"] == "garden" else "projects"]
                if p["name"] == task["place"])["main_branch"]
    return task, main, checkout


def conflicted() -> list[str]:
    return git("diff", "--name-only", "--diff-filter=U").stdout.split()


def resolve(files: list[str], then: str) -> None:
    raise SystemExit(
        "These files have changes from both sides:\n  " + "\n  ".join(files) + "\n"
        "Nothing has landed. Open each file, keep what both sides meant (main's changes are other "
        "agents' finished work; do not drop them) and remove the <<<<<<< ======= >>>>>>> markers. "
        f"Then `git add` those files and {then}.")


def merge() -> None:
    """Land the current worktree's branch on its task's main branch: bring the branch up to date
    with main, then fast-forward main to it. Managers, gardeners and the integrator land this
    way, never with git merge. A conflict is left in the worktree with plain instructions;
    nothing lands until it is resolved."""
    task, main, checkout = task_here()
    if task["kind"] == "item":
        raise SystemExit("Workers do not land their work. Commit everything on your branch, with your item "
                         "set to `Status: done` (or `blocked`), and stop: the integrator reviews your branch "
                         "and lands it, or sends it back with notes.")
    branch = git("branch", "--show-current").stdout.strip()
    again = "`git commit --no-edit`, and run `cointos merge` again"
    if not branch or branch == main:
        raise SystemExit("run this in your task worktree, on your task branch")
    if conflicted():
        resolve(conflicted(), again)
    if git("status", "--porcelain").stdout.strip():
        raise SystemExit("your worktree has uncommitted changes; commit them first, then run `cointos merge` again")
    if git("merge", "--no-edit", main).returncode != 0:
        if conflicted():
            resolve(conflicted(), again)
        git("merge", "--abort")
        raise SystemExit(f"bringing your branch up to date with {main} failed; nothing has landed")
    if git("branch", "--show-current", cwd=checkout).stdout.strip() != main:
        raise SystemExit(f"the main checkout {checkout} is not on {main} right now; nothing has landed. "
                         "Try `cointos merge` again later.")
    result = git("merge", "--ff-only", branch, cwd=checkout)
    if result.returncode != 0:
        raise SystemExit("main could not take your branch; nothing has landed. If main moved meanwhile, run "
                         "`cointos merge` again. Otherwise the main checkout has someone's uncommitted edits "
                         "in the same files; try again later.\n" + result.stderr.strip())
    print(f"landed {branch} on {main}")


def integration() -> tuple[dict, dict, str, Path]:
    """In an integrator's worktree: its task, the worker's task it integrates, main, the checkout."""
    task, main, checkout = task_here()
    if task["kind"] != "integrate":
        raise SystemExit("only the integrator reviews and lands a worker's item")
    worker = ledger()["tasks"][f"{task['place']}:{task['item']}"]
    return task, worker, main, checkout


def review() -> None:
    """Bring the worker's branch into the integrator's worktree as one uncommitted change, drop
    its item leaf if the item is done (a finished item leaves no leaf; git keeps its history), and
    show what to check."""
    task, worker, main, checkout = integration()
    leaf = f".knowledge/{task['item']}"
    account = git("show", f"{worker['branch']}:{leaf}").stdout
    if not (git("diff", "--cached", "--quiet").returncode or conflicted()):
        git("merge", "--squash", worker["branch"])
        if (queues.status(account) or "") == "done":
            git("rm", "-q", "-f", "--", leaf)
    print(f"The worker's account of {task['item']}:\n\n{queues.answer(account).strip()}\n")
    print("The change, staged in your worktree (`git diff --cached` shows it all):")
    print(git("diff", "--cached", "--stat").stdout)
    if conflicted():
        resolve(conflicted(), "carry on with the review; `cointos land` commits it")
    print("Next: check the change against the item and run the tests. Fix small things yourself. Bring "
          "`.knowledge/what/is/the/state.md` (and any leaf the change makes untrue) up to date. Then "
          "`cointos land \"<one-line summary>\"`, or `cointos return \"<what must change>\"`.")


def land(summary: str) -> None:
    """Commit the reviewed change as one commit, with the worker's account and a `Landed:` trailer
    naming the item if its leaf is gone, and land it on main."""
    task, worker, main, checkout = integration()
    if conflicted():
        resolve(conflicted(), "run `cointos land` again")
    leaf = f".knowledge/{task['item']}"
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode == 0:
        raise SystemExit("nothing to land: run `cointos review` first")
    account = queues.answer(git("show", f"{worker['branch']}:{leaf}").stdout).strip()
    trailer = "" if (Path(task["worktree"]) / leaf).exists() else f"\n\nLanded: {task['item']}"
    result = git("commit", "-q", "-m", f"{summary.strip()}\n\n{account}{trailer}")
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    merge()


def send_back(notes: str) -> None:
    task, worker, main, checkout = integration()
    call("return", {"task": task["id"], "notes": notes})
    print(f"sent {task['item']} back to its worker. Your part is over: stop now.")


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
    os.execv(agents.OPENCODE, [agents.OPENCODE, "attach", agent["url"], "--session", agent["session"]])


def view(slot: int) -> None:
    """A viewer window: show, live, whichever agent the daemon gives slot `slot`; idle between agents."""
    def title(text):
        sys.stdout.write(f"\033]0;{text}\007")
        sys.stdout.flush()

    def assigned():
        try:
            state = call()
        except (urllib.error.URLError, OSError, SystemExit):
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
        child = subprocess.Popen([agents.OPENCODE, "attach", agent["url"], "--session", agent["session"]])
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="cointos", description="Control CointOS.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "agents", "check", "go", "up", "merge", "review"):
        sub.add_parser(name)
    sub.add_parser("land", help="integrator: land the reviewed item").add_argument("summary")
    sub.add_parser("return", help="integrator: send the item back to its worker").add_argument("notes")
    sub.add_parser("jobs").add_argument("--all", action="store_true")
    sub.add_parser("watch", help="watch an agent live in OpenCode").add_argument("agent", nargs="?")
    viewing = sub.add_parser("view", help="show agents live in pop-up windows: --all to open them, --off to stop")
    viewing.add_argument("slot", type=int, nargs="?", help="be viewer window N (the daemon opens these)")
    viewing.add_argument("--all", action="store_true", help="open a viewer for every active agent, and for new ones")
    viewing.add_argument("--off", action="store_true", help="open no more viewers (open ones still show new agents)")
    stop = sub.add_parser("stop", help="pause autonomous agents (or stop one agent)")
    stop.add_argument("agent", nargs="?")
    sub.add_parser("halt").add_argument("--keep-coin", action="store_true")
    queue = sub.add_parser("queue", help="add an item to a project's queue")
    queue.add_argument("project")
    queue.add_argument("name")
    queue.add_argument("brief")
    queue.add_argument("--kind", default="queued", choices=("urgent", "queued", "drafted"))
    args = parser.parse_args(argv)

    if args.command == "status":
        show_status(ledger())
    elif args.command == "agents":
        show_agents(ledger())
    elif args.command == "jobs":
        show_jobs(ledger(), limit=10_000 if args.all else 30)
    elif args.command == "check":
        state = ledger()
        for check in state["checks"]:
            print(f"{'ok  ' if check['ok'] else 'FAIL'}  {check['name']}{': ' + check['detail'] if check['detail'] else ''}")
        age = time.time() - state["updated_at"]
        if age > 10:
            print(f"FAIL  ledger is {ago(age)} old: the daemon is not ticking")
        sys.exit(0 if state["checks"] and all(c["ok"] for c in state["checks"]) and age <= 10 else 1)
    elif args.command == "stop":
        print(call("stop-agent", {"agent": args.agent}) if args.agent else "paused: running agents stopped and requeued, "
              "no new agents until `cointos go`" if call("stop")["ok"] else "")
    elif args.command == "go":
        call("go")
        print("resumed: agents will start as work is available")
    elif args.command == "halt":
        halt(args.keep_coin)
    elif args.command == "up":
        systemctl("start", *UNITS)
        print("starting: cointosd loads the models, then agents start as work is available")
    elif args.command == "watch":
        watch(args.agent)
    elif args.command == "view":
        if args.all or args.off:
            call("viewers", {"show": args.all})
            print("viewers: opening windows for active agents" if args.all else "viewers: no new windows")
        elif args.slot is not None:
            view(args.slot)
        else:
            raise SystemExit("usage: cointos view --all | --off")
    elif args.command == "merge":
        merge()
    elif args.command == "review":
        review()
    elif args.command == "land":
        land(args.summary)
    elif args.command == "return":
        send_back(args.notes)
    elif args.command == "queue":
        print(call("queue", {"project": args.project, "name": args.name, "brief": args.brief, "kind": args.kind})["item"])


if __name__ == "__main__":
    main()
