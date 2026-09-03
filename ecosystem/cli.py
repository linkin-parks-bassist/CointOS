from __future__ import annotations

import argparse
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
DIRS = ("inbox/new", "inbox/triaged", "projects", "state/jobs", "logs/runs")


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


def enqueue_task(role: str, task: str, source: str = "local-cli", model: str | None = None, model_reason: str = "", agent_name: str | None = None) -> str:
    from ecosystem.roles import load_role
    from ecosystem.models import snapshot, ids, fallback
    from ecosystem.identity import assign

    initialize()
    load_role(role)  # Reject unknown or malformed roles before queueing.
    inventory = snapshot()
    if model is None:
        model, model_reason = fallback(role, inventory)
    if model not in ids(inventory):
        raise ValueError(f"model {model!r} is not locally available")
    agent_name = agent_name or assign(role)
    job_id = f"task-{uuid.uuid4().hex[:16]}"
    job = {
        "id": job_id, "kind": "agent-task", "state": "queued",
        "attempts": 0, "created_at": now(), "updated_at": now(),
        "role": role, "task": task, "source": source, "model": model,
        "model_reason": model_reason or "Explicit caller selection.",
        "resource_snapshot": inventory,
        "agent_name": agent_name,
    }
    atomic_json(ROOT / "state/jobs" / f"{job_id}.json", job)
    audit("task.queued", job_id=job_id, role=role, source=source, model=model, model_reason=job["model_reason"], agent_name=agent_name)
    return job_id


def amend_latest_task(source: str, role: str, task: str, model: str | None = None, model_reason: str = "") -> str | None:
    from ecosystem.roles import load_role
    load_role(role)
    candidates = []
    for path in (ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("kind") == "agent-task" and job.get("source") == source and job.get("state") in {"queued", "ready"}:
            candidates.append((job["created_at"], path, job))
    if not candidates:
        return None
    _, path, job = max(candidates, key=lambda item: item[0])
    prompt = ROOT / job.get("prompt", "") if job.get("prompt") else None
    if prompt:
        prompt.unlink(missing_ok=True)
    job.update(role=role, task=task.strip(), state="queued", updated_at=now())
    if model:
        job.update(model=model, model_reason=model_reason or "Explicit amendment selection.")
    job.pop("prompt", None)
    atomic_json(path, job)
    audit("task.amended", job_id=job["id"], role=role, source=source)
    return job["id"]


def prepare_next() -> None:
    from ecosystem.roles import render_context

    if (ROOT / "state/PAUSED").exists():
        raise SystemExit("ecosystem is paused")
    for path in sorted((ROOT / "state/jobs").glob("*.json")):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("kind") != "agent-task" or job["state"] != "queued":
            continue
        prompt = render_context(job["role"], job["task"], job["id"], job.get("model", "unspecified"), job.get("model_reason", ""), job.get("agent_name", "Agent"))
        prompt_path = ROOT / "state/jobs" / f"{job['id']}.prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        job.update(state="ready", updated_at=now(), prompt=str(prompt_path.relative_to(ROOT)))
        atomic_json(path, job)
        audit("task.ready", job_id=job["id"], role=job["role"], prompt=job["prompt"])
        print(f"{job['id']} ({job.get('agent_name', 'Agent')}) ready with role {job['role']} on {job.get('model', 'legacy-default')}")
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
        state = json.loads(path.read_text(encoding="utf-8"))["state"]
        counts[state] = counts.get(state, 0) + 1
    print(json.dumps({"paused": (ROOT / "state/PAUSED").exists(), "jobs": counts}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="ecosystem")
    parser.add_argument("command", choices=("init", "scan", "run-once", "status", "pause", "resume", "enqueue", "prepare-next", "roles", "tell-david"))
    parser.add_argument("--role", default="worker")
    parser.add_argument("--task")
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
        print(enqueue_task(args.role, args.task))
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
