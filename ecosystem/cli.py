from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRS = ("inbox/new", "inbox/triaged", "projects", "state/jobs", "state/verifications", "logs/runs")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def audit(event: str, **fields: object) -> None:
    path = ROOT / "logs/runs" / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": now(), "event": event, **fields}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def initialize() -> None:
    for relative in DIRS:
        (ROOT / relative).mkdir(parents=True, exist_ok=True)
    print(f"initialized {ROOT}")


def enqueue_task(role: str | None, task: str, source: str = "local-cli", model: str | None = None,
                 model_reason: str = "", agent_name: str | None = None,
                 idempotency_key: str | None = None,
                 prefer_models_other_than: list[str] | None = None,
                 task_contract: dict | None = None) -> str:
    from ecosystem.identity import validate, generate
    from ecosystem.roles import resolve_role
    from ecosystem.task_contracts import resolve_task_intake

    initialize()
    if task_contract is None:
        raise ValueError("executable work requires an explicit task contract")
    intake = resolve_task_intake(task_contract, ROOT)
    validated_contract = intake["task_contract"]
    if type(task) is not str or task.strip() != validated_contract["objective"]:
        raise ValueError("task differs from validated objective")
    job_id = (f"task-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}"
              if idempotency_key else f"task-{uuid.uuid4().hex[:16]}")
    job_path = ROOT / "state/jobs" / f"{job_id}.json"
    lock_path = ROOT / "state/task-enqueue.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if job_path.exists():
            saved = json.loads(job_path.read_text(encoding="utf-8"))
            if not idempotency_key or saved.get("idempotency_key") != idempotency_key:
                raise ValueError("task identifier collision")
            if saved.get("task_contract") != validated_contract:
                raise ValueError("idempotency key reused with a different task contract")
            return job_id
        resolved_role = resolve_role(role) if not agent_name else None
        identity_role = resolved_role["label"] if resolved_role and resolved_role["known"] else "agent"
        agent_name = validate(agent_name) if agent_name else generate(identity_role, task)
        job = {
            "id": job_id, "kind": "agent-task", "state": "queued",
            "attempts": 0, "created_at": now(), "updated_at": now(),
            "agent_generation": 1, "logical_run_state": "active",
            "role": role, "task": task, "source": source, "model": None,
            "model_reason": "Pending model-mediated routing.",
            "requested_model": model,
            "requested_model_reason": model_reason or ("Caller supplied no model preference."
                                                         if model is None else "Caller supplied a model hint."),
            "prefer_models_other_than": prefer_models_other_than or [],
            "agent_name": agent_name,
            "task_contract": validated_contract,
            "remaining_budget": dict(validated_contract["budget"]),
            "authority_profile": intake["authority_profile"],
            "requirements": intake["requirements"],
            "scope": intake["scope"],
            "write_paths": intake["write_paths"],
            "workload_class": intake["workload_class"],
        }
        if idempotency_key:
            job["idempotency_key"] = idempotency_key
        atomic_json(job_path, job)
    audit("task.queued", job_id=job_id, role=role, source=source,
          requested_model=model, requested_model_reason=job["requested_model_reason"],
          agent_name=agent_name)
    return job_id


