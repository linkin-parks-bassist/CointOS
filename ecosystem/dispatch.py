"""Translate managed work and fresh route capacity into systemd executor lanes.

Job state and model routes are the scheduling representation. Systemd instance
names are only the process-control fingertip; they never encode a model choice.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from ecosystem import cli, models, resource_control

TARGET = "agent-executors.target"
LANE = re.compile(r"agent-executor@([1-9][0-9]*)\.service\Z")
ACTIVE_STATES = {"claimed", "runner_starting", "running"}
BOUND_STATES = {"runner_starting", "running"}
PENDING_STATES = {"queued", "ready"}
ROUTING_STATES = PENDING_STATES | {"claimed"}


def actionable_jobs(root: Path = cli.ROOT) -> list[dict]:
    jobs = []
    for path in (Path(root) / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (type(job) is dict and job.get("kind") == "agent-task"
                and job.get("state") in ACTIVE_STATES | PENDING_STATES
                and resource_control.job_admitted_in_current_mode(job)):
            jobs.append(job)
    return jobs


def desired_lane_count(jobs: list[dict], inventory: dict | None,
                       process_ceiling: int) -> int:
    """Bound work by validated route slots and a model-neutral process ceiling.

    Existing active work is never killed when observations shrink. If no safe
    route can presently be established, one lane may probe a pending task when
    no worker is already active; the executor still revalidates before launch.
    """
    if not jobs or process_ceiling < 1:
        return 0
    active = sum(job.get("state") in ACTIVE_STATES for job in jobs)
    pending = [job for job in jobs if job.get("state") in ROUTING_STATES
               and not (job.get("state") == "claimed"
                        and type(job.get("cancellation_requested_at")) is str
                        and job["cancellation_requested_at"])]
    capacity_by_model: dict[str, int] = {}
    if inventory is not None:
        active_models = {job.get("model") for job in jobs
                         if job.get("state") in BOUND_STATES
                         and type(job.get("model")) is str}
        for model in inventory.get("models", []):
            if type(model) is not dict or model.get("id") not in active_models:
                continue
            slots = model.get("parallel_sequences")
            if (model.get("fresh") is True and model.get("residency_verified") is True
                    and type(slots) is int and slots > 0):
                capacity_by_model[model["id"]] = slots
        for job in pending:
            try:
                decision = models.route(job, inventory)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            slots = decision.get("parallel_sequences")
            model = decision.get("model")
            if (decision.get("valid") is True and type(slots) is int and slots > 0
                    and type(model) is str and model):
                capacity_by_model[model] = max(capacity_by_model.get(model, 0), slots)
    if capacity_by_model:
        # Distinct admitted model pools can progress independently. Realization
        # and per-request leases remain authoritative if their residency later
        # conflicts or an observation becomes stale.
        return max(active, min(len(jobs), sum(capacity_by_model.values()),
                               process_ceiling))
    return active if active else min(1, len(pending), process_ceiling)


def active_lane_ids() -> set[int]:
    result = subprocess.run(
        ["systemctl", "--user", "--plain", "--no-legend", "--no-pager",
         "--type=service", "--state=active,activating", "list-units",
         "agent-executor@*.service"],
        check=True, capture_output=True, text=True)
    ids = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        match = LANE.fullmatch(fields[0]) if fields else None
        if match:
            ids.add(int(match.group(1)))
    return ids


def start_lanes(desired: int) -> None:
    if desired < 1:
        return
    active = active_lane_ids()
    missing = desired - len(active)
    if missing <= 0:
        return
    units = []
    candidate = 1
    while len(units) < missing:
        if candidate not in active:
            units.append(f"agent-executor@{candidate}.service")
        candidate += 1
    subprocess.run(["systemctl", "--user", "start", TARGET], check=True)
    subprocess.run(["systemctl", "--user", "--no-block", "start", *units], check=True)
    print(f"requested {len(units)} executor lanes; desired={desired}, already_active={len(active)}")


def main() -> None:
    if (cli.ROOT / "state/PAUSED").exists():
        print("ecosystem is paused; no executor lanes requested")
        return
    jobs = actionable_jobs()
    if not jobs:
        print("no actionable managed tasks")
        return
    try:
        inventory = models.snapshot()
    except (OSError, ValueError, KeyError, TypeError):
        inventory = None
    ceiling = os.cpu_count() or 1
    desired = desired_lane_count(jobs, inventory, ceiling)
    start_lanes(desired)


if __name__ == "__main__":
    main()
