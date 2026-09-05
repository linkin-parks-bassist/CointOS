"""Fail-safe resource admission and OOM recovery for local inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ecosystem import cli, operator_session, time_policy


POLICY_PATH = cli.ROOT / "config/resource-policy.json"
RUNNING_STATES = {"running"}
HALTED_MODES = {"pressure", "emergency"}
MODEL_CLIENT_UNITS = ("agent-ecosystem.service", "agent-control-worker.service")
LIVE_MODEL_STATUSES = {"ready", "in_use", "busy"}
SURVIVOR_ACTIVE_STATES = {"ready", "running"}
SURVIVOR_INCOMPLETE_STATES = {"awaiting_verification"}
SURVIVOR_TERMINAL_STATES = {"completed", "failed", "rejected"}
SURVIVOR_RETRYABLE_STATES = SURVIVOR_INCOMPLETE_STATES | SURVIVOR_TERMINAL_STATES
SURVIVOR_ROLE = "sole_survivor"
SURVIVOR_AGENT_NAME = "Sole Survivor"
SURVIVOR_PENDING_MODEL_REASON = "Pending model-mediated routing."
SURVIVOR_REQUESTED_MODEL_REASON = (
    "The dedicated bounded emergency model is the only model admitted after OOM."
)
SURVIVOR_MODEL_REASON = (
    "Emergency policy mechanically assigns the sole bounded survivor model."
)
SURVIVOR_QUEUED_FIELDS = frozenset({
    "id", "kind", "state", "attempts", "created_at", "updated_at", "role",
    "task", "source", "model", "model_reason", "requested_model",
    "requested_model_reason", "prefer_models_other_than", "agent_name",
    "idempotency_key", "task_contract", "remaining_budget", "authority_profile",
    "requirements", "scope", "write_paths", "workload_class",
    "agent_generation", "logical_run_state",
})
SURVIVOR_READY_FIELDS = SURVIVOR_QUEUED_FIELDS | {
    "context_tokens", "prompt", "original_prompt",
}
SURVIVOR_RETRY_REQUESTED_FIELDS = frozenset({
    "version", "status", "reason", "replaces", "requested_at", "trigger",
})
SURVIVOR_RETRY_ACTIVE_FIELDS = SURVIVOR_RETRY_REQUESTED_FIELDS | {
    "replacement", "activated_at",
}
STARTED_UNIT_STATES = {"active", "activating", "reloading"}
STOPPED_UNIT_STATES = {"inactive", "failed"}
FAILURE_LOG_TAIL_BYTES = 65536
EMERGENCY_PHASES = (
    "recorded",
    "clients_stopped",
    "models_unloaded",
    "model_loaded",
    "survivor_ready",
    "active",
)
ACTIVE_EMERGENCY_FIELDS = (
    "incident_id",
    "incident_path",
    "emergency_reason",
    "emergency_entered_at",
    "emergency_phase",
    "emergency_error",
    "emergency_error_at",
    "emergency_escalation",
    "interrupted_jobs",
    "client_stop_result",
    "model_unload_result",
    "emergency_model_last_attempt",
    "emergency_model_last_result",
    "emergency_model_ready",
    "sole_survivor_job",
    "survivor_start_result",
    "survivor_retry",
    "active_service_result",
    "recovery_start_result",
    "recovery_error",
    "recovery_error_at",
    "threshold_candidate",
    "threshold_candidate_since_monotonic",
    "healthy_since",
    "healthy_since_monotonic",
    "pressure_incident_id",
    "pressure_entered_at",
    "pressure_released_at",
    "pressure_interrupted_jobs",
    "pressure_dynamic_unloads",
    "pressure_operator_preemptions",
    "pressure_client_stop_result",
    "pressure_client_start_result",
    "pressure_error",
    "pressure_error_at",
)


def policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def state_path() -> Path:
    return cli.ROOT / "state/resource-control.json"


def incident_directory() -> Path:
    return cli.ROOT / "state/resource-incidents"


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()


def oom_kill_count() -> int:
    with Path("/proc/vmstat").open(encoding="utf-8") as stream:
        for line in stream:
            key, value = line.split()
            if key == "oom_kill":
                return int(value)
    raise RuntimeError("/proc/vmstat has no oom_kill counter")


def _meminfo() -> dict[str, int]:
    values = {}
    with Path("/proc/meminfo").open(encoding="utf-8") as stream:
        for line in stream:
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    return values


def _memory_full_avg10() -> float:
    line = Path("/proc/pressure/memory").read_text(encoding="utf-8").splitlines()[1]
    fields = dict(item.split("=", 1) for item in line.split()[1:])
    return float(fields["avg10"])


def _gtt_used_bytes() -> int | None:
    for path in Path("/sys/class/drm").glob("card*/device/mem_info_gtt_used"):
        try:
            return int(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def resource_snapshot() -> dict:
    memory = _meminfo()
    swap_total = memory.get("SwapTotal", 0)
    swap_free = memory.get("SwapFree", 0)
    gtt_used = _gtt_used_bytes()
    return {
        "at": cli.now(),
        "boot_id": boot_id(),
        "oom_kills": oom_kill_count(),
        "memory_available_gb": round(memory.get("MemAvailable", 0) / 1024 ** 3, 3),
        "swap_used_gb": round((swap_total - swap_free) / 1024 ** 3, 3),
        "memory_full_avg10": _memory_full_avg10(),
        "gtt_used_gb": None if gtt_used is None else round(gtt_used / 1024 ** 3, 3),
    }


def load_state(snapshot: dict | None = None) -> dict:
    path = state_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    current = snapshot or resource_snapshot()
    return {
        "version": 1,
        "mode": "normal",
        "boot_id": current["boot_id"],
        "last_oom_kills": 0,
        "updated_at": cli.now(),
    }


def save_state(state: dict) -> None:
    state["updated_at"] = cli.now()
    cli.atomic_json(state_path(), state)


def mode() -> str:
    try:
        return load_state()["mode"]
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return "emergency"


def dispatch_halted() -> bool:
    return mode() in HALTED_MODES


def active_chat_model(configured_default: str) -> str:
    state = load_state()
    if state.get("mode") == "emergency":
        return policy()["emergency"]["chat_model"]
    return configured_default


def job_admitted_in_current_mode(job: dict) -> bool:
    current = mode()
    if current == "normal":
        return True
    if current == "pressure":
        return False
    return job.get("id") == load_state().get("sole_survivor_job")


def _seconds(section: str, key: str) -> float:
    return time_policy.seconds(time_policy.load(), section, key)


def _lemonade_request(path: str, payload: dict | None = None,
                      method: str | None = None, *, timeout: float) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:13305" + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": "Bearer lemonade"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def lemonade_health() -> dict:
    try:
        return _lemonade_request(
            "/v1/health",
            timeout=_seconds("inference", "health_verification_deadline_seconds"),
        )
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


def _model_record_error(item: object) -> str | None:
    if not isinstance(item, dict):
        return "model record is not an object"
    if not isinstance(item.get("model_name"), str) or not item["model_name"]:
        return "model record has no valid model_name"
    if type(item.get("loaded")) is not bool:
        return "model record loaded is not a boolean"
    if type(item.get("backend_alive")) is not bool:
        return "model record backend_alive is not a boolean"
    if not isinstance(item.get("status"), str) or not item["status"]:
        return "model record has no valid status"
    return None


def _health_models(health: object) -> tuple[list[dict] | None, str | None]:
    if not isinstance(health, dict):
        return None, "health response is not an object"
    if health.get("error"):
        return None, f"health request failed: {health['error']}"
    models = health.get("all_models_loaded")
    if not isinstance(models, list):
        return None, "health response has no valid all_models_loaded list"
    for index, item in enumerate(models):
        error = _model_record_error(item)
        if error:
            return None, f"health model {index}: {error}"
    return models, None


def model_is_live(item: dict) -> bool:
    return (_model_record_error(item) is None and item["loaded"] is True
            and item["backend_alive"] is True
            and item["status"] in LIVE_MODEL_STATUSES)


def emergency_model_allocation(settings: dict | None = None) -> dict:
    emergency = (settings if settings is not None else policy())["emergency"]
    context_tokens = emergency.get("chat_context_tokens")
    parallel_requests = emergency.get("parallel_requests")
    if type(context_tokens) is not int or context_tokens <= 0:
        raise ValueError("chat_context_tokens must be a positive integer")
    if type(parallel_requests) is not int or parallel_requests <= 0:
        raise ValueError("parallel_requests must be a positive integer")
    if context_tokens > sys.maxsize // parallel_requests:
        raise ValueError("derived emergency backend context is too large")
    return {
        "chat_context_tokens": context_tokens,
        "parallel_requests": parallel_requests,
        "backend_context_tokens": context_tokens * parallel_requests,
    }


def _observed_parallel_requests(item: dict) -> int | None:
    options = item.get("recipe_options")
    if not isinstance(options, dict):
        return None
    arguments = options.get("llamacpp_args")
    if not isinstance(arguments, str):
        return None
    try:
        tokens = shlex.split(arguments)
    except ValueError:
        return None
    values = []
    for index, token in enumerate(tokens):
        if token == "--parallel" and index + 1 < len(tokens):
            values.append(tokens[index + 1])
        elif token.startswith("--parallel="):
            values.append(token.partition("=")[2])
    if len(values) != 1:
        return None
    try:
        parallel_requests = int(values[0])
    except ValueError:
        return None
    return parallel_requests if parallel_requests > 0 else None


def _model_satisfies_emergency_allocation(item: dict, allocation: dict) -> bool:
    options = item.get("recipe_options")
    if not isinstance(options, dict):
        return False
    backend_context_tokens = options.get("ctx_size")
    if type(backend_context_tokens) is not int or backend_context_tokens <= 0:
        return False
    parallel_requests = _observed_parallel_requests(item)
    return (parallel_requests is not None
            and parallel_requests >= allocation["parallel_requests"]
            and backend_context_tokens // parallel_requests
            >= allocation["chat_context_tokens"])


def emergency_model_live(health: dict | None = None) -> bool:
    current = health if health is not None else lemonade_health()
    models, error = _health_models(current)
    if error:
        return False
    settings = policy()
    expected = settings["emergency"]["chat_model"]
    try:
        allocation = emergency_model_allocation(settings)
    except (KeyError, TypeError, ValueError):
        return False
    return any(item.get("model_name") == expected and model_is_live(item)
               and _model_satisfies_emergency_allocation(item, allocation)
               for item in models or [])


def _hash_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _active_records() -> tuple[list[dict], list[dict]]:
    jobs = []
    for path in sorted((cli.ROOT / "state/jobs").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("state") in RUNNING_STATES:
            prompt = cli.ROOT / record.get("prompt", "")
            output = cli.ROOT / record.get("output", "")
            jobs.append({
                "record": record,
                "record_path": str(path),
                "record_sha256": _hash_file(path),
                "prompt_sha256": _hash_file(prompt),
                "output_sha256": _hash_file(output),
            })
    turns = []
    directory = cli.ROOT / "state/control-turns"
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("deep_state") in {"reserved", "running", "followup_ready", "followup_sending"}:
            turns.append({"record": record, "record_path": str(path),
                          "record_sha256": _hash_file(path)})
    return jobs, turns


def opencode_session_id(output: Path) -> str | None:
    try:
        with output.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                identifier = value.get("sessionID")
                if isinstance(identifier, str) and identifier.startswith("ses_"):
                    return identifier
    except OSError:
        pass
    return None


def checkpoint_running_jobs(incident_id: str, reason: str = "resource emergency") -> list[str]:
    interrupted = []
    for path in sorted((cli.ROOT / "state/jobs").glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("state") not in RUNNING_STATES:
            continue
        output = cli.ROOT / job.get("output", "")
        session = job.get("opencode_session") or opencode_session_id(output)
        job.update(state="interrupted", updated_at=cli.now(), interrupted_by=incident_id,
                   interruption_reason=f"{reason}; durable context flushed before inference unload")
        if session:
            job["opencode_session"] = session
            job["resume_available"] = True
        else:
            job["resume_available"] = False
        cli.atomic_json(path, job)
        cli.audit("task.interrupted", job_id=job["id"], incident_id=incident_id,
                  resume_available=bool(session))
        interrupted.append(job["id"])
    os.sync()
    return interrupted


def _user_systemctl(*arguments: str) -> dict:
    timeout = _seconds("lifecycle", "service_stop_deadline_seconds")
    command = ["systemctl", "--user", *arguments]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"systemctl timed out after {timeout:g} seconds"}
    except OSError as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    if result.returncode != 0:
        return {"ok": False, "returncode": result.returncode,
                "error": f"systemctl exited with status {result.returncode}"}
    return {"ok": True, "returncode": 0, "stdout": result.stdout}


def _user_unit_state(unit: str) -> dict:
    result = _user_systemctl(
        "show", unit, "--property=ActiveState", "--property=ControlGroup",
        "--property=MainPID",
    )
    if not result.get("ok"):
        return result
    fields = {}
    for line in result.get("stdout", "").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key] = value
    if set(fields) != {"ActiveState", "ControlGroup", "MainPID"}:
        return {"ok": False, "error": f"ambiguous unit state for {unit}"}
    try:
        main_pid = int(fields["MainPID"])
    except ValueError:
        return {"ok": False, "error": f"ambiguous unit MainPID for {unit}"}
    if main_pid < 0:
        return {"ok": False, "error": f"ambiguous unit MainPID for {unit}"}
    return {
        "ok": True,
        "unit": unit,
        "active_state": fields["ActiveState"],
        "control_group": fields["ControlGroup"],
        "main_pid": main_pid,
    }


def _verify_user_units(units: tuple[str, ...], expected: str) -> dict:
    states = [_user_unit_state(unit) for unit in units]
    if any(not state.get("ok") for state in states):
        return {"ok": False, "error": "unit state could not be verified", "states": states}
    if expected == "stopped":
        valid = all(state["active_state"] in STOPPED_UNIT_STATES
                    and not state["control_group"] and state["main_pid"] == 0
                    for state in states)
    elif expected == "started":
        valid = all(state["active_state"] in STARTED_UNIT_STATES
                    and bool(state["control_group"]) and state["main_pid"] > 0
                    for state in states)
    else:
        raise ValueError(f"unknown unit postcondition: {expected}")
    return {
        "ok": valid,
        "error": None if valid else (
            "units have no verified live process" if expected == "started"
            else "units did not reach verified stopped state"
        ),
        "states": states,
    }


def _wait_for_started_user_units(units: tuple[str, ...]) -> dict:
    deadline_seconds = _seconds("lifecycle", "reconciliation_deadline_seconds")
    poll_seconds = _seconds("resource", "poll_seconds")
    deadline = time.monotonic() + deadline_seconds
    while True:
        verified = _verify_user_units(units, "started")
        if verified.get("ok"):
            return verified
        now_monotonic = time.monotonic()
        if now_monotonic >= deadline:
            verified["error"] = (
                f"{verified.get('error', 'unit verification failed')} after "
                f"{deadline_seconds:g} seconds"
            )
            return verified
        time.sleep(min(poll_seconds, deadline - now_monotonic))


def _stop_user_units(units: tuple[str, ...]) -> dict:
    actions = []
    for unit in units:
        result = _user_systemctl("stop", unit)
        actions.append({"unit": unit, **result})
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "unit stop failed"),
                    "actions": actions}
    verified = _verify_user_units(units, "stopped")
    return {**verified, "actions": actions}


def _start_user_units(units: tuple[str, ...]) -> dict:
    result = _user_systemctl("start", "--no-block", *units)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "unit start failed"),
                "action": result}
    verified = _wait_for_started_user_units(units)
    return {**verified, "action": result}


def interrupt_model_clients() -> dict:
    return _stop_user_units(MODEL_CLIENT_UNITS)


def unload_all_models() -> dict:
    stop_deadline = _seconds("inference", "model_stop_deadline_seconds")
    try:
        result = _lemonade_request("/v1/unload", {}, timeout=stop_deadline)
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    deadline = time.monotonic() + stop_deadline
    poll_seconds = _seconds("resource", "poll_seconds")
    health = lemonade_health()
    models, error = _health_models(health)
    if error:
        return {"ok": False, "error": error, "response": result, "health": health}
    while models:
        if time.monotonic() >= deadline:
            return {"ok": False, "error": "models remain loaded after stop deadline",
                    "response": result, "health": health}
        time.sleep(poll_seconds)
        health = lemonade_health()
        models, error = _health_models(health)
        if error:
            return {"ok": False, "error": error, "response": result, "health": health}
    return {"ok": True, "response": result, "health": health}


def unload_dynamic_models() -> list[dict]:
    preserved = policy()["emergency"]["chat_model"]
    results = []
    health = lemonade_health()
    models, error = _health_models(health)
    if error:
        return [{"ok": False, "error": error, "health": health}]
    for item in models or []:
        model_name = item.get("model_name")
        if not model_name or model_name == preserved:
            continue
        owner = operator_session.operator_session_owns_model(cli.ROOT, model_name)
        if owner:
            results.append({
                "model": model_name,
                "skipped": True,
                "reason": "active operator session lease",
                "owner_session": owner,
            })
            continue
        try:
            response = _lemonade_request(
                "/v1/unload", {"model_name": model_name},
                timeout=_seconds("inference", "model_stop_deadline_seconds"),
            )
            results.append({"model": model_name, "ok": True, "response": response})
        except Exception as error:
            results.append({"model": model_name, "ok": False,
                            "error": f"{type(error).__name__}: {error}"})
    return results


def _release_interrupted_jobs(identifiers: list[str], released_by: str) -> list[str]:
    released = []
    for identifier in identifiers:
        path = cli.ROOT / "state/jobs" / f"{identifier}.json"
        if not path.exists():
            continue
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("state") != "interrupted":
            continue
        if job.get("resume_available"):
            job["state"] = "ready"
        else:
            previous_model = job.get("model")
            if previous_model and not job.get("requested_model"):
                job["requested_model"] = previous_model
                job["requested_model_reason"] = "Recovered hint from an interrupted dispatch."
            job.update(state="queued", model=None, model_reason="Pending model-mediated routing.")
        job.update(updated_at=cli.now(), resume_reason=released_by)
        cli.atomic_json(path, job)
        released.append(identifier)
    return released


def enter_pressure(state: dict, snapshot: dict) -> dict:
    incident_id = f"pressure-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    state.update(mode="pressure", pressure_entered_at=cli.now(),
                 pressure_incident_id=incident_id)
    save_state(state)
    interrupted = checkpoint_running_jobs(incident_id, "resource pressure")
    stop = _stop_user_units(("agent-ecosystem.service",))
    state.update(pressure_interrupted_jobs=interrupted,
                 pressure_client_stop_result=stop)
    if not stop.get("ok"):
        state.update(pressure_error=stop.get("error", "model client stop failed"),
                     pressure_error_at=cli.now())
        save_state(state)
        cli.audit("resource.pressure_error", incident_id=incident_id,
                  error=state["pressure_error"])
        return state
    unloads = unload_dynamic_models()
    preemptions = _preempt_leased_models_if_unprotected(unloads, incident_id)
    state.update(pressure_dynamic_unloads=unloads)
    if preemptions:
        state["pressure_operator_preemptions"] = preemptions
    state.pop("pressure_error", None)
    state.pop("pressure_error_at", None)
    save_state(state)
    cli.audit("resource.pressure_entered", resources=snapshot,
              interrupted_jobs=interrupted, dynamic_unloads=unloads,
              operator_preemptions=preemptions)
    return state


def _preempt_leased_models_if_unprotected(unloads: list[dict],
                                          incident_id: str) -> list[dict]:
    """Coin may take leased capacity only when no unprotected dynamic model
    remained to be unloaded: every leased model was skipped and every other
    unload succeeded (or there was nothing else to unload)."""
    leased = [record for record in unloads if record.get("skipped")]
    if not leased:
        return []
    failures = [record for record in unloads
                if record.get("skipped") is not True and record.get("ok") is False]
    if failures:
        return []
    return operator_session.preempt_operator_sessions(
        cli.ROOT,
        {"kind": "coin_reserve",
         "required_bytes": policy()["physical_capacity"]["coin_reserved_bytes"],
         "incident_id": incident_id},
        time.monotonic)


def load_emergency_model() -> dict:
    emergency = policy()["emergency"]
    try:
        allocation = emergency_model_allocation()
    except (KeyError, TypeError, ValueError) as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    parallel_requests = allocation["parallel_requests"]
    payload = {
        "model_name": emergency["chat_model"],
        "pinned": True,
        "ctx_size": allocation["backend_context_tokens"],
        "merge_args": True,
        "llamacpp_args": f"--parallel {parallel_requests} --batch-size 512 --ubatch-size 128 --poll 0 --prio -1",
    }
    try:
        result = _lemonade_request(
            "/v1/load", payload,
            timeout=_seconds("inference", "model_start_deadline_seconds"),
        )
        health = lemonade_health()
        if not emergency_model_live(health):
            return {"ok": False, "error": "emergency model remained non-live after load",
                    "response": result, "health": health}
        return {"ok": True, "response": result, "health": health}
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}",
                "health": lemonade_health()}


def _survivor_task(incident_path: Path, incident_id: str,
                   replacement_for: str | None) -> str:
    task = f"""Recover resource incident `{incident_id}`.