def enqueue_child(parent_job: dict, child_contract: dict, idempotency_key: str) -> str:
    from ecosystem.identity import generate
    from ecosystem.task_contracts import (BUDGET_FIELDS, narrow_contract,
                                          resolve_task_intake)

    if type(idempotency_key) is not str or not idempotency_key:
        raise ValueError("child enqueue requires an idempotency key")
    parent_id = parent_job.get("id")
    if type(parent_id) is not str or not parent_id:
        raise ValueError("child enqueue requires a parent job identity")
    initialize()
    child_id = f"task-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}"
    child_path = ROOT / "state/jobs" / f"{child_id}.json"
    parent_path = ROOT / "state/jobs" / f"{parent_id}.json"
    lock_path = ROOT / "state/task-enqueue.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not parent_path.exists():
            raise ValueError("parent job does not exist")
        current_parent = json.loads(parent_path.read_text(encoding="utf-8"))
        reservations = current_parent.setdefault("child_reservations", {})
        reservation = reservations.get(idempotency_key)
        if reservation is None:
            validated = narrow_contract(current_parent, child_contract)
        else:
            validated = resolve_task_intake(child_contract, ROOT)["task_contract"]
            if reservation != {"child_job_id": child_id, "task_contract": validated}:
                raise ValueError("child reservation replay changed contract")
        if child_path.exists():
            saved = json.loads(child_path.read_text(encoding="utf-8"))
            if saved.get("idempotency_key") != idempotency_key:
                raise ValueError("child task identifier collision")
            if saved.get("task_contract") != validated:
                raise ValueError("idempotency key reused with a different child contract")
            return child_id
        if validated["parent_job_id"] != parent_id:
            raise ValueError("child names a different parent")
        intake = resolve_task_intake(validated, ROOT)
        if reservation is None:
            remaining = dict(current_parent.get(
                "remaining_budget", current_parent["task_contract"]["budget"]))
            for field in BUDGET_FIELDS[:-1]:
                remaining[field] -= validated["budget"][field]
            remaining["maximum_children"] -= 1 + validated["budget"]["maximum_children"]
            current_parent["remaining_budget"] = remaining
            current_parent["updated_at"] = now()
            reservations[idempotency_key] = {
                "child_job_id": child_id,
                "task_contract": validated,
            }
            atomic_json(parent_path, current_parent)
        child_job = {
            "id": child_id,
            "kind": "agent-task",
            "state": "queued",
            "attempts": 0,
            "created_at": now(),
            "updated_at": now(),
            "agent_generation": 1,
            "logical_run_state": "active",
            "role": None,
            "task": validated["objective"],
            "source": f"child:{parent_id}",
            "model": None,
            "model_reason": "Pending model-mediated routing.",
            "requested_model": None,
            "requested_model_reason": "Caller supplied no model preference.",
            "prefer_models_other_than": [],
            "agent_name": generate("agent", validated["objective"]),
            "task_contract": validated,
            "remaining_budget": dict(validated["budget"]),
            "authority_profile": intake["authority_profile"],
            "requirements": intake["requirements"],
            "scope": intake["scope"],
            "write_paths": intake["write_paths"],
            "workload_class": intake["workload_class"],
            "idempotency_key": idempotency_key,
        }
        atomic_json(child_path, child_job)
    audit("task.child_queued", job_id=child_id, parent_job_id=parent_id,
          source_key=validated["source_key"])
    return child_id


