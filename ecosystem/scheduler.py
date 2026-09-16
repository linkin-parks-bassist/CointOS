"""Job-boundary time-sharing policy over the trusted scheduling bands."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from ecosystem.inference_capacity import effective_priority

POLICY_PATH = Path(__file__).resolve().parents[1] / "config/model-policy.json"

def policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def scheduling_document(root: Path) -> dict:
    """The accepted scheduling snapshot document; its digest is re-validated
    by the trusted priority helper on every use."""
    return json.loads((Path(root) / "state" / "scheduling-policy.json")
                      .read_text(encoding="utf-8"))


def priority(job: dict, scheduling: dict, now: datetime | None = None) -> int:
    """Trusted band priority for a job; age rises only within its band, so
    unknown roles stay below the large_health floor and cannot cross bands."""
    now = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(job["created_at"])
    age_seconds = max(0.0, (now - created).total_seconds())
    return effective_priority(
        scheduling, job.get("role"), job.get("execution_profile"),
        str(job.get("authority_profile") or "ordinary"), age_seconds)

def choose(jobs: list[tuple[Path, dict]], inventory: dict,
           scheduling: dict, now: datetime | None = None) -> tuple[Path, dict, str]:
    if not jobs: raise ValueError("no jobs to schedule")
    now = now or datetime.now(timezone.utc)
    settings = policy()["workers"]
    loaded = {item["id"] for item in inventory["models"] if item.get("loaded") and item["id"] != policy()["control_plane"]["model"]}
    scored = []
    for path, job in jobs:
        if not job.get("model"):
            continue
        created = datetime.fromisoformat(job["created_at"])
        size = next((item.get("size_gb") or 0 for item in inventory["models"] if item["id"] == job.get("model")), 0)
        resident_bonus = size * settings["switch_penalty_points_per_gb"] if job.get("model") in loaded else 0
        dispatch_penalty = int(job.get("dispatch_count", 0)) * 10000
        score = (priority(job, scheduling, now) * 100000 + resident_bonus
                 - dispatch_penalty)
        scored.append((score, created, path, job, resident_bonus))
    if not scored:
        raise RuntimeError("no model-routed ready job is eligible")
    score, _, path, job, resident_bonus = max(scored, key=lambda item: (item[0], -item[1].timestamp()))
    reason = (f"resident-model batching bonus={resident_bonus:.1f}, queue/resource score={score:.1f}"
              if resident_bonus else f"queue/resource score={score:.1f}; model switch accepted")
    return path, job, reason
