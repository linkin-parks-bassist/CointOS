"""Snapshots: saved lane states (contexts), in memory (/dev/shm) or on disk, and the room they take.

A snapshot is a cache of a conversation's context, never its record: it is used only when its
tokens begin the context as it now is. Snapshots are the elastic memory. The RAM tier has its
own budget (`memory.snapshots_gb`); when it or the headroom runs short, snapshots leave memory
least recently run first, moving to the bounded disk tier or, when that is full, forgotten
(`what/is/the/architecture/of/cointos.md`, *Memory*). Tiers: memory, moving (a spill or unspill
in flight, still occupying RAM), disk. Caller holds LOCK unless stated.
"""
from __future__ import annotations

import array
import hashlib
import secrets
import threading

from cointos import memory
from cointos.state import BACKEND, CONFIG, LOCK, L, log, now

RESERVED: dict[str, float] = {}  # in-flight saves, GB
UNTASKED = frozenset({"user", "coin", "shared"})  # owners that are conversations but not tasks


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
    L["snapshots"].pop(name, None)
    BACKEND.forget(CONFIG, name)


def live(owner: str | None) -> bool:
    """Whether a conversation can still go on, so that its context is worth saving.

    Task outcome, run lifetime and conversation lifetime are deliberately distinct.  A waiting
    or reviewed task can resume later; a terminal task can still issue requests until its current
    agent process exits.  This is the one reachability rule used by snapshot creation, resident
    state retention and final retirement.
    """
    if owner in UNTASKED:
        return True
    task = L["tasks"].get(owner or "")
    return task is not None and (task["status"] in ("waiting", "running", "review")
                                 or any(agent["task"] == owner for agent in L["agents"].values()))


# ---------------------------------------------------------------- room

def room(need_gb: float, keep: str | None = None) -> bool:
    """Whether `need_gb` more fits in the RAM tier's budget, counting transfers and saves in
    flight. Makes room by evicting snapshots of owners not running first, then least recently
    run; RAM is not credited until a spill completes, so an allocation is declined meanwhile."""
    limit = CONFIG["memory"].get("snapshots_gb")
    if limit is None:
        return True
    held = {n: s for n, s in L["snapshots"].items() if s["tier"] in ("memory", "moving")}
    used = sum(map(size_gb, held.values())) + sum(RESERVED.values())
    moving = sum(size_gb(s) for s in held.values() if s["tier"] == "moving")
    candidates = sorted(((n, s) for n, s in held.items() if s["tier"] == "memory" and n != keep),
                        key=lambda pair: (L["tasks"].get(pair[1]["owner"], {}).get("status") == "running",
                                          pair[1]["last_run"]))
    for name, snapshot in candidates:
        if used - moving + need_gb <= limit:
            break
        freed = evict(name)
        used -= freed
        moving += size_gb(snapshot) if not freed else 0
    return used + need_gb <= limit


