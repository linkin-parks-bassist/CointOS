"""Independent semantic verification between process exit and user-visible success."""
from __future__ import annotations

import json
import fcntl
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
testing matters, or the evidence is insufficient. For `accepted: true`, provide
a nonblank summary and at least one nonblank string in each of `claims`,
`evidence`, and `checks`. Do not omit the verdict file."""
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
    job_id = cli.enqueue_task("manager", task, source=f"verification:{target_id}",
                              idempotency_key=f"verification:{target_id}",
                              prefer_models_other_than=[target.get("model", "")],
                              task_contract=contract,
                              verifies_target_id=target_id)
    verifier_path = cli.ROOT / "state/jobs" / f"{job_id}.json"
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
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
    if type(verdict) is not dict:
        return False, None, "verifier verdict did not satisfy its schema"
    summary = verdict.get("summary")
    valid = (type(verdict.get("accepted")) is bool
             and type(summary) is str and bool(summary.strip()))
    valid = valid and all(
        type(verdict.get(key)) is list
        and all(type(item) is str and bool(item.strip())
                for item in verdict[key])
        for key in REQUIRED_LISTS)
    if not valid:
        return False, verdict, "verifier verdict did not satisfy its schema"
    if verdict["accepted"] and any(not verdict[key] for key in REQUIRED_LISTS):
        return False, verdict, "accepted verifier verdict lacks claims, evidence, or checks"
    return verdict["accepted"], verdict, summary.strip()


def finalize(verifier: dict) -> dict:
    from ecosystem.outbox import result_recipients
    verifier_state = verifier.get("state")
    if verifier_state not in {"run_finished", "completed", "failed"}:
        raise ValueError("verifier runner has no terminal outcome")
    target_path = cli.ROOT / "state/jobs" / f"{verifier['verifies']}.json"
    lock_path = cli.ROOT / "state/verification-finalize.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = json.loads(target_path.read_text(encoding="utf-8"))
        if target.get("verification_job") == verifier["id"] \
                and target.get("state") in {"completed", "rejected"}:
            return target
        if target.get("state") != "awaiting_verification":
            raise ValueError("verifier target is not awaiting verification")
        target.setdefault("result_notification_recipients", result_recipients())
        accepted, verdict, summary = read_verdict(target["id"])
        if verifier_state == "failed":
            if accepted:
                verdict = {**verdict, "accepted": False}
                summary = "verifier runner failed; accepted verdict ignored"
            else:
                summary = f"verifier runner failed; {summary}"
            accepted = False
        target.update(state="completed" if accepted else "rejected", updated_at=cli.now(),
                      verification_job=verifier["id"], verification_summary=summary,
                      verification=verdict)
        cli.atomic_json(target_path, target)
    cli.audit("verification.accepted" if accepted else "verification.rejected",
              target_job_id=target["id"], verifier_job_id=verifier["id"], summary=summary)
    return target
