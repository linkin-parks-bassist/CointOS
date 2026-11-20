"""`cointos`: the user's and the agents' command line over the daemon.

Reports (`status`, `agents`, `jobs`, `check`, `projects`) are formatted here as text, which
Coin reuses. A command run inside an agent run acts as that run: the client names it as the
request's `caller` from the run's environment (`COINTOS_TASK_ID`, `COINTOS_AGENT`), so the
daemon can tell which run asked for what.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from cointos import coins, config as configuration, contracts, frontier, git, metrics, opencode, progress, queues, schema
from cointos.client import Unreachable, call, ledger
from cointos.config import ROOT

CONFIG = configuration.load()
UNITS = ["cointosd.service", *([coins.unit(name) for name in coins.names()] or ["cointos-coin.service"])]
LANDING_TIMEOUT = CONFIG["timeouts"]["validation_seconds"] + CONFIG["timeouts"]["api_seconds"]
TERMINAL_COMMANDS = frozenset({"finish", "handoff", "replace", "correct-tests", "land", "return", "incorporate"})


# ---------------------------------------------------------------- reports

def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds}s" if seconds < 120 else f"{seconds // 60}m" if seconds < 7200 else f"{seconds // 3600}h"


def coin_thought(state: dict) -> dict | None:
    return next((t for t in (state.get("thoughts") or {}).values() if t.get("agent") == "coin"), None)


def coin_phase(coin: dict, thought: dict | None) -> str:
    """What Coin is actually doing, from its live thought before a retained tool name."""
    if coin.get("alive") is False:
        return "offline"
    if thought and thought.get("reading"):
        return "reading"
    if thought:
        return (coin.get("live") or {}).get("phase") or "thinking"
    if coin.get("doing"):
        return "tools"
    if coin.get("busy"):
        return "working"
    return "idle"


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
    coin = state.get("coin") or {}
    if coin:
        phase = coin_phase(coin, coin_thought(state))
        if coin.get("busy"):
            label = coin.get("trigger") or phase
            if phase.lower() not in (label.lower(), "working"):
                label += f" · {phase}"
            if phase == "tools" and coin.get("doing"):
                label += f" · {coin['doing']}"
        else:
            label = "idle" + (f" · last: {coin['last_trigger']}" if coin.get("last_trigger") else "")
        last = (f"last turn {ago(now - coin['last_turn_at'])} ago" if coin.get("last_turn_at")
                else "no turns yet")
        current = (f" · turn {ago(now - coin['turn_started_at'])}"
                   if coin.get("busy") and coin.get("turn_started_at") else "")
        lines.insert(1, f"coin     {label} · {coin.get('turns', 0)} turns{current} · {last}")
    frontier = state.get('work_frontier', [])
    if frontier:
        blocked = [row for row in frontier if row['status'] == 'blocked' and not row.get('held_by')]
        owned = sum(bool(row.get('owner') or row.get('continuations')) for row in blocked)
        lines.append(f"wanted   {len(frontier)} open items  {len(blocked)} blocked  "
                     f"{owned} with recovery/continuation  {len(blocked) - owned} without recovery/continuation")
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
        name = (state["tasks"].get(agent["task"]) or {}).get("name") or ""
        lines.append(f"{name:9} {agent['id']:16} {agent['state']:9} {agent['place']}:{agent['title']}  up {ago(now - agent['started_at'])}"
                     f"  {agent['thoughts']} thoughts  last activity {ago(now - agent['last_activity'])} ago")
        if agent.get("doing"):
            lines.append(f"{'':16} {agent['doing'][:140]}")
    return "\n".join(lines) or "no live agents"


def progress_command(args) -> str:
    """Live progress, optionally refreshed: the tool behind a slow-looking factory."""
    def once() -> str:
        data = progress.report(ledger(), CONFIG, minutes=args.minutes, as_json=args.json)
        return json.dumps(data, indent=2) if args.json else data

    if not args.watch:
        return once()
    try:
        while True:
            sys.stdout.write("\033[2J\033[H")
            print(once())
            sys.stdout.flush()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return ""


def jobs_text(state: dict, limit: int | None = 30, project: str | None = None) -> str:
    now = time.time()
    newest = sorted((task for task in state["tasks"].values()
                     if project is None or task.get("place") == project),
                    key=lambda task: task["updated_at"], reverse=True)
    if limit is not None and os.environ.get('COINTOS_AGENT'):
        # Queue outcomes remain current facts; completed standalone runs are explicit history.
        newest = [task for task in newest if task['status'] != 'done' or task.get('record')]
    if limit is not None:
        settled = [task for task in newest if task["status"] in schema.SETTLED]
        history = {task["id"] for task in settled[:limit]}
        newest = [task for task in newest if task["status"] in schema.ACTIVE or task["id"] in history]
    def note(task):
        if os.environ.get('COINTOS_AGENT'):
            task = frontier.file_view(task)
        words = (task.get("note") or "").split()
        count = CONFIG["summary_words"][-1]
        return " ".join(words[:count]) + (" … (task for full note)" if len(words) > count else "")
    return "\n".join(f"{t['status']:8} {t['id']:45} {t['role']:12} runs {t['runs']}"
                     f"  {ago(now - t['updated_at'])} ago  {note(t)}" for t in newest) or "no tasks yet"


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
        if systemctl("restart", UNITS[0]) != 0:
            raise SystemExit(f"daemon restart failed; check {UNITS[0]}")
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


def acceptance_text(result: dict) -> str:
    if os.environ.get('COINTOS_AGENT'):
        result = frontier.file_view(result)
    acceptance = result.get('acceptance') or {}
    via, gate = acceptance.get('via'), acceptance.get('gate')
    outcome = ('accepted hidden test packet; not published' if via == 'tests' else
               'verified and published' if via == 'landing' else
               'verified existing implementation' if via == 'incorporation' else 'acceptance recorded')
    measured = (f"Suite: {gate['suite']} commands, {gate['failed']} failed "
                f"({gate['red_on_main']} already failed on the accepted product)."
                if isinstance(gate, dict) and {'suite', 'failed', 'red_on_main'} <= gate.keys()
                else 'Suite result not retained; acceptance alone does not establish a green suite.')
    push = result.get('push') or {}
    warning = ('\nDelivery warning: ' + push.get('error', 'upstream delivery failed')
               if push.get('status') == 'failed' else '')
    return outcome + '; this is your receipt.\n' + measured + warning


def merge() -> str:
    """Ask the daemon to capture and publish this run's scoped maintenance."""
    try:
        call('merge', {}, timeout=LANDING_TIMEOUT)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    return 'scoped maintenance published; local editor work is preserved.'


