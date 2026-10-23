"""Thoughts and lanes: pre-emptive time-sharing of model lanes among thinking agents.

A thought is advanced one step at a time by the worker of the lane that holds it: a step
reads up to `read_chunk_tokens` of its context, or, once the context is read, generates up to
`chunk_tokens`. Every step runs to its own end, so the lane always holds exactly known tokens.
Between steps the scheduler may give the lane to another thought; the worker then switches
contexts and goes on. A holder change on a busy lane waits for its step to end.

A context is identified by its tokens, not by who owns it: a lane is warm for a thought when
the tokens its state holds begin the thought's tokens, and a snapshot is found by a digest of
the tokens it holds. Owners (an agent's task, Coin, the user) matter only for display and for
forgetting the snapshots of a finished task.
"""
from __future__ import annotations

import queue
import secrets
import threading
import time
import traceback

from cointos import scheduler, snapshots, snapshot_cleanup, performance
from cointos.state import BACKEND, CONFIG, LOCK, L, STOPPING, alert, log, now

RUNS: dict[str, dict] = {}  # thought id -> its tokens and plumbing (kept out of the ledger)
BUSY: dict[int, str] = {}  # lane position -> the thought whose chunk is in flight there
HELD: dict[int, list[int]] = {}  # lane position -> the tokens its state holds
PROMPTS: dict[str, list[int]] = {}  # task -> the tokens of its last rendered prompt


def begins(held: list[int] | None, tokens: list[int]) -> bool:
    """Token-prefix identity, including equality; decode readiness belongs to the backend."""
    return bool(held) and len(held) <= len(tokens) and tokens[:len(held)] == held


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
    tokens, owner = tokens_of(thought_id), L["thoughts"][thought_id]["owner"]
    # Only other conversations: a conversation shares everything with its own earlier states.
    others = [tokens_of(t) for t, thought in L["thoughts"].items()
              if thought["owner"] != owner and thought["model"] == model]
    others += [held for p, held in HELD.items() if L["lanes"][p]["model"] == model and L["lanes"][p]["resident"] != owner]
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
        task = L["tasks"].get((L["agents"].get(agent) or {}).get("task"))
        weight = CONFIG["scheduler"]["weights"].get(task["role"], 1) if task else 1
        L["thoughts"][thought_id] = {"id": thought_id, "agent": agent, "class": klass, "weight": weight, "owner": owner, "model": model,
                                     "lane": None, "since": None, "waiting_since": now(), "warm": [], "reading": True, "opens_turn": False,
                                     "started_at": now(), "generated": 0, "prompt": len(rendered["tokens"]),
                                     "read": 0, "progress_at": now()}
        RUNS[thought_id] = {"prompt": rendered["tokens"], "reader": rendered["reader"], "sampling": sampling,
                            "max": max_new, "generated": [], "queue": queue.Queue(), "cancelled": False,
                            "shared": rendered.get("shared", []),
                            "retained_prefix": rendered.get('retained_prefix')}
        if klass == "user":
            L["user_last_thought"] = now()
        if owner in L["tasks"]:
            previous, PROMPTS[owner] = PROMPTS.get(owner), rendered["tokens"]
            # Report literal prompt changes; an earlier checkpoint can remain
            # reusable even when closing template tokens change.
            if previous and not begins(previous[:-1], rendered["tokens"]):
                threading.Thread(target=report_rewrite, args=(owner, model, previous, rendered["tokens"]),
                                 daemon=True).start()
        if owner in L["tasks"] or snapshots.coin_conversation(owner):
            snapshots.forget_diverged(owner, model, rendered["tokens"])
        for gone in [task for task in PROMPTS if not snapshots.live(task)]:
            del PROMPTS[gone]
        schedule()
    return thought_id


