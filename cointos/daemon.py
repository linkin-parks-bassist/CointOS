"""cointosd: an operating system for agents.

One process owns the model lanes and time-shares them among thinking agents, pre-emptively
(`what/is/the/architecture/of/cointos.md`). HTTP threads carry thoughts in and out, lane
threads advance them, agent threads own OpenCode processes, and the tick measures memory,
reconciles models, looks after agents, spawns work, checks invariants and saves the ledger.
"""
from __future__ import annotations

import faulthandler
import signal
import subprocess
import threading
import time
import traceback

from cointos import (checks, gateway, keys, lanes, lifecycle, memory, opencode, queues, recovery, runs, settings,
                     snapshots, spawner, viewers)
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
            if not snapshots.make_room(CONFIG["models"][name]["memory_gb"]):
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

RUNGS = ("normal", "saved contexts out of memory", "background agents stopped", "work model unloaded")


def guard() -> None:
    """Give memory back while the machine needs it, one rung at a time, and take it again only
    once things are calm (`what/is/the/architecture/of/cointos.md`, *Memory*). Headroom is the
    leading signal: while it stays negative after saved contexts have left memory, climb a rung
    and let the effect show before the next. Sustained pressure is a shortcut to the top. The
    core (daemon, front-desk model, Coin) stays. Caller holds LOCK."""
    measured, server = memory.measure(), BACKEND.budget(CONFIG)
    L["memory"] = {**measured, "server": server, "headroom_gb": memory.headroom_gb(CONFIG, measured, server)}
    snapshots.room(0.0)  # bound caches before general pressure reaches the desktop
    state, limits = L["guard"], CONFIG["memory"]
    short = L["memory"]["headroom_gb"] < 0 and not snapshots.make_room(0.0)  # rung 1 happens here, always
    distress = memory.distressed(CONFIG, measured)
    state["distress_since"] = (state["distress_since"] or now()) if distress else None
    urgent = distress and now() - state["distress_since"] >= limits["distress_seconds"]
    if short or distress:
        state["calm_since"] = None
        top = len(RUNGS) - 1
        rung = top if urgent else min(top, max(state["rung"], 1) + 1) if short else state["rung"]
        if rung > state["rung"] and now() - state["rung_at"] >= limits["shed_step_seconds"]:
            climb(rung, "; ".join(distress) or f"headroom {L['memory']['headroom_gb']} GB")
    else:
        state["calm_since"] = state["calm_since"] or now()
        work_model = CONFIG["models"][CONFIG["work_model"]]
        fits = state["rung"] < 3 or L["memory"]["headroom_gb"] >= work_model["memory_gb"]
        if state["rung"] > 0 and fits and now() - state["calm_since"] >= limits["calm_seconds"]:
            down = state["rung"] - 1 if state["rung"] > 2 else 0  # rung 1 is not a state: it happens whenever needed
            state.update(rung=down, rung_at=now(), calm_since=now())
            alert(f"Memory is calm: back to {RUNGS[state['rung']]}.")
    state["blocked"] = short or state["rung"] >= 2
    state["killed"] = state["rung"] >= 3


def climb(rung: int, why: str) -> None:
    """Take the ladder up to `rung`, doing each rung's work on the way. Caller holds LOCK."""
    state = L["guard"]
    for step in range(state["rung"] + 1, rung + 1):
        if step == 2:
            for agent_id, agent in list(L["agents"].items()):
                if agent["class"] == "background":
                    lifecycle.stop(agent_id, "memory needed", requeue=True, charge=False)
        if step == 3:
            threading.Thread(target=BACKEND.kill, args=(CONFIG, CONFIG["work_model"]), daemon=True).start()
    state.update(rung=rung, rung_at=now())
    alert(f"Giving memory back ({why}): {RUNGS[rung]}.")


# ---------------------------------------------------------------- tick

