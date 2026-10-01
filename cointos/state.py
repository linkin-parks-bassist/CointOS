"""The daemon's shared state: its config, the ledger and the lock that guards it.

The ledger (`state/cointos.json`) is plain data, written only by the daemon. Everything
that changes it holds LOCK; waiting for a change is waiting on LOCK (a Condition).
"""
from __future__ import annotations

import importlib
import json
import threading
import time

from cointos import config as configuration, journal

CONFIG = configuration.load()
BACKEND = importlib.import_module(CONFIG["backend"])
LOCK = threading.Condition(threading.RLock())
L: dict = {}
STOPPING = threading.Event()
ACTIVE = {"chats": 0, "landings": 0}  # admitted chat replies and landing validations, drained before replacement


def now() -> float:
    return time.time()


def log(event: str, **fields) -> None:
    """Add to the bounded recent history. Caller holds LOCK."""
    entry = {"at": now(), "event": event, **fields}
    L["history"].append(entry)
    del L["history"][:-CONFIG["history_length"]]
    try:
        journal.write(entry, CONFIG["journal"]["bytes"])
        L.pop("journal_error", None)
    except OSError as error:
        L["journal_error"] = str(error)


def alert(text: str) -> None:
    """Tell David (through Coin, the dashboard and the history). Caller holds LOCK."""
    L["next_alert"] += 1
    L["alerts"].append({"id": L["next_alert"], "at": now(), "text": text})
    del L["alerts"][:-CONFIG["alerts_kept"]]
    log("alert", text=text)


def fresh(previous: dict) -> dict:
    """A ledger for a starting daemon, keeping what outlives it: tasks, snapshots, history."""
    for task in previous.get("tasks", {}).values():
        task.pop("validating", None)  # no landing validation survives the daemon that ran it
    lanes = [{"model": name, "index": index, "up": False, "holder": None, "resident": None, "free_since": now(),
              "held_for": None, "held_class": None, "held_until": 0, "turn_agent": None, "turn_since": 0}
             for name, shape in CONFIG["models"].items() for index in range(shape["lanes"])]
    tasks = previous.get("tasks", {})
    live_contexts = {task.get("system_context") for task in tasks.values()
                     if task.get("status") in ("waiting", "running", "review")}
    system_contexts = {digest: text for digest, text in previous.get("system_contexts", {}).items()
                       if digest in live_contexts}
    return {
        "started_at": now(), "updated_at": now(), "restarting": False, "quiescing": False,
        "paused": previous.get("paused", True),
        "models": {name: {"up": False, "launching": False, "problems": ["not checked yet"]} for name in CONFIG["models"]},
        "lanes": lanes, "thoughts": {}, "agents": {}, "exiting": {}, "viewers": {}, "viewers_opening": {}, "dependency_problems": {},
        "viewers_showing": previous.get("viewers_showing", False),
        "projects": CONFIG["projects"], "queue": previous.get("queue", {}),
        "snapshots": previous.get("snapshots", {}), "tasks": tasks, "system_contexts": system_contexts,
        "memory": {}, "model_memory": {name: {"memory_gb": shape["memory_gb"], "weights_gb": shape["weights_gb"]}
                                        for name, shape in CONFIG["models"].items()}, "guard": {"rung": 0, "rung_at": 0, "calm_since": None, "distress_since": None,
                                                        "killed": False, "blocked": False},
        "history": previous.get("history", []), "alerts": previous.get("alerts", []),
        "next_alert": previous.get("next_alert", 0), "checks": [],
        "check_incidents": previous.get("check_incidents", {}),
        "user_last_thought": 0, "cadence": previous.get("cadence", {}), "trees": {},
    }


def save() -> None:
    with LOCK:
        L["updated_at"] = now()
        snapshot = json.loads(json.dumps(L))
        configuration.write_json(configuration.LEDGER, snapshot)
