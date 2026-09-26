"""Agents: OpenCode processes in their own git worktrees, talking only to the gateway."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from cointos.config import ROOT, STATE, api_url

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
    finish = ("When your work is committed, bring your branch up to date with "
              f"`git merge {project['main_branch']}` (resolve any conflicts and re-check), then run "
              "`cointos merge` in your worktree to land it on the main branch. If `cointos merge` "
              "refuses, set the item to `Status: blocked` with the reason.")
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


def start_server(agent_id: str, worktree: str, env: dict) -> tuple[subprocess.Popen, str]:
    log_path = agent_dir(agent_id) / "server.log"
    log = open(log_path, "ab")
    server = subprocess.Popen([OPENCODE, "serve", "--hostname", "127.0.0.1", "--port", "0", "--mdns=false"],
                              cwd=worktree, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                              process_group=0)
    log.close()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"opencode serve exited with {server.returncode}")
        found = re.search(r"opencode server listening on (http://127\.0\.0\.1:\d+)",
                          log_path.read_text(errors="replace"))
        if found:
            return server, found[1]
        time.sleep(0.2)
    stop_group(server.pid)
    raise RuntimeError("opencode serve did not report a listening URL within 60s")


def run(config: dict, agent: dict, task: dict, project: dict, key: str, on_event) -> dict:
    """Run one agent to the end of its OpenCode run. Blocking; call from the agent's thread.

    `on_event(kind, value)` reports "server" ((process group id, server URL)), "session" (id)
    and "activity" (a one-line description of what the agent just did, or None). The OpenCode server and client share one process group, which
    the caller owns: it stops the group when it has recorded the end of the run.
    Returns {"finish": last step finish reason, "code": client exit code, "text": last text}.
    """
    directory = agent_dir(agent["id"])
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "opencode.json"
    descriptor = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(opencode_config(config, key), stream, indent=1)
    prepare_worktree(project, task)
    env = {**os.environ, "OPENCODE_CONFIG": str(config_path), "COINTOS_AGENT": agent["id"],
           "PATH": f"{ROOT / 'bin'}:{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"}
    server, url = start_server(agent["id"], task["worktree"], env)
    on_event("server", (server.pid, url))
    command = [OPENCODE, "run", "--attach", url, "--dir", task["worktree"], "--format", "json", "--auto",
               "--title", f"{task['role']}: {task['title']}", "--model", f"{PROVIDER}/{config['work_model']}"]
    if task.get("session"):
        command += ["--session", task["session"]]
        text = ("Your previous run on this assignment stopped before it finished. Check where things "
                "stand and continue it to the end. Do not repeat finished work.")
    else:
        text = prompt(task, project)
    client = subprocess.Popen(command, cwd=task["worktree"], env=env, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=open(directory / "client.log", "ab"),
                              process_group=server.pid)
    client.stdin.write(text.encode())
    client.stdin.close()
    outcome = {"finish": None, "code": None, "text": ""}
    with open(directory / "events.jsonl", "ab") as events:
        for line in iter(client.stdout.readline, b""):
            events.write(line)
            events.flush()
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
                if outcome["finish"] == "stop":
                    break
    try:
        outcome["code"] = client.wait(timeout=10)
    except subprocess.TimeoutExpired:
        client.kill()
        outcome["code"] = client.wait()
    return outcome


def describe(part: dict) -> str | None:
    """One line saying what an OpenCode event part shows the agent doing, if anything."""
    if part.get("type") == "text" and part.get("text"):
        return " ".join(part["text"].split())[:200]
    if part.get("type") == "tool":
        given = (part.get("state") or {}).get("input") or {}
        detail = next((value for value in given.values() if isinstance(value, str) and value), json.dumps(given))
        return f"{part.get('tool')}: {' '.join(str(detail).split())[:180]}"
    return None


def stop_group(pgid: int, grace: float = 5) -> None:
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
