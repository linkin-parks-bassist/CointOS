"""Which thought holds which lane. Pure: plain data in, decisions out.

The policy (`what/is/the/architecture/of/cointos.md`, *The scheduler is pre-emptive*):
- classes are strict: a higher class takes a lane at once, from a generating holder before a
  reading one (a cold read is displaced only when there is no other lane);
- among equals, a thought still reading its context keeps its lane until the read is done;
  a generating holder yields to a waiting equal once its turn has lasted `slice_seconds`;
- a tool call yields the lane, but it stays held for its agent for `yield_grace_seconds`, so
  a quick next thought continues the same turn on the same lane.
"""
from __future__ import annotations


def lane_allows(config: dict, lane: dict, klass: str) -> bool:
    for reserved in config["reserved_lanes"]:
        if reserved["model"] == lane["model"] and reserved["lane"] == lane["index"]:
            return klass in reserved["classes"]
    return True


def is_reserved(config: dict, lane: dict) -> bool:
    return any(r["model"] == lane["model"] and r["lane"] == lane["index"] for r in config["reserved_lanes"])


def rank(config: dict, klass: str) -> int:
    return config["classes"].index(klass) if klass in config["classes"] else len(config["classes"])


def held_for(lane: dict, now: float) -> str | None:
    """The agent a free lane is kept for after its tool call, while the grace lasts."""
    return lane.get("held_for") if lane.get("held_until", 0) > now else None


def order(config: dict, thought: dict, lanes: list[dict], now: float) -> tuple:
    """Earlier is more entitled to a lane: class first; within a class, holders that are reading
    or inside their slice and agents returning to a lane kept for them, then waiting thoughts
    (longest waiting first), then holders whose slice is over."""
    klass = rank(config, thought["class"])
    if thought["lane"] is None:
        returning = any(held_for(lane, now) == thought["agent"] for lane in lanes)
        return (klass, 0, 0) if returning else (klass, 1, thought["waiting_since"])
    in_slice = thought["reading"] or now - thought["since"] < config["scheduler"]["slice_seconds"]
    return klass, 0 if in_slice else 2, thought["since"]


def assign(config: dict, lanes: list[dict], thoughts: list[dict], now: float,
           blocked: frozenset = frozenset()) -> dict[int, str | None]:
    """The holder each lane should have: {lane position: thought id or None}.

    `lanes` are {"model", "index", "up", "holder", "held_for", "held_class", "held_until"};
    `thoughts` are {"id", "agent", "class", "model", "lane", "since", "waiting_since", "warm",
    "reading"}: `lane` is the position a thought holds or None, `warm` the positions whose state
    begins its context, `reading` whether it is still reading its context. Thoughts of a
    `blocked` class get no lane.
    """
    by_id = {t["id"]: t for t in thoughts}
    claimed: dict[int, str] = {}
    for thought in sorted((t for t in thoughts if t["class"] not in blocked), key=lambda t: order(config, t, lanes, now)):
        mine = rank(config, thought["class"])

        def open_to_it(p, lane):
            keeper = held_for(lane, now)
            kept = keeper not in (None, thought["agent"]) and mine >= rank(config, lane["held_class"])
            return (lane["up"] and p not in claimed and lane["model"] == thought["model"] and not kept
                    and lane_allows(config, lane, thought["class"]))

        def displaces_reader(p):
            holder = by_id.get(lanes[p]["holder"])
            return holder is not None and holder["reading"]

        open_lanes = [p for p, lane in enumerate(lanes) if open_to_it(p, lane)]
        if not open_lanes:
            continue
        # Cheapest lane first: its own or one kept for it, then one whose state begins its
        # context, then a free one, then one whose holder is generating rather than reading,
        # then an unreserved one (reserved lanes stay for their classes), then the lowest.
        claimed[min(open_lanes, key=lambda p: (p != thought["lane"] and held_for(lanes[p], now) != thought["agent"],
                                               p not in thought["warm"], lanes[p]["holder"] is not None,
                                               displaces_reader(p), is_reserved(config, lanes[p]), p))] = thought["id"]
    return {p: claimed.get(p) for p, lane in enumerate(lanes) if lane["up"]}
