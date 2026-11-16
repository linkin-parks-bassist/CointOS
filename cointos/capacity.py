"""Unspent execution capacity; disposable caches cannot spend an admitted run's room.

Physical headroom remains the guard's signal, and it already counts what agent processes
use now. Admission additionally holds each active run's room to grow, sized from what it
has actually used: its highest measured unreclaimable memory plus a margin, capped at the
systemd process cap, less what it uses now. An unmeasured run holds the full cap. A new
run holds its starting estimate, and every run holds its not-yet-initialized native state.
Caller holds the state lock.
"""
import os
from pathlib import Path

from cointos import memory
from cointos.state import BACKEND, CONFIG, L, now

USAGE: dict[str, dict] = {}  # agent id -> {"current_gb", "peak_gb"} from its systemd unit


def unit_gb(agent_id: str) -> float | None:
    """An agent unit's unreclaimable memory (anonymous + shared), or None when unreadable.
    Page cache is left out: the kernel reclaims it and MemAvailable already counts it."""
    group = Path(f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/app.slice"
                 f"/cointos-agent-{agent_id}.service")
    try:
        stat = dict(line.split() for line in (group / "memory.stat").read_text().splitlines())
        return (int(stat["anon"]) + int(stat["shmem"])) / memory.GB
    except (OSError, ValueError, KeyError):
        return None


def observe() -> None:
    """Refresh each running agent's usage; the peak only rises while the run lasts."""
    for agent_id in list(USAGE):
        if agent_id not in L["agents"]:
            USAGE.pop(agent_id)
    for agent_id in L["agents"]:
        current = unit_gb(agent_id)
        if current is None:
            continue
        seen = USAGE.setdefault(agent_id, {"current_gb": current, "peak_gb": current})
        seen["current_gb"], seen["peak_gb"] = current, max(seen["peak_gb"], current)


def process_gb() -> float:
    """The hard per-agent cap. systemd MemoryMax's G suffix is binary, whereas our headroom is decimal GB."""
    return max(CONFIG['memory']['agent_memory_gb'],
               CONFIG['memory']['agent_limit_gb'] * 2**30 / memory.GB)


def starting_gb() -> float:
    """What a run not yet measured is expected to grow to: its baseline plus the margin."""
    return min(process_gb(), CONFIG['memory']['agent_memory_gb'] + CONFIG['memory'].get('agent_margin_gb', 1.5))


def growth_gb(agent_id: str) -> float:
    """Room an admitted run still holds to grow into, beyond what MemAvailable already counts."""
    seen = USAGE.get(agent_id)
    if seen is None:
        # Just launched: its unit has not been measured yet, so it holds the starting
        # estimate. One that stays unmeasurable holds the full cap.
        started = (L["agents"].get(agent_id) or {}).get("started_at")
        fresh = started is not None and now() - started < CONFIG['memory'].get('agent_measure_grace_seconds', 60)
        return starting_gb() if fresh else process_gb()
    expected = min(process_gb(), max(CONFIG['memory']['agent_memory_gb'], seen['peak_gb'])
                   + CONFIG['memory'].get('agent_margin_gb', 1.5))
    return max(0.0, expected - seen['current_gb'])


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
    return sum(growth_gb(agent_id) for agent_id in L['agents']) + native + copying


def agent_gb(owner: str) -> float:
    model = CONFIG['work_model']
    return starting_gb() + (0.0 if initialized(model, owner) else resident_gb(model))


def conversation_cache_gb(owner: str | None) -> float:
    """Process caps a waiting user's conversation cache need not stay clear of.

    Process caps protect long-lived growth. This cache is disposable, and the guard sheds
    it first if the processes do grow. Other pending claims and the reserve still apply.
    """
    from cointos import snapshots
    return sum(growth_gb(agent_id) for agent_id in L['agents']) if snapshots.coin_conversation(owner) else 0.0


def headroom_gb(resident_owner: str | None = None) -> float:
    return L['memory'].get('headroom_gb', 0.0) - pending_gb(resident_owner)
