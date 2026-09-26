"""cointosd: owns the GPU lanes and hands them out one model request at a time, by priority.

One process, one lock, one ledger. HTTP threads (gateway, API, dashboard) and agent
threads block on I/O; the tick thread measures, guards, reaps, spawns, checks and saves.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import secrets
import signal
import socket
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cointos import agents, checks, config as configuration, machine, models, queues, scheduler
from cointos.config import KEYS, LEDGER, ROOT

CONFIG = configuration.load()
LOCK = threading.Condition(threading.RLock())
WAKE: dict[str, threading.Event] = {}  # request id -> set when its lane is assigned (or it is dropped)
KEY_OWNERS: dict[str, tuple[str, str]] = {}  # gateway key -> (caller, priority class)
AGENT_KEYS: dict[str, str] = {}  # agent id -> its gateway key (kept out of the ledger)
RECENTLY_STOPPED: dict[str, float] = {}  # agent id -> when; its processes may take a moment to exit
STOPPING = threading.Event()
L: dict = {}  # the ledger
DUMP = bool(os.environ.get("COINTOS_DUMP_REQUESTS"))  # debugging: keep every forwarded request body


def now() -> float:
    return time.time()


def log(event: str, **fields) -> None:
    """Add to the bounded recent history (caller holds LOCK or is single-threaded)."""
    L["history"].append({"at": now(), "event": event, **fields})
    del L["history"][:-CONFIG["history_length"]]


def alert(text: str) -> None:
    L["next_alert"] += 1
    L["alerts"].append({"id": L["next_alert"], "at": now(), "text": text})
    del L["alerts"][:-50]
    log("alert", text=text)


# ---------------------------------------------------------------- ledger

def fresh_ledger(previous: dict) -> dict:
    lanes = [{"model": name, "index": index, "up": False, "occupant": None, "caller": None,
              "free_since": now(), "last_caller": None, "served": 0}
             for name, shape in CONFIG["models"].items() for index in range(shape["lanes"])]
    return {
        "started_at": now(), "updated_at": now(), "paused": previous.get("paused", False),
        "models": {name: {"loaded": False, "problems": ["not loaded yet"], "backend": None}
                   for name in CONFIG["models"]},
        "lanes": lanes, "requests": {}, "agents": {}, "tasks": previous.get("tasks", {}),
        "history": previous.get("history", []), "alerts": previous.get("alerts", []),
        "next_alert": previous.get("next_alert", 0), "checks": [], "machine": {},
        "guard": {"breaches": [], "since": None, "unloaded": False, "calm_since": now()},
        "user_last_request": 0, "recent_requests": [], "last_survey": previous.get("last_survey", {}),
        "last_maintenance": previous.get("last_maintenance", 0), "failing": [],
    }


def save() -> None:
    with LOCK:
        L["updated_at"] = now()
        snapshot = json.loads(json.dumps(L))
    configuration.write_json(LEDGER, snapshot)


def load_keys() -> None:
    keys = configuration.read_json(KEYS, {})
    if "coin" not in keys:
        keys["coin"] = secrets.token_urlsafe(24)
        configuration.write_json(KEYS, keys, mode=0o600)
    KEY_OWNERS[keys["coin"]] = ("coin", "coin")


# ---------------------------------------------------------------- scheduling

def blocked_classes() -> frozenset:
    return frozenset({"background"}) if L["guard"]["breaches"] else frozenset()


def schedule() -> None:
    """Give free lanes to waiting requests. Caller holds LOCK."""
    lanes = [lane if lane["up"] else {**lane, "occupant": "down"} for lane in L["lanes"]]
    waiting = [r for r in L["requests"].values() if r["lane"] is None]
    for request_id, position in scheduler.assign(CONFIG, lanes, waiting, now(), blocked_classes()):
        request, lane = L["requests"][request_id], L["lanes"][position]
        request["lane"], request["started_at"] = position, now()
        lane["occupant"], lane["caller"] = request_id, request["caller"]
        WAKE[request_id].set()


def release(request_id: str) -> None:
    """Free the request's lane (if it had one) and forget it. Caller holds LOCK."""
    request = L["requests"].pop(request_id, None)
    WAKE.pop(request_id, None)
    if request and request["lane"] is not None:
        lane = L["lanes"][request["lane"]]
        if lane["occupant"] == request_id:
            lane.update(occupant=None, caller=None, free_since=now(), last_caller=request["caller"])
            lane["served"] += 1
    schedule()


