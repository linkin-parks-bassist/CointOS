"""Durably claimed local OpenCode executor for prepared role-context jobs."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from ecosystem import cli
from ecosystem import acceptance
from ecosystem import evidence
from ecosystem import job_outcomes
from ecosystem import models
from ecosystem import opencode_client
from ecosystem import task_contracts
from ecosystem import time_policy
from ecosystem import workload_control
from ecosystem.inference_capacity import reserve_sequence, constrain_launch_capacity
from ecosystem.inference_proxy import (
    cancel as cancel_proxy,
    completed_run_termination,
    issue_proxy_credential,
    opencode_environment,
    populate_opencode_credential,
    revoke_proxy_credential,
)
from ecosystem.models import realize, route, snapshot, observe_opencode_backend_capacity
from ecosystem.opencode_capacity import effective_inference_capacity
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


def gated_child_launch(config_fd: int | None, child_argv: list[str], child_env: dict,
                       *, stdin=None, stdout=None, stderr=None,
                       popen=subprocess.Popen) -> dict:
    """Spawn a wrapper which cannot exec before release.

    config_fd=None passes no credential descriptor to the child and closes
    nothing; the gate, identity checks, and cleanup rules still apply.
    """
    if config_fd is not None and (type(config_fd) is not int or config_fd < 0):
        raise ValueError("config_fd must be an open file descriptor or None")
    if (type(child_argv) is not list or not child_argv
            or any(type(argument) is not str for argument in child_argv)):
        error = ValueError("child_argv must be a non-empty list of strings")
        error.launch_failure = {"spawned": False}
        if config_fd is not None:
            os.close(config_fd)
        raise error
    if (type(child_env) is not dict
            or any(type(key) is not str or type(value) is not str
                   for key, value in child_env.items())):
        error = ValueError("child_env must contain string keys and values")
        error.launch_failure = {"spawned": False}
        if config_fd is not None:
            os.close(config_fd)
        raise error

    config_record_fd = config_fd if config_fd is not None else -1
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
            pass_fds=(gate_read_fd,) if config_fd is None
            else (config_fd, gate_read_fd),
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
            "config_fd": config_record_fd,
            "state": "blocked",
            "outcome": None,
        }
        return record
    except BaseException as error:
        if gate_read_fd >= 0:
            os.close(gate_read_fd)
        if record is None and process is not None:
            record = {
                "process": process,
                "pid": process.pid,
                "start_ticks": None,
                "pgid": process.pid,
                "gate_write_fd": gate_write_fd,
                "config_fd": config_record_fd,
                "state": "blocked",
                "outcome": None,
            }
        if record is not None:
            error.launch_failure = {
                "spawned": True,
                "pid": record["pid"],
                "start_ticks": record.get("start_ticks"),
                "pgid": record["pgid"],
                "cleanup": gated_child_cleanup(record),
            }
        else:
            os.close(gate_write_fd)
            if config_fd is not None:
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


def _cleanup_deadline_seconds() -> float:
    return time_policy.seconds(time_policy.load(), "executor", "cleanup_deadline_seconds")


def gated_child_cleanup(record: dict, timeout: float | None = None) -> dict:
    """Cancel, terminate, and reap an owned gated child within bounded waits."""
    if (record.get("outcome") is not None
            and record["outcome"].get("state") == "reaped"):
        return record["outcome"]
    if timeout is None:
        timeout = _cleanup_deadline_seconds()
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


def _persist_job(path: Path, job: dict) -> None:
    """Publish executor state without erasing concurrent task-control writes.

    Cancellation and child enqueue own fields under task-enqueue.lock. The
    executor re-adopts those fields inside the same lock for every job write.
    Lock order is executor.lock then task-enqueue.lock when both are held.
    """
    with (cli.ROOT / "state/task-enqueue.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _adopt_durable_reservation_state(job, path)
        try:
            durable = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            durable = None
        if (type(durable) is dict and durable.get("id") == job.get("id")
                and durable.get("state") == "interrupted"):
            # Resource checkpoint owns this state after stopping a running
            # lane. Closing/accounting the runner may continue, but no phase
            # write may silently turn the checkpoint back into runnable work.
            job["state"] = "interrupted"
            for field in ("interrupted_by", "interruption_reason", "updated_at",
                          "opencode_session", "resume_available"):
                if field in durable:
                    job[field] = durable[field]
        cli.atomic_json(path, job)


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
        if type(budget) is not dict:
            raise ValueError(
                f"job {job['id']} lacks a remaining task budget for its "
                f"execution deadline")
        task_seconds = budget.get("task_seconds")
        if task_seconds is None:
            job["deadline_monotonic"] = None
        elif type(task_seconds) is int and task_seconds > 0:
            job["deadline_monotonic"] = clock() + task_seconds
        else:
            raise ValueError(
                f"job {job['id']} has an invalid remaining task budget")


def _runner_worker_request(job: dict, route_record: dict) -> dict:
    if "deadline_monotonic" not in job:
        raise ValueError("job lacks authoritative deadline_monotonic")
    request = {
        "workload_class": _required_job_field(job, "workload_class"),
        "model_id": route_record["model_id"],
        "context_tokens": route_record["context_tokens_per_sequence"],
        "max_output_tokens": route_record["max_output_tokens"],
        "deadline_monotonic": job["deadline_monotonic"],
        "owner_identity": _required_job_field(job, "owner_identity"),
        "job_id": job["id"],
        "agent_generation": _required_job_field(job, "agent_generation"),
        "caller_handle": _required_job_field(job, "caller_handle"),
        "request_id": job["runner_worker_request_id"],
        "stop_method": "process_group",
    }
    for field in (
        "role", "authority_profile", "execution_profile", "requirements",
        "prompt_tokens", "tool_tokens", "handoff_tokens", "write_paths", "operator_session_id",
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


def _observe_worker_capacity(root, model_id, *, refresh_inventory, clock):
    """Default observation producer: re-derive one routed model's raw facts.

    Reads the registry item, the residency (incarnation), and the loopback
    backend documents for exactly one routed model, then projects them into the
    incarnation-bound capacity observation. Any missing or contradictory fact
    returns None so the launch stays closed instead of guessing.
    """
    from ecosystem import models
    try:
        registry_document = models._get("/v1/models")
        health_document = models._get("/api/v1/health")
    except Exception:
        return None
    registry = (registry_document.get("data")
                if isinstance(registry_document, dict) else None)
    if not isinstance(registry, list):
        return None
    items = [entry for entry in registry
         if isinstance(entry, dict)
         and entry.get("id") == model_id
         and entry.get("downloaded") is True]
    if len(items) != 1:
        return None
    item = items[0]
    health = (health_document.get("all_models_loaded")
              if isinstance(health_document, dict) else None)
    if not isinstance(health, list):
        return None
    residents = [entry for entry in health
         if isinstance(entry, dict)
         and entry.get("model_name") == model_id
         and "backend_url" in entry]
    if len(residents) != 1:
        return None
    resident = residents[0]
    try:
        identity = process_identity(resident["pid"])
        backend_document = models._get_backend(resident["backend_url"], "/v1/models")
        props = models._get_backend(resident["backend_url"], "/props")
        if process_identity(resident["pid"]) != identity:
            return None
        refreshed = models._get("/api/v1/health")["all_models_loaded"]
        matches = [entry for entry in refreshed if entry.get("model_name") == model_id]
        stable = ("model_name", "backend_url", "pid", "loaded", "backend_alive",
                  "recipe_options", "launch_command")
        if len(matches) != 1 or any(matches[0].get(key) != resident.get(key) for key in stable):
            return None
    except Exception:
        return None
    return observe_opencode_backend_capacity(
        item, resident, backend_document, props, clock())


def _qualify_worker_capability(root, *, refresh_inventory, clock):
    """Observe the installed OpenCode identity and any measured client ceiling.

    Package-version changes are metadata, not admission decisions.  Unknown
    versions run under fresh backend capacity and configured output bounds.
    """
    binary = Path.home() / ".local/bin/opencode"
    try:
        probe = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True, timeout=15)
    except Exception:
        raise ValueError("OpenCode executable is unavailable")
    if probe.returncode != 0:
        raise ValueError("OpenCode executable is unavailable")
    catalogue = opencode_client.load_capability_catalogue(
        Path(root) / "config/opencode-capabilities.json")
    return opencode_client.qualified_opencode_capability(probe.stdout, catalogue)


def _load_capacity_policy(root):
    """Default policy producer: read the checked-in capacity policy.

    The policy is an explicit, checked-in fact: the output reserve, the
    rollover fraction, and the observation freshness window. A missing or
    incomplete policy fails closed so no launch can rely on an implicit default.
    """
    from ecosystem.opencode_capacity import POLICY_KEYS
    source = Path(root) / "config/opencode-capacity.json"
    try:
        policy = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        raise ValueError(
            "capacity policy is missing or unreadable; launch stays closed")
    if not isinstance(policy, dict):
        raise ValueError(
            "capacity policy must be a dictionary; launch stays closed")
    missing = [key for key in POLICY_KEYS if key not in policy]
    if missing:
        raise ValueError(
            f"capacity policy is missing required keys {missing}; "
            "launch stays closed")
    return {key: policy[key] for key in POLICY_KEYS}


def _validate_worker_capacity(
        route_record, root, *, observe_capacity, qualify_capability,
        capacity_policy, refresh_inventory, clock):
    """Validate one admitted route against one fresh live capacity record.

    Produces the incarnation-bound observation and the version-qualified
    OpenCode capability, derives the one effective record for the routed model,
    and checks that the admitted lease's model identity and its context and
    output lease terms fit that live record. Any disagreement, contradiction,
    staleness, or missing fact raises ValueError so the caller keeps the job
    ready and never spawns OpenCode.
    """
    model_id = route_record["model_id"]
    observation = observe_capacity(
        root, model_id, refresh_inventory=refresh_inventory, clock=clock)
    if observation is None:
        raise ValueError(
            f"no live backend capacity observation for routed model {model_id!r}; "
            "launch stays closed")
    capability = qualify_capability(
        root, refresh_inventory=refresh_inventory, clock=clock)
    policy = capacity_policy(root)
    record = effective_inference_capacity(observation, capability, policy, clock())
    lease = {
        "model_id": route_record["model_id"],
        "context_tokens_per_sequence": route_record["context_tokens_per_sequence"],
        "max_output_tokens": route_record["max_output_tokens"],
    }
    return constrain_launch_capacity(lease, record)


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
    observe_capacity=_observe_worker_capacity,
    qualify_capability=_qualify_worker_capability,
    capacity_policy=_load_capacity_policy,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> dict:
    """Compose one trusted R1/R3/R4 runner admission before OpenCode can exec."""
    root = cli.ROOT
    owner = process_identity(os.getpid())
    job.update(
        executor_owner_pid=owner["pid"],
        executor_owner_start_ticks=owner["start_ticks"],
    )
    if job.get("state") in {"ready", "claimed"}:
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
        # Close replay evidence belongs to the allocation generation it closed.
        job.pop("runner_close_outcome", None)
        job.pop("runner_close_state", None)
        job.pop("runner_round_outcome", None)
        job.pop("runner_logical_finalized_generation", None)
        _persist_job(job_path, job)
    elif job.get("state") != "runner_starting":
        raise ValueError("runner round requires claimed or runner_starting job")

    worker_request = job.get("runner_worker_request")
    if worker_request is None:
        _claim_execution(job, clock)
        worker_request = _runner_worker_request(job, route_record)
        job["runner_worker_request"] = worker_request
    elif type(worker_request) is not dict:
        raise ValueError("invalid durable runner worker request")
    job["runner_phase"] = "capacity_preflight"
    _persist_job(job_path, job)
    try:
        capacity_record = _validate_worker_capacity(
            route_record, root, observe_capacity=observe_capacity,
            qualify_capability=qualify_capability,
            capacity_policy=capacity_policy,
            refresh_inventory=refresh_inventory, clock=clock)
    except Exception as error:
        job.update(
            state="ready", updated_at=cli.now(),
            runner_deferred_reasons=[f"{type(error).__name__}: {error}"])
        _persist_job(job_path, job)
        return {"state": "deferred", "job": job}
    job["runner_phase"] = "r1_acquire_intent"
    _persist_job(job_path, job)
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
            _persist_job(job_path, job)
            return {"state": "deferred", "job": job}
        job["worker_lease_id"] = worker_lease["lease_id"]
        job["runner_phase"] = "r1_acquired"
        _persist_job(job_path, job)

        opencode = opencode_environment(root, capacity_record, b"\0" * 32)
        environment = os.environ.copy()
        environment.update(opencode["environment"])
        environment["AGENT_JOB_ID"] = job["id"]
        job["runner_phase"] = "spawn_intent"
        _persist_job(job_path, job)
        launch_record = launch(
            opencode["fd"], command, environment,
            stdin=stdin, stdout=stdout, stderr=stderr,
        )
        job.update(
            runner_phase="spawned", executor_pid=launch_record["pid"],
            executor_start_ticks=launch_record["start_ticks"],
            executor_pgid=launch_record["pgid"],
        )
        _persist_job(job_path, job)
        job["runner_phase"] = "process_register_intent"
        _persist_job(job_path, job)
        register(
            root, worker_lease["lease_id"], launch_record["pid"],
            launch_record["start_ticks"], clock,
        )
        process_registered = True
        if worker_request.get("operator_session_id"):
            from ecosystem.operator_session import register_operator_process
            register_operator_process(root, worker_request["operator_session_id"],
                                      launch_record["pid"], launch_record["start_ticks"], clock)
        job["runner_phase"] = "process_registered"
        _persist_job(job_path, job)
        sequence_request = _runner_sequence_request(
            root, job, worker_lease, worker_request, route_record,
        )
        job["runner_sequence_request"] = sequence_request
        job["runner_phase"] = "r3_reserve_intent"
        _persist_job(job_path, job)
        inference_lease = reserve(root, sequence_request, inventory, clock)
        while inference_lease.get("state") in {
            "waiting_for_preemption", "ready_for_revalidation",
        }:
            job.update(
                runner_phase="r3_waiting",
                inference_lease_id=inference_lease["lease_id"],
                updated_at=cli.now(),
            )
            _persist_job(job_path, job)
            if (worker_request["deadline_monotonic"] is not None
                    and clock() >= worker_request["deadline_monotonic"]):
                outcome = gated_child_cleanup(launch_record)
                if outcome.get("state") != "reaped" or outcome.get("process_group_alive") is not False:
                    raise RuntimeError("waiting acquisition cleanup is unresolved")
                from ecosystem.inference_capacity import withdraw_unissued_sequence
                withdraw_unissued_sequence(root, inference_lease["lease_id"], clock)
                _observe_stopped_worker(root, worker_lease, launch_record, outcome,
                                       {"state": "deferred", "returncode": outcome["returncode"]},
                                       clock, release, observe)
                job.update(state="ready", updated_at=cli.now(),
                           runner_deferred_reasons=["acquisition deadline; request retained"])
                _persist_job(job_path, job)
                return {"state": "deferred", "job": job}
            sleeper(0.05)
            inventory = refresh_inventory()
            previous_lease = inference_lease
            inference_lease = reserve(root, sequence_request, inventory, clock)
            if inference_lease.get("state") == "deferred":
                inference_lease["pending_acquisition"] = previous_lease
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
                _persist_job(job_path, job)
                return {"state": "reconciliation_required", "job": job}
            pending = inference_lease.get("pending_acquisition")
            if pending:
                from ecosystem.inference_capacity import withdraw_unissued_sequence
                withdraw_unissued_sequence(root, pending["lease_id"], clock)
            _observe_stopped_worker(
                root, worker_lease, launch_record, outcome,
                {"state": "deferred", "returncode": outcome["returncode"]},
                clock, release, observe,
            )
            job.update(state="ready", updated_at=cli.now(),
                       runner_deferred_reasons=inference_lease.get("reasons", []))
            _persist_job(job_path, job)
            return {"state": "deferred", "job": job}
        if (inference_lease.get("state") not in {"starting", "active"}
                or type(inference_lease.get("backend_sequence")) is not int
                or type(inference_lease.get("expected_release_binding")) is not dict):
            raise ValueError("inference reservation is not credential-ready")
        job["inference_lease_id"] = inference_lease["lease_id"]
        job["runner_phase"] = "r3_reserved"
        _persist_job(job_path, job)
        expected = (
            route_record["model_id"], route_record["context_tokens_per_sequence"],
            route_record["max_output_tokens"],
        )
        actual = (
            inference_lease.get("model_id"), inference_lease.get("context_tokens"),
            inference_lease.get("max_output_tokens"),
        )
        job["runner_phase"] = "credential_issue_intent"
        _persist_job(job_path, job)
        issue(root, inference_lease,
              lambda credential: populate(opencode, credential), clock)
        credential_issued = True
        job["runner_phase"] = "credential_issued"
        _persist_job(job_path, job)
        if actual != expected:
            raise ValueError("inference lease limits differ from admitted route")
        job["runner_phase"] = "gate_release_intent"
        _persist_job(job_path, job)
        release_gate(launch_record)
        job["runner_phase"] = "gate_released"
        _persist_job(job_path, job)
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
        _persist_job(job_path, job)
        return {
            "state": "running", "launch": launch_record,
            "worker_lease": worker_lease, "inference_lease": inference_lease,
        }
    except BaseException as error:
        if inference_lease is not None and inference_lease.get("state") != "deferred":
            job.update(
                state="reconciliation_required", updated_at=cli.now(),
                worker_lease_id=worker_lease["lease_id"],
                inference_lease_id=inference_lease["lease_id"],
                reconciliation_reason=f"{type(error).__name__}: {error}",
            )
            _persist_job(job_path, job)
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
                _persist_job(job_path, job)
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
        _persist_job(job_path, job)
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
    root: Path | None = None,
) -> dict:
    """Close R4 then R3 then R1, or retain both leases for reconciliation."""
    if ("runner_closed_generation" in job
            and job["runner_closed_generation"] == job.get("runner_generation")):
        return {"state": job["runner_close_state"]}
    root = Path(root) if root is not None else cli.ROOT
    saved_outcome = job.get("runner_close_outcome")
    if saved_outcome is not None and saved_outcome != child_outcome:
        raise ValueError("runner close outcome changed during replay")
    if saved_outcome is None:
        job["runner_close_outcome"] = json.loads(json.dumps(child_outcome, sort_keys=True))
        job["runner_phase"] = "close_intent"
        _persist_job(job_path, job)
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
        _persist_job(job_path, job)
        return {"state": "reconciliation_required"}
    evidence = termination(root, inference_lease["lease_id"])
    if evidence is None:
        job.update(
            state="reconciliation_required", updated_at=cli.now(),
            worker_lease_id=worker_lease["lease_id"],
            inference_lease_id=inference_lease["lease_id"],
            reconciliation_reason="verified backend termination is unavailable",
        )
        _persist_job(job_path, job)
        return {"state": "reconciliation_required"}
    revoked = revoke(root, inference_lease["lease_id"], evidence, clock)
    if revoked.get("state") != "revoked" \
            or revoked.get("sequence", {}).get("state") != "released":
        raise RuntimeError("proxy close did not release the inference sequence")
    final_state = "run_finished" if child_outcome["returncode"] == 0 else "failed"
    worker_outcome = {"state": final_state, "returncode": child_outcome["returncode"]}
    _observe_stopped_worker(
        root, worker_lease, launch_record, child_outcome, worker_outcome,
        clock, release, observe,
    )
    job.update(state=final_state, updated_at=cli.now(),
               exit_code=child_outcome["returncode"],
               runner_closed_generation=job.get("runner_generation"),
               runner_close_state=final_state)
    job.pop("executor_pid", None)
    _persist_job(job_path, job)
    return {"state": final_state, "credential": revoked}


def queue_notifications(job: dict) -> None:
    from ecosystem.outbox import enqueue_result, result_recipients
    recipients = job.get("result_notification_recipients")
    if recipients is None:
        recipients = result_recipients()
    for recipient in recipients:
        enqueue_result(int(recipient), job["id"])


def _finalize_run_finished(job: dict, path: Path) -> None:
    """Publish the logical result of a verified, successful runner close."""
    if not job.get("verifies"):
        from ecosystem.outbox import result_recipients
        job.setdefault("result_notification_recipients", result_recipients())
    job["runner_logical_finalized_generation"] = job.get("runner_generation")
    if job.get("verifies"):
        from ecosystem.verification import finalize
        target = finalize(job)
        if job["state"] == "run_finished":
            job.update(state="completed", updated_at=cli.now())
            _persist_job(path, job)
        queue_notifications(target)
    elif job.get("verification_requested") is True:
        from ecosystem.verification import enqueue
        job.update(state="awaiting_verification", updated_at=cli.now())
        _persist_job(path, job)
        enqueue(job)
    else:
        gate = acceptance.artifact_failure(job.get("task_contract"))
        if gate is not None:
            job.update(state="failed", logical_run_state="terminal",
                       error=gate, updated_at=cli.now())
            cli.audit("task.acceptance_failed", job_id=job["id"], error=gate)
        else:
            job.update(state="completed", logical_run_state="terminal",
                       completed_at=cli.now(), updated_at=cli.now())
        _persist_job(path, job)
        queue_notifications(job)


def _process_alive(job: dict) -> bool:
    owner_pid = job.get("executor_owner_pid")
    owner_start_ticks = job.get("executor_owner_start_ticks")
    if type(owner_pid) is int and type(owner_start_ticks) is int:
        try:
            return process_identity(owner_pid)["start_ticks"] == owner_start_ticks
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            return False
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


def _stop_recovered_runner(job: dict, timeout: float | None = None) -> bool | None:
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
    if timeout is None:
        timeout = _cleanup_deadline_seconds()
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
    """Reconcile dead owners under the same lock used by durable claims."""
    cli.initialize()
    with (cli.ROOT / "state/executor.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _recover_abandoned_jobs_locked()


def _recover_early_runner_prefix(path: Path, job: dict) -> None:
    """Resolve an ownerless R1 prefix before returning its job to ready.

    A crash between acquire_worker and persisting worker_lease_id is possible,
    so the durable request identity, not only the job field, locates the lease.
    Only a provably never-spawned/quiescent lease permits retry. Contradictory
    process evidence remains reconciliation_required and blocks unload.
    """
    request_id = job.get("runner_worker_request_id")
    reason = None
    lease = None
    if type(request_id) is not str or not request_id:
        reason = "early runner prefix has no durable worker request identity"
    else:
        try:
            lease = workload_control.find_worker_lease_by_request(cli.ROOT, request_id)
        except (OSError, ValueError) as error:
            reason = f"worker lease lookup failed: {type(error).__name__}: {error}"
    expected = job.get("worker_lease_id")
    if reason is None and expected and (lease is None or lease.get("lease_id") != expected):
        reason = "early runner worker lease identity does not match durable request"
    if reason is None and lease is not None:
        process = lease.get("process")
        if process is not None:
            # An early phase should precede spawn intent. A registered process
            # contradicts that phase; stop only an exact kernel identity, then
            # retain reconciliation for backend/credential proof.
            pid = process.get("pid") if type(process) is dict else None
            ticks = process.get("process_start_ticks") if type(process) is dict else None
            group_alive = None
            if type(pid) is int and type(ticks) is int:
                try:
                    identity = process_identity(pid)
                    if identity["start_ticks"] == ticks and identity["pgid"] == pid:
                        group_alive = _stop_recovered_runner({
                            "executor_pid": pid, "executor_start_ticks": ticks,
                            "executor_pgid": pid,
                        })
                except (OSError, ValueError):
                    pass
            job["recovery_process_group_alive"] = group_alive
            reason = "early runner phase contradicts registered process identity"
        elif lease.get("state") != "quiescent":
            try:
                workload_control.release_worker(
                    cli.ROOT, lease["lease_id"],
                    {"state": "failed", "error": "executor disappeared before runner spawn"},
                    time.monotonic,
                )
                workload_control.observe_workers(cli.ROOT, [{
                    "lease_id": lease["lease_id"], "never_spawned": True,
                    "process_group_alive": False,
                    "backend_request_active": False,
                    "inference_lease_active": False,
                }], time.monotonic)
                settled = workload_control.find_worker_lease_by_request(
                    cli.ROOT, request_id)
                if settled is None or settled.get("state") != "quiescent":
                    reason = "early runner worker lease did not become quiescent"
            except (OSError, RuntimeError, ValueError) as error:
                reason = f"early runner worker lease could not close: {type(error).__name__}: {error}"
    if reason is not None:
        job.update(state="reconciliation_required", updated_at=cli.now(),
                   reconciliation_reason=reason)
        _persist_job(path, job)
        cli.audit("task.reconciliation_required", job_id=job["id"],
                  runner_phase=job.get("runner_phase"), reason=reason)
        return
    stamp = cli.now()
    if job.get("cancellation_requested_at"):
        job.update(state="cancelled", logical_run_state="terminal",
                   cancelled_at=stamp, updated_at=stamp)
        event = "task.cancelled"
    else:
        job.update(state="ready", updated_at=stamp,
                   abandoned_dispatch_recovered_at=stamp)
        event = "task.early_runner_recovered"
    for field in ("worker_lease_id", "executor_pid", "executor_start_ticks",
                  "executor_pgid", "executor_owner_pid", "executor_owner_start_ticks"):
        job.pop(field, None)
    _persist_job(path, job)
    cli.audit(event, job_id=job["id"], runner_phase=job.get("runner_phase"))


def _recover_closed_round(path: Path, job: dict) -> bool:
    """Replay a dead owner's post-close policy from generation-bound evidence.

    Legacy records without an observed round result are left untouched: their
    budget/preemption decision cannot be reconstructed from process exit alone.
    """
    envelope = job.get("runner_round_outcome")
    if envelope is None:
        return False
    generation = job.get("runner_generation")
    closed = job.get("runner_close_outcome")
    result = envelope.get("result") if type(envelope) is dict else None
    valid = (
        type(generation) is int
        and type(envelope) is dict
        and envelope.get("runner_generation") == generation
        and job.get("runner_closed_generation") == generation
        and type(closed) is dict
        and closed.get("state") == "reaped"
        and closed.get("process_group_alive") is False
        and type(result) is dict
        and type(result.get("returncode")) is int
        and closed.get("returncode") == result["returncode"]
        and type(result.get("preempted")) is bool
        and type(result.get("usage")) is dict
        and (result.get("session") is None
             or type(result.get("session")) is str)
        and ("budget_checkpoint" not in result
             or (type(result["budget_checkpoint"]) is dict
                 and type(result["budget_checkpoint"].get("reason")) is str
                 and bool(result["budget_checkpoint"]["reason"])))
        and (not result["preempted"]
             or (type(result.get("reason")) is str
                 and bool(result["reason"])))
        and job.get("runner_close_state") == (
            "run_finished" if result["returncode"] == 0 else "failed")
        and job.get("state") == job.get("runner_close_state")
    )
    if not valid:
        job.update(state="reconciliation_required", updated_at=cli.now(),
                   reconciliation_reason="post-close round evidence is inconsistent",
                   post_close_outcome_review_required=True)
        _persist_job(path, job)
        cli.audit("task.reconciliation_required", job_id=job["id"],
                  reason=job["reconciliation_reason"])
        return True
    if _complete_requested_cancellation(job, path, result):
        return True
    if result.get("budget_checkpoint"):
        checkpoint = result["budget_checkpoint"]
        job = job_outcomes.budget_checkpoint_job(
            job, checkpoint, result.get("session"), cli.now())
        continuation = job["state"] == "ready"
        _persist_job(path, job)
        cli.audit("task.budget_continuation_queued" if continuation
                  else "task.budget_checkpoint", job_id=job["id"],
                  reason=checkpoint["reason"])
        return True
    if result["preempted"]:
        job = job_outcomes.preempted_job(
            job, result.get("session"), result["reason"], cli.now())
        _persist_job(path, job)
        cli.audit("task.preempted", job_id=job["id"],
                  reason=result["reason"],
                  resume_available=bool(result.get("session")))
        return True
    if job["state"] == "run_finished":
        _finalize_run_finished(job, path)
    else:
        if not job.get("verifies"):
            from ecosystem.outbox import result_recipients
            job.setdefault("result_notification_recipients", result_recipients())
        job["runner_logical_finalized_generation"] = generation
        _persist_job(path, job)
        if job.get("verifies"):
            from ecosystem.verification import finalize
            queue_notifications(finalize(job))
        else:
            queue_notifications(job)
    cli.audit("task.post_close_recovered", job_id=job["id"], state=job["state"])
    return True


def _recover_abandoned_jobs_locked() -> int:
    recovered = 0
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (job.get("kind") == "agent-task"
                and job.get("state") in {"run_finished", "failed"}
                and job.get("runner_round_outcome") is not None
                and job.get("runner_closed_generation") == job.get("runner_generation")
                and job.get("runner_logical_finalized_generation")
                    != job.get("runner_generation")):
            if not _process_alive(job) and _recover_closed_round(path, job):
                recovered += 1
            continue
        unclosed_failed_round = (
            job.get("state") == "failed"
            and job.get("runner_round_outcome") is not None
            and job.get("runner_logical_finalized_generation")
                != job.get("runner_generation")
        )
        if (job.get("kind") != "agent-task"
                or (job.get("state") not in {
                    "claimed", "runner_starting", "running",
                    "reconciliation_required",
                } and not unclosed_failed_round)):
            continue
        # Recovery also runs from watchdog processes while an executor owns a
        # round. Preserve every phase of a healthy foreign owner, including a
        # persisted close intent. Exact PID/start-tick identity prevents a
        # recycled PID from keeping an abandoned round alive.
        if _process_alive(job):
            continue
        if job.get("post_close_outcome_review_required"):
            continue
        if job.get("state") == "claimed":
            # No runner or inference lease exists yet. A dead executor's
            # durable claim can return to the ready queue unless cancellation
            # was requested while the owner still held it.
            stamp = cli.now()
            cancellation = job.get("cancellation_requested_at")
            if type(cancellation) is str and cancellation:
                job.update(state="cancelled", logical_run_state="terminal",
                           cancelled_at=stamp, updated_at=stamp)
                event = "task.cancelled"
            else:
                job.update(state="ready", updated_at=stamp,
                           abandoned_dispatch_recovered_at=stamp)
                event = "task.abandoned_claim_recovered"
            job.pop("executor_owner_pid", None)
            job.pop("executor_owner_start_ticks", None)
            _persist_job(path, job)
            cli.audit(event, job_id=job["id"])
            recovered += 1
            continue
        if (job.get("runner_close_outcome") is not None
                and job.get("worker_lease_id") and job.get("inference_lease_id")):
            already_closed = (
                job.get("runner_closed_generation") == job.get("runner_generation")
                and job["runner_close_outcome"].get("process_group_alive") is False
            )
            group_alive = False if already_closed else _stop_recovered_runner(job)
            if group_alive is False:
                launch = job["runner_close_outcome"] if already_closed else {
                    "pid": job["executor_pid"],
                    "start_ticks": job["executor_start_ticks"],
                    "pgid": job["executor_pgid"],
                }
                context = {
                    "worker_lease": {"lease_id": job["worker_lease_id"]},
                    "inference_lease": {"lease_id": job["inference_lease_id"]},
                    "launch": launch,
                }
                try:
                    closed = close_runner_round(
                        job, path, context, job["runner_close_outcome"])
                except (OSError, RuntimeError, ValueError):
                    closed = {"state": "reconciliation_required"}
                if closed["state"] != "reconciliation_required":
                    if (job.get("state") in {"run_finished", "failed"}
                            and job.get("runner_round_outcome") is not None
                            and _recover_closed_round(path, job)):
                        recovered += 1
                        continue
                    pending_preemption = job.pop("pending_preemption_reason", None)
                    session = job.get("opencode_session") or opencode_session_id(
                        cli.ROOT / job.get("output", ""))
                    cancellation = job.get("cancellation_requested_at")
                    if type(cancellation) is str and cancellation:
                        stamp = cli.now()
                        job.update(
                            state="cancelled", logical_run_state="terminal",
                            cancelled_at=stamp, updated_at=stamp,
                            last_preemption_reason=(
                                "cancellation completed during reconciliation"
                            ),
                            runner_close_state="cancelled",
                        )
                        job.pop("reconciliation_reason", None)
                        job.pop("executor_pid", None)
                        _persist_job(path, job)
                        cli.audit("task.cancelled", job_id=job["id"],
                                  reason="cancellation completed during reconciliation")
                    elif pending_preemption and session:
                        job.update(
                            state="ready", logical_run_state="continuing",
                            opencode_session=session, resume_available=True,
                            last_preemption_reason=pending_preemption,
                            preemption_count=int(job.get("preemption_count", 0)) + 1,
                            updated_at=cli.now(),
                        )
                        job.pop("reconciliation_reason", None)
                        job.pop("executor_pid", None)
                        _persist_job(path, job)
                        cli.audit("task.preempted", job_id=job["id"],
                                  reason=pending_preemption, resume_available=True)
                    else:
                        session = job.get("opencode_session") or opencode_session_id(
                            cli.ROOT / job.get("output", ""))
                        if session:
                            job.update(
                                state="ready", logical_run_state="continuing",
                                opencode_session=session, resume_available=True,
                                last_preemption_reason="executor service restarted",
                                preemption_count=int(job.get("preemption_count", 0)) + 1,
                                updated_at=cli.now(),
                            )
                            job.pop("reconciliation_reason", None)
                            job.pop("executor_pid", None)
                            _persist_job(path, job)
                            cli.audit(
                                "task.restart_recovered", job_id=job["id"],
                                resume_available=True,
                            )
                    recovered += 1
                    continue
            job["recovery_process_group_alive"] = group_alive
            job.update(state="reconciliation_required", updated_at=cli.now())
            _persist_job(path, job)
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
            _persist_job(path, job)
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
            group_alive = _stop_recovered_runner(job)
            job["recovery_process_group_alive"] = group_alive
            if group_alive is False and job.get("worker_lease_id"):
                child_outcome = {
                    "state": "reaped",
                    "returncode": -signal.SIGKILL,
                    "process_group_alive": False,
                }
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
                    closed = close_runner_round(job, path, context, child_outcome)
                except (OSError, RuntimeError, ValueError):
                    closed = {"state": "reconciliation_required"}
                if closed["state"] != "reconciliation_required":
                    cancellation = job.get("cancellation_requested_at")
                    if type(cancellation) is str and cancellation:
                        stamp = cli.now()
                        job.update(
                            state="cancelled", logical_run_state="terminal",
                            cancelled_at=stamp, updated_at=stamp,
                            last_preemption_reason=(
                                "cancellation completed during restart recovery"
                            ),
                            runner_close_state="cancelled",
                        )
                        job.pop("reconciliation_reason", None)
                        job.pop("executor_pid", None)
                        _persist_job(path, job)
                        cli.audit(
                            "task.cancelled", job_id=job["id"],
                            reason="cancellation completed during restart recovery",
                        )
                        recovered += 1
                        continue
                    output = cli.ROOT / job.get("output", "")
                    session = job.get("opencode_session") or opencode_session_id(output)
                    if session:
                        job.update(
                            state="ready", logical_run_state="continuing",
                            opencode_session=session, resume_available=True,
                            last_preemption_reason="executor service restarted",
                            preemption_count=int(job.get("preemption_count", 0)) + 1,
                            updated_at=cli.now(),
                        )
                        job.pop("reconciliation_reason", None)
                        job.pop("executor_pid", None)
                        _persist_job(path, job)
                        cli.audit(
                            "task.restart_recovered", job_id=job["id"],
                            resume_available=True,
                        )
                        recovered += 1
                        continue
            job.update(
                state="reconciliation_required", updated_at=cli.now(),
                reconciliation_reason="runner disappeared after inference reservation",
            )
            _persist_job(path, job)
            cli.audit("task.reconciliation_required", job_id=job["id"],
                      inference_lease_id=job["inference_lease_id"])
            recovered += 1
            continue
        if job.get("state") == "runner_starting":
            _recover_early_runner_prefix(path, job)
            recovered += 1
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
        _persist_job(path, job)
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
                and job.get("state") == "ready"
                and job_admitted_in_current_mode(job)):
            waiting.append(job)
    return waiting


def _preemption_reason(job: dict, fairness_started: float | None,
                       scheduling: dict) -> str | None:
    try:
        durable = json.loads(
            (cli.ROOT / "state/jobs" / f"{job['id']}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        durable = None
    if (type(durable) is dict and durable.get("id") == job.get("id")
            and type(durable.get("cancellation_requested_at")) is str
            and durable["cancellation_requested_at"]):
        return "authenticated contact requested cancellation"
    lease_id = job.get("inference_lease_id")
    if lease_id:
        capacity = json.loads((cli.ROOT / "state/inference-capacity.json").read_text())
        if capacity.get("leases", {}).get(lease_id, {}).get("state") == "preemption_requested":
            return "higher-priority inference needs this allocation"
    waiting = _waiting_jobs(job["id"])
    if not waiting:
        return None
    strongest = max(waiting, key=lambda item: priority(item, scheduling))
    strongest_priority = priority(strongest, scheduling)
    running_priority = priority(job, scheduling)
    if strongest_priority > running_priority:
        return (f"higher-priority job {strongest['id']} is waiting "
                f"({strongest_priority} > {running_priority})")
    if strongest_priority < running_priority:
        return None
    quantum = float(scheduling_policy()["workers"]["time_slice_seconds"])
    if fairness_started is not None and time.monotonic() - fairness_started >= quantum:
        return f"{quantum:.0f}-second time slice expired while other work is waiting"
    return None


def _completed_step_after(output_path: Path, offset: int,
                          session: str | None) -> bool:
    try:
        with output_path.open("rb") as stream:
            stream.seek(offset)
            for raw in stream:
                try:
                    event = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if (event.get("type") == "step_finish"
                        and (session is None or event.get("sessionID") == session)):
                    return True
    except OSError:
        return False
    return False


def _close_usage(budget: dict, usage: dict, output_path: Path,
                 last_output_bytes: int, stopped: float) -> dict:
    """Close both observed intervals and count output written up to the stop."""
    from ecosystem import execution_budget
    if output_path.exists():
        size = output_path.stat().st_size
        if size > last_output_bytes:
            usage = execution_budget.account_usage(
                budget, usage, {"kind": "output", "bytes": size - last_output_bytes})
    usage = execution_budget.account_usage(
        budget, usage, {"kind": "run_stopped", "at": stopped})
    usage = execution_budget.account_usage(
        budget, usage, {"kind": "task_stopped", "at": stopped})
    return usage


def _adopt_durable_reservation_state(job: dict, job_path: Path) -> None:
    """Re-adopt the parent's authoritative reservation state from disk.

    enqueue_child durably deducts the child's budget from remaining_budget
    and records child_reservations under task-enqueue.lock while the runner
    round is in flight. The executor's cached parent copy goes stale;
    re-adopt the authoritative fields before persisting so the write-back
    cannot clobber the reservation.
    """
    try:
        durable = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if type(durable) is not dict or durable.get("id") != job.get("id"):
        return
    if "remaining_budget" in durable:
        job["remaining_budget"] = durable["remaining_budget"]
    if "child_reservations" in durable:
        job["child_reservations"] = durable["child_reservations"]
    if "cancellation_requested_at" in durable:
        job["cancellation_requested_at"] = durable["cancellation_requested_at"]
    if "cancellation_reason" in durable:
        job["cancellation_reason"] = durable["cancellation_reason"]


def _persist_parent_job(job: dict, job_path: Path) -> None:
    """Persist the cached parent without clobbering its durable reservation
    state written under task-enqueue.lock."""
    _persist_job(job_path, job)


def _complete_requested_cancellation(job: dict, job_path: Path,
                                     outcome: dict) -> bool:
    """Make a durable cancellation terminal after the runner is closed.

    Cancellation must win over every continuation policy, including a budget
    checkpoint observed during the same runner round.
    """
    try:
        current = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    cancellation = current.get("cancellation_requested_at")
    if type(cancellation) is not str or not cancellation:
        return False
    session = outcome.get("session")
    if session:
        job["opencode_session"] = session
        job["resume_available"] = True
    elif not job.get("opencode_session"):
        job["resume_available"] = False
    job["cancellation_requested_at"] = cancellation
    if "cancellation_reason" in current:
        job["cancellation_reason"] = current["cancellation_reason"]
    job.pop("executor_pid", None)
    job.pop("pending_preemption_reason", None)
    job.pop("reconciliation_reason", None)
    stamp = cli.now()
    reason = outcome.get("reason") or "cancellation completed after runner close"
    job.update(state="cancelled", logical_run_state="terminal",
               cancelled_at=stamp, updated_at=stamp,
               last_preemption_reason=reason,
               runner_close_state="cancelled")
    _persist_job(job_path, job)
    cli.audit("task.cancelled", job_id=job["id"], reason=reason)
    print(f"{job['id']} cancelled: {reason}")
    return True


def _run_preemptibly(process: subprocess.Popen, command: list[str], job: dict,
                     output_path: Path, before_stop, scheduling: dict,
                     initial_output_bytes: int | None = None) -> dict:
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

    usage = dict(job.get("budget_usage") or {})
    # A new runner round starts fresh: live interval markers never carry
    # across rounds, and the per-round run budget resets each round.
    # Task-level counters (task_seconds, output_bytes, evidence_items,
    # children) persist; the attempts policy stays on the job counter.
    usage.pop("run_started", None)
    usage.pop("task_started", None)
    usage.pop("run_seconds", None)
    usage["attempts"] = int(job.get("attempts", 0))
    usage["output_bytes"] = usage.get("output_bytes", 0)
    usage = execution_budget.account_usage(
        budget, usage, {"kind": "run_started", "at": started})
    usage = execution_budget.account_usage(
        budget, usage, {"kind": "task_started", "at": started})
    if initial_output_bytes is None:
        initial_output_bytes = output_path.stat().st_size if output_path.exists() else 0
    last_output_bytes = initial_output_bytes
    fairness_started = None
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
            before_stop()
            execution_budget.stop_process_group(
                process.pid, wrapup_seconds, grace_seconds, observe)
            stopped = time.monotonic()
            return {"returncode": process.wait(), "preempted": False,
                    "budget_checkpoint": outcome,
                    "session": job.get("opencode_session") or opencode_session_id(output_path),
                    "usage": _close_usage(budget, usage, output_path,
                                          last_output_bytes, stopped),
                    "elapsed_seconds": round(stopped - started, 3)}
        elapsed = now - started
        # OpenCode owns context compaction within its durable session.
        session = job.get("opencode_session") or opencode_session_id(output_path)
        if (fairness_started is None
                and _completed_step_after(output_path, initial_output_bytes, session)):
            fairness_started = now
        reason = _preemption_reason(job, fairness_started, scheduling)
        if reason:
            # Give OpenCode a short initial window to publish its durable session id.
            if session or elapsed >= float(settings["preemption_grace_seconds"]):
                before_stop()
                execution_budget.stop_process_group(
                    process.pid, wrapup_seconds, grace_seconds, observe)
                session = session or opencode_session_id(output_path)
                return {"returncode": process.returncode, "preempted": True,
                        "reason": reason, "session": session,
                        "usage": _close_usage(budget, usage, output_path,
                                               last_output_bytes,
                                               time.monotonic()),
                        "elapsed_seconds": round(elapsed, 3)}
        time.sleep(1)
    stopped = time.monotonic()
    return {"returncode": process.returncode, "preempted": False,
            "usage": _close_usage(budget, usage, output_path,
                                  last_output_bytes, stopped),
            "elapsed_seconds": round(stopped - started, 3)}


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


def _resume_without_handoff(job: dict) -> bool:
    """Retire legacy rollover markers only when the client session is retained.

    An already detached context needs explicit recovery review rather than silently
    starting fresh or reconstructing it from a generated handoff.
    """
    if job.get("context_state") not in (
            "handoff_requested", "handoff_durable", "continuation_ready"):
        return True
    if not job.get("opencode_session"):
        return False
    job["context_state"] = "running"
    if job.get("original_prompt"):
        job["prompt"] = job["original_prompt"]
    return True


def _durably_claim_job(path: Path, job: dict) -> bool:
    """Transfer one selected job from the queue to this exact executor.

    Caller holds state/executor.lock. The atomic state/identity write must
    complete before releasing it; subsequent stages own only this record.
    """
    with (cli.ROOT / "state/task-enqueue.lock").open("w") as task_lock:
        fcntl.flock(task_lock, fcntl.LOCK_EX)
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if (current.get("id") != job.get("id")
                or current.get("state") != job.get("state")
                or current.get("state") not in {"ready", "runner_starting"}):
            return False
        if current.get("cancellation_requested_at"):
            stamp = cli.now()
            current.update(state="cancelled", logical_run_state="terminal",
                           cancelled_at=stamp, updated_at=stamp)
            cli.atomic_json(path, current)
            cli.audit("task.cancelled", job_id=current["id"],
                      reason="cancellation completed before runner launch")
            return False
        job.clear()
        job.update(current)
        owner = process_identity(os.getpid())
        job.update(
            state="claimed" if job["state"] == "ready" else "runner_starting",
            executor_owner_pid=owner["pid"],
            executor_owner_start_ticks=owner["start_ticks"],
            claimed_at=cli.now(), updated_at=cli.now(),
        )
        cli.atomic_json(path, job)
        return True


def execute_next(run=subprocess.run) -> bool:
    cli.initialize()
    if (cli.ROOT / "state/PAUSED").exists():
        print("ecosystem is paused")
        return False
    lock_path = cli.ROOT / "state/executor.lock"
    with lock_path.open("w") as lock:
        # The lock now covers only recovery, selection, and the durable claim.
        # Concurrent lanes wait for that short transaction, then reselect a
        # different ready job instead of disappearing until the next timer.
        fcntl.flock(lock, fcntl.LOCK_EX)
        _recover_abandoned_jobs_locked()
        ready = []
        for path in sorted((cli.ROOT / "state/jobs").glob("*.json")):
            job = json.loads(path.read_text(encoding="utf-8"))
            if (job.get("kind") == "agent-task"
                    and job["state"] in {"ready", "runner_starting"}
                    and (job["state"] != "runner_starting"
                         or not _process_alive(job))
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
            if not _durably_claim_job(path, job):
                return False
            # The record, not this lock, now protects ownership. Realizing a
            # model and running OpenCode may take hours; another executor can
            # claim a different ready job while this one remains live-owned.
            fcntl.flock(lock, fcntl.LOCK_UN)
            if not _resume_without_handoff(job):
                reason = "legacy context rollover has no retained OpenCode session; review recovery manually"
                job.update(state="queued", model_reason=reason, updated_at=cli.now())
                _persist_job(path, job)
                cli.audit("task.routing_deferred", job_id=job["id"], reason=reason)
                print(f"{job['id']} routing deferred: {reason}")
                return False
            try:
                decision = route(job, inventory)
            except Exception as error:
                reason = f"model routing failed before runner launch: {type(error).__name__}: {error}"
                job.update(state="ready", model_reason=reason, updated_at=cli.now())
                _persist_job(path, job)
                cli.audit("task.routing_deferred", job_id=job["id"], reason=reason)
                print(f"{job['id']} routing deferred: {reason}")
                return False
            job.setdefault("routing_decisions", []).append({"at": cli.now(), **decision})
            job["resource_snapshot"] = inventory
            if decision["action"] == "defer":
                job.update(state="queued", model=None, model_reason=decision["reason"],
                           updated_at=cli.now())
                job.pop("prompt", None)
                if job.get("opencode_session") and job.get("context_state") in (None, "running"):
                    job["context_state"] = "paused_for_resources"
                _persist_job(path, job)
                cli.audit("task.routing_deferred", job_id=job["id"], reason=decision["reason"])
                print(f"{job['id']} routing deferred: {decision['reason']}")
                return False
            model_changed = decision["model"] != job.get("model")
            if model_changed:
                job.update(model=decision["model"], model_reason=decision["reason"])
                prompt_path = cli.ROOT / "state/jobs" / f"{job['id']}.prompt.md"
                cli.atomic_text(prompt_path, job["task"].strip() + "\n")
                job["prompt"] = str(prompt_path.relative_to(cli.ROOT))
                job.setdefault("original_prompt", job["prompt"])
            else:
                job["model_reason"] = decision["reason"]
            # Shared realization ownership includes native/control callers.
            # Never hold this lock through runner admission.
            with models.realization_lock(cli.ROOT):
                # Another executor may have loaded or reclaimed residency
                # while this lane waited for the model lock. Reject a stale
                # route and let a later pass select from fresh facts.
                try:
                    fresh_inventory = snapshot()
                    fresh_decision = route(job, fresh_inventory)
                except Exception as error:
                    reason = f"pre-realization route refresh failed: {type(error).__name__}: {error}"
                    job.update(state="ready", model_reason=reason, updated_at=cli.now())
                    _persist_job(path, job)
                    cli.audit("task.routing_deferred", job_id=job["id"], reason=reason)
                    print(f"{job['id']} routing deferred: {reason}")
                    return False
                if (fresh_decision.get("action") == "defer"
                        or fresh_decision.get("model") != decision.get("model")):
                    reason = "route changed before model realization"
                    job.update(state="ready", model_reason=reason,
                               updated_at=cli.now())
                    _persist_job(path, job)
                    cli.audit("task.routing_deferred", job_id=job["id"], reason=reason)
                    print(f"{job['id']} routing deferred: {reason}")
                    return False
                inventory = fresh_inventory
                decision = fresh_decision
                try:
                    realization = realize(decision, inventory)
                except Exception as error:
                    reason = f"model route could not be realized safely: {type(error).__name__}: {error}"
                    job.update(state="queued", model=None, model_reason=reason, updated_at=cli.now())
                    job.pop("prompt", None)
                    _persist_job(path, job)
                    cli.audit("task.routing_deferred", job_id=job["id"], reason=reason)
                    print(f"{job['id']} routing deferred: {reason}")
                    return False
                job["model_realization"] = {"at": cli.now(), **realization}
                # Runner admission must use verified post-realization residency.
                inventory = snapshot()
                job["resource_snapshot"] = inventory
                decision = route(job, inventory)
                if (decision.get("action") == "defer"
                        or decision.get("model") != realization.get("model")):
                    reason = "post-realization route has not converged on the realized model"
                    job.update(state="ready", model_reason=reason, updated_at=cli.now())
                    _persist_job(path, job)
                    cli.audit("task.routing_deferred", job_id=job["id"], reason=reason)
                    print(f"{job['id']} routing deferred: {reason}")
                    return False
            job.setdefault("routing_decisions", []).append(
                {"at": cli.now(), "phase": "post_realization", **decision})
            job["model_reason"] = decision["reason"]
            job["context_tokens"] = int(decision["context_tokens"])
            job["scheduling_reason"] = scheduling_reason
            if job.get("context_state") == "paused_for_resources":
                job["context_state"] = "running"
            job.setdefault("context_state", "running")
            job.setdefault("context_generation", 1)
            prompt_path = cli.ROOT / job["prompt"]
            output_path = cli.ROOT / "logs/runs" / f"{job['id']}.opencode.log"
            job.update(attempts=1 if not job["attempts"] else job["attempts"],
                       updated_at=cli.now(), output=str(output_path.relative_to(cli.ROOT)))
            selected = job.get("model") or os.environ.get(
                "AGENT_EXECUTOR_MODEL", "Qwen3.5-4B-GGUF")
            model = selected if "/" in selected else f"Lemonade/{selected}"
            resume_session = job.get("opencode_session")
            # A fresh session must start in its contracted workspace so native
            # project instructions and startup-hook orientation use that root.
            # Retained legacy sessions were created under the home directory.
            run_directory = (str(Path.home()) if resume_session else
                             task_contracts.validate_task_contract(job["task_contract"])["scope"]["workspace"])
            command = [str(Path.home() / ".local/bin/opencode"), "run", "--auto",
                       "--format", "json", "--title", f"agent-job:{job['id']}",
                       "--model", model, "--dir", run_directory]
            if resume_session:
                command.extend(["--session", resume_session])
                resume_path = cli.ROOT / "state/jobs" / f"{job['id']}.resume.md"
                cli.atomic_text(
                    resume_path,
                    "Resume this exact task after a scheduler or resource interruption. "
                    "Re-read the original prepared prompt and current filesystem state, "
                    "verify what was durably completed, then continue from the last safe "
                    "boundary without duplicating finished work.\n",
                )
                prompt_path = resume_path
            command.insert(2, prompt_path.read_text(encoding="utf-8"))
            view_path = cli.ROOT / 'state/worker-views' / f"{job['id']}-{time.time_ns()}.json"
            view_path.parent.mkdir(parents=True, exist_ok=True)
            command = [sys.executable,
                       str(Path(__file__).resolve().parents[1] / 'scripts/opencode_observable.py'),
                       '--view-record', str(view_path), '--', *command]
            try:
                output_mode = "ab" if resume_session else "wb"
                # Baseline before launch: a fresh (truncated) log starts at
                # zero; an appended resume log at its current size, so fast
                # startup writes cannot escape the output budget.
                initial_output_bytes = (output_path.stat().st_size
                                        if resume_session and output_path.exists()
                                        else 0)
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
                        cancel_before_stop, scheduling, initial_output_bytes)
                    # Persist observed usage before close/reconciliation so
                    # no later branch (including reconciliation_required) can
                    # discard accounting.
                    job["budget_usage"] = outcome["usage"]
                    # A dead executor may leave close complete but logical
                    # continuation unpublished. Preserve the observed result
                    # with its generation before starting physical close.
                    job["runner_round_outcome"] = {
                        "runner_generation": job.get("runner_generation"),
                        "result": outcome,
                    }
                    retained_session = outcome.get("session") or opencode_session_id(output_path)
                    if retained_session:
                        job["opencode_session"] = retained_session
                        job["resume_available"] = True
                    if outcome.get("preempted"):
                        job["pending_preemption_reason"] = outcome["reason"]
                        job["logical_run_state"] = "continuing"
                    _persist_parent_job(job, path)
                    child_outcome = gated_child_wait(context["launch"], 0)
                    closed = close_runner_round(job, path, context, child_outcome)
                    if closed["state"] == "reconciliation_required":
                        print(f"{job['id']} requires inference reconciliation")
                        return True
                    if _complete_requested_cancellation(job, path, outcome):
                        return True
                    if outcome.get("budget_checkpoint"):
                        checkpoint = outcome["budget_checkpoint"]
                        job = job_outcomes.budget_checkpoint_job(
                            job, checkpoint, outcome.get("session"), cli.now())
                        continuation = job["state"] == "ready"
                        _persist_job(path, job)
                        if continuation:
                            cli.audit("task.budget_continuation_queued",
                                      job_id=job["id"],
                                      reason=checkpoint["reason"])
                            print(f"{job['id']} budget checkpoint "
                                  f"({checkpoint['reason']}): continuation queued")
                            return True
                        cli.audit("task.budget_checkpoint", job_id=job["id"],
                                  reason=checkpoint["reason"],
                                  state=job["state"])
                        print(f"{job['id']} budget exhausted "
                              f"({checkpoint['reason']}): {job['state']}")
                        return True
                    if outcome["preempted"]:
                        current = json.loads(path.read_text(encoding="utf-8"))
                        if _complete_requested_cancellation(job, path, outcome):
                            return True
                        if current.get("state") == "interrupted":
                            print(f"{job['id']} interrupted by resource control")
                            return True
                        job = job_outcomes.preempted_job(
                            job, outcome.get("session"), outcome["reason"], cli.now())
                        _persist_job(path, job)
                        cli.audit("task.preempted", job_id=job["id"],
                                  reason=outcome["reason"],
                                  resume_available=bool(outcome.get("session")))
                        print(f"{job['id']} preempted: {outcome['reason']}")
                        return True
                    result = subprocess.CompletedProcess(command, outcome["returncode"])
                current = json.loads(path.read_text(encoding="utf-8"))
                session = opencode_session_id(output_path)
                if _complete_requested_cancellation(
                        job, path, {"session": session,
                                    "reason": "cancellation completed as runner exited"}):
                    return True
                if current.get("state") == "interrupted":
                    print(f"{job['id']} interrupted by resource control")
                    return True
                if session:
                    job["opencode_session"] = session
                job.pop("executor_pid", None)
            except subprocess.TimeoutExpired:
                if 'context' in locals():
                    cleanup_outcome = gated_child_cleanup(context["launch"])
                    close_runner_round(job, path, context, cleanup_outcome)
                if job.get("state") != "reconciliation_required":
                    job.update(state="failed", updated_at=cli.now(),
                               error="executor timed out before a clean runner stop")
            except Exception as error:
                detail = f"{type(error).__name__}: {error}"
                if job.get("state") == "ready":
                    job.pop("executor_pid", None)
                    job.update(last_executor_error=detail, updated_at=cli.now())
                    _persist_parent_job(job, path)
                    cli.audit("task.executor_deferred", job_id=job["id"], error=detail)
                    print(f"{job['id']} executor deferred: {detail}")
                    return False
                if job.get("state") not in {"ready", "reconciliation_required"}:
                    job.update(state="failed", updated_at=cli.now(),
                               error=detail)
            job.pop("executor_pid", None)
            if job["state"] == "failed" and not job.get("verifies"):
                from ecosystem.outbox import result_recipients
                job.setdefault("result_notification_recipients", result_recipients())
            if job["state"] == "failed" and job.get("runner_round_outcome"):
                job["runner_logical_finalized_generation"] = job.get("runner_generation")
            _persist_parent_job(job, path)
            cli.audit(f"task.{job['state']}", job_id=job["id"], output=job["output"], exit_code=job.get("exit_code"))
            if job["state"] == "reconciliation_required":
                print(f"{job['id']} requires inference reconciliation")
                return True
            if job["state"] == "run_finished":
                _finalize_run_finished(job, path)
            elif job["state"] == "failed" and job.get("verifies"):
                from ecosystem.verification import finalize
                queue_notifications(finalize(job))
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
