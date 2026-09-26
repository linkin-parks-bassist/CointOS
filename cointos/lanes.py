"""Thoughts and lanes: pre-emptive time-sharing of model lanes among thinking agents.

A thought is advanced one step at a time by the worker of the lane that holds it: a step
reads up to `read_chunk_tokens` of its context, or, once the context is read, generates up to
`chunk_tokens`. Every step runs to its own end, so the lane always holds exactly known tokens.
Between steps the scheduler may give the lane to another thought; the worker then switches
contexts and goes on. A holder change on a busy lane waits for its step to end.

A context is identified by its tokens, not by who owns it: a lane is warm for a thought when
the tokens its state holds begin the thought's tokens, and a snapshot is found by a digest of
the tokens it holds. Owners (an agent's task, Coin, David) matter only for display and for
forgetting the snapshots of a finished task.
"""
from __future__ import annotations

import array
import hashlib
import queue
import secrets
import threading
import time
import traceback

from cointos import memory, scheduler
from cointos.state import BACKEND, CONFIG, LOCK, L, STOPPING, alert, log, now

RUNS: dict[str, dict] = {}  # thought id -> its tokens and plumbing (kept out of the ledger)
BUSY: dict[int, str] = {}  # lane position -> the thought whose chunk is in flight there
HELD: dict[int, list[int]] = {}  # lane position -> the tokens its state holds


def digest(tokens: list[int]) -> str:
    return hashlib.sha256(array.array("i", tokens).tobytes()).hexdigest()


def begins(held: list[int] | None, tokens: list[int]) -> bool:
    """Whether a state holding `held` can go on into `tokens`: the model cannot roll back, so
    `tokens` must extend it by at least one token."""
    return bool(held) and len(held) < len(tokens) and tokens[:len(held)] == held


def common(a: list[int], b: list[int]) -> int:
    """How many tokens `a` and `b` share at their start."""
    low, high = 0, min(len(a), len(b))
    while low < high:
        middle = (low + high + 1) // 2
        if a[:middle] == b[:middle]:
            low = middle
        else:
            high = middle - 1
    return low


def shared_prefix(thought_id: str, model: str) -> int:
    """The longest start this thought's context shares with another context of the model that
    CointOS holds or runs; 0 if it is too short to be worth a snapshot of its own. Caller holds LOCK."""
    tokens = tokens_of(thought_id)
    others = [tokens_of(t) for t, thought in L["thoughts"].items() if t != thought_id and thought["model"] == model]
    others += [held for p, held in HELD.items() if L["lanes"][p]["model"] == model]
    longest = max((common(tokens, other) for other in others), default=0)
    return longest if longest >= CONFIG["scheduler"]["shared_prefix_tokens"] else 0


def tokens_of(thought_id: str) -> list[int]:
    run = RUNS[thought_id]
    return run["prompt"] + run["generated"]


# ---------------------------------------------------------------- thoughts

def begin(agent: str, klass: str, owner: str, model: str, rendered: dict, sampling: dict, max_new: int) -> str:
    """Start a thought and return its id. Its new tokens arrive on RUNS[id]["queue"] as lists,
    and finally {"end": how}, how being done, limit, cancelled or failed."""
    thought_id = secrets.token_hex(6)
    with LOCK:
        L["thoughts"][thought_id] = {"id": thought_id, "agent": agent, "class": klass, "owner": owner, "model": model,
                                     "lane": None, "since": None, "waiting_since": now(), "warm": [], "reading": True,
                                     "started_at": now(), "generated": 0, "prompt": len(rendered["tokens"])}
        RUNS[thought_id] = {"prompt": rendered["tokens"], "reader": rendered["reader"], "sampling": sampling,
                            "max": max_new, "generated": [], "queue": queue.Queue(), "cancelled": False}
        if klass == "user":
            L["user_last_thought"] = now()
        if owner in L["tasks"]:
            forget_diverged(owner, model, rendered["tokens"])
        schedule()
    return thought_id


