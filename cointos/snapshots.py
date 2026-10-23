"""Snapshots: saved lane states (contexts), in memory (/dev/shm) or on disk, and the room they take.

A snapshot is a cache of a conversation's context, never its record: it is used only when its
tokens begin the context as it now is. Snapshots are the elastic memory. The RAM tier has its
own budget (`memory.snapshots_gb`). Replacements reclaim obsolete caches first when both copies
cannot fit. Other capacity/headroom evictions move caches to the bounded disk tier or forget
them when it is full, according to activity and recency
(`what/is/the/architecture/of/cointos.md`, *Memory*). Tiers: memory, moving (a spill or unspill
in flight, still occupying RAM), disk. Caller holds LOCK unless stated.
"""
from __future__ import annotations

import array
import hashlib
import math
import secrets
import threading

from cointos import memory, schema, snapshot_cleanup as cleanup
from cointos.state import BACKEND, CONFIG, LOCK, L, log, now

RESERVED: dict[str, float] = {}  # in-flight saves, GB
TRANSFERS: set[str] = set()  # file ownership survives a logical row's retirement
UNTASKED = frozenset({"user", "coin", "shared"})  # owners that are conversations but not tasks


def coin_conversation(owner: str | None) -> bool:
    return bool(owner and owner.startswith("coin/"))


def digest(tokens: list[int]) -> str:
    return hashlib.sha256(array.array("i", tokens).tobytes()).hexdigest()


def size_gb(snapshot: dict) -> float:
    return snapshot["bytes"] / memory.GB


def drop(name: str, *, transfer_done: bool = False) -> None:
    """Forget a snapshot, deferring an in-flight transfer's file cleanup and accounting."""
    snapshot = L["snapshots"].get(name)
    if snapshot and snapshot.get("tier") == "moving" and not transfer_done:
        snapshot["discard"] = True
        return
    snapshot = L["snapshots"].pop(name, None)
    if snapshot is not None:
        cleanup.queue(name, snapshot)


def live(owner: str | None) -> bool:
    """Whether a conversation can still go on, so that its context is worth saving.

    Task outcome, run lifetime and conversation lifetime are deliberately distinct.  A waiting
    or reviewed task can resume later; a terminal task can still issue requests until its current
    agent process exits.  This is the one reachability rule used by snapshot creation, resident
    state retention and final retirement.
    """
    if owner in UNTASKED or coin_conversation(owner):
        return True
    task = L["tasks"].get(owner or "")
    return task is not None and (task["status"] in schema.ACTIVE
                                 or any(agent["task"] == owner for agent in L["agents"].values()))


# ---------------------------------------------------------------- room

def room(need_gb: float, keep: str | None = None, replacing=()) -> bool:
    """Whether `need_gb` more fits in the RAM tier's budget, counting transfers and saves in
    flight. Reclaim replaceable states first, then evict owners not running and least recently
    run; RAM is not credited until a spill completes, so an allocation is declined meanwhile."""
    limit = CONFIG["memory"].get("snapshots_gb")
    if limit is None:
        return True
    held = {n: s for n, s in L["snapshots"].items() if s["tier"] in ("memory", "moving")}
    used = sum(map(size_gb, held.values())) + sum(RESERVED.values()) + cleanup.occupied('memory')
    # Reclaim a replacement's obsolete cache before displacing other work, only
    # when both copies cannot fit. In-flight transfers remain fully charged.
    obsolete = {name: held[name] for name in replacing
                if name in held and held[name]['tier'] == 'memory' and name != keep
                and not cleanup.pinned(name, 'memory')}
    reclaimable = sum(map(size_gb, obsolete.values()))
    # Do not discard the fallback unless its removal can admit the replacement
    # now in both budgets. Other pending spills are not available memory yet.
    headroom = L['memory'].get('headroom_gb', 0)
    if used - reclaimable + need_gb <= limit and headroom + reclaimable >= need_gb:
        reclaimed = 0
        for name, snapshot in obsolete.items():
            if used - reclaimed + need_gb <= limit and headroom + reclaimed >= need_gb:
                break
            freed = size_gb(snapshot)
            drop(name)
            held.pop(name)
            reclaimed += freed
            log('snapshot evicted', owner=snapshot['owner'], tier='memory',
                tokens=snapshot['tokens'], bytes=snapshot['bytes'], reason='superseded')
    moving = sum(size_gb(s) for s in held.values() if s["tier"] == "moving") + cleanup.occupied('memory')
    candidates = sorted(((n, s) for n, s in held.items() if s["tier"] == "memory" and n != keep
                         and not cleanup.pinned(n, 'memory')),
                        key=lambda pair: (L["tasks"].get(pair[1]["owner"], {}).get("status") == "running",
                                          pair[1]["last_run"]))
    for name, snapshot in candidates:
        if used - moving + need_gb <= limit:
            break
        freed = evict(name)
        used = sum(size_gb(s) for s in L['snapshots'].values() if s['tier'] in ('memory', 'moving')) + sum(RESERVED.values()) + cleanup.occupied('memory')
        moving = sum(size_gb(s) for s in L['snapshots'].values() if s['tier'] == 'moving') + cleanup.occupied('memory')
    return used + need_gb <= limit