def integration() -> tuple[dict, dict, str]:
    """In an integrator's run: its task, the worker's task it integrates, and its run."""
    task, run = run_here()
    if task["kind"] != "integrate":
        raise SystemExit("only the integrator reviews and lands a worker's item")
    return task, ledger()["tasks"][task["worker"]], run


def review() -> str:
    """Inspect the daemon-prepared candidate, with no repository operations in the client."""
    return json.dumps(call('review', {}, timeout=LANDING_TIMEOUT), indent=2)


def land(summary: str) -> str:
    """Accept the reviewed files; the daemon captures, validates and publishes them."""
    return acceptance_text(call('land', {'summary': summary}, timeout=LANDING_TIMEOUT))


def send_back(notes: str) -> str:
    task, worker, run = integration()
    call("return", {"notes": notes})
    return f"sent {task['item']} back to its worker; this is your receipt."


def finish(outcome: str, detail: str, scout_result=None) -> str:
    task, run = run_here()
    body = {"outcome": outcome, "detail": detail}
    if scout_result is not None:
        body['scout_result'] = scout_result
    result = call("finish", body, timeout=LANDING_TIMEOUT)
    actual = result.get('receipt', {}).get('disposition', outcome)
    return f"receipt accepted: {task['id']} {actual}."


def replace(children: list[str]) -> str:
    return json.dumps(call("replace", {"children": children}))


# ---------------------------------------------------------------- live views

def interactive(command: str) -> None:
    """Live views take over a terminal and never return; a captured shell (an agent's tool call)
    would only collect escape codes until its timeout."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SystemExit(f"`cointos {command}` is a live terminal view for a person; "
                         "use `cointos agents`, `cointos jobs` or `cointos task` instead")


def coin_banner(state: dict) -> str:
    """One line naming what started Coin's turn and what it is doing now."""
    coin = state.get("coin") or {}
    thought = coin_thought(state)
    phase = coin_phase(coin, thought)
    model = (coin.get("model") or "").replace("-GGUF", "")
    bits = []
    if coin.get("busy"):
        label = coin.get("trigger") or phase
        bits.append("Coin · " + label)
        if phase.lower() not in (label.lower(), "working"):
            bits.append(phase)
    else:
        bits.append("Coin · idle")
        if coin.get("last_trigger"):
            bits.append("last: " + coin["last_trigger"])
    if model:
        bits.append(model)
    return " · ".join(bits)


def coin_header(state: dict) -> list[str]:
    now = time.time()
    coin = state.get("coin") or {}
    facts = []
    if coin.get("worker_since"):
        facts.append(f"worker {ago(now - coin['worker_since'])} up")
    facts.append(f"{coin.get('turns', 0)} turns")
    if coin.get("busy") and coin.get("turn_started_at"):
        facts.append(f"turn {ago(now - coin['turn_started_at'])}")
    if coin.get("last_turn_at"):
        facts.append(f"last turn {ago(now - coin['last_turn_at'])} ago")
    gpu = (coin.get("gpu_seconds") or 0) + (max(0, now - coin["gpu_since"]) if coin.get("gpu_since") else 0)
    if gpu:
        facts.append(f"GPU {ago(gpu)}")
    if coin.get("process"):
        facts.append(f"pid {coin['process'].get('pid')}")
    return [coin_banner(state), " · ".join(facts)]


