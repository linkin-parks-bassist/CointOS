"""Fail-safe resource admission and OOM recovery for local inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ecosystem import cli, time_policy


POLICY_PATH = cli.ROOT / "config/resource-policy.json"
RUNNING_STATES = {"running"}
HALTED_MODES = {"pressure", "emergency"}
EMERGENCY_PHASES = (
    "recorded",
    "clients_stopped",
    "models_unloaded",
    "model_loaded",
    "survivor_ready",
    "active",
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


def _lemonade_request(path: str, payload: dict | None = None,
                      method: str | None = None, timeout: float = 5.0) -> dict:
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
        return _lemonade_request("/v1/health", timeout=2.0)
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


def model_is_live(item: dict) -> bool:
    return (bool(item.get("loaded")) and bool(item.get("backend_alive"))
            and item.get("status") not in {"failed", "unloaded", "stopped"})


def emergency_model_live(health: dict | None = None) -> bool:
    current = health if health is not None else lemonade_health()
    expected = policy()["emergency"]["chat_model"]
    return any(item.get("model_name") == expected and model_is_live(item)
               for item in current.get("all_models_loaded", []))


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


def _user_systemctl(*arguments: str) -> None:
    subprocess.run(["systemctl", "--user", *arguments], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def interrupt_model_clients() -> None:
    for unit in ("agent-ecosystem.service", "agent-control-worker.service"):
        _user_systemctl("stop", unit)


def unload_all_models() -> dict:
    try:
        result = _lemonade_request("/v1/unload", {}, timeout=10.0)
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    deadline = time.monotonic() + 10.0
    health = lemonade_health()
    while time.monotonic() < deadline and health.get("all_models_loaded"):
        time.sleep(0.25)
        health = lemonade_health()
    return {"ok": not bool(health.get("all_models_loaded")), "response": result,
            "health": health}


def unload_dynamic_models() -> list[dict]:
    preserved = policy()["emergency"]["chat_model"]
    results = []
    for item in lemonade_health().get("all_models_loaded", []):
        model_name = item.get("model_name")
        if not model_name or model_name == preserved:
            continue
        try:
            response = _lemonade_request("/v1/unload", {"model_name": model_name}, timeout=15.0)
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
    _user_systemctl("stop", "agent-ecosystem.service")
    unloads = unload_dynamic_models()
    state.update(pressure_interrupted_jobs=interrupted,
                 pressure_dynamic_unloads=unloads)
    save_state(state)
    cli.audit("resource.pressure_entered", resources=snapshot,
              interrupted_jobs=interrupted, dynamic_unloads=unloads)
    return state


def load_emergency_model() -> dict:
    emergency = policy()["emergency"]
    payload = {
        "model_name": emergency["chat_model"],
        "pinned": True,
        "ctx_size": emergency["chat_context_tokens"],
        "merge_args": True,
        "llamacpp_args": f"--parallel {emergency['parallel_requests']} --batch-size 512 --ubatch-size 128 --poll 0 --prio -1",
    }
    try:
        result = _lemonade_request("/v1/load", payload, timeout=180.0)
        return {"ok": True, "response": result, "health": lemonade_health()}
    except Exception as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}",
                "health": lemonade_health()}


def _prepare_survivor(incident_path: Path, incident_id: str) -> str:
    from ecosystem.roles import render_context

    emergency_model = policy()["emergency"]["chat_model"]
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
    job_id = cli.enqueue_task(
        "sole_survivor", task, source=f"resource-emergency:{incident_id}",
        model=emergency_model,
        model_reason="The dedicated bounded emergency model is the only model admitted after OOM.",
        agent_name="Sole Survivor",
        idempotency_key=f"resource-emergency:{incident_id}",
    )
    path = cli.ROOT / "state/jobs" / f"{job_id}.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    job.update(
        model=emergency_model,
        model_reason="Emergency policy mechanically assigns the sole bounded survivor model.",
    )
    prompt_path = cli.ROOT / "state/jobs" / f"{job_id}.prompt.md"
    prompt = render_context(job.get("role"), job["task"], job["id"], job["model"],
                            job["model_reason"], job["agent_name"])
    cli.atomic_text(prompt_path, prompt)
    job.update(state="ready", updated_at=cli.now(), prompt=str(prompt_path.relative_to(cli.ROOT)))
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
    save_state(state)


def _record_emergency_error(state: dict, message: str) -> dict:
    state.update(emergency_error=message, emergency_error_at=cli.now())
    save_state(state)
    cli.audit("resource.emergency_error", incident_id=state.get("incident_id"),
              phase=state.get("emergency_phase"), error=message)
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


def _survivor_is_ready(state: dict) -> bool:
    identifier = state.get("sole_survivor_job")
    if not identifier:
        return False
    path = cli.ROOT / "state/jobs" / f"{identifier}.json"
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (job.get("id") == identifier and job.get("state") == "ready"
            and job.get("source") == f"resource-emergency:{state.get('incident_id')}")


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
            interrupt_model_clients()
        except Exception as error:
            return _record_emergency_error(
                state, f"client interruption failed: {type(error).__name__}: {error}"
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
        try:
            survivor = _prepare_survivor(
                _incident_path_from_state(state), state["incident_id"]
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
            _user_systemctl("start", "--no-block", "agent-control-worker.service",
                            "agent-ecosystem.service")
        except Exception as error:
            return _record_emergency_error(
                state, f"survivor executor start failed: {type(error).__name__}: {error}"
            )
        os.sync()
        _persist_emergency_phase(state, "active")
        cli.audit("resource.emergency_entered", incident_id=state["incident_id"],
                  reason=state["emergency_reason"], survivor_job=state["sole_survivor_job"],
                  emergency_model_ready=True)
        return state

    if phase == "active":
        if not emergency_model_live():
            return _record_emergency_error(state, "emergency model is not live")
        if not _survivor_is_ready(state):
            return _record_emergency_error(state, "sole survivor job is not ready")
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
            resumed = _release_interrupted_jobs(
                state.get("pressure_interrupted_jobs", []), "resource pressure released")
            state.update(mode="normal", pressure_released_at=cli.now())
            state.pop("healthy_since", None)
            state.pop("healthy_since_monotonic", None)
            state.pop("pressure_interrupted_jobs", None)
            cli.audit("resource.pressure_released", resources=snapshot,
                      resumed_jobs=resumed)
            save_state(state)
            _user_systemctl("start", "--no-block", "agent-ecosystem.service")
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
    resumed = _release_interrupted_jobs(
        state.get("interrupted_jobs", []), f"released by Sole Survivor {job_id}")
    state.update(mode="normal", recovered_at=cli.now(), recovered_by=job_id,
                 recovery_resources=snapshot, resumed_jobs=resumed)
    save_state(state)
    cli.audit("resource.emergency_recovered", incident_id=state.get("incident_id"),
              survivor_job=job_id, resumed_jobs=resumed, resources=snapshot)
    _user_systemctl("start", "--no-block", "agent-ecosystem.service")
    return {"ok": True, "resumed_jobs": resumed, "resources": snapshot}


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
    parser.add_argument("command", choices=("run", "tick", "status", "recover"))
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


if __name__ == "__main__":
    main()