def amend_latest_task(source: str, role: str | None, task: str, model: str | None = None,
                      model_reason: str = "", idempotency_key: str | None = None,
                      task_contract: dict | None = None) -> str | None:
    from ecosystem.task_contracts import resolve_task_intake

    if task_contract is None:
        raise ValueError("amended executable work requires an explicit task contract")
    intake = resolve_task_intake(task_contract, ROOT)
    validated_contract = intake["task_contract"]
    if type(task) is not str or task.strip() != validated_contract["objective"]:
        raise ValueError("task differs from validated objective")
    candidates = []
    for path in (ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if idempotency_key in job.get("amendment_keys", []):
            return job["id"]
        if job.get("kind") == "agent-task" and job.get("source") == source and job.get("state") in {"queued", "ready"}:
            candidates.append((job["created_at"], path, job))
    if not candidates:
        return None
    _, path, job = max(candidates, key=lambda item: item[0])
    prompt = ROOT / job.get("prompt", "") if job.get("prompt") else None
    if prompt:
        prompt.unlink(missing_ok=True)
    job.update(role=role, task=task.strip(), task_contract=validated_contract,
               remaining_budget=dict(validated_contract["budget"]),
               authority_profile=intake["authority_profile"],
               requirements=intake["requirements"], scope=intake["scope"],
               write_paths=intake["write_paths"], workload_class=intake["workload_class"],
               state="queued", updated_at=now())
    if model is not None:
        job.update(requested_model=model,
                   requested_model_reason=model_reason or "Caller supplied an amended model hint.")
    job.update(model=None, model_reason="Pending model-mediated routing.")
    if idempotency_key:
        job.setdefault("amendment_keys", []).append(idempotency_key)
    job.pop("prompt", None)
    atomic_json(path, job)
    audit("task.amended", job_id=job["id"], role=role, source=source)
    return job["id"]


def prepare_next() -> None:
    from ecosystem.roles import render_context
    from ecosystem.models import route, snapshot
    from ecosystem.resource_control import job_admitted_in_current_mode
    from ecosystem.scheduler import priority, scheduling_document

    if (ROOT / "state/PAUSED").exists():
        raise SystemExit("ecosystem is paused")
    queued = []
    for path in (ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if (job.get("kind") == "agent-task" and job["state"] == "queued"
                and job_admitted_in_current_mode(job)):
            queued.append((path, job))
    scheduling = scheduling_document(ROOT)
    for path, job in sorted(queued, key=lambda item: (-priority(item[1], scheduling), item[1]["created_at"])):
        inventory = snapshot()
        decision = route(job, inventory)
        job.setdefault("routing_decisions", []).append({"at": now(), **decision})
        job["resource_snapshot"] = inventory
        if decision["action"] == "defer":
            job.update(updated_at=now(), model=None, model_reason=decision["reason"])
            atomic_json(path, job)
            audit("task.routing_deferred", job_id=job["id"], reason=decision["reason"])
            print(f"{job['id']} routing deferred: {decision['reason']}")
            return
        job.update(model=decision["model"], model_reason=decision["reason"],
                   context_tokens=decision["context_tokens"])
        prompt = render_context(job.get("role"), job["task"], job["id"], job.get("model", "unspecified"), job.get("model_reason", ""), job.get("agent_name", "Agent"), job.get("task_contract"))
        prompt_path = ROOT / "state/jobs" / f"{job['id']}.prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        job.update(state="ready", updated_at=now(), prompt=str(prompt_path.relative_to(ROOT)))
        job.setdefault("original_prompt", job["prompt"])
        atomic_json(path, job)
        audit("task.ready", job_id=job["id"], role=job.get("role"), prompt=job["prompt"])
        role_label = job.get("role") or "unassigned"
        print(f"{job['id']} ({job.get('agent_name', 'Agent')}) ready with role {role_label} on {job.get('model', 'legacy-default')}")
        return
    print("no queued agent task")


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:60] or "untitled"


def title_of(text: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else fallback.replace("-", " ").title()


def scan() -> int:
    initialize()
    count = 0
    for source in sorted((ROOT / "inbox/new").glob("*.md")):
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        job_id = f"idea-{digest[:16]}"
        job_path = ROOT / "state/jobs" / f"{job_id}.json"
        if job_path.exists():
            continue
        job = {
            "id": job_id,
            "kind": "idea-intake",
            "state": "queued",
            "attempts": 0,
            "created_at": now(),
            "updated_at": now(),
            "input": str(source.relative_to(ROOT)),
            "input_sha256": digest,
        }
        atomic_json(job_path, job)
        audit("job.queued", job_id=job_id, input=job["input"], sha256=digest)
        count += 1
    return count


def questions(text: str) -> list[str]:
    lowered = text.lower()
    checks = (
        (("success", "done", "outcome"), "What observable result would make this idea done?"),
        (("constraint", "must", "cannot", "can't"), "What constraints or non-negotiables apply?"),
        (("user", "audience", "customer"), "Who is the first intended user?"),
    )
    return [question for terms, question in checks if not any(term in lowered for term in terms)]


def process(job_path: Path) -> None:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job["state"] not in {"queued", "failed"}:
        return
    job["state"] = "running"
    job["attempts"] += 1
    job["updated_at"] = now()
    atomic_json(job_path, job)
    audit("job.started", job_id=job["id"], attempt=job["attempts"], role="intake")
    try:
        source = ROOT / job["input"]
        raw = source.read_text(encoding="utf-8")
        if hashlib.sha256(source.read_bytes()).hexdigest() != job["input_sha256"]:
            raise ValueError("input changed after it was queued")
        title = title_of(raw, source.stem)
        project = ROOT / "projects" / f"{slug(title)}-{job['input_sha256'][:8]}"
        project.mkdir(parents=True, exist_ok=True)
        qs = questions(raw)
        proposal = (
            f"# {title}\n\n## Source idea\n\n{raw.strip()}\n\n"
            "## Intake assessment\n\n"
            "Status: proposal; no implementation has been authorized or started.\n\n"
            "## Clarifications\n\n"
            + ("\n".join(f"- [ ] {q}" for q in qs) if qs else "No obvious clarification gaps detected; human review is still required.")
            + "\n\n## Proposed next action\n\nReview the scope and answer the clarification items, then approve or revise a small first work unit.\n"
        )
        (project / "README.md").write_text(proposal, encoding="utf-8")
        (project / "status.md").write_text(
            f"# Status\n\n- State: awaiting review\n- Intake job: `{job['id']}`\n- Updated: {now()}\n",
            encoding="utf-8",
        )
        destination = ROOT / "inbox/triaged" / source.name
        if source.exists() and not destination.exists():
            shutil.move(source, destination)
        job.update(state="awaiting_review", updated_at=now(), project=str(project.relative_to(ROOT)))
        atomic_json(job_path, job)
        audit("job.awaiting_review", job_id=job["id"], project=job["project"], questions=len(qs))
        print(f"{job['id']} -> {job['project']}")
    except Exception as error:
        job.update(state="failed", updated_at=now(), error=f"{type(error).__name__}: {error}")
        atomic_json(job_path, job)
        audit("job.failed", job_id=job["id"], error=job["error"])
        raise


def run_once() -> None:
    initialize()
    if (ROOT / "state/PAUSED").exists():
        print("ecosystem is paused", file=sys.stderr)
        raise SystemExit(75)
    from ecosystem.resource_control import dispatch_halted
    if dispatch_halted():
        print("ordinary intake is halted by resource control")
        return
    queued = scan()
    processed = 0
    for path in sorted((ROOT / "state/jobs").glob("*.json")):
        queued_job = json.loads(path.read_text(encoding="utf-8"))
        if queued_job.get("kind") == "idea-intake" and queued_job["state"] == "queued":
            process(path)
            processed += 1
    print(f"queued={queued} processed={processed}")


def status() -> None:
    initialize()
    counts: dict[str, int] = {}
    for path in (ROOT / "state/jobs").glob("*.json"):
        if path.name.endswith(".opencode.json"):
            continue
        state = json.loads(path.read_text(encoding="utf-8"))["state"]
        counts[state] = counts.get(state, 0) + 1
    print(json.dumps({"paused": (ROOT / "state/PAUSED").exists(), "jobs": counts}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="ecosystem")
    parser.add_argument("command", choices=("init", "scan", "run-once", "status", "pause", "resume", "enqueue", "prepare-next", "roles", "tell-david"))
    parser.add_argument("--role", default="worker")
    parser.add_argument("--task")
    parser.add_argument("--task-contract")
    parser.add_argument("--model")
    parser.add_argument("--model-reason", default="")
    parser.add_argument("--agent-name")
    parser.add_argument("--message")
    parser.add_argument("--severity", choices=("info", "warning", "question", "approval"), default="info")
    parser.add_argument("--needs-response", action="store_true")
    args = parser.parse_args()
    if args.command == "init": initialize()
    elif args.command == "scan": print(f"queued={scan()}")
    elif args.command == "run-once": run_once()
    elif args.command == "status": status()
    elif args.command == "pause":
        initialize(); (ROOT / "state/PAUSED").touch(); audit("ecosystem.paused"); print("paused")
    elif args.command == "resume":
        (ROOT / "state/PAUSED").unlink(missing_ok=True); audit("ecosystem.resumed"); print("resumed")
    elif args.command == "enqueue":
        if not args.task:
            parser.error("enqueue requires --task")
        if not args.task_contract:
            parser.error("enqueue requires --task-contract")
        task_contract = json.loads(Path(args.task_contract).read_text(encoding="utf-8"))
        print(enqueue_task(args.role, args.task, model=args.model,
                           model_reason=args.model_reason, agent_name=args.agent_name,
                           task_contract=task_contract))
    elif args.command == "prepare-next": prepare_next()
    elif args.command == "roles":
        from ecosystem.roles import list_roles
        print("\n".join(list_roles()))
    elif args.command == "tell-david":
        from ecosystem.outbox import enqueue
        if not args.message: parser.error("tell-david requires --message")
        origin = os.environ.get("AGENT_JOB_ID")
        recipients = [v for v in os.environ.get("AGENT_TELEGRAM_ALLOWED_USER_IDS", "").split(",") if v.strip()]
        if not recipients: raise SystemExit("no configured Telegram recipient")
        for recipient in recipients:
            print(enqueue(int(recipient), message=args.message, origin_job=origin, severity=args.severity, needs_response=args.needs_response))


if __name__ == "__main__":
    main()
