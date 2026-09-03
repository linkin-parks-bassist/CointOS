"""Randomized, overdue-aware task-card selection for the Steward role."""
from __future__ import annotations
import json, random
from datetime import datetime, timezone
from pathlib import Path
from ecosystem import cli

CARDS = cli.ROOT / "steward-tasks"

def select(config: dict, state: dict, rng: random.Random | random.SystemRandom | None = None, now: datetime | None = None) -> tuple[str, str, str]:
    rng = rng or random.SystemRandom()
    now = now or datetime.now(timezone.utc)
    history = state.get("task_last_selected", {})
    candidates = []
    for item in config["task_deck"]:
        previous = datetime.fromisoformat(history[item["id"]]) if item["id"] in history else None
        age = (now-previous).total_seconds() if previous else item["maximum_interval_seconds"] * 2
        overdue_ratio = age / item["maximum_interval_seconds"]
        weight = item.get("weight", 1) * max(0.25, overdue_ratio)
        candidates.append((item, weight, overdue_ratio))
    item = rng.choices([entry[0] for entry in candidates], weights=[entry[1] for entry in candidates], k=1)[0]
    ratio = next(entry[2] for entry in candidates if entry[0] is item)
    content = (CARDS / item["file"]).read_text(encoding="utf-8").strip()
    reason = f"randomized overdue-weighted selection; overdue ratio={ratio:.2f}"
    return item["id"], content, reason