The immutable incident snapshot is `{incident_path}`. Ordinary dispatch is
mechanically halted. Inspect the snapshot and the minimum relevant journal, model,
job, and repository evidence. Determine the causal chain, make only bounded safe
user-level repairs, and verify stable memory, GTT, swap, PSI, Lemonade, GNOME, and
chatbot state. Do not load a larger model during this incident.

When and only when recovery is safe, run:

`/home/david/agent-ecosystem/scripts/resource-control recover`

That transition validates your `AGENT_JOB_ID` and the live health gate. If it
refuses, keep dispatch halted and report the exact blocker. Write the incident
conclusion to `state/resource-incidents/{incident_id}-conclusion.md`."""
    if replacement_for:
        task = (
            f"This is the one authorized same-model retry of failed survivor "
            f"`{replacement_for}` after correcting its backend allocation. Preserve that "
            f"job and transcript as incident evidence.\n\n{task}"
        )
    return task


def _same_typed_json(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if type(observed) is dict:
        if (not all(type(key) is str for key in observed)
                or set(observed) != set(expected)):
            return False
        return all(
            _same_typed_json(observed[key], expected[key])
            for key in observed
        )
    if type(observed) is list:
        return (len(observed) == len(expected)
                and all(_same_typed_json(left, right)
                        for left, right in zip(observed, expected)))
    if type(observed) in (str, int, float, bool, type(None)):
        return observed == expected
    return False


def _require_canonical_survivor_job(job: dict, expected: dict,
                                    allowed_fields: frozenset[str]) -> None:
    timestamps_are_typed = (
        isinstance(job.get("created_at"), str) and bool(job["created_at"])
        and isinstance(job.get("updated_at"), str) and bool(job["updated_at"])
    )
    if (set(job) != allowed_fields or not timestamps_are_typed
            or any(not _same_typed_json(job.get(key), value)
                   for key, value in expected.items())):
        raise RuntimeError("sole survivor job has a non-canonical descriptor")


def _require_canonical_survivor_prompt(path: Path, expected: str) -> None:
    try:
        observed = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(
            f"sole survivor job has no canonical prompt: {type(error).__name__}: {error}"
        ) from error
    if observed != expected:
        raise RuntimeError("sole survivor job has a non-canonical prompt")


def _prepare_survivor(incident_path: Path, incident_id: str,
                      replacement_for: str | None = None) -> str:
    from ecosystem.roles import render_context

    emergency = policy()["emergency"]
    emergency_model = emergency["chat_model"]
    task = _survivor_task(incident_path, incident_id, replacement_for)
    idempotency_key = (f"resource-emergency:{incident_id}:replace:{replacement_for}"
                       if replacement_for else f"resource-emergency:{incident_id}")
    root = cli.ROOT.resolve()
    conclusion = (root / "state/resource-incidents" / f"{incident_id}-conclusion.md").resolve(strict=False)
    contract = {
        "objective": task,
        "scope": {"workspace": str(root), "read_paths": [str(root)],
                  "write_paths": [str(root)]},
        "authority_profile": "sole_survivor",
        "requirements": {"required_capabilities": ["reasoning", "tool-calling"],
                         "minimum_context_tokens": emergency["chat_context_tokens"]},
        "acceptance": [{"kind": "artifact", "path": str(conclusion)}],
        "budget": {"run_seconds": 300, "task_seconds": 900, "maximum_attempts": 2,
                   "maximum_output_bytes": 65536, "maximum_evidence_items": 20,
                   "maximum_children": 0},
        "source_key": idempotency_key, "parent_job_id": replacement_for,
        "stop_condition": "Stop after safe recovery or an evidence-backed blocked handoff.",
    }
    try:
        job_id = cli.enqueue_task(
            SURVIVOR_ROLE, task, source=f"resource-emergency:{incident_id}",
            model=emergency_model,
            model_reason=SURVIVOR_REQUESTED_MODEL_REASON,
            agent_name=SURVIVOR_AGENT_NAME,
            idempotency_key=idempotency_key,
            task_contract=contract,
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "sole survivor job has a non-canonical descriptor"
        ) from error
    path = cli.ROOT / "state/jobs" / f"{job_id}.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    expected_source = f"resource-emergency:{incident_id}"
    common = {
        "id": job_id,
        "kind": "agent-task",
        "attempts": 0,
        "role": SURVIVOR_ROLE,
        "task": task,
        "source": expected_source,
        "requested_model": emergency_model,
        "requested_model_reason": SURVIVOR_REQUESTED_MODEL_REASON,
        "prefer_models_other_than": [],
        "agent_name": SURVIVOR_AGENT_NAME,
        "idempotency_key": idempotency_key,
        "task_contract": contract,
        "remaining_budget": contract["budget"],
        "authority_profile": contract["authority_profile"],
        "requirements": contract["requirements"],
        "scope": contract["scope"],
        "write_paths": contract["scope"]["write_paths"],
        "workload_class": "repair",
        "agent_generation": 1,
        "logical_run_state": "active",
    }
    prompt_path = cli.ROOT / "state/jobs" / f"{job_id}.prompt.md"
    relative_prompt = str(prompt_path.relative_to(cli.ROOT))
    expected_prompt = render_context(
        SURVIVOR_ROLE, task, job_id, emergency_model,
        SURVIVOR_MODEL_REASON, SURVIVOR_AGENT_NAME, contract,
    )
    if job.get("state") == "ready":
        _require_canonical_survivor_job(job, {
            **common,
            "state": "ready",
            "model": emergency_model,
            "model_reason": SURVIVOR_MODEL_REASON,
            "context_tokens": emergency["chat_context_tokens"],
            "prompt": relative_prompt,
            "original_prompt": relative_prompt,
        }, SURVIVOR_READY_FIELDS)
        _require_canonical_survivor_prompt(prompt_path, expected_prompt)
        return job_id
    _require_canonical_survivor_job(job, {
        **common,
        "state": "queued",
        "model": None,
        "model_reason": SURVIVOR_PENDING_MODEL_REASON,
    }, SURVIVOR_QUEUED_FIELDS)
    if prompt_path.exists():
        _require_canonical_survivor_prompt(prompt_path, expected_prompt)
    else:
        cli.atomic_text(prompt_path, expected_prompt)
    job.update(
        state="ready",
        model=emergency_model,
        model_reason=SURVIVOR_MODEL_REASON,
        context_tokens=emergency["chat_context_tokens"],
        prompt=relative_prompt,
        original_prompt=relative_prompt,
        updated_at=cli.now(),
    )
    cli.atomic_json(path, job)
    cli.audit("resource.sole_survivor_ready", incident_id=incident_id, job_id=job_id)
    return job_id


def _incident_path_from_state(state: dict) -> Path:
    raw_path = state.get("incident_path")
    if not raw_path:
        raise ValueError("resource emergency has no incident path")
    path = Path(raw_path)
    return path if path.is_absolute() else cli.ROOT / path


def _update_incident(state: dict, **fields: object) -> None:
    path = _incident_path_from_state(state)
    incident = json.loads(path.read_text(encoding="utf-8"))
    incident.update(fields)
    cli.atomic_json(path, incident)


def _persist_emergency_phase(state: dict, phase: str) -> None:
    state["emergency_phase"] = phase
    state.pop("emergency_error", None)
    state.pop("emergency_error_at", None)
    state.pop("emergency_escalation", None)
    save_state(state)


def _same_persisted_state(state: dict) -> bool:
    try:
        persisted = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    def stable_fields(candidate: dict) -> dict:
        result = dict(candidate)
        result.pop("updated_at", None)
        resources = result.get("last_resources")
        if isinstance(resources, dict):
            resources = dict(resources)
            resources.pop("at", None)
            result["last_resources"] = resources
        return result

    return stable_fields(persisted) == stable_fields(state)


def _record_emergency_error(state: dict, message: str,
                            escalation: dict | None = None) -> dict:
    effective_escalation = (escalation if escalation is not None
                            else state.get("emergency_escalation"))
    changed = (state.get("emergency_error") != message
               or state.get("emergency_escalation") != effective_escalation
               or not state.get("emergency_error_at"))
    state["emergency_error"] = message
    if effective_escalation is not None:
        escalation = effective_escalation
        state["emergency_escalation"] = escalation
    if changed:
        state["emergency_error_at"] = cli.now()
        save_state(state)
        cli.audit("resource.emergency_error", incident_id=state.get("incident_id"),
                  phase=state.get("emergency_phase"), error=message,
                  escalation=escalation)
    elif not _same_persisted_state(state):
        save_state(state)
    return state


def _record_emergency(state: dict, snapshot: dict, reason: str) -> None:
    directory = incident_directory()
    directory.mkdir(parents=True, exist_ok=True)
    incident_id = state.get("incident_id")
    if not incident_id:
        incident_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{snapshot['oom_kills']}"
    raw_path = state.get("incident_path")
    incident_path = Path(raw_path) if raw_path else directory / f"{incident_id}.json"
    if not incident_path.is_absolute():
        incident_path = cli.ROOT / incident_path
    if not incident_path.exists():
        jobs, turns = _active_records()
        incident = {
            "version": 1,
            "id": incident_id,
            "reason": state.get("emergency_reason", reason),
            "detected_at": state.get("emergency_entered_at", cli.now()),
            "resources": snapshot,
            "lemonade_before": lemonade_health(),
            "active_jobs": jobs,
            "active_control_turns": turns,
            "context_boundary": (
                "OpenCode sessions, exact prompts, durable job/control-turn records, and logs "
                "are preserved. Lemonade does not expose serialization of live backend KV caches."
            ),
        }
        cli.atomic_json(incident_path, incident)
    state.update(mode="emergency", incident_id=incident_id,
                 incident_path=str(incident_path),
                 emergency_reason=state.get("emergency_reason", reason),
                 emergency_entered_at=state.get("emergency_entered_at", cli.now()))
    state.pop("threshold_candidate", None)
    state.pop("threshold_candidate_since_monotonic", None)
    _persist_emergency_phase(state, "recorded")


def _interrupted_job_ids(state: dict) -> list[str]:
    identifiers = list(state.get("pressure_interrupted_jobs", []))
    identifiers.extend(state.get("interrupted_jobs", []))
    incident_id = state.get("incident_id")
    for path in sorted((cli.ROOT / "state/jobs").glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("state") == "interrupted" and job.get("interrupted_by") == incident_id:
            identifiers.append(job["id"])
    return list(dict.fromkeys(identifiers))


def _survivor_job(state: dict) -> dict | None:
    identifier = state.get("sole_survivor_job")
    if not identifier:
        return None
    path = cli.ROOT / "state/jobs" / f"{identifier}.json"
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (job.get("id") != identifier
            or job.get("source") != f"resource-emergency:{state.get('incident_id')}"):
        return None
    return job


def _survivor_has_state(state: dict, allowed_states: set[str]) -> bool:
    job = _survivor_job(state)
    return job is not None and job.get("state") in allowed_states


def _survivor_retry_record(state: dict) -> dict | None:
    record = state.get("survivor_retry")
    if record is None:
        return None
    if not isinstance(record, dict):
        raise RuntimeError("invalid survivor retry record")
    status = record.get("status")
    allowed_fields = (SURVIVOR_RETRY_REQUESTED_FIELDS if status == "requested"
                      else SURVIVOR_RETRY_ACTIVE_FIELDS if status == "active"
                      else frozenset())
    valid = (set(record) == allowed_fields
             and type(record.get("version")) is int
             and record["version"] == 1
             and status in {"requested", "active"}
             and record.get("reason") == "corrected_same_model_allocation"
             and isinstance(record.get("replaces"), str)
             and bool(record["replaces"])
             and isinstance(record.get("requested_at"), str)
             and bool(record["requested_at"])
             and (record.get("trigger") is None
                  or isinstance(record.get("trigger"), dict)))
    replacement = record.get("replacement")
    if status == "active":
        valid = (valid and isinstance(replacement, str) and bool(replacement)
                 and isinstance(record.get("activated_at"), str)
                 and bool(record["activated_at"]))
    if replacement is not None:
        valid = valid and replacement != record.get("replaces")
    if not valid:
        raise RuntimeError("invalid survivor retry record")
    return record


def _transcript_tail(raw_path: object) -> str:
    if not isinstance(raw_path, str) or not raw_path:
        return ""
    try:
        root = cli.ROOT.resolve()
        path = Path(raw_path)
        resolved = (path if path.is_absolute() else root / path).resolve()
        resolved.relative_to(root)
        with resolved.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - FAILURE_LOG_TAIL_BYTES))
            return stream.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _survivor_required_escalation(job: dict) -> dict:
    failure = f"{job.get('error', '')}\n{_transcript_tail(job.get('output'))}".casefold()
    if job.get("state") in SURVIVOR_INCOMPLETE_STATES:
        reason = "survivor_incomplete"
    elif job.get("state") == "failed" and (
            "exceed_context_size_error" in failure
            or "exceeds the available context size" in failure):
        reason = "context_overflow"
    else:
        reason = "survivor_terminal"
    return {
        "status": "required",
        "reason": reason,
        "survivor_job": job.get("id"),
        "survivor_state": job.get("state"),
        "exit_code": job.get("exit_code"),
        "requested_context_tokens": job.get("context_tokens"),
        "transcript": job.get("output"),
        "error": job.get("error"),
    }


def _survivor_is_ready(state: dict) -> bool:
    return _survivor_has_state(state, {"ready"})


def _survivor_is_active(state: dict) -> bool:
    return _survivor_has_state(state, SURVIVOR_ACTIVE_STATES)


def advance_emergency(state: dict, snapshot: dict, reason: str) -> dict:
    phase = state.get("emergency_phase")
    if phase is not None and phase not in EMERGENCY_PHASES:
        return _record_emergency_error(state, f"unknown emergency phase: {phase}")

    if phase is None:
        _record_emergency(state, snapshot, reason)
        phase = "recorded"

    if phase == "recorded":
        try:
            checkpoint_running_jobs(state["incident_id"])
            state["interrupted_jobs"] = _interrupted_job_ids(state)
            save_state(state)
            stopped = interrupt_model_clients()
        except Exception as error:
            return _record_emergency_error(
                state, f"client interruption failed: {type(error).__name__}: {error}"
            )
        state["client_stop_result"] = stopped
        if not stopped.get("ok"):
            return _record_emergency_error(
                state, f"client interruption failed: {stopped.get('error', 'unverified stop')}"
            )
        _update_incident(state, interrupted_jobs=state["interrupted_jobs"])
        _persist_emergency_phase(state, "clients_stopped")
        phase = "clients_stopped"

    if phase == "clients_stopped":
        unload = unload_all_models()
        state["model_unload_result"] = unload
        if not unload.get("ok"):
            return _record_emergency_error(
                state, f"model unload failed: {unload.get('error', 'models remain loaded')}"
            )
        _update_incident(state, unload=unload)
        _persist_emergency_phase(state, "models_unloaded")
        phase = "models_unloaded"

    if phase == "models_unloaded":
        if emergency_model_live():
            loaded = {"ok": True, "reused_live_model": True, "health": lemonade_health()}
        else:
            loaded = load_emergency_model()
        state["emergency_model_last_attempt"] = cli.now()
        state["emergency_model_last_result"] = loaded
        if not loaded.get("ok") or not emergency_model_live(loaded.get("health")):
            state["emergency_model_ready"] = False
            return _record_emergency_error(
                state, f"emergency model load failed or remained non-live: {json.dumps(loaded, sort_keys=True)}"
            )
        state["emergency_model_ready"] = True
        _update_incident(state, emergency_model_load=loaded,
                         lemonade_after=loaded.get("health"))
        _persist_emergency_phase(state, "model_loaded")
        phase = "model_loaded"

    if phase == "model_loaded":
        retry = _survivor_retry_record(state)
        try:
            survivor = _prepare_survivor(
                _incident_path_from_state(state), state["incident_id"],
                replacement_for=(retry["replaces"] if retry is not None else None),
            )
        except Exception as error:
            return _record_emergency_error(
                state, f"sole survivor preparation failed: {type(error).__name__}: {error}"
            )
        state["sole_survivor_job"] = survivor
        if not _survivor_is_ready(state):
            return _record_emergency_error(state, "sole survivor job was not durably ready")
        _persist_emergency_phase(state, "survivor_ready")
        phase = "survivor_ready"

    if phase == "survivor_ready":
        if not emergency_model_live():
            return _record_emergency_error(state, "emergency model is not live")
        if not _survivor_is_ready(state):
            return _record_emergency_error(state, "sole survivor job is not ready")
        try:
            started = _start_user_units(
                ("agent-control-worker.service", "agent-ecosystem.service")
            )
        except Exception as error:
            return _record_emergency_error(
                state, f"survivor executor start failed: {type(error).__name__}: {error}"
            )
        state["survivor_start_result"] = started
        if not started.get("ok"):
            return _record_emergency_error(
                state, f"survivor executor start failed: {started.get('error', 'unverified start')}"
            )
        os.sync()
        retry = _survivor_retry_record(state)
        if retry is not None and retry["status"] == "requested":
            retry.update(
                status="active",
                replacement=state["sole_survivor_job"],
                activated_at=cli.now(),
            )
        _persist_emergency_phase(state, "active")
        cli.audit("resource.emergency_entered", incident_id=state["incident_id"],
                  reason=state["emergency_reason"], survivor_job=state["sole_survivor_job"],
                  emergency_model_ready=True)
        return state

    if phase == "active":
        if not emergency_model_live():
            return _record_emergency_error(state, "emergency model is not live")
        survivor = _survivor_job(state)
        if survivor is None or survivor.get("state") not in SURVIVOR_ACTIVE_STATES:
            escalation = (_survivor_required_escalation(survivor)
                          if survivor is not None
                          and survivor.get("state") in (
                              SURVIVOR_TERMINAL_STATES | SURVIVOR_INCOMPLETE_STATES
                          )
                          else None)
            return _record_emergency_error(
                state, "sole survivor job is not in a live executor state",
                escalation=escalation,
            )
        services = _verify_user_units(
            ("agent-control-worker.service", "agent-ecosystem.service"), "started"
        )
        state["active_service_result"] = services
        if not services.get("ok"):
            return _record_emergency_error(
                state, f"active services have no verified live process: {services.get('error')}"
            )
        state.pop("emergency_error", None)
        state.pop("emergency_error_at", None)
        save_state(state)
    return state


def enter_emergency(state: dict, snapshot: dict, reason: str) -> dict:
    return advance_emergency(state, snapshot, reason)


def _threshold_state(snapshot: dict) -> str:
    settings = policy()
    emergency = settings["emergency"]
    pressure = settings["pressure"]
    gtt = snapshot.get("gtt_used_gb")
    if (snapshot["memory_available_gb"] < emergency["minimum_available_gb"]
            or (gtt is not None and gtt > emergency["maximum_gtt_used_gb"])
            or snapshot["swap_used_gb"] > emergency["maximum_swap_used_gb"]
            or snapshot["memory_full_avg10"] > emergency["maximum_memory_full_avg10"]):
        return "emergency"
    if (snapshot["memory_available_gb"] < pressure["minimum_available_gb"]
            or (gtt is not None and gtt > pressure["maximum_gtt_used_gb"])
            or snapshot["swap_used_gb"] > pressure["maximum_swap_used_gb"]):
        return "pressure"
    return "healthy"


def confirmed_threshold(state: dict, snapshot: dict, now_monotonic: float) -> str:
    observed = _threshold_state(snapshot)
    current = {
        "normal": "healthy",
        "pressure": "pressure",
        "emergency": "emergency",
    }.get(state.get("mode"), "emergency")
    if observed == "healthy" or observed == current:
        state.pop("threshold_candidate", None)
        state.pop("threshold_candidate_since_monotonic", None)
        return observed

    candidate = state.get("threshold_candidate")
    started = state.get("threshold_candidate_since_monotonic")
    if candidate != observed or not isinstance(started, (int, float)):
        state["threshold_candidate"] = observed
        state["threshold_candidate_since_monotonic"] = now_monotonic
        return current

    durations = time_policy.load()
    duration_key = ("emergency_confirmation_seconds" if observed == "emergency"
                    else "pressure_confirmation_seconds")
    required = time_policy.seconds(durations, "resource", duration_key)
    if now_monotonic - float(started) < required:
        return current
    state.pop("threshold_candidate", None)
    state.pop("threshold_candidate_since_monotonic", None)
    return observed


def tick() -> dict:
    snapshot = resource_snapshot()
    state = load_state(snapshot)
    now_monotonic = time.monotonic()
    if state.get("boot_id") != snapshot["boot_id"]:
        state.update(boot_id=snapshot["boot_id"], last_oom_kills=0)
        state.pop("threshold_candidate", None)
        state.pop("threshold_candidate_since_monotonic", None)
        state.pop("healthy_since_monotonic", None)
    previous_oom = int(state.get("last_oom_kills", snapshot["oom_kills"]))
    state["last_oom_kills"] = snapshot["oom_kills"]
    state["last_resources"] = snapshot
    if snapshot["oom_kills"] > previous_oom:
        return enter_emergency(state, snapshot,
                               f"kernel oom_kill increased from {previous_oom} to {snapshot['oom_kills']}")
    if state.get("mode") == "emergency":
        return advance_emergency(state, snapshot,
                                 state.get("emergency_reason", "resource emergency retry"))
    threshold = confirmed_threshold(state, snapshot, now_monotonic)
    if threshold == "emergency" and state.get("mode") != "emergency":
        return enter_emergency(state, snapshot, "critical memory/GTT/swap/PSI threshold crossed before OOM")
    if threshold == "pressure" and state.get("mode") == "normal":
        return enter_pressure(state, snapshot)
    elif threshold == "healthy" and state.get("mode") == "pressure":
        first = state.get("healthy_since_monotonic")
        if not isinstance(first, (int, float)):
            state["healthy_since_monotonic"] = now_monotonic
        elif now_monotonic - float(first) >= time_policy.seconds(
                time_policy.load(), "resource", "healthy_release_seconds"):
            started = _start_user_units(("agent-ecosystem.service",))
            state["pressure_client_start_result"] = started
            if not started.get("ok"):
                state.update(pressure_error=started.get("error", "unverified restart"),
                             pressure_error_at=cli.now())
                save_state(state)
                cli.audit("resource.pressure_error",
                          incident_id=state.get("pressure_incident_id"),
                          error=state["pressure_error"])
                return state
            resumed = _release_interrupted_jobs(
                state.get("pressure_interrupted_jobs", []), "resource pressure released")
            state.update(mode="normal", pressure_released_at=cli.now())
            state.pop("healthy_since", None)
            state.pop("healthy_since_monotonic", None)
            state.pop("pressure_interrupted_jobs", None)
            state.pop("pressure_error", None)
            state.pop("pressure_error_at", None)
            cli.audit("resource.pressure_released", resources=snapshot,
                      resumed_jobs=resumed)
            save_state(state)
            return state
    elif threshold != "healthy":
        state.pop("healthy_since", None)
        state.pop("healthy_since_monotonic", None)
    save_state(state)
    return state


def request_recovery(job_id: str) -> dict:
    state = load_state()
    if state.get("mode") != "emergency":
        raise RuntimeError("resource control is not in emergency mode")
    if not job_id or job_id != state.get("sole_survivor_job"):
        raise PermissionError("only the active Sole Survivor may reopen dispatch")
    path = cli.ROOT / "state/jobs" / f"{job_id}.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    snapshot = resource_snapshot()
    if _threshold_state(snapshot) != "healthy":
        raise RuntimeError(f"recovery health gate refused: {json.dumps(snapshot, sort_keys=True)}")
    incident_id = state.get("incident_id")
    start = _start_user_units(("agent-ecosystem.service",))
    state["recovery_start_result"] = start
    if not start.get("ok"):
        state.update(recovery_error=start.get("error", "unverified restart"),
                     recovery_error_at=cli.now())
        save_state(state)
        cli.audit("resource.recovery_start_failed", incident_id=incident_id,
                  survivor_job=job_id, error=state["recovery_error"])
        return {"ok": False, "resumed_jobs": [], "resources": snapshot,
                "executor_start": start}
    resumed = _release_interrupted_jobs(
        state.get("interrupted_jobs", []), f"released by Sole Survivor {job_id}")
    state.update(mode="normal", recovered_at=cli.now(), recovered_by=job_id,
                 recovery_resources=snapshot, resumed_jobs=resumed)
    for field in ACTIVE_EMERGENCY_FIELDS:
        state.pop(field, None)
    save_state(state)
    cli.audit("resource.emergency_recovered", incident_id=incident_id,
              survivor_job=job_id, resumed_jobs=resumed, resources=snapshot)
    return {"ok": True, "resumed_jobs": resumed, "resources": snapshot,
            "executor_start": start}


def _survivor_retry_result(state: dict, reused: bool) -> dict:
    retry = _survivor_retry_record(state)
    replacement = retry.get("replacement") if retry is not None else None
    result = {
        "ok": bool(retry is not None and retry["status"] == "active"
                   and state.get("emergency_phase") == "active"
                   and state.get("sole_survivor_job") == replacement),
        "reused": reused,
        "replaced_survivor_job": retry.get("replaces") if retry is not None else None,
        "sole_survivor_job": replacement,
        "emergency_phase": state.get("emergency_phase"),
    }
    if not result["ok"]:
        result["error"] = state.get("emergency_error", "survivor retry remains incomplete")
    return result


def request_survivor_retry() -> dict:
    state = load_state()
    if state.get("mode") != "emergency":
        raise RuntimeError("resource control is not in emergency mode")
    retry = _survivor_retry_record(state)
    if retry is not None and retry["status"] == "active":
        result = _survivor_retry_result(state, reused=True)
        if not result["ok"]:
            raise RuntimeError("active survivor retry record is inconsistent")
        return result
    if retry is None:
        if state.get("emergency_phase") != "active":
            raise RuntimeError("survivor retry requires an active emergency")
        survivor = _survivor_job(state)
        if survivor is None or survivor.get("state") not in SURVIVOR_RETRYABLE_STATES:
            raise RuntimeError("survivor retry requires an exited sole survivor")
        state["survivor_retry"] = {
            "version": 1,
            "status": "requested",
            "reason": "corrected_same_model_allocation",
            "replaces": survivor["id"],
            "requested_at": cli.now(),
            "trigger": state.get("emergency_escalation"),
        }
        _persist_emergency_phase(state, "recorded")
    snapshot = resource_snapshot()
    advanced = advance_emergency(
        state, snapshot, "operator requested corrected same-model survivor retry"
    )
    return _survivor_retry_result(advanced, reused=False)


def run_guard() -> None:
    cli.initialize()
    interval = time_policy.seconds(time_policy.load(), "resource", "poll_seconds")
    while True:
        try:
            tick()
        except Exception as error:
            cli.audit("resource.guard_error", error=f"{type(error).__name__}: {error}")
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(prog="resource-control")
    parser.add_argument(
        "command", choices=("run", "tick", "status", "recover", "retry-survivor")
    )
    args = parser.parse_args()
    if args.command == "run":
        run_guard()
    elif args.command == "tick":
        print(json.dumps(tick(), indent=2, sort_keys=True))
    elif args.command == "status":
        print(json.dumps(load_state(), indent=2, sort_keys=True))
    elif args.command == "recover":
        print(json.dumps(request_recovery(os.environ.get("AGENT_JOB_ID", "")),
                         indent=2, sort_keys=True))
    elif args.command == "retry-survivor":
        print(json.dumps(request_survivor_retry(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