def make_room(need_gb: float) -> bool:
    """Whether `need_gb` fits in the headroom, evicting the least recently run snapshots in
    memory as needed. What fits is counted as taken until memory is next measured."""
    headroom = L["memory"].get("headroom_gb", 0.0)
    leaving = memory.to_forget(in_memory(), need_gb, headroom + cleanup.occupied('memory'))
    if leaving is None:
        return False
    # A spill's RAM is released only when it completes; the next measurement sees it.
    available = headroom + sum(evict(name) for name in leaving)
    if available < need_gb:
        return False
    L["memory"]["headroom_gb"] = round(available - need_gb, 1)
    return True


def evict(name: str) -> float:
    """Take a snapshot out of memory: spill it to disk if the disk tier has room (RAM freed
    later), else retire it for cleanup. Neither path credits memory before release."""
    snapshot = L["snapshots"][name]
    if cleanup.pending(name, 'disk') or not cleanup.ready('disk'):
        return 0.0  # a previous disk copy still owns that destination
    if disk_room(size_gb(snapshot), keep=name):
        snapshot["tier"] = "moving"
        TRANSFERS.add(name)
        threading.Thread(target=spill, args=(name,), daemon=True).start()
        return 0.0
    used = sum(size_gb(s) for s in L['snapshots'].values() if s['tier'] in ('disk', 'moving')) + cleanup.occupied('disk')
    if cleanup.occupied('disk') and used - cleanup.occupied('disk') + size_gb(snapshot) <= CONFIG['memory']['disk_snapshots_gb']:
        return 0.0  # deletion in progress can admit a spill later; retain the RAM fallback
    log("snapshot evicted", owner=snapshot.get("owner"), tier="memory", tokens=snapshot.get("tokens"))
    drop(name)
    return 0.0


def disk_room(need_gb: float, keep: str) -> bool:
    """Whether `need_gb` more fits in the disk tier, forgetting its least recently run
    snapshots as needed."""
    if not cleanup.ready('disk') or cleanup.pending(keep, 'disk'):
        return False
    on_disk = {n: s for n, s in L["snapshots"].items() if s["tier"] in ("disk", "moving") and n != keep}
    used = sum(map(size_gb, on_disk.values())) + cleanup.occupied('disk')
    evictable = {n: s for n, s in on_disk.items() if s["tier"] == "disk" and not cleanup.pinned(n, 'disk')}
    leaving = memory.to_forget(evictable, need_gb, CONFIG["memory"]["disk_snapshots_gb"] - used + cleanup.occupied('disk'))
    if leaving is None:
        return False
    for name in leaving:
        log("snapshot evicted", owner=L["snapshots"][name].get("owner"), tier="disk", tokens=L["snapshots"][name].get("tokens"))
        drop(name)
    return used + need_gb <= CONFIG['memory']['disk_snapshots_gb']


