"""Durable, role-aware names for individual agent jobs."""
from __future__ import annotations
import json, random
from ecosystem import cli

DEFAULT_ROSTER = {"worker":["Rob","Nina","Dex"], "steward":["Mabel","Percy"], "intake":["Pip","Dot"], "default":["Alex","Sam"]}

def assign(role: str, rng: random.Random | random.SystemRandom | None = None) -> str:
    rng = rng or random.SystemRandom()
    path = cli.ROOT / "config/agent-names.json"
    roster = json.loads(path.read_text(encoding="utf-8")) if path.exists() else DEFAULT_ROSTER
    choices = roster.get(role, roster["default"])
    active = set()
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("state") in {"queued", "ready", "running"} and job.get("agent_name"):
            active.add(job["agent_name"])
    available = [name for name in choices if name not in active] or choices
    return rng.choice(available)
