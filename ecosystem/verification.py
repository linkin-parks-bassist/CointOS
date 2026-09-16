"""Independent semantic verification between process exit and user-visible success."""
from __future__ import annotations

import json
from pathlib import Path

from ecosystem import cli


REQUIRED_LISTS = ("claims", "evidence", "checks")


def verdict_path(target_id: str) -> Path:
    return cli.ROOT / "state/verifications" / f"{target_id}.json"


def enqueue(target: dict) -> str:
    target_id = target["id"]
    path = verdict_path(target_id)
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
    root = cli.ROOT.resolve()
    contract = {
        "objective": task,
        "scope": {"workspace": str(root), "read_paths": [str(root)],
                  "write_paths": [str(path.resolve(strict=False))]},
        "authority_profile": "independent_verification",
        "requirements": {"required_capabilities": ["reasoning", "tool-calling"],
                         "minimum_context_tokens": 16384},
        "acceptance": [{"kind": "artifact", "path": str(path.resolve(strict=False))}],
        "budget": {"run_seconds": None, "task_seconds": None, "maximum_attempts": None,
                   "maximum_output_bytes": None, "maximum_evidence_items": None,
                   "maximum_children": 0},
        "source_key": f"verification:{target_id}", "parent_job_id": target_id,
        "stop_condition": "Stop after one schema-valid evidence-backed verdict.",
    }
    job_id = cli.enqueue_task("verifier", task, source=f"verification:{target_id}",
                              prefer_models_other_than=[target.get("model", "")],
                              task_contract=contract)
    verifier_path = cli.ROOT / "state/jobs" / f"{job_id}.json"
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    verifier["verifies"] = target_id
    cli.atomic_json(verifier_path, verifier)
    cli.audit("verification.queued", target_job_id=target_id, verifier_job_id=job_id,
              prefer_models_other_than=verifier.get("prefer_models_other_than", []))
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