def report_rewrite(owner: str, model: str, previous: list[int], tokens: list[int]) -> None:
    """Record where a rendered task prompt changed and the text on both sides.

    Shorter compatible snapshots can still be restored. Runs outside LOCK.
    """
    at = common(previous, tokens)
    try:
        text = {key: BACKEND.text(CONFIG, model, part) for key, part in
                (("before", previous[max(0, at - 40):at]), ("previous_after", previous[at:at + 80]),
                 ("next_after", tokens[at:at + 80]))}
    except Exception as error:  # a diagnostic never fails a thought
        text = {"text_unavailable": f"{type(error).__name__}: {error}"}
    with LOCK:
        log("prompt rewritten", owner=owner, previous=len(previous), next=len(tokens), common=at, **text)


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
    that ended by handing control back (a message or a tool call) yields the lane, but while its
    turn is inside its slice the lane stays held for its agent for `yield_grace_seconds` (never
    past the slice's end), so a quick next thought continues the turn. Once the slice is over, a
    tool call is a plain yield: the cooldown is finite. Caller holds LOCK."""
    thought = L["thoughts"].pop(thought_id)
    run = RUNS.pop(thought_id)
    if thought["lane"] is not None:
        lane = L["lanes"][thought["lane"]]
        lane.update(holder=None, free_since=now())
        slice_ends = lane["turn_since"] + CONFIG["scheduler"]["slice_seconds"]
        if how == "done" and now() < slice_ends:
            lane.update(held_for=thought["agent"], held_class=thought["class"],
                        held_until=min(now() + CONFIG["scheduler"]["yield_grace_seconds"], slice_ends))
    run["queue"].put({"end": how})
    agent = L["agents"].get(thought["agent"])
    if agent is not None:
        agent["last_activity"] = now()  # thinking is activity: silence counts from its end
    if agent is not None and how == "done":
        said = snapshots.digest(run["generated"])
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
                           if L["lanes"][p]["model"] == thought["model"]
                           and BACKEND.can_continue(CONFIG, thought["model"], held, tokens)]
        # Reading: no lane holds (nearly) all of its context yet, so the model is still reading it.
        reading = not any(len(HELD[p]) >= len(tokens) - 1 for p in thought["warm"])
        # How much of its context the lane it holds has read (for progress).
        thought["held"] = len(HELD.get(thought["lane"]) or []) if thought["lane"] is not None else 0
        checkpoint = L["snapshots"].get(RUNS[thought_id].get("read_checkpoint"))
        thought["read_checkpoint"] = bool(
            reading and thought["lane"] in thought["warm"] and checkpoint
            and checkpoint["model"] == thought["model"]
            and checkpoint["tokens"] == thought["held"]
            and checkpoint["tier"] != "moving" and not checkpoint.get("discard"))
        if thought["reading"] != reading:
            thought["activity_since"] = now()
        thought["reading"] = reading
    contenders = list(L["thoughts"].values())
    wanted = scheduler.assign(CONFIG, L["lanes"], contenders, now(), blocked())
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
            thought.update(lane=position, since=lane["turn_since"], waiting_since=None, opens_turn=not returning,
                           progress_at=now(), activity_since=now())
    LOCK.notify_all()


def checkpoint_read(position: int, thought_id: str, held: list[int]) -> None:
    """Save a partial read only when an equal would win its expired slice.

    The lane worker still owns BUSY and the native state. Failed admission keeps
    the reader protected, avoiding repeated cold reads when snapshots cannot fit.
    """
    with LOCK:
        thought = L["thoughts"][thought_id]
        if now() - thought["since"] < CONFIG["scheduler"]["slice_seconds"]:
            return
        candidates = [dict(t, read_checkpoint=True) if t["id"] == thought_id else t
                      for t in L["thoughts"].values()]
        winner = scheduler.assign(CONFIG, L["lanes"], candidates, now(), blocked()).get(position)
        if winner in (None, thought_id) or L["thoughts"][winner]["class"] != thought["class"]:
            return
    try:
        if not snapshots.keep(position, held, thought["owner"], "suspended"):
            return
    except BACKEND.Lost:
        raise  # native state loss still requires the worker's recovery
    except Exception as error:
        with LOCK:
            log("read checkpoint failed", model=thought["model"], lane=position,
                owner=thought["owner"], detail=f"{type(error).__name__}: {error}")
        return  # optional fairness save must not discard a successful read
    with LOCK:
        wanted = snapshots.digest(held)
        RUNS[thought_id]["read_checkpoint"] = next(
            (name for name, saved in L["snapshots"].items()
             if saved["model"] == thought["model"] and saved["digest"] == wanted
             and saved["tier"] != "moving" and not saved.get("discard")), None)


def switch(position: int, tokens: list[int], owner: str) -> str | None:
    """Replace the lane's state with the best start for `tokens`: save the state it holds if
    that conversation goes on and it fits; then restore the longest snapshot that begins
    `tokens`. Without one the context is cold and the model reads it. Returns the name of the
    snapshot restored, if any."""
    started = time.monotonic()
    with LOCK:
        lane = dict(L["lanes"][position])
        held = HELD.get(position) or []
        # A task's conversation is one line: when the lane holds the same task's conversation
        # but not the start of where it goes on, that state has diverged and is of no use.
        single_history = owner in L["tasks"] or snapshots.coin_conversation(owner)
        diverged = bool(held) and lane["resident"] == owner and single_history and not begins(held, tokens)
        worth = bool(held) and snapshots.live(lane["resident"]) and not diverged
    if diverged:  # where the conversation stopped reproducing what the lane holds
        at = common(held, tokens)
        try:
            text = {key: BACKEND.text(CONFIG, lane["model"], part) for key, part in
                    (("before", held[max(0, at - 40):at]), ("held_after", held[at:at + 60]), ("next_after", tokens[at:at + 60]))}
        except Exception as error:  # a diagnostic never stops the switch
            text = {"text_unavailable": f"{type(error).__name__}: {error}"}
        with LOCK:
            log("divergence", owner=owner, held=len(held), next=len(tokens), common=at, **text)
    saving = time.monotonic()
    saved = worth and snapshots.keep(position, held, lane["resident"], "suspended")
    save_seconds = time.monotonic() - saving
    with LOCK:
        candidates = sorted(((s["tokens"], name) for name, s in L["snapshots"].items()
                    if s["model"] == lane["model"] and s["tier"] != "moving"
                    and BACKEND.can_continue(CONFIG, lane["model"], tokens[:s["tokens"]], tokens)
                    and s["tokens"] <= len(tokens)
                    and snapshots.digest(tokens[:s["tokens"]]) == s["digest"]), reverse=True)
    restored, broken = None, None
    restored_tokens = 0
    restore_tier = None
    transfer_seconds = restore_seconds = 0.0
    for length, name in candidates:
        with snapshot_cleanup.pin(name) as pinned:
            if not pinned:
                continue
            with LOCK:
                restore_tier = L["snapshots"].get(name, {}).get("tier")
            bringing = time.monotonic()
            ready = snapshots.bring_back(name)
            transfer_seconds += time.monotonic() - bringing
            if not ready:
                continue
            restoring = time.monotonic()
            valid = BACKEND.restore(CONFIG, lane["model"], lane["index"], name)
            restore_seconds += time.monotonic() - restoring
            if valid:
                restored, restored_tokens = name, length
                break
            broken = name  # it would not restore: try the next compatible prefix
            with LOCK:
                snapshots.drop(broken)
    with LOCK:
        if restored is not None and restored in L['snapshots']:
            L["snapshots"][restored]["last_run"] = now()
        HELD[position] = tokens[:restored_tokens]
        L["lanes"][position].update(resident=owner)
        log("switch", model=lane["model"], lane=lane["index"], out=lane["resident"], saved=bool(saved),
            into=owner, restored=restored_tokens, prompt_tokens=len(tokens), diverged=diverged,
            broken_snapshot=broken, restore_tier=restore_tier,
            save_seconds=save_seconds, transfer_seconds=transfer_seconds,
            restore_seconds=restore_seconds, seconds=time.monotonic() - started)
    return restored


# ---------------------------------------------------------------- lanes

def arrived(thought: dict, run: dict, new: list[int]) -> None:
    """New tokens of a thought, as the model writes them: to its asker, and onto its agent's count."""
    run["queue"].put(new)
    with LOCK:
        thought["generated"] += len(new)  # live display; committed token history advances at the step boundary
        thought["progress_at"] = now()
        agent = L["agents"].get(thought["agent"])
        if agent is not None:
            agent["generated"] += len(new)


def reasoning_step(thought: dict, run: dict, chunk: int) -> int:
    """Close budgeted reasoning in this same token history, leaving output room.

    Caller holds LOCK between GPU steps. Synthetic closing tokens are streamed and
    subsequently prefetched like any context extension; HELD is never fabricated.
    """
    reader = run.get("reader", {})
    budget = reader.get("reasoning_budget")
    generated = run["generated"]
    remaining = run["max"] - len(generated)
    if budget is None or reader["think_end"] in generated:
        return min(chunk, remaining)
    close = reader["think_close"]
    used = reader.get("reasoning_used", 0)
    limit = min(max(0, budget - used), max(0, run["max"] - len(close) - 1))
    if len(generated) < limit:
        return min(chunk, remaining, limit - len(generated))
    if remaining > len(close):
        arrived(thought, run, close)
        generated.extend(close)
        thought["reasoning_budget_reached"] = True
        log("reasoning budget reached", agent=thought["agent"], tokens=used + limit)
    return min(chunk, run["max"] - len(generated))


def worker(position: int) -> None:
    """Advance, one step at a time, whichever thought holds this lane."""
    read_chunk = CONFIG["scheduler"]["read_chunk_tokens"]
    while not STOPPING.is_set():
        with LOCK:
            lane = L["lanes"][position]
            while not STOPPING.is_set() and (not lane["up"] or lane["holder"] is None):
                LOCK.wait(1)
            if STOPPING.is_set():
                return
            thought_id = lane["holder"]
            thought, run = L["thoughts"][thought_id], RUNS[thought_id]
            chunk = CONFIG["scheduler"]["chunk_tokens"]  # fixed for this step, refreshed at the next boundary
            chunk = reasoning_step(thought, run, chunk)
            BUSY[position] = thought_id
            timing = L["coin"] if thought["agent"] == "coin" else L["agents"].get(thought["agent"])
            if timing is not None:
                timing["gpu_since"] = now()
            gpu_started = time.monotonic()
            model, index, tokens = lane["model"], lane["index"], tokens_of(thought_id)
            warm = BACKEND.can_continue(CONFIG, model, HELD.get(position), tokens)
            discovered = shared_prefix(thought_id, model) if not warm or len(HELD[position]) < len(tokens) - 1 else 0
            boundaries = sorted(set(run.get("shared", [])) | ({discovered} if discovered else set()))
        restored = None
        generating = False
        generation_started = None
        prefill_measurement = None
        try:
            if not warm:
                restored = switch(position, tokens, thought["owner"])
            held = len(HELD.get(position) or [])
            # Stop initial reading one token short for buffered backends. A backend
            # retaining the complete decoded vector can continue directly from equality.
            if held < len(tokens) - 1:  # still reading its context: one more piece
                end = min(len(tokens) - 1, held + read_chunk)
                # Retain the existing checkpoint slightly before a long prompt's tail.
                # Closing template tokens and small tail edits then need only a short
                # extension, rather than making the sole checkpoint incompatible.
                checkpoint_at = len(run["prompt"]) - 1
                if len(run["prompt"]) > read_chunk:
                    checkpoint_at -= 32
                # A warm lane may already extend beyond the preferred boundary.
                # Advance once instead of rewinding hybrid state; freeze this
                # boundary so subsequent pieces do not save each tail token.
                checkpoint_at = run.setdefault("checkpoint_at", min(len(run["prompt"]) - 1,
                    held + 1 if held > checkpoint_at else checkpoint_at))
                # A resumed exhausted reasoning block may already have synthetic
                # closing tokens in generated before its prompt is read. The
                # native position, not that output buffer, owns checkpoint timing.
                if held < checkpoint_at < end:
                    end = checkpoint_at
                # The first unsaved shared start this piece reaches: read to it exactly and save it.
                shared = next((b for b in boundaries if held < b <= end and not snapshots.shared(model, tokens[:b])), None)
                prefix = run.get('retained_prefix')
                if prefix is not None and not (held < prefix <= end and not snapshots.retain_prefix(
                        model, tokens[:prefix], thought['owner'])):
                    prefix = None
                if prefix is not None and (shared is None or prefix < shared):
                    end, shared = prefix, None
                else:
                    prefix = None
                keep_shared = shared is not None
                upto = tokens[:shared if keep_shared else end]
                prefill_started = time.monotonic()
                BACKEND.prefill(CONFIG, model, index, upto, held)
                prefill_measurement = (len(upto) - held, time.monotonic() - prefill_started)
                if keep_shared:  # the start other contexts share: save it once, for all of them
                    snapshots.keep_shared(position, upto)
                elif prefix is not None:
                    snapshots.keep(position, upto, thought['owner'], 'prefix')
                elif len(upto) == checkpoint_at and snapshots.live(thought["owner"]):
                    snapshots.keep(position, upto, thought["owner"], "checkpoint")
                result, holds = {"tokens": [], "done": False}, upto
                if len(upto) < len(tokens) - 1:
                    checkpoint_read(position, thought_id, upto)
            else:
                generating = True
                generation_started = time.monotonic()
                result = BACKEND.think(CONFIG, model, index, tokens, held, min(chunk, run["max"] - len(run["generated"])),
                                       run["sampling"], lambda new: arrived(thought, run, new))
                if not result["tokens"] and not result["done"]:
                    raise RuntimeError("generation step neither advanced nor ended the thought")
                holds = result["held"]
            failure = None
        except BACKEND.Lost as error:  # the server dropped the lane's state: it holds nothing known
            result, holds, failure = {"tokens": [], "done": False}, [], None
            with LOCK:
                log("lane state lost", model=model, lane=index, detail=str(error), restored=restored)
                if restored is not None:  # a snapshot the server does not keep is of no use
                    snapshots.drop(restored)
        except Exception as error:  # the backend failed under this thought
            traceback.print_exc()
            result, holds, failure = {"tokens": [], "done": False}, [], f"{type(error).__name__}: {error}"
        with LOCK:
            BUSY.pop(position, None)
            if prefill_measurement is not None:
                performance.record("prefill", *prefill_measurement)
            if generating and failure is None:
                performance.record("generation", len(result["tokens"]),
                    result.get("generation_seconds", time.monotonic() - generation_started),
                    draft_tokens=result.get("draft_tokens", 0),
                    accepted_tokens=result.get("draft_accepted_tokens", 0))
            if timing is not None:
                timing["gpu_seconds"] = timing.get("gpu_seconds", 0) + time.monotonic() - gpu_started
                timing["gpu_since"] = None
            run["generated"] += result["tokens"]
            thought["generated"] = len(run["generated"])
            HELD[position] = holds
            read = min(len(holds), thought["prompt"])
            if read > thought["read"] or (not generating and holds):
                # A lost or displaced cache must be prepared again. Successful
                # bounded rereading is work, even below an earlier read frontier.
                thought.update(read=max(read, thought["read"]), progress_at=now())
            L["lanes"][position]["resident"] = thought["owner"]
            agent = L["agents"].get(thought["agent"])
            if generating and failure is None and 'draft_rounds' in result:
                # Native counters describe this completed step, including rejected drafts.
                # Keep totals with their own time/token denominator, never older run spend.
                measured = {key: result[key] for key in
                            ('draft_rounds', 'draft_tokens', 'draft_accepted_tokens', 'generation_seconds')}
                measured['generation_tokens'] = len(result['tokens'])
                thought['decode'] = {**measured, 'at': now(), 'context_tokens': len(tokens),
                                     'sampling': result.get('sampling', {}), 'chunk_tokens': chunk}
                if timing is not None:
                    totals = timing.setdefault('speculation', {})
                    for key, value in measured.items():
                        totals[key] = totals.get(key, 0) + value
            if agent is not None and generating:
                agent["generation_seconds"] = agent.get("generation_seconds", 0) + result.get(
                    "generation_seconds", time.monotonic() - generation_started)
                agent["generation_tokens"] = agent.get("generation_tokens", 0) + len(result["tokens"])
            if result.get("rate"):
                thought["rate"] = round(result["rate"], 1)
                if agent is not None:
                    agent["rate"] = thought["rate"]  # the model's own speed on its last full step
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
    deadline = time.monotonic() + CONFIG["timeouts"]["stop_save_seconds"]
    while time.monotonic() < deadline:
        with LOCK:
            if not BUSY:
                break
        time.sleep(0.1)
    for position, lane in enumerate(L["lanes"]):
        with LOCK:
            held, owner = HELD.get(position) or [], lane["resident"]
            worth = lane["up"] and bool(held) and snapshots.live(owner)
        if worth and snapshots.keep(position, held, owner, "suspended"):
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
