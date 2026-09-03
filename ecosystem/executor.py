"""Serialized local OpenCode executor for prepared role-context jobs."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path

from ecosystem import cli


def queue_notifications(job: dict) -> None:
    from ecosystem.outbox import enqueue
    recipients = [value for value in os.environ.get("AGENT_TELEGRAM_ALLOWED_USER_IDS", "").split(",") if value.strip()]
    for recipient in recipients:
        enqueue(int(recipient), depends_on=job["id"], result_of=job["id"])


def execute_next(run=subprocess.run) -> bool:
    cli.initialize()
    if (cli.ROOT / "state/PAUSED").exists():
        print("ecosystem is paused")
        return False
    lock_path = cli.ROOT / "state/executor.lock"
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("executor already active")
            return False
        for path in sorted((cli.ROOT / "state/jobs").glob("*.json")):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("kind") != "agent-task" or job["state"] != "ready":
                continue
            prompt_path = cli.ROOT / job["prompt"]
            output_path = cli.ROOT / "logs/runs" / f"{job['id']}.opencode.log"
            job.update(state="running", attempts=job["attempts"] + 1, updated_at=cli.now(), output=str(output_path.relative_to(cli.ROOT)))
            cli.atomic_json(path, job)
            cli.audit("task.started", job_id=job["id"], role=job["role"], executor="opencode")
            env = os.environ.copy()
            env["OPENCODE_CONFIG"] = str(cli.ROOT / "config/executor-opencode.json")
            selected = job.get("model") or env.get("AGENT_EXECUTOR_MODEL", "GLM-4.7-Flash-GGUF")
            model = selected if "/" in selected else f"Lemonade/{selected}"
            command = [str(Path.home() / ".local/bin/opencode"), "run", "--auto", "--model", model, "--dir", str(Path.home())]
            try:
                with prompt_path.open("rb") as prompt, output_path.open("wb") as output:
                    result = run(command, stdin=prompt, stdout=output, stderr=subprocess.STDOUT, env=env, timeout=1800)
                job.update(state="completed" if result.returncode == 0 else "failed", updated_at=cli.now(), exit_code=result.returncode)
            except subprocess.TimeoutExpired:
                job.update(state="failed", updated_at=cli.now(), error="executor timed out after 1800 seconds")
            except Exception as error:
                job.update(state="failed", updated_at=cli.now(), error=f"{type(error).__name__}: {error}")
            cli.atomic_json(path, job)
            cli.audit(f"task.{job['state']}", job_id=job["id"], output=job["output"], exit_code=job.get("exit_code"))
            queue_notifications(job)
            print(f"{job['id']} {job['state']}")
            return True
    print("no ready task")
    return False


if __name__ == "__main__": execute_next()
