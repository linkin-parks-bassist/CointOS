"""OpenCode: the fingertip where an agent run becomes processes and files, and back.

Each run is a transient systemd user unit `cointos-agent-<id>` running `python3 -m
cointos.opencode DIR` (`serve_run`): an OpenCode server and a `run` client in the task's
worktree, thinking only through the gateway. The unit writes `server.json`, `events.jsonl` and
`exit.json` into its directory; the daemon follows those files (`watch`) and so can outlive,
and be outlived by, the run. Nothing here decides what a run achieved: `watch` reports
execution facts only.
"""
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
GLOBAL_CONFIG = Path.home() / ".config/opencode/opencode.json"
PROVIDER = "cointos"
# Commands no agent may run; `control` ability lifts only the CointOS lifecycle ones.
DENIED_COMMANDS = ["sudo *", "su *", "systemctl *", "apt *", "apt-get *", "dpkg *", "snap *",
                   "pip install *", "pip3 install *", "npm install -g *", "git push*"]
LIFECYCLE_COMMANDS = ["cointos halt*", "cointos up*", "cointos stop*", "cointos kill*", "cointos resume*", "cointos restart*"]


def run_dir(agent_id: str) -> Path:
    return STATE / "agents" / agent_id


def unit(agent_id: str) -> str:
    return f"cointos-agent-{agent_id}"


def settings(config: dict, key: str, task: dict, protected: list[str]) -> dict:
    """The run's OpenCode config: the gateway as its only provider, and narrow denials."""
    work = config["work_model"]
    shape = config["models"][work]
    home = str(Path.home())
    try:
        servers = json.loads(GLOBAL_CONFIG.read_text()).get("mcp", {})
    except (OSError, ValueError):
        servers = {}
    abilities = set(task.get("abilities") or ["standard"])
    denied = DENIED_COMMANDS + ([] if "control" in abilities else LIFECYCLE_COMMANDS)
    network = "allow" if "network" in abilities else "deny"
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
        # Agents get the kt MCP server; every other globally configured server is disabled.
        "mcp": {name: {**server, "enabled": False} for name, server in servers.items() if name != "knowledgetrees"},
        "permission": {
            "*": "allow", "webfetch": network, "websearch": network, "doom_loop": "deny",
            "bash": {"*": "allow", **{command: "deny" for command in denied}},
            "external_directory": {"*": "deny", f"{home}/**": "allow", f"{home}/Avnet/**": "deny"},
            "read": {"*": "allow", "*.env": "deny", f"{home}/Avnet/**": "deny"},
            "edit": {"*": "allow", **{path: "deny" for path in protected}, f"{home}/Avnet/**": "deny"},
        },
        "autoupdate": False, "share": "disabled",
    }


def launch(config: dict, agent_id: str, task: dict, key: str, text: str, protected: list[str]) -> None:
    """Start a run as its own systemd unit, outside the daemon, so that it outlives a daemon
    replacement. `text` is the message the run starts with."""
    directory = run_dir(agent_id)
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / "opencode.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(settings(config, key, task, protected), stream, indent=1)
    command = [OPENCODE, "run", "--dir", task["worktree"], "--format", "json", "--auto",
               "--title", f"{task['role']}: {task['title']}", "--model", f"{PROVIDER}/{config['work_model']}"]
    if task.get("session"):
        command += ["--session", task["session"]]
    spec = {"task": {"id": task["id"], "worktree": task["worktree"]}, "command": command, "text": text}
    (directory / "run.json").write_text(json.dumps(spec))
    for stale in ("server.json", "exit.json"):
        (directory / stale).unlink(missing_ok=True)
    subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit(agent_id)}",
                    f"--working-directory={ROOT}", f"--setenv=COINTOS_AGENT={agent_id}",
                    "--property=Before=cointosd.service",
                    "--property=KillMode=control-group", "--property=TimeoutStopSec=15",
                    # A runaway tool is killed inside its own agent, never by the machine's OOM
                    # handling, which would pick the model server. Only the tool dies (the largest
                    # process); the agent sees it killed and carries on.
                    f"--property=MemoryMax={config['memory']['agent_limit_gb']}G", "--property=MemorySwapMax=0",
                    "--property=OOMPolicy=continue",
                    sys.executable, "-m", "cointos.opencode", str(directory)], check=True)


