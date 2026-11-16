"""Live scheduler settings. The active config file is the only persistent value."""
from __future__ import annotations

import json
import math

from cointos import config as configuration, lanes, scheduler
from cointos.state import CONFIG, L, log, now


def slice_seconds(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("GPU time slice must be a finite number greater than zero")
    return value


def chunk_tokens(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Generation step must be a positive integer number of tokens")
    return value


def effective() -> dict:
    return {key: CONFIG["scheduler"][key] for key in ("slice_seconds", "chunk_tokens")}


def apply(value, chunk=None) -> None:
    """Caller holds the daemon lock. Existing turns keep their clocks and GPU steps."""
    value = slice_seconds(value)
    chunk = chunk_tokens(CONFIG["scheduler"]["chunk_tokens"] if chunk is None else chunk)
    if chunk != CONFIG["scheduler"]["chunk_tokens"]:
        log("Generation step changed", tokens=chunk)
    CONFIG["scheduler"]["chunk_tokens"] = chunk
    changed = CONFIG["scheduler"]["slice_seconds"] != value
    CONFIG["scheduler"]["slice_seconds"] = value
    L["scheduler"] = effective()
    L["config_error"] = None
    if changed:
        for lane in L["lanes"]:
            if lane.get("held_for") is not None:
                lane["held_until"] = min(lane["held_until"], lane["turn_since"] + value)
        log("GPU time slice changed", seconds=value)
        lanes.schedule()  # respects BUSY: a GPU step is never cut in half


def refresh() -> None:
    """Poll once per daemon tick; ignore all other settings and retain the last valid value."""
    try:
        document = json.loads(configuration.CONFIG.read_text(encoding="utf-8"))
        apply(document["scheduler"]["slice_seconds"], chunk_tokens(document["scheduler"]["chunk_tokens"]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        message = f"Config not applied: {error}"
        if L.get("config_error") != message:
            log("config rejected", detail=message)
        L["config_error"] = message
        L["scheduler"] = effective()


def set_scheduler(changes: dict) -> dict:
    """Persist requested fields only; validate the complete live pair before applying."""
    if not changes or set(changes) - {"slice_seconds", "chunk_tokens"}:
        raise ValueError("Expected slice_seconds and/or chunk_tokens")
    path = configuration.CONFIG
    document = json.loads(path.read_text(encoding="utf-8"))
    document["scheduler"].update(changes)
    value = slice_seconds(document["scheduler"]["slice_seconds"])
    chunk = chunk_tokens(document["scheduler"]["chunk_tokens"])
    configuration.write_json(path, document, mode=path.stat().st_mode & 0o777)
    apply(value, chunk)
    return {"ok": True, **effective()}


def set_priority(task_id: str, weight) -> dict:
    """A live user override; preserve ownership, context and charged budgets."""
    from cointos import runs
    task = L['tasks'].get(task_id)
    if task is None or task['status'] not in ('waiting', 'running'):
        raise ValueError('GPU priority requires a waiting or running task')
    if weight is not None and (type(weight) not in (int, float) or not math.isfinite(weight) or weight <= 0):
        raise ValueError('GPU priority weight must be finite and greater than zero')
    effective = runs.scheduling_default(task) if weight is None else weight
    if weight is None:
        task.pop('scheduling_weight', None)
    else:
        task['scheduling_weight'] = weight
    thoughts = list(L['thoughts'].values())
    for peer in thoughts:
        if peer['owner'] == task_id:
            peer['weight'] = effective
    task['updated_at'] = now()
    lanes.schedule()  # BUSY retains the in-flight step; the next decision uses the new weight
    log('GPU priority changed', task=task_id, weight=effective, override=weight)
    return {'ok': True, 'task': task_id, 'weight': effective, 'override': weight}
