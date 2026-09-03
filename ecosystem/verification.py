"""Independent semantic verification between process exit and user-visible success."""
from __future__ import annotations

import json
from pathlib import Path

from ecosystem import cli
from ecosystem.models import snapshot


REQUIRED_LISTS = ("claims", "evidence", "checks")


def verdict_path(target_id: str) -> Path:
    return cli.ROOT / "state/verifications" / f"{target_id}.json"


def choose_model(producer_model: str) -> tuple[str, str]:
    inventory = snapshot()
    config = json.loads((cli.ROOT / "config/executor-opencode.json").read_text(encoding="utf-8"))
    configured = set(config.get("provider", {}).get("Lemonade", {}).get("models", {}))
    models = [item for item in inventory.get("models", []) if item.get("id") in configured]
    if not models:
        raise RuntimeError("no verifier-capable model is configured")
    eligible = [item for item in models if item.get("id") != producer_model]
    if not eligible:
        eligible = models
    def score(item: dict) -> tuple[int, int, float]:
        labels = set(item.get("labels", []))
        capability = 2 if "reasoning" in labels else 1 if "coding" in labels else 0
        return capability, int(bool(item.get("loaded"))), float(item.get("size_gb") or 0)
    chosen = max(eligible, key=score)
    reason = ("Independent verification model selected from live inventory; favored "
              "reasoning/coding capability, residency, and useful capacity while avoiding "
              f"the producer model {producer_model!r} where possible.")
    return chosen["id"], reason


def enqueue(target: dict) -> str:
    target_id = target["id"]
    path = verdict_path(target_id)
    model, reason = choose_model(target.get("model", ""))
    task = f"""Verify agent task `{target_id}` independently.

Read its durable job at `{cli.ROOT / 'state/jobs' / (target_id + '.json')}`, exact
prepared prompt, and complete executor log. Inspect relevant artifacts, Git diff,
tests, timestamps, and live state. A clean executor exit is not success. Determine
whether the original assigned task was actually completed and whether every material
claim is current and supported. Do not repair anything.

Write exactly one JSON object to `{path}` with this shape:
{{"accepted": true_or_false, "summary": "plain factual result", "claims": ["..."],
  "evidence": ["reproducible observation"], "checks": ["command or inspection and outcome"]}}
Use `accepted: false` when work is incomplete, misleading, stale, untested where
testing matters, or the evidence is insufficient. Do not omit the verdict file."""
    job_id = cli.enqueue_task("verifier", task, source=f"verification:{target_id}",
                              model=model, model_reason=reason)
    verifier_path = cli.ROOT / "state/jobs" / f"{job_id}.json"
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    verifier["verifies"] = target_id
    cli.atomic_json(verifier_path, verifier)
    cli.audit("verification.queued", target_job_id=target_id, verifier_job_id=job_id, model=model)
    return job_id


def read_verdict(target_id: str) -> tuple[bool, dict | None, str]:
    path = verdict_path(target_id)
    if not path.exists():
        return False, None, "verifier left no verdict"
    try:
        verdict = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return False, None, f"invalid verifier verdict: {type(error).__name__}"
    valid = isinstance(verdict.get("accepted"), bool) and isinstance(verdict.get("summary"), str)
    valid = valid and all(isinstance(verdict.get(key), list) for key in REQUIRED_LISTS)
    if not valid:
        return False, verdict, "verifier verdict did not satisfy its schema"
    return verdict["accepted"], verdict, verdict["summary"].strip()


def finalize(verifier: dict) -> dict:
    target_path = cli.ROOT / "state/jobs" / f"{verifier['verifies']}.json"
    target = json.loads(target_path.read_text(encoding="utf-8"))
    accepted, verdict, summary = read_verdict(target["id"])
    target.update(state="completed" if accepted else "rejected", updated_at=cli.now(),
                  verification_job=verifier["id"], verification_summary=summary,
                  verification=verdict)
    cli.atomic_json(target_path, target)
    cli.audit("verification.accepted" if accepted else "verification.rejected",
              target_job_id=target["id"], verifier_job_id=verifier["id"], summary=summary)
    return target
