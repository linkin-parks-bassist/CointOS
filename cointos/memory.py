"""Memory: the one pool shared by David's desktop, the models and CointOS.

One rule governs it (`what/is/the/architecture/of/cointos.md`, *Memory*): an allocation
happens only if it fits in the headroom, and snapshots give way first.
"""
from __future__ import annotations

GB = 1e9


def measure() -> dict:
    """Available memory, swap in use and memory pressure, from /proc."""
    values = {}
    with open("/proc/meminfo", encoding="ascii") as stream:
        for line in stream:
            name, rest = line.split(":", 1)
            values[name] = int(rest.split()[0]) * 1024
    psi = 0.0
    with open("/proc/pressure/memory", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("full"):
                psi = float(line.split()[1].split("=")[1])
    return {"available_gb": round(values["MemAvailable"] / GB, 1),
            "swap_gb": round((values["SwapTotal"] - values["SwapFree"]) / GB, 2), "psi": psi}


def headroom_gb(config: dict, measured: dict, server: dict | None) -> float:
    """What CointOS may still allocate: the tighter of the machine's available memory beyond
    the reserve kept for David, and what is left of the model server's own allowance."""
    room = measured["available_gb"] - config["memory"]["reserve_gb"]
    if server is not None:
        room = min(room, server["limit_gb"] - server["used_gb"])
    return round(room, 1)


def distressed(config: dict, measured: dict) -> list[str]:
    """What shows the machine struggling right now (empty when it is not). Pressure is the
    measure: swap in use lingers long after pressure has gone, so it is not one."""
    limit = config["memory"]["max_psi"]
    return [f"memory pressure {measured['psi']} > {limit}"] if measured["psi"] > limit else []


def to_forget(snapshots: dict[str, dict], need_gb: float, headroom: float) -> list[str] | None:
    """The snapshots to forget, least recently run first, so that `need_gb` more fits in the
    headroom; None if forgetting them all would not be enough. `snapshots` maps a context to
    {"bytes", "last_run"}."""
    chosen, free = [], headroom
    for context, snapshot in sorted(snapshots.items(), key=lambda item: item[1]["last_run"]):
        if free >= need_gb:
            break
        chosen.append(context)
        free += snapshot["bytes"] / GB
    return chosen if free >= need_gb else None


def snapshot_gb(snapshots: dict[str, dict], model: str, tokens: int) -> float:
    """A context's expected snapshot size, from the bytes per token of that model's snapshots."""
    known = [s for s in snapshots.values() if s["model"] == model and s["tokens"]]
    if not known:
        return 0.0  # no evidence yet; the first save of a model is measured
    return round(tokens * sum(s["bytes"] for s in known) / sum(s["tokens"] for s in known) / GB, 2)
