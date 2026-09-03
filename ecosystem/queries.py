"""Deterministic answers over authoritative lifecycle projections."""
from __future__ import annotations
from datetime import datetime
import re

ROLES = "intake|worker|steward"

def resolve(text: str, proposed_query: str = "general", proposed_role: str = "") -> tuple[str, str]:
    normalized = " ".join(text.lower().split())
    patterns = (
        rf"\blast\b.*?\b(?P<role>{ROLES})\b.*?\b(spawned?|started?|instantiated?|ran)\b",
        rf"\bwhen\b.*?\b(?P<role>{ROLES})\b.*?\b(spawned?|started?|instantiated?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match: return "last_role_spawn", match.group("role")
    return proposed_query, proposed_role

def answer(query: str, role: str, facts: dict) -> str | None:
    if query != "last_role_spawn" or not role:
        return None
    item = facts.get("latest_by_role", {}).get(role.lower())
    if not item:
        return f"I can't find any recorded {role} run yet."
    timestamp = datetime.fromisoformat(item["created_at"])
    name = item.get("agent_name") or "an unnamed agent"
    return f"The last {role} was {name}, spawned at {timestamp:%-I:%M:%S %p on %-d %B %Y} ({facts['timezone']})."
