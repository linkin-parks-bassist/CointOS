"""The daemon's shared state: its config, the ledger and the lock that guards it.

The ledger (`state/cointos.json`) is plain data, written only by the daemon. Everything
that changes it holds LOCK; waiting for a change is waiting on LOCK (a Condition).
"""
from __future__ import annotations

import importlib
import json
import threading
import time

from cointos import config as configuration, journal, schema

CONFIG = configuration.load()
BACKEND = importlib.import_module(CONFIG["backend"])
LOCK = threading.Condition(threading.RLock())
L: dict = {}
STARTUP: dict = {}  # in-process restoration evidence, never part of the durable ledger
STOPPING = threading.Event()
ACTIVE = {"chats": 0, "landings": 0}  # admitted chat replies and landing validations
SAVE_LOCK = threading.Lock()  # file publication order, never acquired before LOCK
SAVE_SEQUENCE = 0
SAVED_SEQUENCE = 0
SAVED_VALUE = None  # target and last successfully published non-telemetry values
JOURNAL_APPLIED = 0  # completed diagnostic batch, not durable task authority


def now() -> float:
    return time.time()


def log(event: str, **fields) -> None:
    """Add to the bounded recent history. Caller holds LOCK."""
    entry = {"at": now(), "event": event, **fields}
    L["history"].append(entry)
    del L["history"][:-CONFIG["history_length"]]
    journal.write(entry, CONFIG["journal"]["bytes"])


def alert(text: str) -> None:
    """Record dashboard diagnostics; actionable delivery uses messages and the frontier. Caller holds LOCK."""
    L["next_alert"] += 1
    L["alerts"].append({"id": L["next_alert"], "at": now(), "text": text})
    del L["alerts"][:-CONFIG["alerts_kept"]]
    log("alert", text=text)


def enqueue_message(origin: str, target: str, text: str) -> None:
    """Keep unaccepted user questions until transport acknowledgement. Caller holds LOCK."""
    messages = L['messages'] + [{'at': now(), 'from': origin, 'to': target, 'text': text, 'read': False}]
    recent = messages[-CONFIG['messages_kept']:]
    L['messages'] = [m for m in messages[:-CONFIG['messages_kept']]
                     if m['to'] == 'user' and not m['read']] + recent
    log('message', sender=origin, to=target)


def fresh(previous: dict) -> dict:
    """A ledger for a starting daemon, keeping what outlives it: tasks, snapshots, history."""
    configuration.validate_ledger(previous)
    for task in previous.get("tasks", {}).values():
        task.pop("validating", None)  # no landing validation survives the daemon that ran it
    lanes = [{"model": name, "index": index, "up": False, "holder": None, "resident": None, "free_since": now(),
              "held_for": None, "held_class": None, "held_until": 0, "turn_agent": None, "turn_since": 0}
             for name, shape in CONFIG["models"].items() for index in range(shape["lanes"])]
    tasks = previous.get("tasks", {})
    live_contexts = {digest for task in tasks.values() if task.get("status") in schema.ACTIVE
                     for digest in (task.get("system_context"), task.get("tool_context"))}
    system_contexts = {digest: text for digest, text in previous.get("system_contexts", {}).items()
                       if digest in live_contexts}
    return {
        'frontier_version': previous.get('frontier_version', 1),
        'work_frontier': [],
        "started_at": now(), "updated_at": now(), "restarting": False,
        "paused": previous.get("paused", True),
        "models": {name: {"up": False, "launching": False, "problems": ["not checked yet"]} for name in CONFIG["models"]},
        "lanes": lanes, "thoughts": {}, "agents": {}, "exiting": {}, "viewers": {}, "viewers_opening": {},
        "dependency_problems": previous.get("dependency_problems", {}),
        "viewers_showing": previous.get("viewers_showing", False),
        "projects": CONFIG["projects"], "queue": previous.get("queue", {}), "messages": previous.get("messages", []),
        "snapshots": previous.get("snapshots", {}), "tasks": tasks, "system_contexts": system_contexts,
        "snapshot_garbage": previous.get("snapshot_garbage", {}),
        "memory": {}, "model_memory": {name: {"memory_gb": shape["memory_gb"], "weights_gb": shape["weights_gb"],
                                              "weights_reclaimable": shape.get("backend", "llama") != "gufo"}
                                        for name, shape in CONFIG["models"].items()}, "guard": {"rung": 0, "rung_at": 0, "calm_since": None, "distress_since": None,
                                                        "killed": False, "blocked": False},
        "history": previous.get("history", []), "alerts": previous.get("alerts", []),
        "next_alert": previous.get("next_alert", 0), "checks": [],
        "check_incidents": previous.get("check_incidents", {}),
        "user_last_thought": 0, "cadence": previous.get("cadence", {}), "trees": {},
        # What Coin is doing, as it reports it, for its dashboard card; no turn outlives the daemon.
        "coin": {"busy": False, "since": now(), "doing": None, "live": {},
                 "last_turn_at": previous.get("coin", {}).get("last_turn_at")},
    }


def _snapshot(value, active=None):
    """Copy plain JSON data without encoding large immutable strings under LOCK.

    Keep the JSON round-trip's normalization for unusual keys/types. Aliases
    become independent values; cycles are refused before publication.
    """
    kind = type(value)
    if kind not in (dict, list, tuple):
        return value if kind in (str, int, float, bool, type(None)) else json.loads(json.dumps(value))
    if kind is dict and any(type(key) is not str for key in value):
        return json.loads(json.dumps(value))
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ValueError("Circular reference detected")
    active.add(identity)
    try:
        return ({key: _snapshot(item, active) for key, item in value.items()}
                if kind is dict else [_snapshot(item, active) for item in value])
    finally:
        active.remove(identity)


def flush_journal() -> None:
    """Flush diagnostics outside LOCK, then publish only the newest error status."""
    global JOURNAL_APPLIED
    sequence, error = journal.flush()
    with LOCK:
        if sequence > JOURNAL_APPLIED:
            JOURNAL_APPLIED = sequence
            if error is None:
                L.pop("journal_error", None)
            else:
                L["journal_error"] = error


def save() -> None:
    """Publish a consistent ledger without holding our state lock during file I/O.

    A caller already holding LOCK still owns that outer critical section. Such
    callers must end their transaction before saving to gain nonblocking I/O.
    Publication never reacquires LOCK: a nested caller may be waiting here.
    """
    global SAVE_SEQUENCE, SAVED_SEQUENCE, SAVED_VALUE
    flush_journal()
    with LOCK:
        L["updated_at"] = now()
        snapshot = _snapshot(L)
        SAVE_SEQUENCE += 1
        sequence = SAVE_SEQUENCE
    with SAVE_LOCK:
        # A later snapshot contains all mutations visible to this one. If it
        # reached publication first, this save is already durably covered.
        if sequence > SAVED_SEQUENCE:
            # Startup reconstructs memory and updated_at, and adopt() refreshes
            # each run's last_activity. Their heartbeat alone needs no new file.
            value = {key: body for key, body in snapshot.items() if key not in ('updated_at', 'memory')}
            if 'agents' in value:
                value['agents'] = {agent: {field: item for field, item in data.items() if field != 'last_activity'}
                                   for agent, data in value['agents'].items()}
            published = (configuration.LEDGER, value)
            if published != SAVED_VALUE:
                configuration.write_json(configuration.LEDGER, snapshot)
                SAVED_VALUE = published
            SAVED_SEQUENCE = sequence