def in_memory() -> dict[str, dict]:
    return {n: s for n, s in L["snapshots"].items() if s["tier"] == "memory" and not cleanup.pinned(n, 'memory')}


def spill(name: str) -> None:
    """Move a snapshot to disk. Runs outside LOCK."""
    with LOCK:
        original = L['snapshots'].get(name)
        TRANSFERS.add(name)
    try:
        BACKEND.spill(CONFIG, name)
    except OSError as error:
        with LOCK:
            if L['snapshots'].get(name) is original:
                drop(name, transfer_done=True)
            elif original is not None:
                cleanup.queue(name, original)
            TRANSFERS.discard(name)
            log("spill failed", snapshot=name, error=str(error))
        return
    with LOCK:
        snapshot = L["snapshots"].get(name)
        if snapshot is original and snapshot and not snapshot.get("discard") and live(snapshot["owner"]):
            snapshot["tier"] = "disk"
            log("snapshot spilled", snapshot=name, owner=snapshot["owner"], bytes=snapshot["bytes"])
        elif snapshot is original:
            drop(name, transfer_done=True)
        elif original is not None:
            cleanup.queue(name, original, tier='disk')
        TRANSFERS.discard(name)


def bring_back(name: str) -> bool:
    """Make a snapshot restorable: one on disk returns to memory if it fits. Runs outside LOCK;
    returns whether the snapshot is in memory now."""
    with LOCK:
        snapshot = L["snapshots"].get(name)
        if snapshot is None or snapshot["tier"] == "moving" or snapshot.get('discard'):
            return False
        if snapshot["tier"] == "memory":
            return True
        if cleanup.pending(name, 'memory') or not cleanup.ready('memory'):
            return False
        if not (room(size_gb(snapshot), name) and make_room(size_gb(snapshot))):
            return False
        snapshot["tier"] = "moving"
        snapshot['unspilling'] = True
        TRANSFERS.add(name)
    try:
        BACKEND.copy_back(CONFIG, name)
    except OSError as error:
        with LOCK:
            if L['snapshots'].get(name) is snapshot:
                drop(name, transfer_done=True)
            else:
                cleanup.queue(name, snapshot)
            TRANSFERS.discard(name)
            log("unspill failed", snapshot=name, error=str(error))
        return False
    with LOCK:
        current = L["snapshots"].get(name)
        if current is not snapshot or snapshot.get("discard") or not live(snapshot["owner"]):
            if current is snapshot:
                drop(name, transfer_done=True)
            else:
                cleanup.queue(name, snapshot)
            TRANSFERS.discard(name)
            return False
        snapshot["tier"] = "memory"
        snapshot.pop('unspilling', None)
        cleanup.queue(name, snapshot, tier='disk')
        TRANSFERS.discard(name)
    return True


def persist() -> None:
    """Before the machine shuts down, move the snapshots held in memory (/dev/shm, which a reboot
    wipes) to the disk tier, so agents resume warm after it. Nothing else loses them: a daemon
    restart, a model killed or Lemonade killed all leave /dev/shm as it is. Runs outside LOCK."""
    with LOCK:
        names = list(L['snapshots'])
    leaving = []
    for name in names:
        with LOCK:
            snapshot = L['snapshots'].get(name)
            if snapshot is None or snapshot['tier'] != 'memory':
                continue
            admitted = disk_room(size_gb(snapshot), keep=name)
        if not admitted:
            # Shutdown may wait for disk capacity. Ordinary lane work never does.
            cleanup.drain('disk', wait=True)
        with LOCK:
            snapshot = L['snapshots'].get(name)
            if snapshot and snapshot['tier'] == 'memory' and disk_room(size_gb(snapshot), keep=name):
                snapshot['tier'] = 'moving'
                TRANSFERS.add(name)
                leaving.append(name)
    for name in leaving:
        spill(name)
    with LOCK:
        log("snapshots moved to disk for shutdown", count=len(leaving))


# ---------------------------------------------------------------- saving and forgetting

