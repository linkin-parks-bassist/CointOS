"""The self-check invariants, evaluated every tick over the ledger. Pure."""
from __future__ import annotations

from cointos import memory
from cointos.scheduler import held_for, lane_allows


def evaluate(config: dict, ledger: dict, now: float, processes: dict[str, list[int]],
             blocked: frozenset = frozenset()) -> list[dict]:
    """`processes` maps agent id to the live pids found carrying that id."""
    limits = config["checks"]
    rank = {klass: position for position, klass in enumerate(config["classes"])}
    lanes, thoughts = ledger["lanes"], list(ledger["thoughts"].values())
    waiting = [t for t in thoughts if t["lane"] is None and t["class"] not in blocked]
    results = []

    def check(name, problems):
        results.append({"name": name, "ok": not problems, "detail": "; ".join(problems)})

    def idle_for(lane):  # a lane kept for an agent's grace is not idle until the grace ends
        return now - max(lane["free_since"], lane.get("held_until", 0))

    check("no lane idle while an agent waits", [
        f"{lane['model']} lane {lane['index']} idle {idle_for(lane):.0f}s"
        for lane in lanes if lane["up"] and lane["holder"] is None and held_for(lane, now) is None
        and idle_for(lane) > limits["idle_lane_seconds"]
        and any(t["model"] == lane["model"] and lane_allows(config, lane, t["class"]) for t in waiting)])

    def held_by(test, t):
        """Lanes t could use whose holder passes `test`."""
        return [lane for lane in lanes if lane["model"] == t["model"] and lane["holder"] in ledger["thoughts"]
                and test(ledger["thoughts"][lane["holder"]]) and lane_allows(config, lane, t["class"])]

    check("higher classes pre-empt", [
        f"{t['agent']} ({t['class']}) waited {now - t['waiting_since']:.0f}s behind a lower class"
        for t in waiting if now - t["waiting_since"] > limits["preempt_seconds"]
        and held_by(lambda h, t=t: rank.get(h["class"], 99) > rank.get(t["class"], 99), t)])

    def overdue(h, t):  # how long h has held on past its slice while t was waiting
        return min(now - t["waiting_since"], now - h["since"] - config["scheduler"]["slice_seconds"])

    check("no agent starves", [
        f"{t['agent']} passed over for {max(overdue(h, t) for h in thoughts if h['lane'] is not None):.0f}s by an equal past its slice"
        for t in waiting if held_by(lambda h, t=t: h["class"] == t["class"] and not h["reading"]
                                    and overdue(h, t) > limits["starve_seconds"], t)])

    thinking = {t["agent"] for t in thoughts}
    check("no silent agent", [
        f"{agent_id} running tools silently for {now - agent['last_activity']:.0f}s"
        for agent_id, agent in ledger["agents"].items()
        if agent_id not in thinking and now - agent["last_activity"] > limits["agent_silent_seconds"]])

    check("no looping agent", [
        f"{agent_id} repeated one thought {agent['repeats']} times"
        for agent_id, agent in ledger["agents"].items() if agent["repeats"] > limits["max_identical_thoughts"]])

    # An agent leaves the ledger before its processes are stopped, so processes of an agent in
    # `exiting` are expected until that entry's grace runs out.
    problems = [f"{agent_id} has no live process" for agent_id, agent in ledger["agents"].items()
                if agent["state"] != "starting" and agent_id not in processes]
    problems += [f"stray agent process {agent_id} (pids {pids})" for agent_id, pids in processes.items()
                 if agent_id not in ledger["agents"] and agent_id not in ledger["exiting"]]
    check("agents match processes", problems)

    measured = ledger.get("memory") or {}
    problems = memory.distressed(config, measured) if measured else []
    if measured and measured["headroom_gb"] < 0:
        problems.append(f"headroom {measured['headroom_gb']} GB below the {config['memory']['reserve_gb']} GB reserve")
    check("memory within bounds", problems)
    return results