def environment(directory: Path, spec: dict) -> dict:
    """The run's processes know their run (COINTOS_AGENT, from the unit) and task, so the CLI
    can submit receipts and proposals as them."""
    return {**os.environ, "OPENCODE_CONFIG": str(directory / "opencode.json"),
            "COINTOS_TASK_ID": spec["task"]["id"],
            "PATH": f"{ROOT / 'bin'}:{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"}


def start_server(directory: Path, worktree: str, env: dict) -> tuple[subprocess.Popen, str]:
    log_path = directory / "server.log"
    with open(log_path, "ab") as log:
        server = subprocess.Popen([OPENCODE, "serve", "--hostname", "127.0.0.1", "--port", "0", "--mdns=false"],
                                  cwd=worktree, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                  process_group=0)
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


def serve_run(directory: Path) -> None:
    """The run's unit: its OpenCode server and client, their events into `events.jsonl`, and the
    client's exit code into `exit.json`. Nothing here depends on the daemon being up."""
    spec = json.loads((directory / "run.json").read_text())
    env = environment(directory, spec)
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
    """Follow a run from its files until its unit has ended. Blocking; safe to call again for a
    run already under way (after a daemon restart): it reads the events from the start.

    `on_event(kind, value)` reports "server" ((pid, server URL)), "session" (id) and "activity"
    (a one-line description of what the agent just did, or None). Returns execution facts only:
    {"finish": the last step's finish marker, "code": the client's exit code}.
    """
    directory = run_dir(agent_id)
    facts, offset, server_seen = {"finish": None, "code": None}, 0, False
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
            if event.get("type") == "step_finish":
                facts["finish"] = part.get("reason")
        if not running and not complete:
            if (directory / "exit.json").exists():
                facts["code"] = json.loads((directory / "exit.json").read_text())["code"]
            return facts
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


def evidence(agent_id: str, limit: int) -> list[str]:
    """The run's most recent outward text and completed tool calls, newest first; never its
    hidden reasoning."""
    try:
        lines = (run_dir(agent_id) / "events.jsonl").read_text(errors="replace").splitlines()
    except OSError:
        return []
    found = []
    for line in reversed(lines):
        try:
            part = json.loads(line).get("part") or {}
        except ValueError:
            continue
        if part.get("type") == "text" and part.get("text"):
            found.append("OUTWARD: " + clip(part["text"]))
        elif part.get("type") == "tool" and (part.get("state") or {}).get("status") == "completed":
            state = part["state"]
            found.append("TOOL: " + clip(part.get("tool")) + " " + clip(state.get("input"), 900) +
                         "\nRESULT: " + clip(state.get("output"), 1400))
        if len(found) >= limit:
            break
    return found


def clip(text, limit=1200) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def attach(agent: dict) -> list[str]:
    """The command that shows a live run in OpenCode's own view."""
    return [OPENCODE, "attach", agent["url"], "--session", agent["session"]]


# ---------------------------------------------------------------- processes

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


def processes_by(variable: str) -> dict[str, list[int]]:
    """Live processes carrying an environment variable, by its value."""
    found: dict[str, list[int]] = {}
    prefix = variable.encode() + b"="
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
            if entry.startswith(prefix):
                found.setdefault(entry[len(prefix):].decode(), []).append(int(proc.name))
                break
    return found


def find_processes() -> dict[str, list[int]]:
    """Live agent processes, by agent id."""
    return processes_by("COINTOS_AGENT")


if __name__ == "__main__":
    serve_run(Path(sys.argv[1]))
