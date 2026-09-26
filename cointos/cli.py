"""`cointos`: one control surface over the daemon's ledger."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cointos import agents, config as configuration, models

CONFIG = configuration.load()
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
    now = time.time()
    m = state["machine"]
    print(f"CointOS  up {ago(now - state['started_at'])}  {'PAUSED' if state['paused'] else 'running'}"
          f"  agents {len(state['agents'])}  waiting requests {sum(r['lane'] is None for r in state['requests'].values())}")
    if m:
        print(f"machine  available {m['mem_available_gb']} GB  psi {m['psi_full_avg10']}  swap {m['swap_used_gb']} GB"
              f"  gpu {m['gpu_used_gb']} GB")
    if state["guard"]["breaches"]:
        print("GUARD    " + "; ".join(state["guard"]["breaches"]))
    for name, model in state["models"].items():
        lanes = [lane for lane in state["lanes"] if lane["model"] == name]
        shown = "  ".join(f"[{lane['index']}] {lane['caller'] or ('idle' if lane['up'] else 'down')}" for lane in lanes)
        print(f"{name:20} {'up' if model['loaded'] else 'DOWN ' + '; '.join(model['problems'])}  {shown}")
    counts = {}
    for task in state["tasks"].values():
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    print("tasks    " + ("  ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"))
    failing = [c for c in state["checks"] if not c["ok"]]
    print("check    " + ("green" if not failing else "RED: " + "; ".join(f"{c['name']}: {c['detail']}" for c in failing)))


def show_agents(state: dict) -> None:
    now = time.time()
    if not state["agents"]:
        print("no live agents")
    for agent in state["agents"].values():
        lane = next((f"lane {l['model'].split('-')[0]}/{l['index']}" for l in state["lanes"] if l["caller"] == agent["id"]), "")
        waiting = any(r["caller"] == agent["id"] and r["lane"] is None for r in state["requests"].values())
        print(f"{agent['id']:18} {agent['state']:8} {agent['project']}:{agent['title']}  up {ago(now - agent['started_at'])}"
              f"  requests {agent['requests']}  last {ago(now - agent['last_activity'])} ago"
              f"  {lane or ('waiting for a lane' if waiting else 'working')}")
        if agent.get("session"):
            print(f"{'':18} session {agent['session']}")


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
    for name in CONFIG["models"]:
        try:
            models.unload(CONFIG, name)
        except Exception as error:
            print(f"could not unload {name}: {error}")
    left = agents.find_processes()
    for pids in left.values():
        for pid in pids:
            agents.stop_group(pid, grace=2)
    print("halted: daemon" + ("" if keep_coin else " and Coin") + " stopped, agents stopped, models unloaded"
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="cointos", description="Control CointOS.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "agents", "check", "go", "up", "merge"):
        sub.add_parser(name)
    sub.add_parser("jobs").add_argument("--all", action="store_true")
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
    elif args.command == "merge":
        merge()
    elif args.command == "queue":
        print(call("queue", {"project": args.project, "name": args.name, "brief": args.brief, "kind": args.kind})["item"])


if __name__ == "__main__":
    main()
