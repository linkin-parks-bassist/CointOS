"""Job-boundary time-sharing policy for model-resident workers."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[1] / "config/model-policy.json"

def policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))

def choose(jobs: list[tuple[Path, dict]], inventory: dict, now: datetime | None = None) -> tuple[Path, dict, str]:
    if not jobs: raise ValueError("no jobs to schedule")
    now = now or datetime.now(timezone.utc)
    settings = policy()["workers"]
    loaded = {item["id"] for item in inventory["models"] if item.get("loaded") and item["id"] != policy()["control_plane"]["model"]}
    scored = []
    for path, job in jobs:
        created = datetime.fromisoformat(job["created_at"])
        age_minutes = max(0.0, (now - created).total_seconds() / 60)
        size = next((item.get("size_gb") or 0 for item in inventory["models"] if item["id"] == job.get("model")), 0)
        resident_bonus = size * settings["switch_penalty_points_per_gb"] if job.get("model") in loaded else 0
        starvation = 10000 if age_minutes >= settings["maximum_starvation_minutes"] else 0
        score = age_minutes * settings["queue_age_points_per_minute"] + resident_bonus + starvation
        scored.append((score, created, path, job, resident_bonus))
    score, _, path, job, resident_bonus = max(scored, key=lambda item: (item[0], -item[1].timestamp()))
    reason = (f"resident-model batching bonus={resident_bonus:.1f}, queue/resource score={score:.1f}"
              if resident_bonus else f"queue/resource score={score:.1f}; model switch accepted")
    return path, job, reason

