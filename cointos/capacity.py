"""Unspent execution capacity; disposable caches cannot spend an admitted run's room.

Physical headroom remains the guard's signal. Admission additionally holds each active
run's full process cap and its not-yet-initialized native state. Holding the full cap
is conservative: it also leaves room for bookkeeping and allocator transients.
Caller holds the state lock.
"""
from cointos import memory
from cointos.state import BACKEND, CONFIG, L


def process_gb() -> float:
    # systemd MemoryMax's G suffix is binary, whereas our headroom is decimal GB.
    return max(CONFIG['memory']['agent_memory_gb'],
               CONFIG['memory']['agent_limit_gb'] * 2**30 / memory.GB)


def resident_gb(model: str) -> float:
    if not BACKEND.resident_states(CONFIG, model):
        return 0.0
    return L['models'][model].get('resident_state_bytes', float('inf')) / memory.GB


def initialized(model: str, owner: str) -> bool:
    from cointos import lanes
    return bool(lanes.RESIDENT.get((model, owner)))


def pending_gb(resident_owner: str | None = None) -> float:
    from cointos import snapshots
    model = CONFIG['work_model']
    owners = {a['task'] for a in L['agents'].values() if a.get('task')}
    native = sum(resident_gb(model) for owner in owners
                 if owner != resident_owner and not initialized(model, owner))
    copying = sum(snapshots.RESERVED.values()) + sum(
        s['bytes'] / memory.GB for s in L['snapshots'].values()
        if s.get('unspilling') and s['tier'] == 'moving')
    return len(L['agents']) * process_gb() + native + copying


def agent_gb(owner: str) -> float:
    model = CONFIG['work_model']
    return process_gb() + (0.0 if initialized(model, owner) else resident_gb(model))


def headroom_gb(resident_owner: str | None = None) -> float:
    return L['memory'].get('headroom_gb', 0.0) - pending_gb(resident_owner)