def look_after_agents() -> None:
    """Derive each agent's state from its thoughts, and stop silent or looping agents. Caller holds LOCK."""
    limits = CONFIG["checks"]
    for agent_id, agent in list(L["agents"].items()):
        if agent["state"] != "starting":
            mine = [t for t in L["thoughts"].values() if t["agent"] == agent_id]
            holding = [t for t in mine if t["lane"] is not None]
            agent["state"] = ("reading" if any(t["reading"] for t in holding) else "thinking" if holding
                              else "waiting" if mine else "running")
            if mine or L["quiescing"]:
                # Deployment quiescence defers new thoughts; waiting on it is the daemon's
                # silence, not the agent's.
                agent["last_activity"] = now()
        if agent["repeats"] > limits["max_identical_thoughts"]:
            lifecycle.stop(agent_id, "repeating one thought", requeue=True)
    for agent_id in checks.silent_agents(CONFIG, L, now()):
        lifecycle.stop(agent_id, "silent too long", requeue=True)


def tick(timers: dict) -> None:
    with LOCK:
        settings.refresh()
        guard()  # memory is measured first: everything after asks whether something fits
    if now() - timers["models"] >= CONFIG["model_check_seconds"]:
        timers["models"] = now()
        check_models()
    processes = opencode.find_processes()
    windows = viewers.open_windows() if CONFIG["viewers"]["max_viewers"] else set()
    with LOCK:
        lanes.schedule()  # time is an input too: a slice runs out between events
        look_after_agents()
        recovery.enforce()
        _, _, queue_changed = spawner.refresh()
        L["incidents"] = recovery.incidents()
        if CONFIG["viewers"]["max_viewers"]:
            viewers.look_after(windows)
        if now() - timers["spawn"] >= CONFIG["spawner"]["interval_seconds"]:
            timers["spawn"] = now()
            try:
                spawner.spawn()
            except Exception as error:
                traceback.print_exc()
                alert(f"Spawner error: {type(error).__name__}: {error}")
        for agent_id, ended_at in list(L["exiting"].items()):
            if now() - ended_at > CONFIG["checks"]["exit_grace_seconds"]:
                del L["exiting"][agent_id]
        L["checks"] = checks.evaluate(CONFIG, L, now(), processes, lanes.blocked())
        for message in checks.notifications(CONFIG, L["check_incidents"], L["checks"], now()):
            alert(message)
        for thought in checks.stalled_thoughts(CONFIG, L, now()):
            lanes.cancel(thought["id"])
    save()
    if queue_changed:
        queues.publish()


def shutdown() -> None:
    """Stop the daemon, not the agents: their runs are units of their own, which the next
    daemon adopts. Thoughts in flight are cut; OpenCode retries them, and they resume from their
    context's checkpoint or from the lane's state saved here."""
    with LOCK:
        log("daemon stopped")
    STOPPING.set()  # lanes finish the step in flight and take no more
    with LOCK:
        LOCK.notify_all()
    stopping = system_stopping()
    steps = [("save lane contexts", lanes.save_all)]
    if stopping:
        steps.append(("persist snapshots", snapshots.persist))
    steps.append(("save final ledger", save))
    for name, step in steps:
        try:
            step()
        except Exception as error:
            traceback.print_exc()
            with LOCK:
                log("shutdown step failed", step=name, error=f"{type(error).__name__}: {error}")


def system_stopping() -> bool:
    """Whether the whole machine is shutting down (not just this daemon being restarted)."""
    state = subprocess.run(["systemctl", "is-system-running"], capture_output=True, text=True).stdout.strip()
    return state == "stopping"


def main() -> None:
    faulthandler.register(signal.SIGUSR1, all_threads=True)  # `kill -USR1` shows every thread's stack
    previous = read_json(LEDGER, {}) or {}
    L.update(fresh(previous))
    keys.load()
    with LOCK:
        runs.adopt(previous)
        snapshots.forget_transfers()
        snapshots.forget_orphans()
        log("daemon started")
    save()
    queues.publish()
    gateway.serve()
    lanes.start()

    def on_signal(signum, frame):
        STOPPING.set()
        with LOCK:
            LOCK.notify_all()

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
    shutdown()


if __name__ == "__main__":
    main()
