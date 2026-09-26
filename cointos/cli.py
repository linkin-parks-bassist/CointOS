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

from cointos import agents, config as configuration

CONFIG = configuration.load()
BACKEND = importlib.import_module(CONFIG["backend"])
UNITS = ["cointosd.service", "cointos-coin.service"]


def call(action: str | None = None, body: dict | None = None, timeout: float = 10):
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
        print(f"{agent['id']:16} {agent['state']:9} {agent['project']}:{agent['title']}  up {ago(now - agent['started_at'])}"
              f"  {agent['thoughts']} thoughts  last activity {ago(now - agent['last_activity'])} ago")
        if agent.get("doing"):
            print(f"{'':16} {agent['doing'][:140]}")


def show_jobs(state: dict, limit: int = 30) -> None:
    now = time.time()
    tasks = sorted(state["tasks"].values(), key=lambda t: t["updated_at"], reverse=True)[:limit]
    if not tasks:
        print("no tasks yet")
    for task in tasks:
        print(f"{task['status']:8} {task['project']}:{task['title']:36} {task['role']:8} runs {task['runs']}"
              f"  {ago(now - task['updated_at'])} ago  {task.get('note') or ''}")


def systemctl(*args) -> int:
    return subprocess.run(["systemctl", "--user", *args]).returncode


def halt(keep_coin: bool) -> None:
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
            agents.stop_group(pid, grace=2)
    print("halted: daemon" + ("" if keep_coin else " and Coin") + " stopped, agents stopped, models killed"
          "\nbring it back with: cointos up")


def merge() -> None:
    """Land the current worktree's branch on its project's main branch, fast-forward only."""
    def git(*args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    branch = git("branch", "--show-current").stdout.strip()
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    checkout = common.parent
    project = next((p for p in CONFIG["projects"] if Path(p["path"]).resolve() == checkout.resolve()), None)
    if project is None:
        raise SystemExit(f"{checkout} is not a configured CointOS project")
    main = project["main_branch"]
    if not branch or branch == main:
        raise SystemExit("run this in your task worktree, on your task branch")
    if git("status", "--porcelain").stdout.strip():
        raise SystemExit("your worktree has uncommitted changes; commit them first")
    if git("branch", "--show-current", cwd=checkout).stdout.strip() != main:
        raise SystemExit(f"the project checkout {checkout} is not on {main}; cannot merge now")
    result = git("merge", "--ff-only", branch, cwd=checkout)
    if result.returncode != 0:
        raise SystemExit(f"fast-forward merge refused (run `git merge {main}` in your worktree first):\n"
                         + result.stderr.strip())
    print(f"merged {branch} into {main}")


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
            time.sleep(2)
            continue
        idle_shown = False
        title(f"CointOS {slot}: {agent['id']} on {agent['project']}: {agent['title']}")
        child = subprocess.Popen([agents.OPENCODE, "attach", agent["url"], "--session", agent["session"]])
        while child.poll() is None:
            time.sleep(2)
            current = assigned()
            if current is None or current["id"] != agent["id"]:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
        subprocess.run(["stty", "sane"], check=False)  # the TUI may leave the terminal in raw mode


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="cointos", description="Control CointOS.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "agents", "check", "go", "up", "merge"):
        sub.add_parser(name)
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
    elif args.command == "queue":
        print(call("queue", {"project": args.project, "name": args.name, "brief": args.brief, "kind": args.kind})["item"])


if __name__ == "__main__":
    main()
