"""Owned cache-file retirement, independent of lane work and the state lock."""
from contextlib import contextmanager
import math
import threading

from cointos import memory
from cointos.state import BACKEND, CONFIG, LOCK, L, STOPPING, log

ACTIVE: dict[str, threading.Event] = {}
PINS: dict[str, int] = {}


def key(entry: dict) -> str:
    if entry['backend'] not in ('llama', 'gufo') or entry['tier'] not in ('memory', 'disk'):
        raise ValueError('invalid cache cleanup store')
    name, size = entry['name'], entry['bytes']
    if (not isinstance(name, str) or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for c in name)
            or type(size) not in (int, float) or not math.isfinite(size) or size < 0):
        raise ValueError('invalid cache cleanup record')
    return f"{entry['backend']}:{entry['tier']}:{name}"


def jobs() -> dict:
    return L.setdefault('snapshot_garbage', {})


def occupied(tier: str) -> float:
    return sum(e['bytes'] for e in jobs().values() if e['tier'] == tier) / memory.GB


def ready(tier: str) -> bool:
    return tier not in L.get('snapshot_scan_errors', {})


def pending(name: str, tier: str | None = None) -> bool:
    return any(e['name'] == name and (tier is None or e['tier'] == tier) for e in jobs().values())


def queue(name: str, snapshot: dict, tier: str | None = None) -> None:
    """Reserve retired file identities and bytes. Caller holds LOCK."""
    kind = BACKEND.cache_kind(CONFIG, snapshot.get('model'))
    tiers = (tier,) if tier else ('memory', 'disk') if snapshot.get('tier') == 'moving' else (snapshot.get('tier'),)
    if tiers == (None,):
        tiers = ('memory', 'disk')
    for store in tiers:
        for backend in (kind,) if kind else ('llama', 'gufo'):
            enqueue({'backend': backend, 'tier': store, 'name': name, 'bytes': snapshot.get('bytes', 0)})


def enqueue(entry: dict) -> None:
    identifier = key(entry)
    old = jobs().get(identifier)
    if old is None:
        jobs()[identifier] = dict(entry)
    else:
        old['bytes'] = max(old['bytes'], entry['bytes'])


def claimed(entry: dict) -> bool:
    from cointos import snapshots
    name, tier = entry['name'], entry['tier']
    if name in snapshots.TRANSFERS:
        return True
    if tier == 'memory' and name in snapshots.RESERVED:
        return True
    snapshot = L['snapshots'].get(name)
    if snapshot is None:
        return False
    kind = BACKEND.cache_kind(CONFIG, snapshot.get('model'))
    return ((kind is None or kind == entry['backend'])
            and (snapshot['tier'] == 'moving' or snapshot['tier'] == tier))


def pinned(name: str, tier: str) -> bool:
    return any(count and identifier.endswith(f':{tier}:{name}') for identifier, count in PINS.items())


@contextmanager
def pin(name: str):
    """Keep a selected restore's input files alive through the native call."""
    identifiers = []
    with LOCK:
        snapshot = L['snapshots'].get(name)
        if snapshot and snapshot['tier'] != 'moving' and not snapshot.get('discard'):
            kind = BACKEND.cache_kind(CONFIG, snapshot.get('model'))
            tiers = ('memory', 'disk') if snapshot['tier'] == 'disk' else ('memory',)
            proposed = [f'{kind}:{tier}:{name}' for tier in tiers]
            # A disk restore cannot overwrite a RAM file already being retired.
            conflict = (snapshot['tier'] == 'disk' and pending(name, 'memory'))
            if kind and not conflict and not any(k in ACTIVE for k in proposed):
                for identifier in proposed:
                    jobs().pop(identifier, None)  # an active cache supersedes stale cleanup metadata
                    PINS[identifier] = PINS.get(identifier, 0) + 1
                identifiers = proposed
                refresh_error()
    try:
        yield bool(identifiers)
    finally:
        with LOCK:
            for identifier in identifiers:
                PINS[identifier] -= 1
                if not PINS[identifier]:
                    del PINS[identifier]
            LOCK.notify_all()