def forget_diverged(owner: str, model: str, tokens: list[int]) -> None:
    """A task's conversation is one line of history: its snapshots that do not begin the context
    it goes on with (left by a run that stopped mid-thought) can never be used again. Caller holds LOCK."""
    for name in [n for n, s in L["snapshots"].items()
                 if s["owner"] == owner and s["model"] == model
                 and (s["tokens"] >= len(tokens) or digest(tokens[:s["tokens"]]) != s["digest"])]:
        L["snapshots"].pop(name)
        BACKEND.forget(CONFIG, name)
        log("snapshot forgotten", owner=owner, reason="diverged from its conversation")


def cancel(thought_id: str) -> None:
    """Its asker is gone: drop a waiting thought now, a running one at its step's end."""
    with LOCK:
        run = RUNS.get(thought_id)
        if run is None:
            return
        run["cancelled"] = True
        if L["thoughts"][thought_id]["lane"] is None:
            finish(thought_id, "cancelled")


def cancel_agent(agent: str) -> None:
    """Drop every thought of an agent that has ended. Caller holds LOCK."""
    for thought_id, thought in list(L["thoughts"].items()):
        if thought["agent"] == agent:
            cancel(thought_id)


def finish(thought_id: str, how: str) -> None:
    """End a thought and free its lane, whose state stays for whoever continues it. A thought
    that ended by handing control back (a message or a tool call) keeps its lane held for its
    agent for `yield_grace_seconds`, so a quick next thought continues the turn. Caller holds LOCK."""
    thought = L["thoughts"].pop(thought_id)
    run = RUNS.pop(thought_id)
    if thought["lane"] is not None:
        lane = L["lanes"][thought["lane"]]
        lane.update(holder=None, free_since=now())
        if how == "done":
            lane.update(held_for=thought["agent"], held_class=thought["class"],
                        held_until=now() + CONFIG["scheduler"]["yield_grace_seconds"])
    run["queue"].put({"end": how})
    agent = L["agents"].get(thought["agent"])
    if agent is not None and how == "done":
        said = digest(run["generated"])
        agent["repeats"] = agent["repeats"] + 1 if agent["last_thought"] == said else 1
        agent["last_thought"] = said
        agent["thoughts"] += 1
    schedule()


# ---------------------------------------------------------------- scheduling

def blocked() -> frozenset:
    return frozenset({"background"}) if L["guard"]["blocked"] or L["guard"]["killed"] else frozenset()


def schedule() -> None:
    """Apply the scheduler's choice of holders. Caller holds LOCK."""
    for thought_id, thought in L["thoughts"].items():
        tokens = tokens_of(thought_id)
        thought["warm"] = [p for p, held in HELD.items()
                           if L["lanes"][p]["model"] == thought["model"] and begins(held, tokens)]
        # Reading: no lane holds (nearly) all of its context yet, so the model is still reading it.
        reading = not any(len(HELD[p]) >= len(tokens) - 1 for p in thought["warm"])
        # How much of its context the lane it holds has read (for progress).
        thought["held"] = len(HELD.get(thought["lane"]) or []) if thought["lane"] is not None else 0
        if thought["reading"] and not reading and thought["lane"] is not None:
            # The read is done: the turn's slice counts generating time only, from now.
            L["lanes"][thought["lane"]]["turn_since"] = thought["since"] = now()
        thought["reading"] = reading
    wanted = scheduler.assign(CONFIG, L["lanes"], list(L["thoughts"].values()), now(), blocked())
    for position, thought_id in wanted.items():
        lane = L["lanes"][position]
        if lane["holder"] == thought_id:
            continue
        if position in BUSY:
            continue  # the change waits for this step's end
        if thought_id is not None and thought_id in BUSY.values():
            continue  # its step is in flight on another lane; it moves when that step ends
        if lane["holder"] is not None:
            L["thoughts"][lane["holder"]].update(lane=None, since=None, waiting_since=now())
        lane["holder"] = thought_id
        if thought_id is None:
            lane["free_since"] = now()
        else:
            thought = L["thoughts"][thought_id]
            # An agent back within its grace continues its turn: its slice keeps counting.
            returning = scheduler.held_for(lane, now()) == thought["agent"] and lane.get("turn_agent") == thought["agent"]
            lane.update(turn_agent=thought["agent"], turn_since=lane["turn_since"] if returning else now(),
                        held_for=None, held_until=0)
            thought.update(lane=position, since=lane["turn_since"], waiting_since=None)
    LOCK.notify_all()


