"""Serialized local OpenCode executor for prepared role-context jobs."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import re
from pathlib import Path

from ecosystem import cli


def notify(job: dict) -> None:
    token = os.environ.get("AGENT_TELEGRAM_BOT_TOKEN")
    recipients = [value for value in os.environ.get("AGENT_TELEGRAM_ALLOWED_USER_IDS", "").split(",") if value.strip()]
    if not token:
        return
    from ecosystem.telegram import reply
    summary = f"Job {job['id']} {job['state']} ({job['role']}).\nLog: {job.get('output', 'none')}"
    output_path = cli.ROOT / job["output"] if job.get("output") else None
    if output_path and output_path.exists():
        clean = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", output_path.read_text(encoding="utf-8", errors="replace")).strip()
        if clean:
            summary += "\n\nResult (tail):\n" + clean[-3000:]
    for recipient in recipients:
        try:
            reply(token, int(recipient), summary)
        except Exception as error:
            cli.audit("telegram.notification_failed", job_id=job["id"], error=f"{type(error).__name__}: {error}")


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
            model = env.get("AGENT_EXECUTOR_MODEL", "Lemonade/GLM-4.7-Flash-GGUF")
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
            notify(job)
            print(f"{job['id']} {job['state']}")
            return True
    print("no ready task")
    return False


if __name__ == "__main__": execute_next()
