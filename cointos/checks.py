"""The self-check invariants, evaluated every tick over the ledger. Pure."""
from __future__ import annotations

from cointos.machine import breaches
from cointos.scheduler import lane_allows


def evaluate(config: dict, ledger: dict, now: float, agent_processes: dict[str, list[int]],
             blocked_classes: frozenset = frozenset()) -> list[dict]:
    """`agent_processes` maps agent id to the live pids found carrying that id."""
    limits = config["checks"]
    waiting = [r for r in ledger["requests"].values() if r["lane"] is None]
    results = []

    def check(name, problems):
        results.append({"name": name, "ok": not problems, "detail": "; ".join(problems)})

    problems = []
    for lane in ledger["lanes"]:
        if lane["up"] and lane["occupant"] is None and now - lane["free_since"] > limits["lane_idle_seconds"]:
            if any(r["model"] == lane["model"] and r["class"] not in blocked_classes
                   and lane_allows(config, lane, r["class"]) for r in waiting):
                problems.append(f"{lane['model']} lane {lane['index']} idle {now - lane['free_since']:.0f}s with work waiting")
    check("lanes busy when work waits", problems)

    reserved = [(entry["model"], set(entry["classes"])) for entry in config["reserved_lanes"]]
    check("reserved lane serves within limit", [
        f"{r['caller']} waited {now - r['queued_at']:.0f}s for {r['model']}"
        for r in waiting for model, classes in reserved
        if r["model"] == model and r["class"] in classes and now - r["queued_at"] > limits["coin_wait_seconds"]])

    check("no silent agent", [
        f"{agent_id} silent {now - agent['last_activity']:.0f}s"
        for agent_id, agent in ledger["agents"].items()
        if now - agent["last_activity"] > limits["agent_silent_seconds"]])

    check("no looping agent", [
        f"{agent_id} repeated one request {agent['repeats']} times"
        for agent_id, agent in ledger["agents"].items() if agent["repeats"] > limits["max_identical_requests"]])

    problems = [f"{agent_id} has no live process" for agent_id in ledger["agents"] if agent_id not in agent_processes]
    problems += [f"stray agent process {agent_id} (pids {pids})" for agent_id, pids in agent_processes.items()
                 if agent_id not in ledger["agents"]]
    check("agents match processes", problems)

    check("machine within limits", breaches(config["limits"], ledger["machine"]) if ledger.get("machine") else [])
    return results
