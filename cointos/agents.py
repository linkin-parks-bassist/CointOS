"""Agents: OpenCode processes in their own git worktrees, talking only to the gateway."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from cointos.config import ROOT, STATE, api_url, load as load_config

TIMEOUTS = load_config()["timeouts"]

OPENCODE = str(Path.home() / ".local/bin/opencode")
GLOBAL_OPENCODE = Path.home() / ".config/opencode/opencode.json"
PROVIDER = "cointos"
ROLE_FILES = {"worker": "worker.md", "manager": "manager.md", "steward": "steward.md"}


def agent_dir(agent_id: str) -> Path:
    return STATE / "agents" / agent_id


def git(*args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def prepare_worktree(project: dict, task: dict) -> None:
    """Create the task's worktree on its own branch from the main branch, once."""
    if Path(task["worktree"]).is_dir():
        return
    Path(task["worktree"]).parent.mkdir(parents=True, exist_ok=True)
    exists = git("-C", project["path"], "rev-parse", "--verify", "--quiet", task["branch"], check=False).returncode == 0
    if exists:
        git("-C", project["path"], "worktree", "add", task["worktree"], task["branch"])
    else:
        git("-C", project["path"], "worktree", "add", "-b", task["branch"], task["worktree"], project["main_branch"])


def remove_worktree(project: dict, task: dict) -> bool:
    """Remove the worktree and branch once the branch is merged into main. Returns whether it was merged."""
    merged = git("-C", project["path"], "merge-base", "--is-ancestor", task["branch"], project["main_branch"],
                 check=False).returncode == 0
    if merged:
        git("-C", project["path"], "worktree", "remove", "--force", task["worktree"], check=False)
        git("-C", project["path"], "branch", "-d", task["branch"], check=False)
    return merged


def opencode_config(config: dict, key: str) -> dict:
    """The agent's OpenCode config: the gateway as its only provider, narrow denials."""
    work = config["work_model"]
    shape = config["models"][work]
    home = str(Path.home())
    mcp = {}
    try:
        for name, server in json.loads(GLOBAL_OPENCODE.read_text()).get("mcp", {}).items():
            if name != "knowledgetrees":
                mcp[name] = {**server, "enabled": False}
    except (OSError, ValueError):
        pass
    denied_commands = ["sudo *", "su *", "systemctl *", "apt *", "apt-get *", "dpkg *", "snap *",
                       "pip install *", "pip3 install *", "npm install -g *", "git push*", "cointos halt*",
                       "cointos up*", "cointos stop*"]
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{PROVIDER}/{work}",
        "provider": {PROVIDER: {
            "npm": "@ai-sdk/openai-compatible", "name": "CointOS gateway",
            # A request can wait for a lane and then prefill for minutes before its first byte;
            # the daemon's silence check, not a client timeout, decides when an agent is stuck.
            "options": {"baseURL": api_url(config) + "/v1", "apiKey": key,
                        "timeout": False, "headerTimeout": False, "chunkTimeout": False},
            "models": {work: {"name": work, "tool_call": True,
                              "limit": {"context": shape["ctx_size"] // shape["lanes"],
                                        "output": config["scheduler"]["max_thought_tokens"]}}},
        }},
        "mcp": mcp,
        "permission": {
            "*": "allow", "webfetch": "deny", "websearch": "deny", "doom_loop": "deny",
            "bash": {"*": "allow", **{command: "deny" for command in denied_commands}},
            "external_directory": {"*": "deny", f"{home}/**": "allow", f"{home}/Avnet/**": "deny"},
            "read": {"*": "allow", "*.env": "deny", f"{home}/Avnet/**": "deny"},
            "edit": {"*": "allow", f"{home}/Avnet/**": "deny"},
        },
        "autoupdate": False, "share": "disabled",
    }


