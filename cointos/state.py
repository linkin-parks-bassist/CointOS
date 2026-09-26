"""The daemon's shared state: its config, the ledger and the lock that guards it.

The ledger (`state/cointos.json`) is plain data, written only by the daemon. Everything
that changes it holds LOCK; waiting for a change is waiting on LOCK (a Condition).
"""
from __future__ import annotations

import importlib
import json
import threading
import time

from cointos import config as configuration

CONFIG = configuration.load()
BACKEND = importlib.import_module(CONFIG["backend"])
LOCK = threading.Condition(threading.RLock())
L: dict = {}
STOPPING = threading.Event()


def now() -> float:
    return time.time()


def log(event: str, **fields) -> None:
    """Add to the bounded recent history. Caller holds LOCK."""
    L["history"].append({"at": now(), "event": event, **fields})
    del L["history"][:-CONFIG["history_length"]]


def alert(text: str) -> None:
    """Tell David (through Coin, the dashboard and the history). Caller holds LOCK."""
    L["next_alert"] += 1
    L["alerts"].append({"id": L["next_alert"], "at": now(), "text": text})
    del L["alerts"][:-CONFIG["alerts_kept"]]
    log("alert", text=text)


def fresh(previous: dict) -> dict:
    """A ledger for a starting daemon, keeping what outlives it: tasks, snapshots, history."""
    lanes = [{"model": name, "index": index, "up": False, "holder": None, "resident": None, "free_since": now(),
              "held_for": None, "held_class": None, "held_until": 0, "turn_agent": None, "turn_since": 0}
             for name, shape in CONFIG["models"].items() for index in range(shape["lanes"])]
    return {
        "started_at": now(), "updated_at": now(), "paused": previous.get("paused", False),
        "models": {name: {"up": False, "launching": False, "problems": ["not checked yet"]} for name in CONFIG["models"]},
        "lanes": lanes, "thoughts": {}, "agents": {}, "exiting": {}, "viewers": {}, "viewers_opening": {}, "dependency_problems": {},
        "viewers_showing": previous.get("viewers_showing", False),
        "snapshots": previous.get("snapshots", {}), "tasks": previous.get("tasks", {}),
        "memory": {}, "model_memory": {name: {"memory_gb": shape["memory_gb"], "weights_gb": shape["weights_gb"]}
                                        for name, shape in CONFIG["models"].items()}, "guard": {"rung": 0, "rung_at": 0, "calm_since": None, "distress_since": None,
                                                        "killed": False, "blocked": False},
        "history": previous.get("history", []), "alerts": previous.get("alerts", []),
        "next_alert": previous.get("next_alert", 0), "checks": [], "failing": [],
        "user_last_thought": 0, "last_survey": previous.get("last_survey", {}),
        "last_maintenance": previous.get("last_maintenance", 0),
    }


def save() -> None:
    with LOCK:
        L["updated_at"] = now()
        snapshot = json.loads(json.dumps(L))
        configuration.write_json(configuration.LEDGER, snapshot)
