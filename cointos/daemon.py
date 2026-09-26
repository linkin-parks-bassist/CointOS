"""cointosd: an operating system for agents.

One process owns the model lanes and time-shares them among thinking agents, pre-emptively
(`what/is/the/architecture/of/cointos.md`). HTTP threads carry thoughts in and out, lane
threads advance them, agent threads own OpenCode processes, and the tick measures memory,
reconciles models, looks after agents, spawns work, checks invariants and saves the ledger.
"""
from __future__ import annotations

import faulthandler
import signal
import threading
import time
import traceback

from cointos import agents, checks, gateway, lanes, memory, work
from cointos.config import LEDGER, read_json
from cointos.state import BACKEND, CONFIG, LOCK, L, STOPPING, alert, fresh, log, now, save


# ---------------------------------------------------------------- models

def check_models() -> None:
    """Match lanes to what the model server actually serves, and launch a wanted model that
    is missing, one at a time, once its memory fits."""
    try:
        found, unreachable = BACKEND.models(CONFIG), None
    except Exception as error:
        found, unreachable = None, f"model server unreachable: {error}"
    with LOCK:
        for name, state in L["models"].items():
            if state["launching"]:
                continue
            problems = [unreachable] if found is None else found[name].get("problems", [])
            if not problems and not state["up"]:
                state.update(up=True, problems=[])
                lanes.lanes_up(name)
                log("model up", model=name)
            elif problems and state["up"]:
                state.update(up=False, problems=problems)
                lanes.lanes_down(name)
                alert(f"{name} stopped serving: {'; '.join(problems)}")
            elif problems:
                state["problems"] = problems
        if found is None or STOPPING.is_set() or any(m["launching"] for m in L["models"].values()):
            return
        for name, state in L["models"].items():
            if state["up"] or (L["guard"]["killed"] and name == CONFIG["work_model"]):
                continue
            if not lanes.make_room(CONFIG["models"][name]["memory_gb"]):
                state["problems"] = [f"waiting for {CONFIG['models'][name]['memory_gb']} GB of headroom"]
                continue
            state["launching"] = True
            threading.Thread(target=launch, args=(name,), daemon=True).start()
            return


def launch(name: str) -> None:
    try:
        BACKEND.launch(CONFIG, name)
    except Exception as error:
        with LOCK:
            alert(f"Could not launch {name}: {error}")
    finally:
        with LOCK:
            L["models"][name]["launching"] = False


# ---------------------------------------------------------------- memory

def guard() -> None:
    """Keep the one memory rule: snapshots give way when headroom goes negative; background
    work waits while it stays negative; sustained distress stops background agents and kills
    the work model until its memory fits again. Caller holds LOCK."""
    measured, server = memory.measure(), BACKEND.budget(CONFIG)
    L["memory"] = {**measured, "server": server, "headroom_gb": memory.headroom_gb(CONFIG, measured, server)}
    state = L["guard"]
    state["blocked"] = L["memory"]["headroom_gb"] < 0 and not lanes.make_room(0.0)
    distress = memory.distressed(CONFIG, measured)
    if not distress:
        state["distress_since"] = None
        work_model = CONFIG["work_model"]
        if state["killed"] and L["memory"]["headroom_gb"] >= CONFIG["models"][work_model]["memory_gb"]:
            state["killed"] = False  # check_models launches it again
            alert(f"Memory has recovered; launching {work_model} again.")
        return
    state["distress_since"] = state["distress_since"] or now()
    if state["killed"] or now() - state["distress_since"] < CONFIG["memory"]["distress_seconds"]:
        return
    state["killed"] = True
    alert("The machine is under memory distress (" + "; ".join(distress) + "): stopping background agents "
          f"and killing {CONFIG['work_model']}.")
    for agent_id, agent in list(L["agents"].items()):
        if agent["class"] == "background":
            work.stop_agent(agent_id, "memory distress", requeue=True, charge=False)
    threading.Thread(target=BACKEND.kill, args=(CONFIG, CONFIG["work_model"]), daemon=True).start()


# ---------------------------------------------------------------- tick

def look_after_agents() -> None:
    """Derive each agent's state from its thoughts, and stop silent or looping agents. Caller holds LOCK."""
    limits = CONFIG["checks"]
    for agent_id, agent in list(L["agents"].items()):
        if agent["state"] != "starting":
            mine = [t for t in L["thoughts"].values() if t["agent"] == agent_id]
            holding = [t for t in mine if t["lane"] is not None]
            agent["state"] = ("reading" if any(t["reading"] for t in holding) else "thinking" if holding
                              else "waiting" if mine else "acting")
            if mine:
                agent["last_activity"] = now()
        if agent["state"] == "acting" and now() - agent["last_activity"] > limits["agent_silent_seconds"]:
            work.stop_agent(agent_id, "silent too long", requeue=True)
        elif agent["repeats"] > limits["max_identical_thoughts"]:
            work.stop_agent(agent_id, "repeating one thought", requeue=True)


def tick(timers: dict) -> None:
    if now() - timers["models"] >= CONFIG["model_check_seconds"]:
        timers["models"] = now()
        check_models()
    processes = agents.find_processes()
    with LOCK:
        guard()
        lanes.schedule()  # time is an input too: a slice runs out between events
        look_after_agents()
        if now() - timers["spawn"] >= CONFIG["spawner"]["interval_seconds"]:
            timers["spawn"] = now()
            try:
                work.spawn()
            except Exception as error:
                traceback.print_exc()
                alert(f"Spawner error: {type(error).__name__}: {error}")
        for agent_id, ended_at in list(L["exiting"].items()):
            if now() - ended_at > CONFIG["checks"]["exit_grace_seconds"]:
                del L["exiting"][agent_id]
        L["checks"] = checks.evaluate(CONFIG, L, now(), processes, lanes.blocked())
        failing = [c["name"] for c in L["checks"] if not c["ok"]]
        for check in L["checks"]:
            if not check["ok"] and check["name"] not in L["failing"]:
                alert(f"Self-check failed: {check['name']}: {check['detail']}")
        L["failing"] = failing
    save()


def shutdown() -> None:
    with LOCK:
        for agent_id in list(L["agents"]):
            work.stop_agent(agent_id, "daemon stopping", requeue=True, charge=False)
        log("daemon stopped")
    STOPPING.set()
    with LOCK:
        LOCK.notify_all()
    time.sleep(1)
    save()


def main() -> None:
    faulthandler.register(signal.SIGUSR1, all_threads=True)  # `kill -USR1` shows every thread's stack
    L.update(fresh(read_json(LEDGER, {}) or {}))
    work.load_keys()
    work.recover_leftovers()
    with LOCK:
        log("daemon started")
    save()
    gateway.serve()
    lanes.start()

    def on_signal(signum, frame):
        shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    timers = {"models": 0.0, "spawn": 0.0}
    while not STOPPING.is_set():
        started = time.monotonic()
        try:
            tick(timers)
        except Exception:
            traceback.print_exc()
        time.sleep(max(0.0, CONFIG["tick_seconds"] - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