def _coin_event_key(entry: dict):
    return (entry.get("at"), entry.get("event"), entry.get("detail"), entry.get("turn"), entry.get("seconds"))


def _coin_event_line(entry: dict) -> str:
    when = time.strftime("%H:%M:%S", time.localtime(entry["at"]))
    if entry.get("event") == "turn started":
        return f"{when}  started · {entry.get('trigger') or 'working'}"
    if entry.get("event") == "tool":
        return f"{when}  ⚙ {entry.get('detail') or 'tool'}"
    if entry.get("event") == "turn ended":
        spent = f" · {ago(entry['seconds'])}" if entry.get("seconds") is not None else ""
        return f"{when}  turn ended{spent}"
    return f"{when}  {entry['event']}"


def coin_profile(name=None):
    """Choose the journal owner before opening a passive display."""
    name = name or os.environ.get('COINTEL')
    names = coins.names()
    if not name and names:
        print("Choose Coin: " + ", ".join(f"{i + 1} {n}" for i, n in enumerate(names)))
        selected = input("Coin: ").strip()
        if not selected:
            raise ValueError("Choose a Coin identity")
        name = names[int(selected) - 1] if selected.isdigit() and 1 <= int(selected) <= len(names) else selected
    profile = coins.profile(name)
    if not profile.get('retain_diagnostics', CONFIG['coin'].get('retain_diagnostics', True)):
        raise ValueError(f"{profile.get('name', 'Coin')} has diagnostics disabled; no conversation viewer is retained")
    return profile


def automatic_coin_profile(state):
    """Resolve the worker that owns the automatic slot without asking the user."""
    coin = state.get('coin') or {}
    owner = ((coin.get('live') or {}).get('owner') or '').split('/', 1)[0]
    profiles = [(name, coins.profile(name)) for name in coins.names()]
    pid = (coin.get('process') or {}).get('pid')
    if pid:
        for name, profile in profiles:
            try:
                result = subprocess.run(['systemctl', '--user', 'show', coins.unit(name),
                                         '--property=MainPID', '--value'], capture_output=True,
                                        text=True, timeout=CONFIG['timeouts']['api_seconds'])
            except (OSError, subprocess.TimeoutExpired):
                return None
            if result.returncode == 0 and result.stdout.strip() == str(pid):
                return profile
    if not pid and owner:
        return next((profile for _, profile in profiles if profile['identity'] == owner), None)
    return {} if not profiles else None


def coin_view_state(state, profile):
    """Never mix another identity's live text into this journal."""
    if not profile or '_error' in state:
        return state
    prefix = profile['identity'] + '/'
    thoughts = {key: item for key, item in state.get('thoughts', {}).items()
                if item.get('agent') == 'coin' and (item.get('owner') or '').startswith(prefix)}
    live = (state.get('coin') or {}).get('live') or {}
    if not (live.get('owner') or '').startswith(prefix):
        live = {}
    return {**state, 'thoughts': thoughts, 'coin': {
        'name': profile['name'], 'busy': bool(thoughts), 'live': live,
        'turns': next(iter(thoughts), None)}}


def _coin_live_states(profile=None):
    while True:
        try:
            request = urllib.request.Request(configuration.api_url(CONFIG) + "/api/live",
                                             headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(request, timeout=CONFIG["timeouts"]["api_seconds"]) as response:
                for raw in response:
                    line = raw.decode(errors="replace").strip()
                    if line.startswith("data: "):
                        yield coin_view_state(json.loads(line[6:]), profile)
        except (OSError, ValueError) as error:
            yield {"_error": str(error)}
            time.sleep(1)


def _append_text(existing: str, value: str) -> str:
    if value.startswith(existing):
        return value[len(existing):]
    for size in range(min(len(existing), len(value)), 0, -1):
        if existing.endswith(value[:size]):
            return value[size:]
    return value


def write_transcript(task_id: str, out: str | None) -> str:
    """Write a task's whole agent record to a file and say where it is."""
    from cointos import transcript
    task = ledger()["tasks"].get(task_id)
    if task is None:
        raise SystemExit(f"no task {task_id}")
    if not os.environ.get('COINTOS_AGENT') and not transcript.sessions_of(task, configuration.STATE / 'agents'):
        raise SystemExit(f"{task_id} has no agent session on record")
    result = (call('read-log', {'task': task_id, 'export': True}) if os.environ.get('COINTOS_AGENT') else
              transcript.read_task(task, configuration.STATE / 'agents', export=True))
    text, messages = result['text'], result['messages']
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id)
    path = Path(out or Path(os.environ.get("COINTOS_SCRATCH") or ".") / f"transcript-{name}.txt")
    path.write_text(text)
    return f"{path}: {messages} messages in {result['sessions']} session(s), {len(text):,} characters. Search it, or read the parts you need."


