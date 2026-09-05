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
from ecosystem.inference_capacity import reserve_sequence
from ecosystem.inference_proxy import (
    cancel as cancel_proxy,
    completed_run_termination,
    issue_proxy_credential,
    opencode_environment,
    populate_opencode_credential,
    revoke_proxy_credential,
)
from ecosystem.models import realize, route, snapshot
from ecosystem.scheduler import choose, policy as scheduling_policy, priority
from ecosystem.resource_control import job_admitted_in_current_mode, mode as resource_mode, opencode_session_id
from ecosystem.workload_control import (
    acquire_worker,
    observe_workers,
    register_process,
    release_worker,
)


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


def _required_job_field(job: dict, name: str):
    value = job.get(name)
    if value is None or value == "":
        raise ValueError(f"job lacks authoritative {name}")
    return value


def _runner_worker_request(job: dict, route_record: dict) -> dict:
    request = {
        "workload_class": _required_job_field(job, "workload_class"),
        "model_id": route_record["model_id"],
        "context_tokens": route_record["context_tokens_per_sequence"],
        "max_output_tokens": route_record["max_output_tokens"],
        "deadline_monotonic": _required_job_field(job, "deadline_monotonic"),
        "owner_identity": _required_job_field(job, "owner_identity"),
        "job_id": job["id"],
        "agent_generation": _required_job_field(job, "agent_generation"),
        "caller_handle": _required_job_field(job, "caller_handle"),
        "request_id": job["runner_worker_request_id"],
        "stop_method": "process_group",
    }
    for field in (
        "role", "authority_profile", "execution_profile", "requirements",
        "prompt_tokens", "tool_tokens", "handoff_tokens", "write_paths",
    ):
        if field in job:
            request[field] = job[field]
    if "role" not in request:
        raise ValueError("job lacks authoritative role")
    _required_job_field(request, "authority_profile")
    return request


def _runner_sequence_request(root: Path, job: dict, worker_lease: dict,
                             worker_request: dict, route_record: dict) -> dict:
    policy = json.loads((root / "config/resource-policy.json").read_text(
        encoding="utf-8"))["inference_capacity"]
    workload_class = worker_request["workload_class"]
    if workload_class == "front":
        raise ValueError("ordinary executor runners cannot claim the front proxy")
    return {
        "request_id": job["runner_sequence_request_id"],
        "worker_lease_id": worker_lease["lease_id"],
        "worker_request_id": worker_request["request_id"],
        "owner_identity": worker_request["owner_identity"],
        "workload_class": workload_class,
        "proxy_identity": policy["work_proxy_identity"],
        "route": route_record,
        "role": worker_request["role"],
        "execution_profile": worker_request.get("execution_profile"),
        "authority_profile": worker_request["authority_profile"],
        "preemption_method": worker_request["stop_method"],
    }


def _observe_stopped_worker(root: Path, worker_lease: dict, launch_record: dict,
                            outcome: dict, clock, release, observe) -> None:
    release(root, worker_lease["lease_id"], outcome, clock)
    observe(root, [{
        "lease_id": worker_lease["lease_id"],
        "pid": launch_record["pid"],
        "process_start_ticks": launch_record["start_ticks"],
        "process_group_alive": False,
        "backend_request_active": False,
        "inference_lease_active": False,
        "checkpoint_observed": True,
    }], clock)