def prompt(task: dict, project: dict) -> str:
    """Base role, the agent's role, then its assignment."""
    roles = ROOT / "roles"
    parts = [(roles / "_base.md").read_text(), (roles / ROLE_FILES[task["role"]]).read_text()]
    where = (f"Project: {project['name']}, repository {project['path']}, main branch "
             f"`{project['main_branch']}`.\nYour worktree: {task['worktree']}, on branch `{task['branch']}`.")
    finish = ("When your work and your item's new status are committed, bring your branch up to date with "
              f"`git merge {project['main_branch']}` (resolve any conflicts and re-check), then run "
              "`cointos merge` in your worktree to land it on the main branch. Only what lands counts: "
              "commit nothing after that. If `cointos merge` refuses, set the item to "
              "`Status: blocked` with the reason.")
    if task["kind"] == "item":
        assignment = (f"{where}\n\nYour item: `.knowledge/{task['item']}` (read it with kt). As it was "
                      f"queued:\n\n{task['brief']}\n\n{finish}")
    elif task["kind"] == "breakdown":
        assignment = (f"{where}\n\nBreak down the drafted idea `.knowledge/{task['item']}`:\n\n"
                      f"{task['brief']}\n\n{finish}")
    elif task["kind"] == "survey":
        assignment = f"{where}\n\nSurvey this project and keep its queue right.\n\n{finish}"
    else:
        assignment = (f"{where}\n\nDo a maintenance check of CointOS: run `cointos check`, "
                      f"`cointos status` and `cointos agents`, and look at the knowledge tree.\n\n{finish}")
    return "\n\n".join(parts) + "\n\n# Your assignment\n\n" + assignment


def start_server(directory: Path, worktree: str, env: dict) -> tuple[subprocess.Popen, str]:
    log_path = directory / "server.log"
    log = open(log_path, "ab")
    server = subprocess.Popen([OPENCODE, "serve", "--hostname", "127.0.0.1", "--port", "0", "--mdns=false"],
                              cwd=worktree, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                              process_group=0)
    log.close()
    deadline = time.monotonic() + TIMEOUTS["agent_start_seconds"]
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"opencode serve exited with {server.returncode}")
        found = re.search(r"opencode server listening on (http://127\.0\.0\.1:\d+)",
                          log_path.read_text(errors="replace"))
        if found:
            return server, found[1]
        time.sleep(0.2)
    stop_group(server.pid)
    raise RuntimeError(f"opencode serve did not report a listening URL within {TIMEOUTS['agent_start_seconds']}s")


def unit(agent_id: str) -> str:
    return f"cointos-agent-{agent_id}"


def launch(config: dict, agent_id: str, task: dict, project: dict, key: str) -> None:
    """Start an agent's run as its own systemd unit, outside the daemon, so that it outlives a
    daemon restart. The unit runs `python3 -m cointos.agents DIR` (`serve_run`); the daemon
    follows it through the files it writes (`watch`)."""
    directory = agent_dir(agent_id)
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / "opencode.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(opencode_config(config, key), stream, indent=1)
    resumed = bool(task.get("session"))
    text = ("Your previous run on this assignment stopped before it finished. Check where things "
            "stand and continue it to the end. Do not repeat finished work. It is finished only when "
            f"it has landed on `{project['main_branch']}` with `cointos merge`.") if resumed else prompt(task, project)
    command = [OPENCODE, "run", "--dir", task["worktree"], "--format", "json", "--auto",
               "--title", f"{task['role']}: {task['title']}", "--model", f"{PROVIDER}/{config['work_model']}"]
    if resumed:
        command += ["--session", task["session"]]
    spec = {"project": project, "task": task, "command": command, "text": text}
    (directory / "run.json").write_text(json.dumps(spec))
    for stale in ("server.json", "exit.json"):
        (directory / stale).unlink(missing_ok=True)
    subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit(agent_id)}",
                    f"--working-directory={ROOT}", f"--setenv=COINTOS_AGENT={agent_id}",
                    "--property=KillMode=control-group", "--property=TimeoutStopSec=15",
                    # A runaway tool is killed inside its own agent, never by the machine's OOM
                    # handling, which would pick the model server. Only the tool dies (the largest
                    # process); the agent sees it killed and carries on.
                    f"--property=MemoryMax={config['memory']['agent_limit_gb']}G", "--property=MemorySwapMax=0",
                    "--property=OOMPolicy=continue",
                    sys.executable, "-m", "cointos.agents", str(directory)], check=True)