def make_room(need_gb: float) -> bool:
    """Whether `need_gb` fits in the headroom, evicting the least recently run snapshots in
    memory as needed. What fits is counted as taken until memory is next measured."""
    headroom = L["memory"].get("headroom_gb", 0.0)
    leaving = memory.to_forget(in_memory(), need_gb, headroom)
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
    later, returns 0), else forget it (returns the GB freed now)."""
    snapshot = L["snapshots"][name]
    if disk_room(size_gb(snapshot), keep=name):
        snapshot["tier"] = "moving"
        threading.Thread(target=spill, args=(name,), daemon=True).start()
        return 0.0
    drop(name)
    return size_gb(snapshot)


def disk_room(need_gb: float, keep: str) -> bool:
    """Whether `need_gb` more fits in the disk tier, forgetting its least recently run
    snapshots as needed."""
    on_disk = {n: s for n, s in L["snapshots"].items() if s["tier"] in ("disk", "moving") and n != keep}
    used = sum(map(size_gb, on_disk.values()))
    evictable = {n: s for n, s in on_disk.items() if s["tier"] == "disk"}
    leaving = memory.to_forget(evictable, need_gb, CONFIG["memory"]["disk_snapshots_gb"] - used)
    if leaving is None:
        return False
    for name in leaving:
        drop(name)
    return True


def in_memory() -> dict[str, dict]:
    return {n: s for n, s in L["snapshots"].items() if s["tier"] == "memory"}


def spill(name: str) -> None:
    """Move a snapshot to disk. Runs outside LOCK."""
    try:
        BACKEND.spill(CONFIG, name)
    except OSError as error:
        with LOCK:
            drop(name, transfer_done=True)
            log("spill failed", snapshot=name, error=str(error))
        return
    with LOCK:
        snapshot = L["snapshots"].get(name)
        if snapshot and not snapshot.get("discard") and live(snapshot["owner"]):
            snapshot["tier"] = "disk"
            log("snapshot spilled", snapshot=name, owner=snapshot["owner"], bytes=snapshot["bytes"])
        else:
            drop(name, transfer_done=True)


def bring_back(name: str) -> bool:
    """Make a snapshot restorable: one on disk returns to memory if it fits. Runs outside LOCK;
    returns whether the snapshot is in memory now."""
    with LOCK:
        snapshot = L["snapshots"].get(name)
        if snapshot is None or snapshot["tier"] == "moving":
            return False
        if snapshot["tier"] == "memory":
            return True
        if not (room(size_gb(snapshot), name) and make_room(size_gb(snapshot))):
            return False
        snapshot["tier"] = "moving"
    try:
        BACKEND.unspill(CONFIG, name)
    except OSError as error:
        with LOCK:
            drop(name, transfer_done=True)
            log("unspill failed", snapshot=name, error=str(error))
        return False
    with LOCK:
        snapshot = L["snapshots"].get(name)
        if snapshot is None or snapshot.get("discard") or not live(snapshot["owner"]):
            drop(name, transfer_done=True)
            return False
        snapshot["tier"] = "memory"
    return True


def persist() -> None:
    """Before the machine shuts down, move the snapshots held in memory (/dev/shm, which a reboot
    wipes) to the disk tier, so agents resume warm after it. Nothing else loses them: a daemon
    restart, a model killed or Lemonade killed all leave /dev/shm as it is. Runs outside LOCK."""
    with LOCK:
        leaving = []
        # Disk admission may evict entries. Reserve each accepted transfer before
        # checking the next, so their combined size counts against the disk limit.
        for name, snapshot in list(L["snapshots"].items()):
            if snapshot["tier"] == "memory" and disk_room(size_gb(snapshot), keep=name):
                snapshot["tier"] = "moving"
                leaving.append(name)
    for name in leaving:
        spill(name)
    with LOCK:
        log("snapshots moved to disk for shutdown", count=len(leaving))


# ---------------------------------------------------------------- saving and forgetting

def keep(position: int, held: list[int], owner: str, kind: str) -> bool:
    """Save the lane's state (holding exactly `held`) as a snapshot of `owner`'s conversation, if
    it fits. A *checkpoint* is a conversation as committed (a thought's context, read, before it
    generates) and supersedes the conversation's older snapshots; a *suspended* state (a thought
    stopped part way) supersedes only older suspended ones, so the checkpoint outlives a thought
    that is abandoned. Runs outside LOCK; returns whether it was saved."""
    with LOCK:
        model, index = L["lanes"][position]["model"], L["lanes"][position]["index"]
        wanted = digest(held)
        if any(s["digest"] == wanted for s in L["snapshots"].values()):
            return True
        need = memory.snapshot_gb(L["snapshots"], model, len(held))
        if not room(need) or not make_room(need):
            return False
        name = secrets.token_hex(6)
        RESERVED[name] = need
    try:
        saved = BACKEND.save(CONFIG, model, index, name)
    except Exception:
        with LOCK:
            RESERVED.pop(name, None)
        BACKEND.forget(CONFIG, name)
        raise
    with LOCK:
        RESERVED.pop(name, None)
        if not live(owner):  # its conversation ended while the state was being written
            BACKEND.forget(CONFIG, name)
            return False
        for older in [n for n, s in L["snapshots"].items()
                      if s["owner"] == owner and s["model"] == model and s["tokens"] <= len(held)
                      and (kind == "checkpoint" or s["kind"] == "suspended")
                      and s["digest"] == digest(held[:s["tokens"]])]:
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


def keep_shared(position: int, tokens: list[int]) -> None:
    """Save a lane holding exactly a context start that several contexts share. Runs outside LOCK."""
    if keep(position, tokens, "shared", "checkpoint"):
        with LOCK:
            log("shared prefix saved", model=L["lanes"][position]["model"], tokens=len(tokens))


def forget_diverged(owner: str, model: str, tokens: list[int]) -> None:
    """A task's conversation is one line of history: its snapshots that do not begin the context
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


def forget_transfers() -> None:
    """At daemon startup, discard interrupted copies: no transfer thread survived it."""
    for name in [n for n, s in L["snapshots"].items() if s["tier"] == "moving"]:
        drop(name, transfer_done=True)
        log("snapshot forgotten", snapshot=name, reason="its transfer was interrupted")
