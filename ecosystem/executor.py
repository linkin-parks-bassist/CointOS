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
from ecosystem import continuation
from ecosystem import evidence
from ecosystem import task_contracts
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
from ecosystem import scheduler
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
        error = ValueError("child_argv must be a non-empty list of strings")
        error.launch_failure = {"spawned": False}
        os.close(config_fd)
        raise error
    if (type(child_env) is not dict
            or any(type(key) is not str or type(value) is not str
                   for key, value in child_env.items())):
        error = ValueError("child_env must contain string keys and values")
        error.launch_failure = {"spawned": False}
        os.close(config_fd)
        raise error

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
    except Exception as error:
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
            error.launch_failure = {
                "spawned": True,
                "pid": record["pid"],
                "start_ticks": record.get("start_ticks"),
                "pgid": record["pgid"],
                "cleanup": gated_child_cleanup(record, 0.2),
            }
        else:
            os.close(gate_write_fd)
            os.close(config_fd)
            error.launch_failure = {"spawned": False}
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


def _process_group_alive(pgid: int) -> bool | None:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def _reaped_outcome(record: dict, returncode: int) -> dict:
    group_alive = _process_group_alive(record["pgid"])
    state = "reaped" if group_alive is False else "reconciliation_required"
    outcome = {
        "state": state,
        "returncode": returncode,
        "pid": record["pid"],
        "start_ticks": record["start_ticks"],
        "pgid": record["pgid"],
        "process_group_alive": group_alive,
    }
    record["state"] = state
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
    if (record.get("outcome") is not None
            and record["outcome"].get("state") == "reaped"):
        return record["outcome"]
    record["outcome"] = None
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
    group_alive = _process_group_alive(record["pgid"])
    if group_alive is True:
        try:
            os.killpg(record["pgid"], signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _process_group_alive(record["pgid"]) is True:
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    return _reaped_outcome(record, returncode)


def _required_job_field(job: dict, name: str):
    value = job.get(name)
    if value is None or value == "":
        raise ValueError(f"job lacks authoritative {name}")
    return value


def _claim_execution(job: dict, clock) -> None:
    """Initialize a job's durable execution claim. Values already present on
    the record are authoritative and are never rewritten; replay reuses them."""
    if "agent_generation" not in job:
        job["agent_generation"] = 1
    if "logical_run_state" not in job:
        job["logical_run_state"] = "active"
    if "owner_identity" not in job:
        job["owner_identity"] = f"executor:{job['id']}"
    if "caller_handle" not in job:
        job["caller_handle"] = "executor:local"
    if "deadline_monotonic" not in job:
        budget = job.get("remaining_budget")
        if type(budget) is not dict or type(budget.get("task_seconds")) is not int:
            raise ValueError(
                f"job {job['id']} lacks a remaining task budget for its "
                f"execution deadline")
        job["deadline_monotonic"] = clock() + budget["task_seconds"]


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
                            process_outcome: dict, release_outcome: dict,
                            clock, release, observe) -> None:
    if (process_outcome.get("state") != "reaped"
            or process_outcome.get("process_group_alive") is not False):
        raise ValueError("worker process group termination is not established")
    release(root, worker_lease["lease_id"], release_outcome, clock)
    observation = {
        "lease_id": worker_lease["lease_id"],
        "pid": launch_record["pid"],
        "process_start_ticks": launch_record["start_ticks"],
        "process_group_alive": False,
        "backend_request_active": False,
        "inference_lease_active": False,
    }
    if type(process_outcome.get("checkpoint_observed")) is bool:
        observation["checkpoint_observed"] = process_outcome["checkpoint_observed"]
    observe(root, [observation], clock)


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
    refresh_inventory=snapshot,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> dict:
    """Compose one trusted R1/R3/R4 runner admission before OpenCode can exec."""
    root = cli.ROOT
    if job.get("state") == "ready":
        generation = int(job.get("runner_generation", 0)) + 1
        _claim_execution(job, clock)
        job.update(
            state="runner_starting",
            runner_generation=generation,
            runner_worker_request_id=f"{job['id']}:runner:{generation}:worker",
            runner_sequence_request_id=f"{job['id']}:runner:{generation}:sequence",
            runner_phase="generation_claimed",
            updated_at=cli.now(),
        )
        job.pop("worker_lease_id", None)
        job.pop("inference_lease_id", None)
        job.pop("runner_worker_request", None)
        job.pop("runner_sequence_request", None)
        job.pop("runner_spawn_failure", None)
        cli.atomic_json(job_path, job)
    elif job.get("state") != "runner_starting":
        raise ValueError("runner round requires ready or runner_starting job")

    worker_request = job.get("runner_worker_request")
    if worker_request is None:
        _claim_execution(job, clock)
        worker_request = _runner_worker_request(job, route_record)
        job["runner_worker_request"] = worker_request
    elif type(worker_request) is not dict:
        raise ValueError("invalid durable runner worker request")
    job["runner_phase"] = "r1_acquire_intent"
    cli.atomic_json(job_path, job)
    worker_lease = None
    launch_record = None
    inference_lease = None
    credential_issued = False
    process_registered = False
    try:
        worker_lease = acquire(root, worker_request, clock)
        if worker_lease.get("state") == "deferred":
            job.update(state="ready", updated_at=cli.now(),
                       runner_deferred_reasons=worker_lease.get("reasons", []))
            cli.atomic_json(job_path, job)
            return {"state": "deferred", "job": job}
        job["worker_lease_id"] = worker_lease["lease_id"]
        job["runner_phase"] = "r1_acquired"
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
        job["runner_phase"] = "spawn_intent"
        cli.atomic_json(job_path, job)
        launch_record = launch(
            opencode["fd"], command, environment,
            stdin=stdin, stdout=stdout, stderr=stderr,
        )
        job.update(
            runner_phase="spawned", executor_pid=launch_record["pid"],
            executor_start_ticks=launch_record["start_ticks"],
            executor_pgid=launch_record["pgid"],
        )
        cli.atomic_json(job_path, job)
        job["runner_phase"] = "process_register_intent"
        cli.atomic_json(job_path, job)
        register(
            root, worker_lease["lease_id"], launch_record["pid"],
            launch_record["start_ticks"], clock,
        )
        process_registered = True
        job["runner_phase"] = "process_registered"
        cli.atomic_json(job_path, job)
        sequence_request = _runner_sequence_request(
            root, job, worker_lease, worker_request, route_record,
        )
        job["runner_sequence_request"] = sequence_request
        job["runner_phase"] = "r3_reserve_intent"
        cli.atomic_json(job_path, job)
        inference_lease = reserve(root, sequence_request, inventory, clock)
        while inference_lease.get("state") in {
            "waiting_for_preemption", "ready_for_revalidation",
        }:
            job.update(
                runner_phase="r3_waiting",
                inference_lease_id=inference_lease["lease_id"],
                updated_at=cli.now(),
            )
            cli.atomic_json(job_path, job)
            if clock() >= worker_request["deadline_monotonic"]:
                outcome = gated_child_cleanup(launch_record)
                job.update(
                    state="reconciliation_required", updated_at=cli.now(),
                    reconciliation_reason=(
                        "inference waiter reached its deadline without withdrawal support"
                    ),
                    cleanup_state=outcome["state"],
                )
                cli.atomic_json(job_path, job)
                return {"state": "reconciliation_required", "job": job}
            sleeper(0.05)
            inventory = refresh_inventory()
            inference_lease = reserve(root, sequence_request, inventory, clock)
        if inference_lease.get("state") == "deferred":
            outcome = gated_child_cleanup(launch_record)
            if outcome["state"] != "reaped":
                job.update(
                    state="reconciliation_required", updated_at=cli.now(),
                    worker_lease_id=worker_lease["lease_id"],
                    executor_pid=launch_record["pid"],
                    executor_start_ticks=launch_record["start_ticks"],
                    executor_pgid=launch_record["pgid"],
                    reconciliation_reason="gated process group termination is unresolved",
                )
                cli.atomic_json(job_path, job)
                return {"state": "reconciliation_required", "job": job}
            _observe_stopped_worker(
                root, worker_lease, launch_record, outcome,
                {"state": "deferred", "returncode": outcome["returncode"]},
                clock, release, observe,
            )
            job.update(state="ready", updated_at=cli.now(),
                       runner_deferred_reasons=inference_lease.get("reasons", []))
            cli.atomic_json(job_path, job)
            return {"state": "deferred", "job": job}
        if (inference_lease.get("state") not in {"starting", "active"}
                or type(inference_lease.get("backend_sequence")) is not int
                or type(inference_lease.get("expected_release_binding")) is not dict):
            raise ValueError("inference reservation is not credential-ready")
        job["inference_lease_id"] = inference_lease["lease_id"]
        job["runner_phase"] = "r3_reserved"
        cli.atomic_json(job_path, job)
        expected = (
            route_record["model_id"], route_record["context_tokens_per_sequence"],
            route_record["max_output_tokens"],
        )
        actual = (
            inference_lease.get("model_id"), inference_lease.get("context_tokens"),
            inference_lease.get("max_output_tokens"),
        )
        job["runner_phase"] = "credential_issue_intent"
        cli.atomic_json(job_path, job)
        issue(root, inference_lease,
              lambda credential: populate(opencode, credential), clock)
        credential_issued = True
        job["runner_phase"] = "credential_issued"
        cli.atomic_json(job_path, job)
        if actual != expected:
            raise ValueError("inference lease limits differ from admitted route")
        job["runner_phase"] = "gate_release_intent"
        cli.atomic_json(job_path, job)
        release_gate(launch_record)
        job["runner_phase"] = "gate_released"
        cli.atomic_json(job_path, job)
        job.update(
            state="running", runner_phase="running", updated_at=cli.now(),
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
            cleanup_outcome = None
            failure = getattr(error, "launch_failure", None)
            if launch_record is not None:
                cleanup_outcome = gated_child_cleanup(launch_record)
            elif failure is not None and failure.get("spawned") is True:
                launch_record = {
                    "pid": failure["pid"],
                    "start_ticks": failure.get("start_ticks"),
                    "pgid": failure.get("pgid"),
                }
                cleanup_outcome = failure["cleanup"]
            job["runner_spawn_failure"] = {
                "phase": job.get("runner_phase"),
                "error": f"{type(error).__name__}: {error}",
                "spawned": launch_record is not None,
                "cleanup_state": (
                    cleanup_outcome["state"] if cleanup_outcome is not None else None
                ),
            }
            if cleanup_outcome is not None and cleanup_outcome["state"] != "reaped":
                job.update(
                    state="reconciliation_required", updated_at=cli.now(),
                    worker_lease_id=worker_lease["lease_id"],
                    executor_pid=launch_record["pid"],
                    executor_start_ticks=launch_record.get("start_ticks"),
                    executor_pgid=launch_record["pgid"],
                    reconciliation_reason="gated process group termination is unresolved",
                )
                cli.atomic_json(job_path, job)
                raise
            worker_outcome = {
                "state": "failed",
                "error": f"{type(error).__name__}: {error}",
            }
            if worker_lease is not None:
                if process_registered:
                    _observe_stopped_worker(
                        root, worker_lease, launch_record, cleanup_outcome,
                        worker_outcome, clock, release, observe,
                    )
                elif launch_record is not None:
                    release(root, worker_lease["lease_id"], worker_outcome, clock)
                    observe(root, [{
                        "lease_id": worker_lease["lease_id"],
                        "reaped_spawn": {
                            "pid": launch_record["pid"],
                            "process_start_ticks": launch_record.get("start_ticks"),
                            "returncode": cleanup_outcome.get("returncode"),
                            "process_group_alive": False,
                        },
                        "process_group_alive": False,
                        "backend_request_active": False,
                        "inference_lease_active": False,
                    }], clock)
                else:
                    release(root, worker_lease["lease_id"], worker_outcome, clock)
                    observe(root, [{
                        "lease_id": worker_lease["lease_id"],
                        "never_spawned": True,
                        "process_group_alive": False,
                        "backend_request_active": False,
                        "inference_lease_active": False,
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
    saved_outcome = job.get("runner_close_outcome")
    if saved_outcome is not None and saved_outcome != child_outcome:
        raise ValueError("runner close outcome changed during replay")
    if saved_outcome is None:
        job["runner_close_outcome"] = json.loads(json.dumps(child_outcome, sort_keys=True))
        job["runner_phase"] = "close_intent"
        cli.atomic_json(job_path, job)
    inference_lease = context["inference_lease"]
    worker_lease = context["worker_lease"]
    launch_record = context["launch"]
    if (child_outcome.get("state") != "reaped"
            or child_outcome.get("process_group_alive") is not False):
        job.update(
            state="reconciliation_required", updated_at=cli.now(),
            worker_lease_id=worker_lease["lease_id"],
            inference_lease_id=inference_lease["lease_id"],
            reconciliation_reason="runner process group termination is unresolved",
        )
        cli.atomic_json(job_path, job)
        return {"state": "reconciliation_required"}
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
        cli.ROOT, worker_lease, launch_record, child_outcome, worker_outcome,
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


def _stop_recovered_runner(job: dict, timeout: float = 0.2) -> bool | None:
    pid = job.get("executor_pid")
    start_ticks = job.get("executor_start_ticks")
    pgid = job.get("executor_pgid")
    if any(type(value) is not int for value in (pid, start_ticks, pgid)):
        return None
    try:
        identity = process_identity(pid)
    except FileNotFoundError:
        return _process_group_alive(pgid)
    if identity["start_ticks"] != start_ticks or identity["pgid"] != pgid:
        return None
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _process_group_alive(pgid) is True:
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    if _process_group_alive(pgid) is True:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return False
    return _process_group_alive(pgid)


def recover_abandoned_jobs() -> int:
    recovered = 0
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (job.get("kind") != "agent-task"
                or job.get("state") not in {
                    "runner_starting", "running", "reconciliation_required",
                }):
            continue
        if (job.get("runner_close_outcome") is not None
                and job.get("worker_lease_id") and job.get("inference_lease_id")):
            group_alive = _stop_recovered_runner(job)
            if group_alive is False:
                context = {
                    "worker_lease": {"lease_id": job["worker_lease_id"]},
                    "inference_lease": {"lease_id": job["inference_lease_id"]},
                    "launch": {
                        "pid": job["executor_pid"],
                        "start_ticks": job["executor_start_ticks"],
                        "pgid": job["executor_pgid"],
                    },
                }
                try:
                    closed = close_runner_round(
                        job, path, context, job["runner_close_outcome"])
                except (OSError, RuntimeError, ValueError):
                    closed = {"state": "reconciliation_required"}
                if closed["state"] != "reconciliation_required":
                    recovered += 1
                    continue
            job["recovery_process_group_alive"] = group_alive
            job.update(state="reconciliation_required", updated_at=cli.now())
            cli.atomic_json(path, job)
            recovered += 1
            continue
        if (job.get("state") == "runner_starting"
                and job.get("runner_phase") not in {
                    "generation_claimed", "r1_acquire_intent", "r1_acquired",
                }):
            if job.get("inference_lease_id"):
                try:
                    cancel_result = cancel_proxy(
                        cli.ROOT, job["inference_lease_id"], time.monotonic)
                    job["recovery_cancel_state"] = cancel_result["state"]
                except ValueError:
                    job["recovery_cancel_state"] = "credential_absent"
            job["recovery_process_group_alive"] = _stop_recovered_runner(job)
            job.update(
                state="reconciliation_required", updated_at=cli.now(),
                reconciliation_reason=(
                    f"restart cannot resolve admission prefix {job.get('runner_phase')!r}"
                ),
            )
            cli.atomic_json(path, job)
            cli.audit("task.reconciliation_required", job_id=job["id"],
                      runner_phase=job.get("runner_phase"))
            recovered += 1
            continue
        if job.get("inference_lease_id"):
            try:
                cancel_result = cancel_proxy(
                    cli.ROOT, job["inference_lease_id"], time.monotonic)
                job["recovery_cancel_state"] = cancel_result["state"]
            except ValueError:
                job["recovery_cancel_state"] = "credential_absent"
            job["recovery_process_group_alive"] = _stop_recovered_runner(job)
            job.update(
                state="reconciliation_required", updated_at=cli.now(),
                reconciliation_reason="runner disappeared after inference reservation",
            )
            cli.atomic_json(path, job)
            cli.audit("task.reconciliation_required", job_id=job["id"],
                      inference_lease_id=job["inference_lease_id"])
            recovered += 1
            continue
        if _process_alive(job):
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


def _preemption_reason(job: dict, started: float, scheduling: dict) -> str | None:
    waiting = _waiting_jobs(job["id"])
    if not waiting:
        return None
    strongest = max(waiting, key=lambda item: priority(item, scheduling))
    if priority(strongest, scheduling) > priority(job, scheduling):
        return (f"higher-priority job {strongest['id']} is waiting "
                f"({priority(strongest, scheduling)} > {priority(job, scheduling)})")
    quantum = float(scheduling_policy()["workers"]["time_slice_seconds"])
    if time.monotonic() - started >= quantum:
        return f"{quantum:.0f}-second time slice expired while other work is waiting"
    return None


def _run_preemptibly(process: subprocess.Popen, command: list[str], job: dict,
                     output_path: Path, before_stop, scheduling: dict) -> dict:
    from ecosystem import execution_budget
    from ecosystem.time_policy import load as load_time_policy

    settings = scheduling_policy()["workers"]
    budget = job.get("remaining_budget")
    if type(budget) is not dict:
        raise ValueError(f"job {job['id']} lacks a remaining budget for execution")
    times = load_time_policy()["workload"]
    wrapup_seconds = float(times["wrapup_seconds"])
    grace_seconds = float(times["termination_grace_seconds"])
    started = time.monotonic()
    identity = process_identity(process.pid)

    def observe():
        # A zombie is gone: it can no longer act on signals, and poll()
        # reaps it so the pid cannot be mistaken for a live or reused one.
        if process.poll() is not None:
            return None
        try:
            current = process_identity(process.pid)
        except (OSError, ValueError):
            return None
        return current if current["start_ticks"] == identity["start_ticks"] else None

    usage = execution_budget.account_usage(
        budget, {"attempts": int(job.get("attempts", 0))},
        {"kind": "run_started", "at": started})
    usage = execution_budget.account_usage(
        budget, usage, {"kind": "task_started", "at": started})
    last_output_bytes = output_path.stat().st_size if output_path.exists() else 0
    while process.poll() is None:
        now = time.monotonic()
        if output_path.exists():
            size = output_path.stat().st_size
            if size > last_output_bytes:
                usage = execution_budget.account_usage(
                    budget, usage, {"kind": "output", "bytes": size - last_output_bytes})
                last_output_bytes = size
        outcome = execution_budget.budget_outcome(budget, usage, now)
        if outcome["state"] == "checkpoint_required":
            handoff_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff.md"
            request_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff-request.md"
            if not handoff_path.exists():
                cli.atomic_text(request_path, f"""The task budget is exhausted. Do not continue
the main task. Write a concise, sufficient handoff to `{handoff_path}`.
Record the objective, authoritative instructions, decisions and rationale, exact completed
work, changed files, tests and evidence, unresolved risks, and the next concrete action.
Distinguish verified facts from assumptions. This artifact seeds the next attempt.
""")
            before_stop()
            execution_budget.stop_process_group(
                process.pid, wrapup_seconds, grace_seconds, observe)
            return {"returncode": process.wait(), "preempted": False,
                    "budget_checkpoint": outcome, "usage": usage,
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
        elapsed = now - started
        context_rollover = False
        context_usage = None
        observed = opencode_context_usage(output_path, job.get("opencode_session"))
        context_limit = int(job.get("context_tokens") or 0)
        if observed and context_limit:
            context_usage = continuation.observe_context_usage(
                observed, {"context_tokens": context_limit})
            transition = continuation.context_transition(
                job, context_usage, float(settings["context_rollover_fraction"]))
            context_rollover = (
                transition["context_state"] == "handoff_requested"
                and job.get("context_state") != "handoff_requested")
        reason = (f"context reached {context_usage['total_tokens']}/{context_limit} tokens "
                  f"({float(settings['context_rollover_fraction']):.0%}); durable handoff required"
                  if context_rollover else _preemption_reason(job, started, scheduling))
        if reason:
            session = job.get("opencode_session") or opencode_session_id(output_path)
            # Give OpenCode a short initial window to publish its durable session id.
            if session or elapsed >= float(settings["preemption_grace_seconds"]):
                before_stop()
                execution_budget.stop_process_group(
                    process.pid, wrapup_seconds, grace_seconds, observe)
                session = session or opencode_session_id(output_path)
                return {"returncode": process.returncode, "preempted": True,
                        "reason": reason, "session": session,
                        "context_rollover": context_rollover,
                        "context_usage": context_usage,
                        "elapsed_seconds": round(elapsed, 3)}
        time.sleep(1)
    return {"returncode": process.returncode, "preempted": False,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def discovery_evidence(job: dict) -> dict:
    """A2: bounded evidence authority for one discovery run.

    The scope comes from the job's executable contract; the item budget from
    its remaining shared budget; the byte budget from the evidence tool's page
    envelope. Both limits are remaining budgets counted across read_evidence
    calls, not per-call allowances. A discovery run inspects the environment
    only through the bounded evidence reader and records output only through
    record_contribution; it holds no unrestricted read or shell authority.
    """
    contract = job.get("task_contract")
    if type(contract) is not dict:
        raise ValueError("discovery evidence requires an executable task contract")
    validated = task_contracts.validate_task_contract(contract)
    remaining = job.get("remaining_budget")
    if type(remaining) is not dict or type(remaining.get("maximum_evidence_items")) is not int \
            or remaining["maximum_evidence_items"] < 0:
        raise ValueError("discovery evidence requires the remaining evidence budget")
    scope = validated["scope"]
    return {
        "scope": {
            "workspace": scope["workspace"],
            "read_paths": list(scope["read_paths"]),
            "write_paths": list(scope["write_paths"]),
        },
        "limits": {
            "maximum_bytes": evidence.DEFAULT_MAXIMUM_BYTES,
            "maximum_items": remaining["maximum_evidence_items"],
        },
    }


def execute_next(run=subprocess.run) -> bool:
    cli.initialize()
    rollover_fraction = float(scheduling_policy()["workers"]["context_rollover_fraction"])
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
        recover_abandoned_jobs()
        ready = []
        for path in sorted((cli.ROOT / "state/jobs").glob("*.json")):
            job = json.loads(path.read_text(encoding="utf-8"))
            if (job.get("kind") == "agent-task"
                    and job["state"] in {"ready", "runner_starting"}
                    and job_admitted_in_current_mode(job)):
                ready.append((path, job))
        if ready:
            try:
                scheduling = scheduler.scheduling_document(cli.ROOT)
                inventory = snapshot()
                path, job, scheduling_reason = choose(ready, inventory, scheduling)
            except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
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
                if job.get("opencode_session") and job.get("context_state") in (None, "running"):
                    job["context_state"] = "paused_for_resources"
                cli.atomic_json(path, job)
                cli.audit("task.routing_deferred", job_id=job["id"], reason=decision["reason"])
                print(f"{job['id']} routing deferred: {decision['reason']}")
                return False
            model_changed = decision["model"] != job.get("model")
            if model_changed:
                from ecosystem.roles import render_context
                job.update(model=decision["model"], model_reason=decision["reason"])
                if job.get("context_state") not in ("handoff_requested", "handoff_durable"):
                    prompt_path = cli.ROOT / "state/jobs" / f"{job['id']}.prompt.md"
                    cli.atomic_text(prompt_path, render_context(
                        job.get("role"), job["task"], job["id"], job["model"],
                        job["model_reason"], job.get("agent_name", "Agent"),
                        task_contract=job.get("task_contract")))
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
            if job.get("context_state") in ("handoff_requested", "handoff_durable") \
                    and not job.get("opencode_session"):
                resource_policy = json.loads(
                    (cli.ROOT / "config/resource-policy.json").read_text(encoding="utf-8"))
                reserves = resource_policy.get("context_reserves", {})
                destination_lease = {
                    "model_id": job["model"],
                    "context_tokens": int(decision["context_tokens"]),
                    "prompt_tokens": int(decision.get(
                        "prompt_tokens", reserves.get("prompt_tokens"))),
                    "handoff_tokens": int(decision.get(
                        "handoff_tokens", reserves.get("handoff_tokens"))),
                    "tool_tokens": int(decision.get(
                        "tool_tokens", reserves.get("tool_tokens"))),
                    "max_output_tokens": int(decision.get(
                        "max_output_tokens", reserves.get("max_output_tokens"))),
                }
                continuation_record = continuation.prepare_continuation(
                    job,
                    job.get("handoff")
                    if job.get("context_state") == "handoff_durable" else None,
                    {"evidence_paths": list(job.get("context_logs", []))},
                    destination_lease)
                job.update(continuation_record)
                degraded_note = (
                    "The handoff is a mechanical degraded artifact: the agent did not "
                    "emit a semantic summary.\n"
                    if job.get("handoff_degraded") else "")
                handoff_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff.md"
                rollover_prompt = cli.ROOT / "state/jobs" / f"{job['id']}.rollover.md"
                cli.atomic_text(rollover_prompt, f"""Continue the exact assigned task in a fresh context.
{degraded_note}
Read the original prompt at `{cli.ROOT / job.get('original_prompt', job.get('prompt', ''))}`, the handoff at
`{handoff_path}`, and the current filesystem state. Treat the handoff as a navigation
aid, not authority: verify consequential claims before relying on them. Continue from
the next incomplete boundary without repeating completed work.
""")
                job["prompt"] = str(rollover_prompt.relative_to(cli.ROOT))
            if job.get("context_state") in ("continuation_ready", "paused_for_resources"):
                job["context_state"] = "running"
            job.setdefault("context_state", "running")
            job.setdefault("context_generation", 1)
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
                if job.get("context_state") == "handoff_requested":
                    handoff_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff.md"
                    request_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff-request.md"
                    cli.atomic_text(request_path, f"""The context reached the {rollover_fraction:.0%} rollover threshold.
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
                        cancel_before_stop, scheduling,
                    )
                    child_outcome = gated_child_wait(context["launch"], 0)
                    closed = close_runner_round(job, path, context, child_outcome)
                    if closed["state"] == "reconciliation_required":
                        print(f"{job['id']} requires inference reconciliation")
                        return True
                    if outcome.get("budget_checkpoint"):
                        from ecosystem import execution_budget

                        checkpoint = outcome["budget_checkpoint"]
                        handoff_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff.md"
                        handoff = None
                        try:
                            if handoff_path.stat().st_size > 0:
                                handoff = {
                                    "path": str(handoff_path.relative_to(cli.ROOT)),
                                    "bytes": handoff_path.stat().st_size,
                                    "job_id": job["id"],
                                    "agent_generation": int(job.get("agent_generation", 1)),
                                }
                        except OSError:
                            handoff = None
                        state_record = execution_budget.checkpoint_job_state(
                            checkpoint, handoff)
                        # checkpoint_required is persisted first; only
                        # record_budget_handoff may produce partial_handoff_ready.
                        job.update(state=state_record["state"],
                                   logical_run_state="terminal",
                                   budget_outcome=checkpoint,
                                   budget_usage=outcome["usage"],
                                   updated_at=cli.now())
                        if handoff:
                            job["budget_handoff"] = state_record["artifact"]
                        job.pop("executor_pid", None)
                        cli.atomic_json(path, job)
                        cli.audit("task.budget_checkpoint", job_id=job["id"],
                                  reason=checkpoint["reason"],
                                  state=state_record["state"])
                        print(f"{job['id']} budget exhausted "
                              f"({checkpoint['reason']}): {state_record['state']}")
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
                                job["context_state"] = "handoff_requested"
                                job["context_usage"] = outcome.get("context_usage")
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
                if job.get("context_state") in (None, "running"):
                    final_observed = opencode_context_usage(
                        output_path, job.get("opencode_session"))
                    final_limit = int(job.get("context_tokens") or 0)
                    if final_observed and final_limit:
                        final_usage = continuation.observe_context_usage(
                            final_observed, {"context_tokens": final_limit})
                        job.update(continuation.context_transition(
                            job, final_usage, rollover_fraction))
                job.pop("executor_pid", None)
            except subprocess.TimeoutExpired:
                if 'context' in locals():
                    cleanup_outcome = gated_child_cleanup(context["launch"])
                    close_runner_round(job, path, context, cleanup_outcome)
                if job.get("state") != "reconciliation_required":
                    job.update(state="failed", updated_at=cli.now(),
                               error="executor timed out before a clean runner stop")
            except Exception as error:
                if job.get("state") not in {"ready", "reconciliation_required"}:
                    job.update(state="failed", updated_at=cli.now(),
                               error=f"{type(error).__name__}: {error}")
            job.pop("executor_pid", None)
            if job.get("state") == "run_finished" \
                    and job.get("context_state") == "handoff_requested":
                handoff_path = cli.ROOT / "state/jobs" / f"{job['id']}.handoff.md"
                handoff = None
                try:
                    text = handoff_path.read_text(encoding="utf-8")
                    if text.strip():
                        handoff = {
                            "path": str(handoff_path.relative_to(cli.ROOT)),
                            "summary": text.strip().splitlines()[0][:200],
                            "token_count": max(1, (len(text) + 2) // 3),
                            "job_id": job["id"],
                            "agent_generation": int(job.get("agent_generation", 1)),
                        }
                except OSError:
                    handoff = None
                if handoff:
                    job.update(continuation.attest_handoff(job, handoff))
                    job.pop("handoff_degraded", None)
                else:
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
                job.pop("context_usage", None)
                job.update(state="ready", context_rollover_count=rollover_index,
                           updated_at=cli.now())
                cli.atomic_json(path, job)
                cli.audit("task.context_rolled_over", job_id=job["id"],
                          handoff=str(handoff_path.relative_to(cli.ROOT)),
                          durable=job.get("context_state") == "handoff_durable",
                          degraded=bool(job.get("handoff_degraded")))
                print(f"{job['id']} context rolled over; handoff "
                      f"{'attested' if handoff else 'missing, degraded artifact written'}")
                return True
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