def drop_requests(caller: str) -> None:
    """Wake and forget a caller's waiting requests (its agent was stopped). Caller holds LOCK."""
    for request_id, request in list(L["requests"].items()):
        if request["caller"] == caller and request["lane"] is None:
            L["requests"].pop(request_id)
            WAKE.pop(request_id).set()


def client_gone(connection: socket.socket) -> bool:
    try:
        return connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT) == b""
    except BlockingIOError:
        return False
    except OSError:
        return True


# ---------------------------------------------------------------- HTTP: gateway, API, dashboard

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def reply(self, status: int, value, content_type="application/json"):
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/v1/models":
            return self.reply(200, {"object": "list", "data": [
                {"id": name, "object": "model", "owned_by": "cointos"} for name in CONFIG["models"]]})
        if path == "/api/ledger":
            with LOCK:
                return self.reply(200, L)
        if path in ("/", "/index.html"):
            return self.reply(200, (ROOT / "web/dashboard.html").read_bytes(), "text/html; charset=utf-8")
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/v1/chat/completions":
                return self.gateway(self.body())
            if path.startswith("/api/"):
                return self.reply(200, api(path[5:], self.body()))
            self.reply(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ApiError as error:
            self.reply(400, {"error": str(error)})
        except Exception as error:  # a handler error must never take the daemon down
            traceback.print_exc()
            try:
                self.reply(500, {"error": f"{type(error).__name__}: {error}"})
            except OSError:
                pass

    def gateway(self, body: dict):
        key = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        caller, klass = KEY_OWNERS.get(key, (f"user:{self.client_address[1]}", "user"))
        name = body.get("model", "")
        name = {"work": CONFIG["work_model"], "front": CONFIG["front_model"]}.get(name, name)
        if name not in CONFIG["models"]:
            return self.reply(404, {"error": {"message": f"unknown model {name!r}"}})
        cap = CONFIG["max_output_tokens"]
        body["model"] = name
        body["max_tokens"] = min(int(body.get("max_tokens") or body.get("max_completion_tokens") or cap), cap)
        body.pop("max_completion_tokens", None)
        body["cache_prompt"] = True
        request_id = secrets.token_hex(6)
        signature = hashlib.sha256(json.dumps([body.get("messages"), body.get("tools")], sort_keys=True).encode()).hexdigest()
        wake = threading.Event()
        with LOCK:
            L["requests"][request_id] = {"id": request_id, "caller": caller, "class": klass, "model": name,
                                         "queued_at": now(), "lane": None, "started_at": None}
            WAKE[request_id] = wake
            if klass == "user":
                L["user_last_request"] = now()
            agent = L["agents"].get(caller)
            if agent:
                agent["requests"] += 1
                agent["last_activity"] = now()
                agent["repeats"] = agent["repeats"] + 1 if agent["last_signature"] == signature else 1
                agent["last_signature"] = signature
            schedule()
        try:
            while not wake.wait(1):
                if client_gone(self.connection):
                    return
            with LOCK:
                request = L["requests"].get(request_id)
                if request is None or request["lane"] is None:
                    return self.reply(503, {"error": {"message": "request dropped"}})
                lane = L["lanes"][request["lane"]]
                backend = L["models"][name]["backend"]
            body["id_slot"] = lane["index"]
            if DUMP:
                configuration.write_json(configuration.STATE / "dump" / f"{caller}-{request_id}.json", body)
            timings = self.forward(backend, body)
            with LOCK:
                L["recent_requests"].append({
                    "caller": caller, "model": name, "lane": lane["index"], "at": now(),
                    "waited": round(request["started_at"] - request["queued_at"], 1),
                    "seconds": round(now() - request["started_at"], 1), "prompt": timings.get("prompt_n"),
                    "cached": timings.get("cache_n"), "generated": timings.get("predicted_n")})
                del L["recent_requests"][:-100]
        finally:
            with LOCK:
                release(request_id)
                if agent := L["agents"].get(caller):
                    agent["last_activity"] = now()

    def forward(self, backend: str, body: dict) -> dict:
        """Relay one completion from the model's llama-server, streaming as it arrives."""
        target = urllib.parse.urlparse(backend)
        upstream = http.client.HTTPConnection(target.hostname, target.port, timeout=None)
        try:
            upstream.request("POST", target.path.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                             {"Content-Type": "application/json"})
            response = upstream.getresponse()
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.end_headers()
            tail = b""
            while chunk := response.read1(65536):
                tail = (tail + chunk)[-8192:]
                self.wfile.write(chunk)
                self.wfile.flush()
            found = re.findall(rb'"timings":(\{[^{}]*\})', tail)
            return json.loads(found[-1]) if found else {}
        finally:
            upstream.close()


class ApiError(Exception):
    pass


def api(action: str, body: dict):
    """Control actions for the CLI, Coin and the dashboard."""
    with LOCK:
        if action == "stop":
            L["paused"] = True
            for agent_id in list(L["agents"]):
                stop_agent(agent_id, "stopped by David", requeue=True, charge=False)
            log("paused")
            return {"ok": True, "paused": True}
        if action == "go":
            L["paused"] = False
            log("resumed")
            return {"ok": True, "paused": False}
        if action == "stop-agent":
            if body.get("agent") not in L["agents"]:
                raise ApiError(f"no live agent {body.get('agent')!r}")
            stop_agent(body["agent"], "stopped by David", requeue=body.get("requeue", False), charge=False)
            return {"ok": True}
        if action == "queue":
            project = project_named(body.get("project", ""))
            item = queues.add(project, body.get("kind", "queued"), body["name"], body["brief"])
            log("queued", project=project["name"], item=item)
            return {"ok": True, "item": item}
        if action == "shutdown":
            threading.Thread(target=shutdown, daemon=True).start()
            return {"ok": True}
    raise ApiError(f"unknown action {action!r}")


def project_named(name: str) -> dict:
    for project in CONFIG["projects"]:
        if project["name"].lower() == name.lower():
            return project
    raise ApiError(f"unknown project {name!r}; configured: {[p['name'] for p in CONFIG['projects']]}")


# ---------------------------------------------------------------- models

def bring_up_models() -> None:
    for name in CONFIG["models"]:
        if STOPPING.is_set():
            return
        bring_up(name)


def bring_up(name: str) -> None:
    try:
        entry = models.load(CONFIG, name)
        with LOCK:
            L["models"][name] = {"loaded": True, "problems": [], "backend": entry["backend_url"]}
            for lane in L["lanes"]:
                if lane["model"] == name:
                    lane.update(up=True, free_since=now())
            log("model up", model=name)
            schedule()
    except Exception as error:
        with LOCK:
            L["models"][name] = {"loaded": False, "problems": [str(error)], "backend": None}
            alert(f"Could not load {name}: {error}")


def take_down(name: str) -> None:
    with LOCK:
        for lane in L["lanes"]:
            if lane["model"] == name:
                lane["up"] = False
        L["models"][name] = {"loaded": False, "problems": ["unloaded by the guard"], "backend": None}
    try:
        models.unload(CONFIG, name)
    except Exception as error:
        with LOCK:
            alert(f"Could not unload {name}: {error}")


# ---------------------------------------------------------------- agents and tasks

def start_agent(task_id: str) -> None:
    """Start an agent on a task. Caller holds LOCK."""
    task = L["tasks"][task_id]
    agent_id = f"{task['role']}-{secrets.token_hex(3)}"
    key = secrets.token_urlsafe(24)
    KEY_OWNERS[key] = (agent_id, "background")
    AGENT_KEYS[agent_id] = key
    task.update(status="running", runs=task["runs"] + 1, agent=agent_id, updated_at=now())
    agent = {"id": agent_id, "role": task["role"], "project": task["project"], "task": task_id,
             "item": task.get("item"), "title": task["title"], "worktree": task["worktree"],
             "pid": None, "session": task.get("session"), "requests": 0, "repeats": 0,
             "last_signature": None, "last_activity": now(), "started_at": now(), "state": "starting",
             "outcome": None}
    L["agents"][agent_id] = agent
    log("agent started", agent=agent_id, task=task_id, run=task["runs"])
    threading.Thread(target=agent_thread, args=(agent_id, dict(task), key), daemon=True).start()


def agent_thread(agent_id: str, task: dict, key: str) -> None:
    def on_event(kind, value):
        with LOCK:
            agent = L["agents"].get(agent_id)
            if agent is None:
                if kind == "server":  # stopped while starting
                    threading.Thread(target=agents.stop_group, args=(value,), daemon=True).start()
                return
            if kind == "server":
                agent["pid"], agent["state"] = value, "running"
            elif kind == "session" and agent["session"] != value:
                agent["session"] = value
                L["tasks"][agent["task"]]["session"] = value
            agent["last_activity"] = now()
    try:
        outcome = agents.run(CONFIG, {"id": agent_id}, task, project_named(task["project"]), key, on_event)
    except Exception as error:
        outcome = {"finish": None, "code": None, "text": "", "error": f"{type(error).__name__}: {error}"}
    with LOCK:
        agent = L["agents"].get(agent_id)
        if agent is not None and agent["state"] != "stopping":
            agent.update(state="exited", outcome=outcome)


def stop_agent(agent_id: str, reason: str, requeue: bool, charge: bool = True) -> None:
    """Stop an agent now and settle its task. An uncharged stop (David, the guard, a halt)
    does not count against the task's runs. Caller holds LOCK."""
    agent = L["agents"].get(agent_id)
    if agent is None:
        return
    RECENTLY_STOPPED[agent_id] = now()
    if not charge and agent["task"] in L["tasks"]:
        L["tasks"][agent["task"]]["runs"] -= 1
    agent["state"] = "stopping"
    if agent["pid"]:
        threading.Thread(target=agents.stop_group, args=(agent["pid"],), daemon=True).start()
    task = L["tasks"].get(agent["task"])
    if task is not None:
        exhausted = task["runs"] >= CONFIG["spawner"]["max_runs_per_task"]
        task.update(status="waiting" if requeue and not exhausted else "failed", agent=None,
                    note=reason, updated_at=now())
        if task["status"] == "failed":
            alert(f"Gave up on {task['title']} in {task['project']} after {task['runs']} runs: {reason}")
    finish_agent(agent_id, reason)


def finish_agent(agent_id: str, reason: str) -> None:
    agent = L["agents"].pop(agent_id)
    KEY_OWNERS.pop(AGENT_KEYS.pop(agent_id, ""), None)
    drop_requests(agent_id)
    log("agent ended", agent=agent_id, task=agent["task"], reason=reason,
        requests=agent["requests"], seconds=round(now() - agent["started_at"]))


def settle(agent_id: str) -> None:
    """An agent's run ended by itself: decide whether its task is finished. Caller holds LOCK."""
    agent = L["agents"][agent_id]
    task = L["tasks"][agent["task"]]
    outcome = agent["outcome"] or {}
    project = project_named(task["project"])
    if task["kind"] in ("item", "breakdown"):
        found = queues.read_item(Path(task["worktree"]), task["item"]) or queues.read_item(Path(project["path"]), task["item"])
        leaf_status = found["status"] if found else None
        finished = leaf_status in (("done", "blocked") if task["kind"] == "item" else ("in progress", "done", "blocked"))
        detail = f"item status {leaf_status}"
    else:
        finished = outcome.get("finish") == "stop"
        detail = f"run finished with {outcome.get('finish')}"
    if outcome.get("error"):
        detail += f"; {outcome['error']}"
    if finished:
        merged = agents.remove_worktree(project, task)
        task.update(status="done", agent=None, updated_at=now(), note=detail + ("" if merged else "; branch not merged"),
                    result=(outcome.get("text") or "")[-2000:])
        log("task finished", task=agent["task"], detail=task["note"])
        finish_agent(agent_id, "finished")
    else:
        stop_agent(agent_id, f"run ended unfinished ({detail})", requeue=True)


def next_task() -> str | None:
    """The next task to run, creating it from the queues if needed. Caller holds LOCK."""
    tasks = L["tasks"]
    waiting = sorted((t for t in tasks.values() if t["status"] == "waiting"), key=lambda t: t["created_at"])
    if waiting:
        return waiting[0]["id"]
    candidates = []
    for project in CONFIG["projects"]:
        for found in queues.scan(project):
            task_id = f"{project['name']}:{found['item']}"
            known = tasks.get(task_id)
            if known and (known["status"] in ("running", "waiting") or known["leaf_hash"] == found["hash"]):
                continue
            if found["kind"] in ("urgent", "queued") and found["status"] == "queued":
                candidates.append((0 if found["kind"] == "urgent" else 1, "item", "worker", project, found))
            elif found["kind"] == "drafted" and found["status"] == "drafted":
                candidates.append((2, "breakdown", "manager", project, found))
    if candidates:
        _, kind, role, project, found = min(candidates, key=lambda c: c[0])
        return new_task(project, kind, role, found["item"], found["brief"], found["hash"])
    spawner = CONFIG["spawner"]
    for project in CONFIG["projects"]:
        if now() - L["last_survey"].get(project["name"], 0) > spawner["survey_every_seconds"]:
            L["last_survey"][project["name"]] = now()
            return new_task(project, "survey", "manager", None, "", None)
    maintained = [p for p in CONFIG["projects"] if p["name"] == spawner["maintenance_project"]]
    if maintained and now() - L["last_maintenance"] > spawner["maintenance_every_seconds"]:
        L["last_maintenance"] = now()
        return new_task(maintained[0], "maintenance", "steward", None, "", None)
    return None


def new_task(project: dict, kind: str, role: str, item: str | None, brief: str, leaf_hash: str | None) -> str:
    name = Path(item).stem if item else f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    task_id = f"{project['name']}:{item}" if item else f"{project['name']}:{name}"
    worktree = str(configuration.STATE / "worktrees" / project["name"] / name)
    L["tasks"][task_id] = {
        "id": task_id, "project": project["name"], "kind": kind, "role": role, "item": item,
        "title": name, "brief": brief, "leaf_hash": leaf_hash, "status": "waiting", "runs": 0,
        "session": None, "agent": None, "worktree": worktree, "branch": f"cointos/{name}",
        "created_at": now(), "updated_at": now(), "note": None,
    }
    log("task created", task=task_id)
    return task_id


def spawn() -> None:
    """Keep up to max_agents agents alive while there is room and work. Caller holds LOCK."""
    if (L["paused"] or L["guard"]["breaches"] or not L["models"][CONFIG["work_model"]]["loaded"]
            or now() - L["user_last_request"] < CONFIG["user_quiet_seconds"]):
        return
    while len(L["agents"]) < CONFIG["spawner"]["max_agents"]:
        task_id = next_task()
        if task_id is None:
            return
        start_agent(task_id)


# ---------------------------------------------------------------- tick

def guard() -> None:
    """Act on physical limits. Caller holds LOCK."""
    state, limits = L["guard"], CONFIG["limits"]
    found = machine.breaches(limits, L["machine"])
    if found and not state["breaches"]:
        state["since"] = now()
        alert("Memory limit crossed: " + "; ".join(found) + ". Stopping background agents.")
        for agent_id in list(L["agents"]):
            stop_agent(agent_id, "guard: memory limit", requeue=True, charge=False)
    state["breaches"] = found
    if found:
        state["calm_since"] = None
        work = CONFIG["work_model"]
        if not state["unloaded"] and now() - state["since"] > limits["unload_after_seconds"]:
            state["unloaded"] = True
            alert(f"Memory pressure persists; unloading {work}.")
            threading.Thread(target=take_down, args=(work,), daemon=True).start()
    else:
        state["since"] = None
        state["calm_since"] = state["calm_since"] or now()
        if state["unloaded"] and now() - state["calm_since"] > limits["calm_seconds_before_reload"]:
            state["unloaded"] = False
            alert(f"Memory is calm again; reloading {CONFIG['work_model']}.")
            threading.Thread(target=bring_up, args=(CONFIG["work_model"],), daemon=True).start()


def tick(last_spawn: list) -> None:
    measured = machine.sample()
    processes = agents.find_processes()
    with LOCK:
        processes = {a: p for a, p in processes.items() if a not in RECENTLY_STOPPED or a in L["agents"]}
        L["machine"] = measured
        guard()
        limits = CONFIG["checks"]
        for agent_id, agent in list(L["agents"].items()):
            if agent["state"] == "exited":
                settle(agent_id)
            elif agent["state"] == "running" and agent_id not in processes:
                stop_agent(agent_id, "agent process died", requeue=True)
            elif now() - agent["last_activity"] > limits["agent_silent_seconds"]:
                stop_agent(agent_id, "silent too long", requeue=True)
            elif agent["repeats"] > limits["max_identical_requests"]:
                stop_agent(agent_id, "repeating one request", requeue=True)
        if now() - last_spawn[0] >= CONFIG["spawner"]["interval_seconds"]:
            last_spawn[0] = now()
            try:
                spawn()
            except Exception as error:
                traceback.print_exc()
                alert(f"Spawner error: {type(error).__name__}: {error}")
        schedule()
        for agent_id, stopped_at in list(RECENTLY_STOPPED.items()):
            if now() - stopped_at > 30:
                del RECENTLY_STOPPED[agent_id]
        live = dict(processes)
        for agent_id, agent in L["agents"].items():
            if agent["state"] == "starting":
                live.setdefault(agent_id, [])  # still being launched
        L["checks"] = checks.evaluate(CONFIG, L, now(), live, blocked_classes())
        failing = [c["name"] for c in L["checks"] if not c["ok"]]
        for check in L["checks"]:
            if not check["ok"] and check["name"] not in L["failing"]:
                alert(f"Self-check failed: {check['name']}: {check['detail']}")
        L["failing"] = failing
    save()


def recover_leftovers(previous: dict) -> None:
    """Stop agent processes left by an earlier daemon and requeue their tasks."""
    for agent_id, pids in agents.find_processes().items():
        for pid in pids:
            try:
                agents.stop_group(pid, grace=2)
            except PermissionError:
                pass
    for task in L["tasks"].values():
        if task["status"] == "running":
            task.update(status="waiting", agent=None, note="daemon restarted", updated_at=now())
    if previous.get("agents"):
        log("recovered", agents=list(previous["agents"]))


def shutdown() -> None:
    if STOPPING.is_set():
        return
    STOPPING.set()
    with LOCK:
        for agent_id in list(L["agents"]):
            stop_agent(agent_id, "daemon stopping", requeue=True, charge=False)
        log("daemon stopped")
    time.sleep(1)
    save()


def main() -> None:
    previous = configuration.read_json(LEDGER, {}) or {}
    L.update(fresh_ledger(previous))
    load_keys()
    recover_leftovers(previous)
    log("daemon started")
    save()
    server = ThreadingHTTPServer(("127.0.0.1", CONFIG["port"]), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=bring_up_models, daemon=True).start()

    def on_signal(signum, frame):
        shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    last_spawn = [0.0]
    while not STOPPING.is_set():
        started = time.monotonic()
        try:
            tick(last_spawn)
        except Exception:
            traceback.print_exc()
        time.sleep(max(0.0, CONFIG["tick_seconds"] - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