# ---------------------------------------------------------------- memory for contexts

def in_memory() -> dict[str, dict]:
    return {n: s for n, s in L["snapshots"].items() if s["tier"] == "memory"}


def make_room(need_gb: float) -> bool:
    """Whether `need_gb` fits in the headroom, moving the least recently run snapshots out of
    memory as needed: to disk while the disk tier has room, else forgotten. What fits is
    counted as taken until memory is next measured. Caller holds LOCK."""
    leaving = memory.to_forget(in_memory(), need_gb, L["memory"].get("headroom_gb", 0.0))
    if leaving is None:
        return False
    for name in leaving:
        snapshot = L["snapshots"][name]
        L["memory"]["headroom_gb"] = round(L["memory"]["headroom_gb"] + snapshot["bytes"] / memory.GB, 1)
        if disk_room(snapshot["bytes"] / memory.GB, keep=name):
            snapshot["tier"] = "moving"
            threading.Thread(target=spill, args=(name,), daemon=True).start()
        else:
            L["snapshots"].pop(name)
            BACKEND.forget(CONFIG, name)
    L["memory"]["headroom_gb"] = round(L["memory"]["headroom_gb"] - need_gb, 1)
    return True


def disk_room(need_gb: float, keep: str) -> bool:
    """Whether `need_gb` more fits in the disk tier, forgetting its least recently run
    snapshots as needed. Caller holds LOCK."""
    on_disk = {n: s for n, s in L["snapshots"].items() if s["tier"] in ("disk", "moving") and n != keep}
    used = sum(s["bytes"] for s in on_disk.values()) / memory.GB
    leaving = memory.to_forget(on_disk, need_gb, CONFIG["memory"]["disk_snapshots_gb"] - used)
    if leaving is None:
        return False
    for name in leaving:
        L["snapshots"].pop(name)
        BACKEND.forget(CONFIG, name)
    return True


def spill(name: str) -> None:
    try:
        BACKEND.spill(CONFIG, name)
    except OSError as error:
        with LOCK:
            L["snapshots"].pop(name, None)
            log("spill failed", snapshot=name, error=str(error))
        BACKEND.forget(CONFIG, name)
        return
    with LOCK:
        if name in L["snapshots"]:
            L["snapshots"][name]["tier"] = "disk"


def saved_prefix(model: str, tokens: list[int]) -> bool:
    with LOCK:
        wanted = digest(tokens)
        return any(s["model"] == model and s["digest"] == wanted for s in L["snapshots"].values())


def save_prefix(position: int, tokens: list[int]) -> None:
    """Save a lane holding exactly a context start that several contexts share."""
    if keep(position, tokens, "shared", "checkpoint"):
        with LOCK:
            log("shared prefix saved", model=L["lanes"][position]["model"], tokens=len(tokens))


def keep(position: int, held: list[int], owner: str, kind: str) -> bool:
    """Save the lane's state (holding exactly `held`) as a snapshot of `owner`'s conversation, if
    it fits. A *checkpoint* is a conversation as committed (a thought's context, read, before it
    generates) and supersedes the conversation's older snapshots; a *suspended* state (a thought
    stopped part way) supersedes only older suspended ones, so the checkpoint outlives a thought
    that is abandoned. Returns whether it was saved."""
    with LOCK:
        model, index = L["lanes"][position]["model"], L["lanes"][position]["index"]
        wanted = digest(held)
        if any(s["digest"] == wanted for s in L["snapshots"].values()):
            return True
        if not make_room(memory.snapshot_gb(L["snapshots"], model, len(held))):
            return False
    name = secrets.token_hex(6)
    saved = BACKEND.save(CONFIG, model, index, name)
    with LOCK:
        for older in [n for n, s in L["snapshots"].items()
                      if s["owner"] == owner and s["model"] == model and s["tokens"] <= len(held)
                      and (kind == "checkpoint" or s["kind"] == "suspended")
                      and s["digest"] == digest(held[:s["tokens"]])]:
            L["snapshots"].pop(older)
            BACKEND.forget(CONFIG, older)
        L["snapshots"][name] = {"owner": owner, "model": model, "tokens": len(held), "digest": wanted, "kind": kind,
                                "bytes": saved["bytes"], "last_run": now(), "tier": "memory"}
    return True