def superseded(owner: str, model: str, held: list[int], kind: str) -> list[str]:
    """Caches this exact token extension replaces; caller holds LOCK."""
    return [n for n, s in L['snapshots'].items()
            if owner != 'shared' and s['owner'] == owner and s['model'] == model and s['tokens'] <= len(held)
            and (s['kind'] == kind or (kind == 'checkpoint' and s['kind'] == 'suspended'))
            and s['digest'] == digest(held[:s['tokens']])]


def keep(position: int, held: list[int], owner: str, kind: str) -> bool:
    """Save the lane's state (holding exactly `held`) as a snapshot of `owner`'s conversation, if
    it fits. A *checkpoint* is a committed prompt prefix saved before generation; it may end
    before the prompt's tail and supersedes older checkpoints/suspensions. A *prefix*
    saves a semantic boundary that outlives changing tails; only a newer compatible
    prefix supersedes it. A *suspended* state (a thought
    stopped part way) supersedes only older suspended ones, so the checkpoint outlives a thought
    that is abandoned. Shared starts serve different histories, so longer shared states do not
    supersede shorter tiers. Under budget pressure a superseded cache can be discarded before
    saving; a failed replacement then rereads instead of retaining that old hint. Runs outside
    LOCK; returns whether it was saved."""
    need, reclaimed = 0.0, False
    wanted = digest(held)
    while True:
        with LOCK:
            model, index = L["lanes"][position]["model"], L["lanes"][position]["index"]
            for saved in L["snapshots"].values():
                if saved["model"] == model and saved["digest"] == wanted:
                    if owner == "shared":
                        saved["owner"] = "shared"
                    if kind == 'prefix' and saved['owner'] != 'shared':
                        saved['kind'] = 'prefix'
                    elif kind == "checkpoint" and saved['kind'] != 'prefix':
                        saved["kind"] = "checkpoint"
                    return True
            if not cleanup.ready('memory'):
                return False
            # Retiring the last sample must not turn this allocation's estimate into zero.
            need = max(need, memory.snapshot_gb(L["snapshots"], model, len(held)))
            limit = CONFIG['memory'].get('snapshots_gb')
            used = sum(size_gb(s) for s in L['snapshots'].values() if s['tier'] in ('memory', 'moving')) + sum(RESERVED.values()) + cleanup.occupied('memory')
            if limit is not None and need > limit:
                return False
            if reclaimed:
                if ((limit is not None and used + need > limit)
                        or L['memory'].get('headroom_gb', 0) < need):
                    return False
                admitted = make_room(need)  # no further eviction after this transaction's reclaim
            else:
                admitted = room(need, replacing=superseded(owner, model, held, kind)) and make_room(need)
            if admitted:
                name = secrets.token_hex(6)
                while name in L['snapshots'] or name in RESERVED or name in TRANSFERS or cleanup.pending(name):
                    name = secrets.token_hex(6)
                RESERVED[name] = need
                break
            # Select reclaim work in physical bytes, avoiding a floating-point
            # boundary turning an exactly sufficient cache into an apparent miss.
            need_bytes = math.ceil(need * memory.GB)
            used_bytes = sum(math.ceil(s['bytes']) for s in L['snapshots'].values() if s['tier'] in ('memory', 'moving'))
            used_bytes += math.ceil(sum(RESERVED.values()) * memory.GB)
            used_bytes += sum(math.ceil(e['bytes']) for e in cleanup.jobs().values() if e['tier'] == 'memory')
            deficit = max(need_bytes - math.floor(L['memory'].get('headroom_gb', 0) * memory.GB),
                          used_bytes + need_bytes - math.floor(limit * memory.GB) if limit is not None else 0)
            pending, release = set(), 0
            for identifier, entry in cleanup.jobs().items():
                if entry['tier'] != 'memory' or cleanup.PINS.get(identifier):
                    continue
                pending.add(identifier)
                release += math.ceil(entry['bytes'])
                if release >= deficit:
                    break
            if reclaimed or not pending or release < deficit:
                return False
        # Only RAM release needed for this save may delay it. Disk disposal is
        # independent, and neither operation can retain the state lock.
        cleanup.drain('memory', identifiers=pending, wait=True)
        reclaimed = True
    try:
        saved = BACKEND.save(CONFIG, model, index, name)
    except Exception:
        with LOCK:
            cleanup.queue(name, {'model': model, 'bytes': need * memory.GB}, tier='memory')
            RESERVED.pop(name, None)
        raise
    with LOCK:
        RESERVED.pop(name, None)
        if not live(owner):  # its conversation ended while the state was being written
            cleanup.queue(name, {'model': model, 'bytes': saved['bytes']}, tier='memory')
            return False
        for older in superseded(owner, model, held, kind):
            drop(older)
        L["snapshots"][name] = {"owner": owner, "model": model, "tokens": len(held), "digest": wanted, "kind": kind,
                                "bytes": saved["bytes"], "last_run": now(), "tier": "memory"}
        room(0.0)  # reconcile the server's actual size against the estimate
    return True


