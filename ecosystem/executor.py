"""Serialized local OpenCode executor for prepared role-context jobs."""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from ecosystem import cli
from ecosystem.inference_proxy import issue_proxy_credential, opencode_environment
from ecosystem.models import realize, route, snapshot
from ecosystem.scheduler import choose, policy as scheduling_policy, priority
from ecosystem.resource_control import job_admitted_in_current_mode, mode as resource_mode, opencode_session_id


_GATED_EXEC_WRAPPER = r"""
import os
import sys

gate_fd = int(sys.argv[1])
child_argv = sys.argv[2:]
try:
    release = os.read(gate_fd, 1)
finally:
    os.close(gate_fd)
if release != b"\x01":
    os._exit(125)
os.execvpe(child_argv[0], child_argv, os.environ)
"""


def process_identity(pid: int) -> dict:
    """Read the kernel identity needed to distinguish a process from PID reuse."""
    if type(pid) is not int or pid <= 0:
        raise ValueError("pid must be a positive integer")
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    fields_after_command = stat.rsplit(")", 1)[1].split()
    if len(fields_after_command) <= 19:
        raise ValueError(f"malformed /proc/{pid}/stat")
    identity = {
        "pid": pid,
        "pgid": int(fields_after_command[2]),
        "start_ticks": int(fields_after_command[19]),
    }
    if identity["pgid"] <= 0 or identity["start_ticks"] <= 0:
        raise ValueError(f"invalid /proc/{pid}/stat identity")
    return identity


def _close_record_fd(record: dict, field: str) -> None:
    fd = record.get(field, -1)
    record[field] = -1
    if type(fd) is int and fd >= 0:
        try:
            os.close(fd)
        except OSError as error:
            if error.errno != 9:
                raise


def gated_child_launch(config_fd: int, child_argv: list[str], child_env: dict,
                       *, stdin=None, stdout=None, stderr=None,
                       popen=subprocess.Popen) -> dict:
    """Take config_fd and spawn a wrapper which cannot exec before release."""
    if type(config_fd) is not int or config_fd < 0:
        raise ValueError("config_fd must be an open file descriptor")
    if (type(child_argv) is not list or not child_argv
            or any(type(argument) is not str for argument in child_argv)):
        os.close(config_fd)
        raise ValueError("child_argv must be a non-empty list of strings")
    if (type(child_env) is not dict
            or any(type(key) is not str or type(value) is not str
                   for key, value in child_env.items())):
        os.close(config_fd)
        raise ValueError("child_env must contain string keys and values")

    gate_read_fd, gate_write_fd = os.pipe()
    process = None
    record = None
    try:
        process = popen(
            [sys.executable, "-c", _GATED_EXEC_WRAPPER,
             str(gate_read_fd), *child_argv],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=child_env,
            pass_fds=(config_fd, gate_read_fd),
            start_new_session=True,
            close_fds=True,
        )
        os.close(gate_read_fd)
        gate_read_fd = -1
        identity = process_identity(process.pid)
        if identity["pgid"] != process.pid:
            raise RuntimeError("gated child did not establish its own process group")
        record = {
            "process": process,
            **identity,
            "gate_write_fd": gate_write_fd,
            "config_fd": config_fd,
            "state": "blocked",
            "outcome": None,
        }
        return record
    except Exception:
        if gate_read_fd >= 0:
            os.close(gate_read_fd)
        if record is None and process is not None:
            record = {
                "process": process,
                "pid": process.pid,
                "start_ticks": None,
                "pgid": process.pid,
                "gate_write_fd": gate_write_fd,
                "config_fd": config_fd,
                "state": "blocked",
                "outcome": None,
            }
        if record is not None:
            gated_child_cleanup(record, 0.2)
        else:
            os.close(gate_write_fd)
            os.close(config_fd)
        raise