def source_files(args) -> str:
    result = call('source', {key: getattr(args, key) for key in ('task', 'project', 'path', 'start', 'limit')
                             if getattr(args, key) is not None})
    lines = (result['files'] if 'files' in result else
             [f'{number}: {line}' for number, line in enumerate(result['lines'], result['start'])])
    if result.get('next'):
        lines.append(f"Continue with --start {result['next']}.")
    return '\n'.join(lines)


def read_log(args) -> str:
    """An index of an agent's thoughts, replies and tool calls, or entries from it by number."""
    from cointos import transcript
    if os.environ.get('COINTOS_AGENT'):
        return call('read-log', {'task': args.task, **{key: getattr(args, key) for key in
                    ('show', 'kind', 'turn', 'grep', 'last') if getattr(args, key) is not None}})['text']
    if args.task == "coin":
        found = transcript.coin_entries(ROOT / "state/coin/turns.jsonl")
    else:
        task = ledger()["tasks"].get(args.task)
        if task is None:
            raise SystemExit(f"no task {args.task}")
        return transcript.read_task(task, configuration.STATE / 'agents', show=args.show, kind=args.kind,
                                    turn=args.turn, grep=args.grep, last=args.last)['text']
    return transcript.view(found, show=args.show, kind=args.kind, turn=args.turn, grep=args.grep, last=args.last)


def coin_log(stop=None, profile=None) -> None:
    """Show Coin in OpenCode's viewer until the slot changes; the monitor if that cannot start."""
    from cointos import coin_mirror
    profile = coin_profile() if profile is None else profile
    state = configuration.STATE / coins.state(profile.get("identity"))
    try:
        coin_mirror.show(state / "turns.jsonl", state / f"mirror-{os.getpid()}", opencode.OPENCODE, _coin_live_states(profile), stop, name=profile.get("name"))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"OpenCode view unavailable ({error}); showing Coin's monitor.", file=sys.stderr)
        from cointos.coin_view import watch
        watch(_coin_live_states(profile), stop)


def coin_live(profile=None) -> None:
    """A standalone Coin log, or the body of a Coin viewer slot."""
    interactive("coin")
    coin_log(profile=coin_profile(profile))
    print()


def watch(agent_id: str | None) -> None:
    """Open OpenCode's live view of an agent's session (the first live agent if none is named),
    or Coin's own live view when named `coin`."""
    if agent_id == "coin":
        return coin_live()
    interactive("watch")
    live = ledger()["agents"]
    if not live:
        raise SystemExit("no live agents")
    agent = live.get(agent_id) if agent_id else next(iter(live.values()))
    if agent is None:
        raise SystemExit(f"no live agent {agent_id!r}; live: {', '.join(live)}")
    if not agent.get("url") or not agent.get("session"):
        raise SystemExit(f"{agent['id']} is still starting; try again in a moment")
    command = opencode.attach(agent)
    os.execve(command[0], command, opencode.attach_environment(agent))


