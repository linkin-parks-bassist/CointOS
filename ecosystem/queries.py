"""Deterministic answers over authoritative lifecycle projections."""
from __future__ import annotations
from datetime import datetime

def answer(query: str, role: str, facts: dict) -> str | None:
    if query != "last_role_spawn" or not role:
        return None
    item = facts.get("latest_by_role", {}).get(role.lower())
    if not item:
        return f"I can't find any recorded {role} run yet."
    timestamp = datetime.fromisoformat(item["created_at"])
    name = item.get("agent_name") or "an unnamed agent"
    return f"The last {role} was {name}, spawned at {timestamp:%-I:%M:%S %p on %-d %B %Y} ({facts['timezone']})."