def forget_owner(owner: str) -> None:
    """Forget the snapshots of a conversation that is over. Caller holds LOCK."""
    for name in [n for n, s in L["snapshots"].items() if s["owner"] == owner]:
        L["snapshots"].pop(name)
        BACKEND.forget(CONFIG, name)


def live(owner: str | None) -> bool:
    """Whether a conversation can still go on, so that its context is worth saving. Caller holds LOCK."""
    task = L["tasks"].get(owner or "")
    return owner is not None and (task is None or task["status"] in ("running", "waiting"))


def switch(position: int, tokens: list[int], owner: str) -> None:
    """Replace the lane's state with the best start for `tokens`: save the state it holds if
    that conversation goes on and it fits (snapshots give way, least recently run first); then
    restore the longest snapshot that begins `tokens`. Without one the context is cold and the
    model reads it."""
    with LOCK:
        lane = dict(L["lanes"][position])
        held = HELD.get(position) or []
        worth = bool(held) and live(lane["resident"])
    save = worth and keep(position, held, lane["resident"], "suspended")
    with LOCK:
        candidates = sorted(((s["tokens"], name) for name, s in L["snapshots"].items()
                             if s["model"] == lane["model"] and s["tier"] != "moving" and s["tokens"] < len(tokens)
                             and digest(tokens[:s["tokens"]]) == s["digest"]), reverse=True)
    restored, broken = None, None
    for count, name in candidates[:1]:
        with LOCK:  # a snapshot on disk comes back to memory first, if it fits
            snapshot = L["snapshots"].get(name)
            back = snapshot is not None and snapshot["tier"] == "disk" and make_room(snapshot["bytes"] / memory.GB)
            if back:
                snapshot["tier"] = "moving"
            usable = snapshot is not None and (back or snapshot["tier"] == "memory")
        if back:
            BACKEND.unspill(CONFIG, name)
            with LOCK:
                snapshot["tier"] = "memory"
        if usable:
            if BACKEND.restore(CONFIG, lane["model"], lane["index"], name):
                restored = count
            else:
                broken = name  # it would not restore: it is of no further use
    with LOCK:
        if broken is not None:
            L["snapshots"].pop(broken, None)
            BACKEND.forget(CONFIG, broken)
        elif restored is not None:
            L["snapshots"][candidates[0][1]]["last_run"] = now()
        HELD[position] = tokens[:restored] if restored else []
        L["lanes"][position].update(resident=owner)
        log("switch", model=lane["model"], lane=lane["index"], out=lane["resident"], saved=bool(save),
            into=owner, restored=restored or 0)


# ---------------------------------------------------------------- lanes

