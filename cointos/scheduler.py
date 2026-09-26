"""Who gets which free lane. Pure: plain data in, assignments out."""
from __future__ import annotations


def lane_allows(config: dict, lane: dict, klass: str) -> bool:
    for reserved in config["reserved_lanes"]:
        if reserved["model"] == lane["model"] and reserved["lane"] == lane["index"]:
            return klass in reserved["classes"]
    return True


def is_reserved(config: dict, lane: dict) -> bool:
    return any(r["model"] == lane["model"] and r["lane"] == lane["index"] for r in config["reserved_lanes"])


def assign(config: dict, lanes: list[dict], waiting: list[dict], now: float,
           blocked_classes: frozenset = frozenset()) -> list[tuple[str, int]]:
    """Pair waiting requests with free lanes.

    `lanes` are {"model", "index", "occupant", "last_caller"}; `waiting` are
    {"id", "caller", "class", "model", "queued_at"}. Returns (request id, lane position)
    pairs. Highest class first, oldest first within a class, except that a request whose
    caller last used a free lane goes first within its class (warm prompt cache) unless an
    older request of that class has waited longer than the warm grace.
    """
    rank = {klass: position for position, klass in enumerate(config["priorities"])}
    free = {position for position, lane in enumerate(lanes) if lane["occupant"] is None}
    grace = config["warm_lane_grace_seconds"]
    candidates = [r for r in waiting if r["class"] not in blocked_classes]
    oldest = {}
    for request in candidates:
        key = (request["model"], request["class"])
        oldest[key] = min(oldest.get(key, now), request["queued_at"])

    def warm_lane(request):
        for position in free:
            lane = lanes[position]
            if lane["model"] == request["model"] and lane["last_caller"] == request["caller"]:
                return position
        return None

    def order(request):
        warm = (warm_lane(request) is not None
                and now - oldest[(request["model"], request["class"])] <= grace)
        return (rank.get(request["class"], len(rank)), not warm, request["queued_at"])

    assignments = []
    for request in sorted(candidates, key=order):
        usable = [p for p in free if lanes[p]["model"] == request["model"]
                  and lane_allows(config, lanes[p], request["class"])]
        if not usable:
            continue
        warm = warm_lane(request)
        # Warm lane first; otherwise keep reserved lanes free for their own classes.
        position = warm if warm in usable else min(usable, key=lambda p: (is_reserved(config, lanes[p]), p))
        free.discard(position)
        assignments.append((request["id"], position))
    return assignments