def gated_child_release(record: dict) -> dict:
    """Release a blocked wrapper after its caller has durably authorized launch."""
    if record.get("state") in {"gate_released", "reaped"}:
        return record
    if record.get("state") != "blocked":
        raise RuntimeError(f"cannot release gated child in state {record.get('state')!r}")
    identity = process_identity(record["pid"])
    if (identity["start_ticks"] != record["start_ticks"]
            or identity["pgid"] != record["pgid"]):
        raise RuntimeError("gated child identity changed before release")
    try:
        written = os.write(record["gate_write_fd"], b"\x01")
        if written != 1:
            raise RuntimeError("gate release was incomplete")
        record["state"] = "gate_released"
    finally:
        _close_record_fd(record, "gate_write_fd")
        _close_record_fd(record, "config_fd")
    return record


def _reaped_outcome(record: dict, returncode: int) -> dict:
    outcome = {
        "state": "reaped",
        "returncode": returncode,
        "pid": record["pid"],
        "start_ticks": record["start_ticks"],
    }
    record["state"] = "reaped"
    record["outcome"] = outcome
    return outcome


def gated_child_wait(record: dict, timeout: float) -> dict:
    """Wait a bounded interval for a released child and cache the reap result."""
    if record.get("outcome") is not None:
        return record["outcome"]
    returncode = record["process"].wait(timeout=timeout)
    _close_record_fd(record, "gate_write_fd")
    _close_record_fd(record, "config_fd")
    return _reaped_outcome(record, returncode)