def worker(position: int) -> None:
    """Advance, one step at a time, whichever thought holds this lane."""
    chunk, read_chunk = CONFIG["scheduler"]["chunk_tokens"], CONFIG["scheduler"]["read_chunk_tokens"]
    while not STOPPING.is_set():
        with LOCK:
            lane = L["lanes"][position]
            while not STOPPING.is_set() and (not lane["up"] or lane["holder"] is None):
                LOCK.wait(1)
            if STOPPING.is_set():
                return
            thought_id = lane["holder"]
            thought, run = L["thoughts"][thought_id], RUNS[thought_id]
            BUSY[position] = thought_id
            model, index, tokens = lane["model"], lane["index"], tokens_of(thought_id)
            warm = begins(HELD.get(position), tokens)
            shared = shared_prefix(thought_id, model) if not warm or len(HELD[position]) < len(tokens) - 1 else 0
        try:
            if not warm:
                switch(position, tokens, thought["owner"])
            held = len(HELD.get(position) or [])
            # Reading stops one token short: generating then extends the lane by exactly one token.
            # (Holding the whole context would make the model roll back one token to generate,
            # which it cannot do; it would read everything again.)
            if held < len(tokens) - 1:  # still reading its context: one more piece
                end = min(len(tokens) - 1, held + read_chunk)
                keep_shared = held < shared <= end and not saved_prefix(model, tokens[:shared])
                upto = tokens[:shared if keep_shared else end]
                BACKEND.prefill(CONFIG, model, index, upto)
                if keep_shared:  # the start other contexts share: save it once, for all of them
                    save_prefix(position, upto)
                elif len(upto) == len(tokens) - 1 and not run["generated"] and live(thought["owner"]):
                    keep(position, upto, thought["owner"], "checkpoint")  # the conversation as committed
                result, holds = {"tokens": [], "done": False}, upto
            else:
                began = time.monotonic()
                result = BACKEND.think(CONFIG, model, index, tokens, min(chunk, run["max"] - len(run["generated"])),
                                       run["sampling"], run["queue"].put)
                result["seconds"] = time.monotonic() - began
                holds = tokens + result["tokens"][:-1] if result["tokens"] else tokens
            failure = None
        except Exception as error:  # the backend failed under this thought
            traceback.print_exc()
            result, holds, failure = {"tokens": [], "done": False}, [], f"{type(error).__name__}: {error}"
        with LOCK:
            BUSY.pop(position, None)
            run["generated"] += result["tokens"]
            thought["generated"] = len(run["generated"])
            HELD[position] = holds
            L["lanes"][position]["resident"] = thought["owner"]
            agent = L["agents"].get(thought["agent"])
            if agent is not None and result.get("seconds") and len(result["tokens"]) > 1:
                # Generation speed, smoothed over steps: what the agent gets while it holds a lane.
                step = len(result["tokens"]) / result["seconds"]
                agent["rate"] = round(step if agent.get("rate") is None else 0.6 * agent["rate"] + 0.4 * step, 1)
            if failure and not lane["up"]:
                pass  # its model went away; lanes_down made the thought wait for another lane
            elif failure:
                alert(f"{model} lane {index} failed a thought of {thought['agent']}: {failure}")
                finish(thought_id, "failed")
            elif result["done"] or run["cancelled"] or len(run["generated"]) >= run["max"]:
                finish(thought_id, "done" if result["done"] else "cancelled" if run["cancelled"] else "limit")
            else:
                schedule()


def save_all() -> None:
    """On a graceful stop: once the steps in flight have ended, save each lane's context whose
    conversation goes on, so a restarted daemon resumes it warm instead of reading it again."""
    for _ in range(600):
        with LOCK:
            if not BUSY:
                break
        time.sleep(0.1)
    for position, lane in enumerate(L["lanes"]):
        with LOCK:
            held, owner = HELD.get(position) or [], lane["resident"]
            worth = lane["up"] and bool(held) and live(owner)
        if worth and keep(position, held, owner, "suspended"):
            with LOCK:
                log("saved on stop", model=lane["model"], lane=lane["index"], owner=owner, tokens=len(held))


def lanes_down(model: str) -> None:
    """A model went away: its lanes are down, their states are gone, and their holders wait
    again. Caller holds LOCK."""
    for position, lane in enumerate(L["lanes"]):
        if lane["model"] == model and lane["up"]:
            lane.update(up=False, resident=None)
            HELD.pop(position, None)
            if lane["holder"] is not None:
                L["thoughts"][lane["holder"]].update(lane=None, since=None, waiting_since=now())
                lane["holder"] = None
    schedule()


def lanes_up(model: str) -> None:
    """A model is serving in its configured shape: its lanes take thoughts. Caller holds LOCK."""
    for position, lane in enumerate(L["lanes"]):
        if lane["model"] == model and not lane["up"]:
            lane.update(up=True, resident=None, free_since=now())
            HELD.pop(position, None)
    schedule()


def start() -> None:
    for position in range(len(L["lanes"])):
        threading.Thread(target=worker, args=(position,), daemon=True, name=f"lane-{position}").start()