def serve_run(directory: Path) -> None:
    """The agent's unit: its OpenCode server and client, their events into `events.jsonl`, and
    its exit code into `exit.json`. Nothing here depends on the daemon being up."""
    spec = json.loads((directory / "run.json").read_text())
    prepare_worktree(spec["project"], spec["task"])
    env = {**os.environ, "OPENCODE_CONFIG": str(directory / "opencode.json"),
           "PATH": f"{ROOT / 'bin'}:{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"}
    server, url = start_server(directory, spec["task"]["worktree"], env)
    (directory / "server.json").write_text(json.dumps({"pid": server.pid, "url": url}))
    command = spec["command"][:2] + ["--attach", url] + spec["command"][2:]
    with open(directory / "events.jsonl", "ab") as events, open(directory / "client.log", "ab") as errors:
        client = subprocess.Popen(command, cwd=spec["task"]["worktree"], env=env, stdin=subprocess.PIPE,
                                  stdout=events, stderr=errors)
        client.stdin.write(spec["text"].encode())
        client.stdin.close()
        code = client.wait()
    (directory / "exit.json").write_text(json.dumps({"code": code}))
    stop_group(server.pid)


def active(agent_id: str) -> bool:
    state = subprocess.run(["systemctl", "--user", "is-active", unit(agent_id)], capture_output=True, text=True).stdout
    return state.strip() in ("active", "activating", "deactivating")


def stop(agent_id: str) -> None:
    subprocess.run(["systemctl", "--user", "stop", unit(agent_id)], capture_output=True)


def watch(agent_id: str, on_event) -> dict:
    """Follow an agent's run from its files until its unit has ended, reporting as `run` did.
    Blocking; call from the agent's thread. Safe to call again for a run already under way
    (after a daemon restart): it reads the events from the start.

    `on_event(kind, value)` reports "server" ((pid, server URL)), "session" (id) and "activity"
    (a one-line description of what the agent just did, or None).
    Returns {"finish": last step finish reason, "code": client exit code, "text": last text}.
    """
    directory = agent_dir(agent_id)
    outcome, offset, server_seen = {"finish": None, "code": None, "text": ""}, 0, False
    while True:
        running = active(agent_id)
        if not server_seen and (directory / "server.json").exists():
            server = json.loads((directory / "server.json").read_text())
            on_event("server", (server["pid"], server["url"]))
            server_seen = True
        try:
            with open(directory / "events.jsonl", "rb") as stream:
                stream.seek(offset)
                chunk = stream.read()
        except FileNotFoundError:
            chunk = b""
        complete = chunk[:chunk.rfind(b"\n") + 1]
        offset += len(complete)
        for line in complete.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("sessionID"):
                on_event("session", event["sessionID"])
            part = event.get("part") or {}
            on_event("activity", describe(part))
            if part.get("type") == "text" and part.get("text"):
                outcome["text"] = part["text"]
            if event.get("type") == "step_finish":
                outcome["finish"] = part.get("reason")
        if not running and not complete:
            if (directory / "exit.json").exists():
                outcome["code"] = json.loads((directory / "exit.json").read_text())["code"]
            return outcome
        time.sleep(0.5)


def describe(part: dict) -> str | None:
    """One line saying what an OpenCode event part shows the agent doing, if anything."""
    if part.get("type") == "text" and part.get("text"):
        return " ".join(part["text"].split())[:200]
    if part.get("type") == "tool":
        given = (part.get("state") or {}).get("input") or {}
        detail = next((value for value in given.values() if isinstance(value, str) and value), json.dumps(given))
        return f"{part.get('tool')}: {' '.join(str(detail).split())[:180]}"
    return None


def stop_group(pgid: int, grace: float = TIMEOUTS["agent_stop_grace_seconds"]) -> None:
    """Stop a process group: TERM, then KILL whatever is left."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def find_processes() -> dict[str, list[int]]:
    """Live processes carrying a COINTOS_AGENT id, by agent id."""
    found: dict[str, list[int]] = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            environ = (proc / "environ").read_bytes()
            state = (proc / "stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if state == "Z":
            continue
        for entry in environ.split(b"\0"):
            if entry.startswith(b"COINTOS_AGENT="):
                found.setdefault(entry[14:].decode(), []).append(int(proc.name))
                break
    return found


if __name__ == "__main__":
    serve_run(Path(sys.argv[1]))