def view(slot: int) -> None:
    """A viewer window: show, live, whichever agent the daemon gives slot `slot`; idle between agents."""
    interactive("view")
    def title(text):
        sys.stdout.write(f"\033]0;{text}\007")
        sys.stdout.flush()

    def assigned():
        try:
            state = ledger()
        except (Unreachable, ValueError):
            return None
        target = state["viewers"].get(str(slot))
        if target == "coin":
            profile = automatic_coin_profile(state)
            if profile is None or not profile.get('retain_diagnostics', CONFIG['coin'].get('retain_diagnostics', True)):
                return None
            return {"id": "coin:" + profile.get('identity', 'coin'), "coin": True, "profile": profile}
        agent = state["agents"].get(target)
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
        if agent.get("coin"):
            title(f"CointOS {slot}: {agent['profile'].get('name', 'Coin')}")
            def still_coin():
                current = assigned()
                return not current or current["id"] != agent["id"]
            coin_log(still_coin, profile=agent["profile"])
            continue
        title(f"CointOS {slot}: {agent['id']} on {agent['place']}: {agent['title']}")
        child = subprocess.Popen(opencode.attach(agent), env=opencode.attach_environment(agent))
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
    jobs = sub.add_parser("jobs", help="show all unfinished work and recent terminal history")
    jobs.add_argument("--all", action="store_true", help="include complete history")
    jobs.add_argument("--project", help="show only tasks belonging to this exact project")
    sub.add_parser("metrics", help="pipeline effectiveness over a recent window, from the event journal").add_argument(
        "--hours", type=float, default=24.0)
    progress_parser = sub.add_parser("progress", help="live read/generation progress, lane-switch mix and backend speculation")
    progress_parser.add_argument("--minutes", type=float, default=5.0, help="event window (default 5)")
    progress_parser.add_argument("--json", action="store_true", help="machine-readable output")
    progress_parser.add_argument("--watch", type=float, metavar="SECONDS", help="repeat every SECONDS until interrupted")
    transcribing = sub.add_parser("transcript", help="write a task's complete agent transcript, including reasoning and tool output, to a file")
    transcribing.add_argument("task")
    transcribing.add_argument("--out", help="file to write; default is this run's scratch directory or the current one")
    logging_ = sub.add_parser("log", help="read an agent's record, or Coin's with task coin: an index, or entries by number")
    logging_.add_argument("task")
    logging_.add_argument("--show", help="the full text of entry N, or entries N-M")
    logging_.add_argument("--kind", choices=("thought", "reply", "tool", "user", "compaction", "system"))
    logging_.add_argument("--turn", type=int)
    logging_.add_argument("--grep")
    logging_.add_argument("--last", type=int, default=40, help="how many index lines (default 40)")
    source = sub.add_parser('source', help='inspect accepted project source or assigned task files')
    scope = source.add_mutually_exclusive_group(required=True)
    scope.add_argument('--task')
    scope.add_argument('--project')
    source.add_argument('--path', help='relative file, or directory ending in /; omit to list files')
    source.add_argument('--start', type=int)
    source.add_argument('--limit', type=int)
    task = sub.add_parser("task", help="show current work, binding tests, receipts and dependencies")
    task.add_argument("task")
    task.add_argument("--history", action="store_true", help="include full historical execution narratives")
    diagnostic = sub.add_parser('diagnostic', help='prepare recovery files in scratch, inspect retained probes, or prepare accepted project files')
    diagnostic.add_argument('--path')
    diagnostic.add_argument('--project')
    sub.add_parser("halt").add_argument("--keep-coin", action="store_true")
    sub.add_parser("stop", help="pause autonomous agents and return their unfinished work to waiting")
    sub.add_parser("kill", help="kill one run and hold unfinished work until explicitly resumed").add_argument("agent")
    sub.add_parser("resume", help="release a killed task for scheduling").add_argument("task")
    sub.add_parser("watch", help="watch an agent live in OpenCode, or Coin's log").add_argument("agent", nargs="?")
    sub.add_parser("coin", help="watch one Coin identity's live log").add_argument("profile", nargs="?", help="Cointel identity (asks when omitted)")
    viewing = sub.add_parser("view", help="show agents and Coin in pop-up windows: --all to open them, --off to stop")
    viewing.add_argument("slot", type=int, nargs="?", help="be viewer window N (the daemon opens these)")
    viewing.add_argument("--all", action="store_true", help="open a viewer for every active agent, and for new ones")
    viewing.add_argument("--off", action="store_true", help="open no more viewers (open ones still show new agents)")
    viewing.add_argument("--coin", action="store_true", help="enable viewer windows so Coin occupies a slot while active")

    finishing = sub.add_parser("finish", help="agent: submit this run's one completion receipt")
    disposition = finishing.add_mutually_exclusive_group(required=True)
    disposition.add_argument("--complete", help="evidence the assigned concern is complete")
    disposition.add_argument("--blocked", help="specific blocker requiring intervention")
    finishing.add_argument('--scout-result-json', type=json.loads,
                           help='steward: typed no_action, manager_handoff or user_decision result')
    handing = sub.add_parser('handoff', help='manager or mandatory splitter: atomically queue children and complete')
    handing.add_argument('summary')
    handing.add_argument('--items-json', type=json.loads, required=True)
    sub.add_parser("land", help="integrator: land the reviewed item").add_argument("summary")
    sub.add_parser("return", help="integrator: send the item back to its worker").add_argument("notes")
    sub.add_parser("replace", help="First Responder: hand off to existing items and complete atomically").add_argument("children", nargs="+")
    incorporated = sub.add_parser("incorporate", help="integrator: settle an implementation already present in the accepted product")
    incorporated.add_argument("task", help="project:task in review")
    incorporated.add_argument("--commit", help=argparse.SUPPRESS)
    incorporated.add_argument("--worker-commit", help=argparse.SUPPRESS)
    messaging = sub.add_parser("message", help="send a message to an active task's inbox (an agent run sends as its task)")
    messaging.add_argument("to", help="PROJECT:NAME task id, 'mailbox:NAME', or 'user'")
    messaging.add_argument("text")
    messaging.add_argument("--mailbox", help="send as this local external mailbox")
    inbox = sub.add_parser("inbox", help="read unread messages (an agent run reads its task's; otherwise the user's)")
    inbox.add_argument("--mailbox", help="read this local external mailbox")

    queue = sub.add_parser("queue", help="add an item to a project's queue")
    queue.add_argument("project")
    queue.add_argument("name")
    queue.add_argument("brief")
    queue.add_argument("--kind", default="queued", choices=tuple(schema.QUEUE_KINDS))
    queue.add_argument("--stage", choices=schema.STAGES, help="construction stage (default: implementation)")
    queue.add_argument("--reasoning-effort", choices=schema.EFFORTS, help="override the stage's reasoning effort")
    budget_options(queue)
    queue.add_argument("--dependencies-json", type=json.loads, help="structured array of prerequisite item IDs")
    queue.add_argument("--relies-on-json", type=json.loads, help="structured array of existing API names")
    queue.add_argument("--summary", help="short dashboard description")
    correcting = sub.add_parser('correct-tests', help='request independent test correction; atomically completes First Responders')
    for name in ('project', 'packet', 'name', 'brief'):
        correcting.add_argument(name)
    correcting.add_argument('--reason', required=True)
    correcting.add_argument('--summary', required=True)
    correcting.add_argument('--relies-on-json', type=json.loads, required=True)
    checking = sub.add_parser("check-work", help="validate a proposal or your queued handoff without starting work")
    checking.add_argument("--project", help="project name; defaults to the calling agent's project")
    checking.add_argument("--name", help="new proposal name")
    checking.add_argument("--brief", help="new proposal brief; omit to check queued work")
    checking.add_argument("--kind", default="queued", choices=tuple(schema.QUEUE_KINDS))
    checking.add_argument("--stage", choices=schema.STAGES)
    checking.add_argument("--reasoning-effort", choices=schema.EFFORTS)
    checking.add_argument("--dependencies-json", type=json.loads)
    checking.add_argument("--relies-on-json", type=json.loads)
    checking.add_argument("--summary")
    budget_options(checking)
    holding = sub.add_parser("hold", help="keep a queue item from starting while you decide about it")
    holding.add_argument("item", help="PROJECT:ITEM")
    holding.add_argument("--release", action="store_true", help="release your hold without revising")
    revising = sub.add_parser("revise", help="replace a brief; omitted stage, reasoning and budget metadata is retained")
    revising.add_argument("item", help="PROJECT:ITEM")
    revising.add_argument("brief", help="the complete revised brief, including any Depends on: line")
    revising.add_argument("--reason", required=True, help="why the item changes")
    revising.add_argument("--stage", choices=schema.STAGES)
    revising.add_argument("--reasoning-effort", choices=schema.EFFORTS)
    budget_options(revising)
    revising.add_argument("--dependencies-json", type=json.loads, help="structured array of prerequisite item IDs")
    revising.add_argument("--relies-on-json", type=json.loads, help="structured array of existing API names")
    revising.add_argument("--summary", help="short dashboard description")
    moving = sub.add_parser("move", help="reorder a queue item within its project")
    moving.add_argument("item", help="PROJECT:ITEM")
    moving.add_argument("to", choices=("top", "up", "down", "bottom"))
    cancelling = sub.add_parser("cancel", help="withdraw unaccepted queue items for good: stop their runs and preserve recoverable work")
    cancelling.add_argument("items", nargs="+", help="PROJECT:ITEM; dependents must be cancelled together")
    cancelling.add_argument("--reason", required=True)
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
    budget = sub.add_parser("budget", help="set waiting generation limits or increase a live task's allowance")
    budget.add_argument("task", help="project:task ID")
    budget_options(budget)

    project = sub.add_parser("project", help="create and manage registered projects")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_sub.add_parser("list", help="list projects in scheduling order")
    for name in ("add", "new"):
        command = project_sub.add_parser(name, help=("register an existing project" if name == "add" else
                                                      "create a project and its knowledge tree, then register it"))
        if name == "add":
            command.add_argument("path")
            command.add_argument("--name")
        else:
            command.add_argument("name")
            command.add_argument("--path")
        command.add_argument("--main-branch", help=argparse.SUPPRESS if os.environ.get('COINTOS_AGENT') else None)
        command.add_argument("--priority", type=int, default=100, help="lower values run first within a lifecycle class")
        command.add_argument("--disabled", action="store_true")
        policy_options(command)
    project_set = project_sub.add_parser("set", help="change project scheduling and policy options")
    project_set.add_argument("name")
    project_set.add_argument("--main-branch", help=argparse.SUPPRESS if os.environ.get('COINTOS_AGENT') else None)
    project_set.add_argument("--priority", type=int)
    enabled = project_set.add_mutually_exclusive_group()
    enabled.add_argument("--enable", action="store_true")
    enabled.add_argument("--disable", action="store_true")
    policy_options(project_set)
    project_sub.add_parser("remove", help="remove an idle project from CointOS (its files remain)").add_argument("name")

    splitting = sub.add_parser("split", help="stop an implementer or Operator whose job is too big; a manager salvages it and cuts it up")
    splitting.add_argument("task")
    splitting.add_argument("--reason", default="the user stopped it as too big")
    recovering = sub.add_parser("recover", help="stop a run whose assignment is malformed and send it to a First Responder")
    recovering.add_argument("task")
    recovering.add_argument("--reason", required=True)
    agent = sub.add_parser("agent", help="run one ad-hoc operator with explicit scope and abilities")
    agent_run = agent.add_subparsers(dest="agent_command", required=True).add_parser("run")
    agent_run.add_argument("name")
    agent_run.add_argument("brief")
    scope = agent_run.add_mutually_exclusive_group()
    scope.add_argument("--project")
    scope.add_argument("--system", action="store_true", help="run from the installed CointOS runtime (default)")
    agent_run.add_argument("--directory", help="station this agent in a directory; its writes are confined there")
    agent_run.add_argument("--tool", action="append", default=[], help="a configured MCP server for its station, or '*' for all")
    agent_run.add_argument("--ability", action="append", choices=schema.ABILITIES, default=[])
    agent_run.add_argument("--role", choices=sorted({kind["role"] for kind in schema.KINDS.values()}), default="operator")
    agent_run.add_argument("--task", help="for an integrator: the reviewed worker task; for a first-responder: the failed task")
    agent_run.add_argument("--stage", choices=schema.STAGES)
    agent_run.add_argument("--summary", help="for a worker: 5-20 plain words saying what the task is for")
    agent_run.add_argument("--dependencies-json", type=json.loads, help="for a worker: structured array of prerequisite item IDs")
    agent_run.add_argument("--relies-on-json", type=json.loads, help="for a test-contract worker: structured array of existing API names")
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


