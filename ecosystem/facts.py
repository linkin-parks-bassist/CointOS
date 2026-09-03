"""Exact queryable lifecycle facts for the control plane."""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from ecosystem import cli

LOCAL = ZoneInfo("Australia/Sydney")

def lifecycle() -> dict:
    by_role: dict[str, dict] = {}
    recent = []
    for path in (cli.ROOT / "state/jobs").glob("task-*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("kind") != "agent-task": continue
        fact = {key:job.get(key) for key in ("id","role","agent_name","state","created_at","updated_at","model")}
        for key in ("created_at","updated_at"):
            if fact.get(key): fact[key] = datetime.fromisoformat(fact[key]).astimezone(LOCAL).isoformat()
        recent.append(fact)
        role = job.get("role")
        if role and (role not in by_role or fact["created_at"] > by_role[role]["created_at"]): by_role[role] = fact
    recent.sort(key=lambda item:item.get("created_at", ""), reverse=True)
    return {"timezone":"Australia/Sydney", "now":datetime.now(LOCAL).isoformat(), "latest_by_role":by_role, "recent_agents":recent[:10]}