def shared(model: str, tokens: list[int]) -> bool:
    """Whether a snapshot of exactly this context start exists. Runs outside LOCK."""
    with LOCK:
        wanted = digest(tokens)
        return any(s["model"] == model and s["digest"] == wanted for s in L["snapshots"].values())


def retain_prefix(model: str, tokens: list[int], owner: str) -> bool:
    """Protect an already saved semantic prefix from this owner's tail supersession."""
    with LOCK:
        wanted = digest(tokens)
        for saved in L['snapshots'].values():
            if saved['model'] == model and saved['digest'] == wanted:
                if saved['owner'] == owner:
                    saved['kind'] = 'prefix'
                return True
        return False


def keep_shared(position: int, tokens: list[int]) -> None:
    """Save a lane holding exactly a context start that several contexts share. Runs outside LOCK."""
    if keep(position, tokens, "shared", "checkpoint"):
        with LOCK:
            log("shared prefix saved", model=L["lanes"][position]["model"], tokens=len(tokens))


def forget_diverged(owner: str, model: str, tokens: list[int]) -> None:
    """A task or Coin conversation is one line of history: snapshots that do not begin the context
    it goes on with (left by a run that stopped mid-thought) can never be used again."""
    for name in [n for n, s in L["snapshots"].items()
                 if s["owner"] == owner and s["model"] == model
                 and (s["tokens"] >= len(tokens) or digest(tokens[:s["tokens"]]) != s["digest"])]:
        drop(name)
        log("snapshot forgotten", owner=owner, reason="diverged from its conversation")


def forget_owner(owner: str) -> None:
    """Forget the snapshots of a conversation that is over."""
    for name in [n for n, s in L["snapshots"].items() if s["owner"] == owner]:
        drop(name)


def forget_orphans() -> None:
    """Reconcile saved states against conversation reachability, not task-record presence."""
    for owner in {s["owner"] for s in L["snapshots"].values() if not s.get("discard")}:
        if live(owner):
            continue
        forget_owner(owner)
        log("snapshot forgotten", owner=owner, reason="its conversation is over")


def recover_transfers() -> None:
    """At startup, retain an intact owned copy; no old transfer thread survives."""
    for name in [n for n, s in L["snapshots"].items() if s["tier"] == "moving"]:
        snapshot = L['snapshots'][name]
        tier = None
        if not snapshot.get('discard') and live(snapshot['owner']):
            tier = BACKEND.recover_transfer(CONFIG, snapshot.get('model'), name, snapshot.get('bytes'))
        if tier is not None:
            snapshot['tier'] = tier
            log('snapshot transfer recovered', snapshot=name, owner=snapshot['owner'], tier=tier)
            continue
        drop(name, transfer_done=True)
        log("snapshot forgotten", snapshot=name, reason="its transfer was interrupted")


def forget_untracked() -> None:
    """Reconcile cache files after interrupted saves, protecting saves still in flight.

    Runs outside LOCK. A backend save writes outside LOCK before its ledger entry exists;
    RESERVED owns that file until publication. A dead daemon loses only that reservation.
    """
    cleanup.discover()