def gated_child_cleanup(record: dict, timeout: float = 0.2) -> dict:
    """Cancel, terminate, and reap an owned gated child within bounded waits."""
    if record.get("outcome") is not None:
        return record["outcome"]
    _close_record_fd(record, "gate_write_fd")
    process = record["process"]
    returncode = process.poll()
    if returncode is None:
        identity_matches = False
        try:
            identity = process_identity(record["pid"])
            identity_matches = (
                record.get("start_ticks") in {None, identity["start_ticks"]}
                and identity["pgid"] == record["pgid"]
            )
        except FileNotFoundError:
            pass
        if identity_matches:
            try:
                os.killpg(record["pgid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if identity_matches:
                try:
                    os.killpg(record["pgid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _close_record_fd(record, "config_fd")
                outcome = {
                    "state": "reconciliation_required",
                    "returncode": None,
                    "pid": record["pid"],
                    "start_ticks": record.get("start_ticks"),
                }
                record["state"] = outcome["state"]
                record["outcome"] = outcome
                return outcome
    _close_record_fd(record, "config_fd")
    return _reaped_outcome(record, returncode)


def queue_notifications(job: dict) -> None:
    from ecosystem.outbox import enqueue
    for path in (cli.ROOT / "state/jobs").glob("outbox-*.json"):
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("result_of") == job["id"] and existing.get("state") != "delivered":
            return
    recipients = [value for value in os.environ.get("AGENT_TELEGRAM_ALLOWED_USER_IDS", "").split(",") if value.strip()]
    for recipient in recipients:
        enqueue(int(recipient), depends_on=job["id"], result_of=job["id"])


def _process_alive(job: dict) -> bool:
    pid = job.get("executor_pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
    marker = f"agent-job:{job.get('id', '')}".encode()
    for command_path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if marker in command_path.read_bytes():
                return True
        except OSError:
            continue
    return False


def recover_abandoned_jobs() -> int:
    recovered = 0
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("kind") != "agent-task" or job.get("state") != "running" or _process_alive(job):
            continue
        output = cli.ROOT / job.get("output", "")
        session = job.get("opencode_session") or opencode_session_id(output)
        previous_model = job.get("model")
        if previous_model and not job.get("requested_model"):
            job["requested_model"] = previous_model
            job["requested_model_reason"] = "Recovered hint from an abandoned legacy dispatch."
        if session:
            job["opencode_session"] = session
            job["resume_available"] = True
        else:
            job["resume_available"] = False
        job.pop("executor_pid", None)
        job.update(state="queued", model=None, model_reason="Pending model-mediated routing.",
                   updated_at=cli.now(), abandoned_dispatch_recovered_at=cli.now())
        cli.atomic_json(path, job)
        cli.audit("task.abandoned_dispatch_recovered", job_id=job["id"],
                  resume_available=bool(session))
        recovered += 1
    return recovered


def opencode_context_usage(output_path: Path, session: str | None = None) -> dict | None:
    latest = None
    try:
        with output_path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "step_finish":
                    continue
                if session and event.get("sessionID") != session:
                    continue
                tokens = event.get("part", {}).get("tokens", {})
                total = tokens.get("total")
                if isinstance(total, int):
                    latest = {
                        "session": event.get("sessionID"),
                        "total_tokens": total,
                        "input_tokens": tokens.get("input"),
                        "output_tokens": tokens.get("output"),
                    }
    except OSError:
        return None
    return latest


def _job_opencode_config(job: dict, credential: bytes) -> dict:
    lease = job.get("inference_lease")
    if type(lease) is not dict:
        raise ValueError("OpenCode launch requires an authoritative inference lease")
    return opencode_environment(cli.ROOT, lease, credential)


def _waiting_jobs(running_id: str) -> list[dict]:
    waiting = []
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (job.get("id") != running_id and job.get("kind") == "agent-task"
                and job.get("state") in {"queued", "ready"}
                and job_admitted_in_current_mode(job)):
            waiting.append(job)
    return waiting


def _preemption_reason(job: dict, started: float) -> str | None:
    waiting = _waiting_jobs(job["id"])
    if not waiting:
        return None
    strongest = max(waiting, key=priority)
    if priority(strongest) > priority(job):
        return (f"higher-priority job {strongest['id']} is waiting "
                f"({priority(strongest)} > {priority(job)})")
    quantum = float(scheduling_policy()["workers"]["time_slice_seconds"])
    if time.monotonic() - started >= quantum:
        return f"{quantum:.0f}-second time slice expired while other work is waiting"
    return None


def _stop_process(process: subprocess.Popen, grace_seconds: float) -> None:
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=5)


def _run_preemptibly(command: list[str], prompt, output, env: dict,
                     job: dict, path: Path, output_path: Path,
                     pass_fds: tuple[int, ...]) -> dict:
    settings = scheduling_policy()["workers"]
    process = subprocess.Popen(
        command, stdin=prompt, stdout=output, stderr=subprocess.STDOUT,
        env=env, pass_fds=pass_fds, start_new_session=True,
    )
    job.update(executor_pid=process.pid, last_started_at=cli.now(),
               dispatch_count=int(job.get("dispatch_count", 0)) + 1)
    cli.atomic_json(path, job)
    started = time.monotonic()
    timeout = float(settings["max_job_seconds"])
    while process.poll() is None:
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            _stop_process(process, float(settings["preemption_grace_seconds"]))
            raise subprocess.TimeoutExpired(command, timeout)
        context_usage = opencode_context_usage(output_path, job.get("opencode_session"))
        context_limit = int(job.get("context_tokens") or 0)
        rollover_fraction = float(settings["context_rollover_fraction"])
        context_rollover = bool(
            not job.get("handoff_pending") and context_usage and context_limit
            and context_usage["total_tokens"] >= context_limit * rollover_fraction
        )
        reason = (f"context reached {context_usage['total_tokens']}/{context_limit} tokens "
                  f"({rollover_fraction:.0%}); durable handoff required"
                  if context_rollover else _preemption_reason(job, started))
        if reason:
            session = job.get("opencode_session") or opencode_session_id(output_path)
            # Give OpenCode a short initial window to publish its durable session id.
            if session or elapsed >= float(settings["preemption_grace_seconds"]):
                _stop_process(process, float(settings["preemption_grace_seconds"]))
                session = session or opencode_session_id(output_path)
                return {"returncode": process.returncode, "preempted": True,
                        "reason": reason, "session": session,
                        "context_rollover": context_rollover,
                        "context_usage": context_usage,
                        "elapsed_seconds": round(elapsed, 3)}
        time.sleep(1)
    return {"returncode": process.returncode, "preempted": False,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def execute_next(run=subprocess.run) -> bool:
    cli.initialize()
    recover_abandoned_jobs()
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
        ready = []
        for path in sorted((cli.ROOT / "state/jobs").glob("*.json")):
            job = json.loads(path.read_text(encoding="utf-8"))
            if (job.get("kind") == "agent-task" and job["state"] == "ready"
                    and job_admitted_in_current_mode(job)):
                ready.append((path, job))
        if ready:
            try:
                inventory = snapshot()
                path, job, scheduling_reason = choose(ready, inventory)
            except RuntimeError as error:
                cli.audit("scheduler.admission_deferred", reason=str(error))
                print(str(error))
                return False
            if resource_mode() == "emergency":
                emergency = json.loads((cli.ROOT / "config/resource-policy.json").read_text(
                    encoding="utf-8"))["emergency"]
                decision = {
                    "action": "use_loaded", "model": emergency["chat_model"],
                    "context_tokens": emergency["chat_context_tokens"], "valid": True,
                    "reason": "Emergency policy mechanically assigns the sole survivor model.",
                }
            else:
                decision = route(job, inventory)
            job.setdefault("routing_decisions", []).append({"at": cli.now(), **decision})
            job["resource_snapshot"] = inventory
            if decision["action"] == "defer":
                job.update(state="queued", model=None, model_reason=decision["reason"],
                           updated_at=cli.now())
                job.pop("prompt", None)
                cli.atomic_json(path, job)
                cli.audit("task.routing_deferred", job_id=job["id"], reason=decision["reason"])
                print(f"{job['id']} routing deferred: {decision['reason']}")
                return False
            model_changed = decision["model"] != job.get("model")
            if model_changed:
                from ecosystem.roles import render_context
                job.update(model=decision["model"], model_reason=decision["reason"])
                if not job.get("handoff_pending") and not job.get("fresh_context_after_handoff"):
                    prompt_path = cli.ROOT / "state/jobs" / f"{job['id']}.prompt.md"
                    cli.atomic_text(prompt_path, render_context(
                        job.get("role"), job["task"], job["id"], job["model"],
                        job["model_reason"], job.get("agent_name", "Agent")))
                    job["prompt"] = str(prompt_path.relative_to(cli.ROOT))
                    job.setdefault("original_prompt", job["prompt"])
            else:
                job["model_reason"] = decision["reason"]
            try:
                realization = realize(decision, inventory)
            except Exception as error:
                reason = f"model route could not be realized safely: {type(error).__name__}: {error}"
                job.update(state="queued", model=None, model_reason=reason, updated_at=cli.now())
                job.pop("prompt", None)
                cli.atomic_json(path, job)
                cli.audit("task.routing_deferred", job_id=job["id"], reason=reason)
                print(f"{job['id']} routing deferred: {reason}")
                return False
            job["model_realization"] = {"at": cli.now(), **realization}
            job["context_tokens"] = int(decision["context_tokens"])
            job["scheduling_reason"] = scheduling_reason
            prompt_path = cli.ROOT / job["prompt"]
            output_path = cli.ROOT / "logs/runs" / f"{job['id']}.opencode.log"
            job.update(state="running", attempts=job["attempts"] + 1,
                       updated_at=cli.now(), output=str(output_path.relative_to(cli.ROOT)))
            cli.atomic_json(path, job)
            cli.audit("task.started", job_id=job["id"], role=job.get("role"), executor="opencode")
            try:
                credentials = []
                issue_proxy_credential(
                    cli.ROOT, job.get("inference_lease"), credentials.append, time.monotonic)
                opencode = _job_opencode_config(job, credentials.pop())
            except Exception as error:
                job.update(state="failed", updated_at=cli.now(),
                           error=f"inference launch refused: {type(error).__name__}: {error}")
                cli.atomic_json(path, job)
                cli.audit("task.inference_launch_refused", job_id=job["id"], error=job["error"])
                return True
            env = os.environ.copy()
            env.update(opencode["environment"])
            env["AGENT_JOB_ID"] = job["id"]
            selected = job.get("model") or env.get("AGENT_EXECUTOR_MODEL", "Qwen3.5-4B-GGUF")
            model = selected if "/" in selected else f"Lemonade/{selected}"
            command = [str(Path.home() / ".local/bin/opencode"), "run", "--auto",
                       "--format", "json", "--title", f"agent-job:{job['id']}",
                       "--model", model, "--dir", str(Path.home())]
            resume_session = job.get("opencode_session")
            if resume_session:
                command.extend(["--session", resume_session])
                if job.get("handoff_pending"):
                    handoff_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff.md"
                    request_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff-request.md"
                    cli.atomic_text(request_path, f"""The context reached the 75 percent rollover threshold.
Do not continue the main task. Write a concise, sufficient handoff to `{handoff_path}`.
Record the objective, authoritative instructions, decisions and rationale, exact completed
work, changed files, tests and evidence, unresolved risks, and the next concrete action.
Distinguish verified facts from assumptions. This artifact will seed a fresh context.
""")
                    prompt_path = request_path
                else:
                    resume_path = cli.ROOT / "state/jobs" / f"{job['id']}.resume.md"
                    cli.atomic_text(
                        resume_path,
                        "Resume this exact task after a scheduler or resource interruption. "
                        "Re-read the original prepared prompt and current filesystem state, "
                        "verify what was durably completed, then continue from the last safe "
                        "boundary without duplicating finished work.\n",
                    )
                    prompt_path = resume_path
            try:
                output_mode = "ab" if resume_session else "wb"
                with prompt_path.open("rb") as prompt, output_path.open(output_mode) as output:
                    if run is subprocess.run:
                        outcome = _run_preemptibly(
                            command, prompt, output, env, job, path, output_path,
                            opencode["pass_fds"])
                        if outcome["preempted"]:
                            current = json.loads(path.read_text(encoding="utf-8"))
                            if current.get("state") == "interrupted":
                                print(f"{job['id']} interrupted by resource control")
                                return True
                            if outcome.get("session"):
                                job["opencode_session"] = outcome["session"]
                                job["resume_available"] = True
                            else:
                                job["resume_available"] = False
                            job.pop("executor_pid", None)
                            job.update(state="ready", updated_at=cli.now(),
                                       last_preemption_reason=outcome["reason"],
                                       preemption_count=int(job.get("preemption_count", 0)) + 1)
                            if outcome.get("context_rollover"):
                                job["handoff_pending"] = True
                                job["context_rollover_usage"] = outcome.get("context_usage")
                            cli.atomic_json(path, job)
                            cli.audit("task.preempted", job_id=job["id"],
                                      reason=outcome["reason"],
                                      resume_available=bool(outcome.get("session")))
                            print(f"{job['id']} preempted: {outcome['reason']}")
                            return True
                        result = subprocess.CompletedProcess(command, outcome["returncode"])
                    else:
                        result = run(command, stdin=prompt, stdout=output,
                                     stderr=subprocess.STDOUT, env=env,
                                     pass_fds=opencode["pass_fds"], timeout=1800)
                current = json.loads(path.read_text(encoding="utf-8"))
                if current.get("state") == "interrupted":
                    print(f"{job['id']} interrupted by resource control")
                    return True
                session = opencode_session_id(output_path)
                if session:
                    job["opencode_session"] = session
                job.pop("executor_pid", None)
                job.update(state="run_finished" if result.returncode == 0 else "failed", updated_at=cli.now(), exit_code=result.returncode)
            except subprocess.TimeoutExpired:
                job.update(state="failed", updated_at=cli.now(), error="executor timed out after 1800 seconds")
            except Exception as error:
                job.update(state="failed", updated_at=cli.now(), error=f"{type(error).__name__}: {error}")
            finally:
                os.close(opencode["fd"])
            job.pop("executor_pid", None)
            if job.get("handoff_pending") and job.get("state") == "run_finished":
                handoff_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff.md"
                if not handoff_path.exists():
                    cli.atomic_text(handoff_path, f"""# Mechanical context handoff

The agent did not emit the requested semantic handoff. This explicit degraded
artifact preserves the recoverable boundaries without pretending to summarize work.

- Job: `{job['id']}`
- Objective: {job.get('task', '')}
- Original prompt: `{job.get('original_prompt', job.get('prompt', ''))}`
- Previous OpenCode session: `{job.get('opencode_session', 'unknown')}`
- Executor log: `{job.get('output', '')}`
- Required next action: inspect those durable sources and current filesystem state,
  reconstruct only verified progress, then continue without duplicating completed work.
""")
                    job["handoff_degraded"] = True
                rollover_index = int(job.get("context_rollover_count", 0)) + 1
                archived_log = output_path.with_name(
                    f"{job['id']}.context-{rollover_index}.opencode.log")
                shutil.copy2(output_path, archived_log)
                previous_session = job.get("opencode_session")
                if previous_session:
                    job.setdefault("previous_opencode_sessions", []).append(previous_session)
                job.setdefault("context_logs", []).append(str(archived_log.relative_to(cli.ROOT)))
                job.pop("opencode_session", None)
                job.pop("handoff_pending", None)
                rollover_prompt = cli.ROOT / "state/jobs" / f"{job['id']}.rollover.md"
                cli.atomic_text(rollover_prompt, f"""Continue the exact assigned task in a fresh context.

Read the original prompt at `{cli.ROOT / job.get('original_prompt', job.get('prompt', ''))}`, the handoff at
`{handoff_path}`, and the current filesystem state. Treat the handoff as a navigation
aid, not authority: verify consequential claims before relying on them. Continue from
the next incomplete boundary without repeating completed work.
""")
                job.update(state="ready", prompt=str(rollover_prompt.relative_to(cli.ROOT)),
                           fresh_context_after_handoff=True,
                           context_rollover_count=rollover_index, updated_at=cli.now())
                cli.atomic_json(path, job)
                cli.audit("task.context_rolled_over", job_id=job["id"],
                          handoff=str(handoff_path.relative_to(cli.ROOT)),
                          degraded=bool(job.get("handoff_degraded")))
                print(f"{job['id']} context rolled over; fresh session ready")
                return True
            if job.get("state") == "run_finished":
                job.pop("fresh_context_after_handoff", None)
            cli.atomic_json(path, job)
            cli.audit(f"task.{job['state']}", job_id=job["id"], output=job["output"], exit_code=job.get("exit_code"))
            if job.get("verifies"):
                from ecosystem.verification import finalize
                target = finalize(job)
                if job["state"] == "run_finished":
                    job.update(state="completed", updated_at=cli.now())
                    cli.atomic_json(path, job)
                queue_notifications(target)
            elif job["state"] == "run_finished":
                from ecosystem.verification import enqueue
                job.update(state="awaiting_verification", updated_at=cli.now())
                cli.atomic_json(path, job)
                enqueue(job)
            else:
                queue_notifications(job)
            print(f"{job['id']} {job['state']}")
            return True
    print("no ready task")
    return False


def run_until_idle() -> None:
    while True:
        cli.prepare_next()
        if not execute_next():
            return


if __name__ == "__main__":
    run_until_idle()