def launch_runner_round(
    job: dict,
    job_path: Path,
    route_record: dict,
    inventory: dict,
    command: list[str],
    *,
    stdin,
    stdout,
    stderr,
    acquire=acquire_worker,
    launch=gated_child_launch,
    register=register_process,
    reserve=reserve_sequence,
    issue=issue_proxy_credential,
    populate=populate_opencode_credential,
    release_gate=gated_child_release,
    release=release_worker,
    observe=observe_workers,
    cancel=cancel_proxy,
    clock=time.monotonic,
) -> dict:
    """Compose one trusted R1/R3/R4 runner admission before OpenCode can exec."""
    root = cli.ROOT
    if job.get("state") == "ready":
        generation = int(job.get("runner_generation", 0)) + 1
        job.update(
            state="runner_starting",
            runner_generation=generation,
            runner_worker_request_id=f"{job['id']}:runner:{generation}:worker",
            runner_sequence_request_id=f"{job['id']}:runner:{generation}:sequence",
            updated_at=cli.now(),
        )
        job.pop("worker_lease_id", None)
        job.pop("inference_lease_id", None)
        cli.atomic_json(job_path, job)
    elif job.get("state") != "runner_starting":
        raise ValueError("runner round requires ready or runner_starting job")

    worker_request = _runner_worker_request(job, route_record)
    worker_lease = None
    launch_record = None
    inference_lease = None
    credential_issued = False
    try:
        worker_lease = acquire(root, worker_request, clock)
        if worker_lease.get("state") == "deferred":
            job.update(state="ready", updated_at=cli.now(),
                       runner_deferred_reasons=worker_lease.get("reasons", []))
            cli.atomic_json(job_path, job)
            return {"state": "deferred", "job": job}
        job["worker_lease_id"] = worker_lease["lease_id"]
        cli.atomic_json(job_path, job)

        provisional = {
            "model_id": route_record["model_id"],
            "context_tokens": route_record["context_tokens_per_sequence"],
            "max_output_tokens": route_record["max_output_tokens"],
        }
        opencode = opencode_environment(root, provisional, b"\0" * 32)
        environment = os.environ.copy()
        environment.update(opencode["environment"])
        environment["AGENT_JOB_ID"] = job["id"]
        launch_record = launch(
            opencode["fd"], command, environment,
            stdin=stdin, stdout=stdout, stderr=stderr,
        )
        register(
            root, worker_lease["lease_id"], launch_record["pid"],
            launch_record["start_ticks"], clock,
        )
        sequence_request = _runner_sequence_request(
            root, job, worker_lease, worker_request, route_record,
        )
        inference_lease = reserve(root, sequence_request, inventory, clock)
        if inference_lease.get("state") == "deferred":
            outcome = gated_child_cleanup(launch_record)
            _observe_stopped_worker(
                root, worker_lease, launch_record,
                {"state": "deferred", "returncode": outcome["returncode"]},
                clock, release, observe,
            )
            job.update(state="ready", updated_at=cli.now(),
                       runner_deferred_reasons=inference_lease.get("reasons", []))
            cli.atomic_json(job_path, job)
            return {"state": "deferred", "job": job}
        job["inference_lease_id"] = inference_lease["lease_id"]
        cli.atomic_json(job_path, job)
        expected = (
            route_record["model_id"], route_record["context_tokens_per_sequence"],
            route_record["max_output_tokens"],
        )
        actual = (
            inference_lease.get("model_id"), inference_lease.get("context_tokens"),
            inference_lease.get("max_output_tokens"),
        )
        issue(root, inference_lease,
              lambda credential: populate(opencode, credential), clock)
        credential_issued = True
        if actual != expected:
            raise ValueError("inference lease limits differ from admitted route")
        release_gate(launch_record)
        job.update(
            state="running", updated_at=cli.now(),
            worker_lease_id=worker_lease["lease_id"],
            inference_lease_id=inference_lease["lease_id"],
            executor_pid=launch_record["pid"],
            executor_start_ticks=launch_record["start_ticks"],
            last_started_at=cli.now(),
            dispatch_count=int(job.get("dispatch_count", 0)) + 1,
        )
        job.pop("runner_deferred_reasons", None)
        cli.atomic_json(job_path, job)
        return {
            "state": "running", "launch": launch_record,
            "worker_lease": worker_lease, "inference_lease": inference_lease,
        }
    except Exception as error:
        if inference_lease is not None and inference_lease.get("state") != "deferred":
            job.update(
                state="reconciliation_required", updated_at=cli.now(),
                worker_lease_id=worker_lease["lease_id"],
                inference_lease_id=inference_lease["lease_id"],
                reconciliation_reason=f"{type(error).__name__}: {error}",
            )
            cli.atomic_json(job_path, job)
            if launch_record is not None:
                gated_child_cleanup(launch_record)
            if credential_issued:
                try:
                    cancel(root, inference_lease["lease_id"], clock)
                except Exception as cancel_error:
                    job["reconciliation_cancel_error"] = (
                        f"{type(cancel_error).__name__}: {cancel_error}"
                    )
        else:
            if launch_record is not None:
                gated_child_cleanup(launch_record)
            if worker_lease is not None:
                worker_outcome = {
                    "state": "failed", "error": f"{type(error).__name__}: {error}",
                }
                if launch_record is not None:
                    _observe_stopped_worker(
                        root, worker_lease, launch_record, worker_outcome,
                        clock, release, observe,
                    )
                else:
                    release(root, worker_lease["lease_id"], worker_outcome, clock)
                    observe(root, [{
                        "lease_id": worker_lease["lease_id"],
                        "process_group_alive": False,
                        "backend_request_active": False,
                        "inference_lease_active": False,
                        "checkpoint_observed": True,
                    }], clock)
            job.update(state="ready", updated_at=cli.now(),
                       runner_deferred_reasons=[f"{type(error).__name__}: {error}"])
        cli.atomic_json(job_path, job)
        raise