def show_task(task_id: str, history: bool = False) -> str:
    try:
        current = ledger()
        reader = current['tasks'].get(os.environ.get('COINTOS_TASK_ID')) or {}
        view = frontier.inspect(task_id, current, history)
        if reader:
            view = frontier.agent_view(view, reader)
        return json.dumps(view, indent=2)
    except ValueError as error:
        raise SystemExit(str(error)) from error


def hold_command(args) -> str:
    if args.release:
        call("unhold", ({"item": args.item}))
        return f"released {args.item}"
    call("hold", ({"item": args.item}))
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
    if args.coin:
        call("viewers", {"show": True})
        return "viewer windows on; Coin occupies a slot while it is active"
    if args.slot is not None:
        return view(args.slot)
    if not (args.all or args.off):
        raise SystemExit("usage: cointos view --all | --off | --coin")
    call("viewers", {"show": args.all})
    return "viewers: opening windows for active agents and Coin" if args.all else "viewers: no new windows"


COMMANDS = {
    "status": lambda args: status_text(ledger()),
    "agents": lambda args: agents_text(ledger()),
    "jobs": lambda args: jobs_text(ledger(), project=args.project, **({"limit": None} if args.all else {})),
    "check": lambda args: show_check(),
    "metrics": lambda args: (call('metrics', {'hours': args.hours})['text'] if os.environ.get('COINTOS_AGENT')
                             else metrics.report(args.hours)),
    "progress": progress_command,
    "task": lambda args: show_task(args.task, args.history),
    "transcript": lambda args: write_transcript(args.task, args.out),
    "log": lambda args: read_log(args),
    'source': source_files,
    "go": lambda args: resume(),
    "stop": stop_command,
    "kill": lambda args: kill_command(args.agent),
    "resume": lambda args: (call("resume-task", {"task": args.task}) and f"released {args.task} for scheduling"),
    "up": lambda args: up(),
    "halt": lambda args: halt(args.keep_coin),
    "restart": lambda args: restart(),
    "watch": lambda args: watch(args.agent),
    "coin": lambda args: coin_live(args.profile),
    "view": view_command,
    "finish": lambda args: finish(*(("complete", args.complete) if args.complete is not None else ("blocked", args.blocked)),
                                  scout_result=args.scout_result_json),
    "merge": lambda args: merge(),
    'handoff': lambda args: json.dumps(call('handoff', {'summary': args.summary, 'items': args.items_json})),
    "review": lambda args: review(),
    'diagnostic': lambda args: json.dumps(call('diagnostic', {'path': args.path, 'project': args.project}), indent=2),
    "land": lambda args: land(args.summary),
    "return": lambda args: send_back(args.notes),
    "replace": lambda args: replace(args.children),
    "incorporate": lambda args: acceptance_text(call("incorporate", {"task": args.task, "commit": args.commit,
                                                                "worker_commit": args.worker_commit},
                                                timeout=LANDING_TIMEOUT)),
    "message": lambda args: "sent to " + call("send", {**({"mailbox": args.mailbox} if args.mailbox else {}),
                                                        "to": args.to, "text": args.text})["to"],
    "inbox": lambda args: "\n\n".join(f"From {m['from']}:\n{m['text']}"
                                       for m in call("inbox", {**({"mailbox": args.mailbox} if args.mailbox else {})})["messages"]) or "no unread messages",
    "queue": lambda args: call("queue", ({
        "project": args.project, "name": args.name, "brief": args.brief, "kind": args.kind, "stage": args.stage,
        "reasoning_effort": args.reasoning_effort, "budget": limits(args), "dependencies": args.dependencies_json,
        "relies_on": args.relies_on_json, "summary": args.summary}))["item"],
    "hold": hold_command,
    "correct-tests": lambda args: json.dumps(call('correct-tests', {
        'project': args.project, 'packet': args.packet, 'name': args.name, 'brief': args.brief,
        'reason': args.reason, 'summary': args.summary, 'relies_on': args.relies_on_json})),
    "check-work": lambda args: json.dumps(call("check-work", {
        **({"brief": args.brief} if args.brief is not None else {}), "project": args.project,
        "name": args.name, "kind": args.kind, "stage": args.stage, "reasoning_effort": args.reasoning_effort,
        "budget": limits(args), "dependencies": args.dependencies_json, "relies_on": args.relies_on_json,
        "summary": args.summary}), indent=2),
    "revise": lambda args: json.dumps(call("revise", ({
        "item": args.item, "brief": args.brief, "reason": args.reason, "stage": args.stage,
        "reasoning_effort": args.reasoning_effort, "budget": limits(args), "dependencies": args.dependencies_json,
        "relies_on": args.relies_on_json, "summary": args.summary}))),
    "move": lambda args: json.dumps(call("move", {"item": args.item, "to": args.to})),
    "cancel": lambda args: json.dumps(call("cancel", ({"items": args.items, "reason": args.reason}))),
    "supersede": lambda args: json.dumps(call("supersede", {"task": args.task, "replacements": args.replacements,
                                                            "reason": args.reason})),
    "clear-review": lambda args: json.dumps(call("clear-review", {"task": args.task, "reason": args.reason})),
    "reasoning": lambda args: json.dumps(call("reasoning", {"task": args.task, "effort": args.effort})),
    "budget": lambda args: json.dumps(call("budget", {"task": args.task, "budget": limits(args) or {}})),
    "project": project_command,
    "split": lambda args: json.dumps(call("split", {"task": args.task, "reason": args.reason})),
    "recover": lambda args: json.dumps(call("recover", {"task": args.task, "reason": args.reason})),
    "agent": lambda args: agent_result(call("run-agent", {"name": args.name, "brief": args.brief, "project": args.project,
                                             "role": args.role, "task": args.task, "stage": args.stage,
                                             "summary": args.summary, "dependencies": args.dependencies_json,
                                             "relies_on": args.relies_on_json,
                                             "abilities": args.ability or ["standard"],
                                             "reasoning_effort": args.reasoning_effort, "budget": limits(args),
                                             "station": {"directory": args.directory, "tools": args.tool}})),
}