def refresh_error() -> None:
    problem = next(iter(L.get('snapshot_scan_errors', {}).values()), None) or next((e['error'] for e in jobs().values() if e.get('error')), None)
    if problem:
        if L.get('snapshot_cleanup_error') != problem:
            log('snapshot file cleanup failed', error=problem)
        L['snapshot_cleanup_error'] = problem
    else:
        L.pop('snapshot_cleanup_error', None)


def discover(tier: str | None = None) -> None:
    """Inspect stores outside LOCK, then fence unclaimed file identities under it."""
    if tier is None:
        for store in ('memory', 'disk'):
            discover(store)
        return
    try:
        entries = BACKEND.snapshot_files(CONFIG, tier)
    except OSError as error:
        with LOCK:
            L.setdefault('snapshot_scan_errors', {})[tier] = str(error)
            refresh_error()
        return
    with LOCK:
        for entry in entries:
            if not claimed(entry):
                enqueue(entry)
        L.setdefault('snapshot_scan_errors', {}).pop(tier, None)
        if not L['snapshot_scan_errors']:
            L.pop('snapshot_scan_errors')
        refresh_error()
        LOCK.notify_all()


def clean(identifier: str, wait: bool = False) -> bool:
    """Unlink one fenced file outside LOCK; charge it through actual completion."""
    with LOCK:
        entry = jobs().get(identifier)
        if entry is None:
            return False
        try:
            if key(entry) != identifier:
                raise ValueError('cache cleanup identity mismatch')
        except (KeyError, ValueError) as failed:
            entry['error'] = str(failed)
            refresh_error()
            return False
        from cointos import snapshots
        if (entry['name'] in snapshots.TRANSFERS or PINS.get(identifier)
                or (entry['tier'] == 'memory' and entry['name'] in snapshots.RESERVED)):
            return False
        if claimed(entry):
            jobs().pop(identifier)
            refresh_error()
            return False  # protecting a live file is not physical memory reclamation
        running = ACTIVE.get(identifier)
        if running is None:
            running = ACTIVE[identifier] = threading.Event()
            mine = True
        else:
            mine = False
    if not mine:
        if wait:
            running.wait()
        return False
    error, freed, headroom, completed = None, 0, None, False
    try:
        freed = BACKEND.delete_snapshot_file(CONFIG, entry)
        if entry['tier'] == 'memory' and freed:
            headroom = memory.headroom_gb(CONFIG, memory.measure(), BACKEND.budget(CONFIG))
        completed = True
    except (OSError, ValueError, KeyError) as failed:
        error = str(failed) or type(failed).__name__
    finally:
        with LOCK:
            if jobs().get(identifier) is entry:
                if error:
                    entry['error'] = error
                elif completed:
                    jobs().pop(identifier)
                    if headroom is not None:
                        from cointos import snapshots
                        pending_ram = sum(snapshots.RESERVED.values()) + sum(
                            s['bytes'] / memory.GB for s in L['snapshots'].values()
                            if s.get('unspilling') and s['tier'] == 'moving')
                        # A measurement may already include the release. Never add
                        # metadata bytes beyond physical headroom or unpaid saves.
                        L['memory']['headroom_gb'] = min(
                            L['memory'].get('headroom_gb', 0) + freed / memory.GB,
                            headroom - pending_ram)
                refresh_error()
            ACTIVE.pop(identifier, None)
            running.set()
            LOCK.notify_all()
    return error is None


def drain(tier: str, *, identifiers=None, wait=False) -> None:
    """Attempt a finite batch; only callers needing RAM reclamation wait for peers."""
    with LOCK:
        batch = [k for k, e in jobs().items() if e['tier'] == tier and (identifiers is None or k in identifiers)]
    for identifier in batch:
        clean(identifier, wait=wait)


def run(tier: str) -> None:
    while not STOPPING.is_set():
        discover(tier)
        drain(tier)
        STOPPING.wait(CONFIG['tick_seconds'])