def close_runner_round(
    job: dict,
    job_path: Path,
    context: dict,
    child_outcome: dict,
    *,
    termination=completed_run_termination,
    revoke=revoke_proxy_credential,
    release=release_worker,
    observe=observe_workers,
    clock=time.monotonic,
) -> dict:
    """Close R4 then R3 then R1, or retain both leases for reconciliation."""
    if ("runner_closed_generation" in job
            and job["runner_closed_generation"] == job.get("runner_generation")):
        return {"state": job["runner_close_state"]}
    if job.get("state") == "reconciliation_required":
        return {"state": "reconciliation_required"}
    inference_lease = context["inference_lease"]
    worker_lease = context["worker_lease"]
    launch_record = context["launch"]
    evidence = termination(cli.ROOT, inference_lease["lease_id"])
    if evidence is None:
        job.update(
            state="reconciliation_required", updated_at=cli.now(),
            worker_lease_id=worker_lease["lease_id"],
            inference_lease_id=inference_lease["lease_id"],
            reconciliation_reason="verified backend termination is unavailable",
        )
        cli.atomic_json(job_path, job)
        return {"state": "reconciliation_required"}
    revoked = revoke(cli.ROOT, inference_lease["lease_id"], evidence, clock)
    if revoked.get("state") != "revoked" \
            or revoked.get("sequence", {}).get("state") != "released":
        raise RuntimeError("proxy close did not release the inference sequence")
    final_state = "run_finished" if child_outcome["returncode"] == 0 else "failed"
    worker_outcome = {"state": final_state, "returncode": child_outcome["returncode"]}
    _observe_stopped_worker(
        cli.ROOT, worker_lease, launch_record, worker_outcome,
        clock, release, observe,
    )
    job.update(state=final_state, updated_at=cli.now(),
               exit_code=child_outcome["returncode"],
               runner_closed_generation=job.get("runner_generation"),
               runner_close_state=final_state)
    job.pop("executor_pid", None)
    cli.atomic_json(job_path, job)
    return {"state": final_state, "credential": revoked}


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
        if (job.get("kind") != "agent-task"
                or job.get("state") not in {"runner_starting", "running"}
                or _process_alive(job)):
            continue
        if job.get("inference_lease_id"):
            job.update(
                state="reconciliation_required", updated_at=cli.now(),
                reconciliation_reason="runner disappeared after inference reservation",
            )
            cli.atomic_json(path, job)
            cli.audit("task.reconciliation_required", job_id=job["id"],
                      inference_lease_id=job["inference_lease_id"])
            recovered += 1
            continue
        if job.get("state") == "runner_starting":
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


def _run_preemptibly(process: subprocess.Popen, command: list[str], job: dict,
                     output_path: Path, before_stop) -> dict:
    settings = scheduling_policy()["workers"]
    started = time.monotonic()
    timeout = float(settings["max_job_seconds"])
    while process.poll() is None:
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            before_stop()
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
                before_stop()
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
            if (job.get("kind") == "agent-task"
                    and job["state"] in {"ready", "runner_starting"}
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
            job.update(attempts=job["attempts"] + 1,
                       updated_at=cli.now(), output=str(output_path.relative_to(cli.ROOT)))
            selected = job.get("model") or os.environ.get(
                "AGENT_EXECUTOR_MODEL", "Qwen3.5-4B-GGUF")
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
                    if run is not subprocess.run:
                        raise ValueError("injected runner bypass is not permitted")
                    context = launch_runner_round(
                        job, path, decision, inventory, command,
                        stdin=prompt, stdout=output, stderr=subprocess.STDOUT,
                    )
                    if context["state"] == "deferred":
                        print(f"{job['id']} runner admission deferred")
                        return False
                    cli.audit("task.started", job_id=job["id"], role=job.get("role"),
                              executor="opencode")
                    cancelled = False

                    def cancel_before_stop():
                        nonlocal cancelled
                        if not cancelled:
                            cancel_proxy(
                                cli.ROOT, context["inference_lease"]["lease_id"],
                                time.monotonic,
                            )
                            cancelled = True

                    outcome = _run_preemptibly(
                        context["launch"]["process"], command, job, output_path,
                        cancel_before_stop,
                    )
                    child_outcome = gated_child_wait(context["launch"], 0)
                    closed = close_runner_round(job, path, context, child_outcome)
                    if closed["state"] == "reconciliation_required":
                        print(f"{job['id']} requires inference reconciliation")
                        return True
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
                current = json.loads(path.read_text(encoding="utf-8"))
                if current.get("state") == "interrupted":
                    print(f"{job['id']} interrupted by resource control")
                    return True
                session = opencode_session_id(output_path)
                if session:
                    job["opencode_session"] = session
                job.pop("executor_pid", None)
            except subprocess.TimeoutExpired:
                if 'context' in locals():
                    gated_child_cleanup(context["launch"])
                    close_runner_round(
                        job, path, context,
                        {"returncode": context["launch"]["process"].returncode},
                    )
                if job.get("state") != "reconciliation_required":
                    job.update(state="failed", updated_at=cli.now(),
                               error="executor timed out after 1800 seconds")
            except Exception as error:
                if job.get("state") not in {"ready", "reconciliation_required"}:
                    job.update(state="failed", updated_at=cli.now(),
                               error=f"{type(error).__name__}: {error}")
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