def agent_result(result: dict) -> str:
    return json.dumps(result) if os.environ.get('COINTOS_AGENT') else result['task']


def deliver_receipt() -> None:
    """Acknowledge that this managed run's terminal receipt is visible outside its unit."""
    task_id, run = os.environ.get("COINTOS_TASK_ID"), os.environ.get("COINTOS_AGENT")
    if not task_id or not run:
        raise SystemExit("terminal CointOS commands require a managed agent run")
    # The daemon stops this exact unit.  This acknowledgement call may be cut off with it.
    call("receipt-delivered")


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


def main(argv=None, *, acknowledge=True) -> None:
    args = parser().parse_args(argv)
    try:
        output = COMMANDS[args.command](args)
    except ValueError as error:
        if args.command in TERMINAL_COMMANDS and has_receipt_here():
            print(str(error), file=sys.stderr, flush=True)
            if acknowledge:
                deliver_receipt()
            return
        raise SystemExit(str(error))
    except Unreachable as error:
        raise SystemExit(str(error))
    if output:
        if os.environ.get('COINTOS_AGENT'):
            try:
                output = json.dumps(frontier.file_view(json.loads(output)), indent=2)
            except (ValueError, TypeError):
                pass  # Plain-text replies already have their command-owned presentation.
        print(output, flush=args.command in TERMINAL_COMMANDS)
    if acknowledge and args.command in TERMINAL_COMMANDS and has_receipt_here():
        deliver_receipt()


if __name__ == "__main__":
    main()
