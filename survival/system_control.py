"""Durable lifecycle-effect execution at the privileged system fingertip."""

import hashlib
import json
import math
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from survival import (
    checkpoint,
    lifecycle,
    protocol,
    records,
    systemd_notify,
    telegram_api,
    time_policy,
)
from survival.json_codec import decode_json_object


SURVIVAL_UNITS = frozenset((
    "cointelprofessional-checkpoint.service",
    "cointelprofessional-gateway.service",
    "cointelprofessional-guardian.service",
    "cointelprofessional-guardian.socket",
))
DESTRUCTIBLE_SYSTEM_UNITS = frozenset(("lemond.service",))
DESTRUCTIBLE_USER_UNITS = frozenset((
    "agent-models.service",
    "agent-telegram.service",
    "agent-notifier.service",
    "agent-ecosystem.service",
    "agent-ecosystem.path",
    "agent-ecosystem.timer",
    "agent-watchdog.service",
    "agent-watchdog.timer",
    "agent-resource-guard.service",
))
DESTRUCTIBLE_UNITS = DESTRUCTIBLE_SYSTEM_UNITS | DESTRUCTIBLE_USER_UNITS
SYSTEMCTL_ACTIONS = frozenset((
    "start", "stop", "terminate", "kill", "reset_failed", "status",
))
DIRECT_EFFECT_KINDS = frozenset((
    "notify", "close_admission", "checkpoint", "reconcile", "verify",
    "resume", "finish",
))
REQUIRED_ADAPTER_KINDS = DIRECT_EFFECT_KINDS | frozenset(("system", "user"))
PRODUCTION_ADAPTER_KINDS = REQUIRED_ADAPTER_KINDS | frozenset(("wait",))
EFFECT_COMPLETION_EVENTS = {
    "close_admission": "admission_closed",
    "checkpoint": "checkpointed",
    "stop_units": "units_stopped",
    "kill_units": "units_killed",
    "stop_lemonade": "backend_stopped",
    "start_lemonade": "lemonade_started",
    "start_units": "units_started",
    "reconcile": "reconciled",
    "verify": "verified",
    "resume": "resumed",
    "finish": "finished",
}
REQUEST_FIELDS = frozenset(("schema_version", "command", "state"))
RESULT_FIELDS = frozenset((
    "schema_version", "effect_idempotency_key", "ok", "result",
))
MAX_EFFECT_OUTPUT_BYTES = 4096
MAXIMUM_EFFECTS_PER_ADVANCE = 128
USER_MANAGER_HOST = "david@.host"
CATALOG_FIELDS = frozenset((
    "schema_version", "backend_unit", "checkpoint", "model_health", "user_units",
))
CATALOG_CATEGORIES = (
    "activation_sources", "inference_prerequisites", "control_services",
    "ordinary_services", "inactive_units",
)
MODEL_HEALTH_FIELDS = frozenset(("host", "port", "path", "required_model"))
UNIT_ENTRY_FIELDS = frozenset(("unit", "required"))
ACTIVE_JOB_STATES = frozenset(("claimed", "reserved", "running", "verifying"))
JOB_TRANSITION_FIELDS = frozenset((
    "schema_version", "request_id", "job_id", "transition_state",
    "opencode_session",
))
JOB_TRANSITION_STATES = frozenset(("intended", "completed"))


def authorize_peer(uid: int, gateway_uid: int) -> None:
    """Admit exactly one configured Unix gateway identity."""
    if (
        type(uid) is not int
        or type(gateway_uid) is not int
        or uid < 0
        or gateway_uid < 0
        or uid != gateway_uid
    ):
        raise PermissionError("peer uid is not the configured gateway uid")


def validate_destructible_units(units: list[str]) -> list[str]:
    """Validate an explicit list against the immutable destructible allowlist."""
    if type(units) is not list or any(type(unit) is not str for unit in units):
        raise ValueError("invalid destructible unit list")
    survival = [unit for unit in units if unit in SURVIVAL_UNITS]
    if survival:
        raise ValueError(f"survival unit cannot be destroyed: {survival[0]}")
    unknown = [unit for unit in units if unit not in DESTRUCTIBLE_UNITS]
    if unknown:
        raise ValueError(f"unit is outside the destructible allowlist: {unknown[0]}")
    return list(units)


def load_lifecycle_catalog(path):
    """Decode the installed semantic unit catalogue as exact plain data."""
    try:
        value = decode_json_object(Path(path).read_bytes(), "lifecycle catalogue")
    except OSError as error:
        raise ValueError("cannot read lifecycle catalogue") from error
    if set(value) != CATALOG_FIELDS or value.get("schema_version") != 1:
        raise ValueError("invalid lifecycle catalogue fields")
    if type(value["backend_unit"]) is not str:
        raise ValueError("invalid lifecycle backend unit")
    validate_destructible_units([value["backend_unit"]])
    checkpoint.validate_checkpoint_catalog(value["checkpoint"])
    model_health = value["model_health"]
    if (
        type(model_health) is not dict
        or set(model_health) != MODEL_HEALTH_FIELDS
        or type(model_health["host"]) is not str
        or not model_health["host"]
        or type(model_health["port"]) is not int
        or not 0 < model_health["port"] < 65536
        or type(model_health["path"]) is not str
        or not model_health["path"].startswith("/")
        or type(model_health["required_model"]) is not str
        or not model_health["required_model"]
    ):
        raise ValueError("invalid lifecycle model health contract")
    categories = value["user_units"]
    if type(categories) is not dict or set(categories) != set(CATALOG_CATEGORIES):
        raise ValueError("invalid lifecycle catalogue categories")
    seen = set()
    for category in CATALOG_CATEGORIES:
        entries = categories[category]
        if type(entries) is not list:
            raise ValueError("invalid lifecycle unit entries")
        for entry in entries:
            if (
                type(entry) is not dict
                or set(entry) != UNIT_ENTRY_FIELDS
                or type(entry["unit"]) is not str
                or type(entry["required"]) is not bool
            ):
                raise ValueError("invalid lifecycle unit entry")
            validate_destructible_units([entry["unit"]])
            if entry["unit"] in seen:
                raise ValueError("duplicate lifecycle unit")
            seen.add(entry["unit"])
    return value


def checked_action(run, verify) -> dict:
    """Require both a zero command status and an independently checked condition."""
    result = _normalise_process_result(run())
    verified = verify()
    return {
        "ok": result["exit_code"] == 0 and verified is True,
        "exit_code": result["exit_code"],
    }


def _subprocess_runner(argv: list[str], timeout=10, heartbeat=None) -> dict:
    """Run one fixed-argv command and retain only bounded diagnostics."""
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                stdout, stderr = process.communicate()
                return {
                    "exit_code": -1,
                    "stdout": _bounded_text(stdout),
                    "stderr": _bounded_text(
                        stderr or f"command exceeded {timeout:g}-second deadline"
                    ),
                }
            try:
                stdout, stderr = process.communicate(timeout=min(1.0, remaining))
                return _normalise_process_result({
                    "exit_code": process.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                })
            except subprocess.TimeoutExpired:
                if heartbeat is not None:
                    heartbeat()
    except OSError as error:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": _bounded_text(str(error)),
        }


def _run_with_watchdog(
    operation,
    deadline_seconds,
    heartbeat,
    pulse_seconds=1.0,
):
    """Bound a non-subprocess fingertip while preserving guardian liveness."""
    for value, name in (
        (deadline_seconds, "external operation deadline"),
        (pulse_seconds, "watchdog pulse period"),
    ):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid {name}")
    if not callable(operation) or not callable(heartbeat):
        raise ValueError("invalid watchdog operation")
    values = []
    errors = []

    def run():
        try:
            values.append(operation())
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    deadline = time.monotonic() + deadline_seconds
    while worker.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"ok": False, "error": "external operation deadline expired"}
        worker.join(min(pulse_seconds, remaining))
        if worker.is_alive():
            heartbeat()
    if errors:
        return {"ok": False, "error": _bounded_text(str(errors[0]))}
    if len(values) != 1 or type(values[0]) is not dict:
        return {"ok": False, "error": "invalid external operation result"}
    return values[0]


def _normalise_process_result(result) -> dict:
    if type(result) is dict:
        exit_code = result.get("exit_code", result.get("returncode", -1))
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
    else:
        exit_code = getattr(result, "returncode", -1)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
    if type(exit_code) is not int:
        exit_code = -1
    return {
        "exit_code": exit_code,
        "stdout": _bounded_text(stdout),
        "stderr": _bounded_text(stderr),
    }


def _bounded_text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if type(value) is not str:
        value = str(value)
    return value[:MAX_EFFECT_OUTPUT_BYTES]


def _invoke(adapter, argv: list[str]) -> dict:
    try:
        return _normalise_process_result(adapter(list(argv)))
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": _bounded_text(str(error)),
        }


def _manager_prefix(manager: str) -> list[str]:
    if manager == "system":
        return ["systemctl", "--system"]
    if manager == "user":
        return ["systemctl", "--user", f"--machine={USER_MANAGER_HOST}"]
    raise ValueError("invalid systemd manager")


def _active_state(result: dict) -> str:
    value = result["stdout"].strip()
    if value in {"active", "inactive", "failed", "activating", "deactivating"}:
        return value
    return "unknown"


def _query_cgroup_empty(manager: str, unit: str, uid: int | None, query) -> dict:
    show = _invoke(
        query,
        _manager_prefix(manager) + [
            "show", "--property=ControlGroup", "--value", unit,
        ],
    )
    cgroup_path = show["stdout"].strip()
    result = {
        "empty": False,
        "path": cgroup_path,
        "query": show,
    }
    if show["exit_code"] != 0:
        result["error"] = "cgroup path was not verified"
        return result
    if not cgroup_path:
        result["empty"] = True
        return result
    if not cgroup_path.startswith("/"):
        result["error"] = "cgroup path was not verified"
        return result
    if manager == "user":
        expected_slice = f"/user.slice/user-{uid}.slice/"
        expected_manager = f"/user@{uid}.service/"
        if expected_slice not in cgroup_path or expected_manager not in cgroup_path:
            result["error"] = "cgroup path does not match configured uid"
            return result
    events_path = Path("/sys/fs/cgroup") / cgroup_path.lstrip("/") / "cgroup.events"
    try:
        with events_path.open(encoding="utf-8") as source:
            text = source.read(MAX_EFFECT_OUTPUT_BYTES + 1)
    except OSError as error:
        result["error"] = _bounded_text(str(error))
        return result
    if len(text) > MAX_EFFECT_OUTPUT_BYTES:
        result["error"] = "cgroup events exceeded bounded read"
        return result
    values = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 2:
            result["error"] = "invalid cgroup events"
            return result
        values[fields[0]] = fields[1]
    if values.get("populated") not in {"0", "1"}:
        result["error"] = "missing cgroup population state"
        return result
    result["empty"] = values["populated"] == "0"
    return result


def _normalise_cgroup_result(result) -> dict:
    if type(result) is bool:
        return {"empty": result}
    if type(result) is not dict or type(result.get("empty")) is not bool:
        return {"empty": False, "error": "invalid cgroup query result"}
    value = {}
    for key, item in result.items():
        value[key] = _bounded_text(item) if type(item) in {str, bytes} else item
    return value


def _unit_action(
    manager: str,
    action: str,
    unit: str,
    uid: int | None,
    runner,
    query,
    cgroup,
) -> dict:
    if action not in SYSTEMCTL_ACTIONS:
        raise ValueError(f"systemctl action is outside the allowlist: {action!r}")
    allowlist = DESTRUCTIBLE_SYSTEM_UNITS if manager == "system" else DESTRUCTIBLE_USER_UNITS
    if unit in SURVIVAL_UNITS:
        raise ValueError(f"survival unit cannot be controlled: {unit}")
    if unit not in allowlist:
        raise ValueError(f"unit is outside the {manager} allowlist: {unit}")
    if manager == "user" and (type(uid) is not int or uid < 0):
        raise ValueError("user manager uid must be configured explicitly")

    prefix = _manager_prefix(manager)
    if action == "status":
        action_result = {"exit_code": 0, "stdout": "", "stderr": ""}
    elif action in {"terminate", "kill"}:
        signal_name = "SIGTERM" if action == "terminate" else "SIGKILL"
        action_result = _invoke(
            runner,
            prefix + ["kill", "--kill-who=all", f"--signal={signal_name}", unit],
        )
    elif action == "reset_failed":
        action_result = _invoke(runner, prefix + ["reset-failed", unit])
    else:
        action_result = _invoke(runner, prefix + [action, unit])
    load_result = None
    installed = True
    if action == "status":
        load_result = _invoke(
            query,
            prefix + ["show", "--property=LoadState", "--value", unit],
        )
        installed = load_result["exit_code"] == 0 and load_result["stdout"].strip() == "loaded"
    state_result = _invoke(query, prefix + ["is-active", unit])
    state = _active_state(state_result) if installed else "not-found"
    if action == "status":
        cgroup_result = {"empty": False}
    elif cgroup is None:
        cgroup_result = _query_cgroup_empty(manager, unit, uid, query)
    else:
        try:
            cgroup_result = _normalise_cgroup_result(cgroup(manager, unit, uid))
        except OSError as error:
            cgroup_result = {"empty": False, "error": _bounded_text(str(error))}

    if action == "status":
        postcondition = installed and state != "unknown"
    elif action == "start":
        postcondition = state == "active"
    elif action == "stop":
        postcondition = state == "inactive" and cgroup_result["empty"] is True
    elif action == "kill":
        postcondition = (
            state in {"active", "inactive", "failed"}
            and cgroup_result["empty"] is True
        )
    elif action == "reset_failed":
        postcondition = state in {"active", "inactive"}
    else:
        postcondition = state in {"active", "inactive", "failed", "deactivating"}
    return {
        "ok": action_result["exit_code"] == 0 and postcondition,
        "action": action,
        "unit": unit,
        "exit_code": action_result["exit_code"],
        "stdout": action_result["stdout"],
        "stderr": action_result["stderr"],
        "state": state,
        "state_query": state_result,
        "cgroup_empty": cgroup_result["empty"],
        "cgroup": cgroup_result,
        "installed": installed,
        "load_query": load_result,
    }


def system_unit(
    action: str,
    unit: str,
    *,
    runner=_subprocess_runner,
    query=_subprocess_runner,
    cgroup=None,
) -> dict:
    """Execute one allowlisted system-manager operation and verify its result."""
    return _unit_action("system", action, unit, None, runner, query, cgroup)


def user_unit(
    action: str,
    unit: str,
    *,
    uid: int | None = None,
    runner=_subprocess_runner,
    query=_subprocess_runner,
    cgroup=None,
) -> dict:
    """Execute one allowlisted user-manager operation for the configured uid."""
    return _unit_action("user", action, unit, uid, runner, query, cgroup)


def _validate_effect(effect: object) -> None:
    if type(effect) is not dict or set(effect) != lifecycle.EFFECT_FIELDS:
        raise ValueError("invalid lifecycle effect")
    if (
        type(effect["kind"]) is not str
        or effect["kind"] not in lifecycle.EFFECT_KINDS
        or type(effect["request_id"]) is not str
        or type(effect["phase"]) is not str
        or effect["phase"] not in lifecycle.PHASES
        or effect["idempotency_key"] != lifecycle._effect_key(
            effect["request_id"], effect["phase"], effect["kind"],
        )
    ):
        raise ValueError("invalid lifecycle effect")


def _normalise_effect_result(kind: str, effect_key: str, results: list[dict]) -> dict:
    return {
        "kind": kind,
        "effect_idempotency_key": effect_key,
        "ok": bool(results) and all(
            type(result) is dict and result.get("ok") is True for result in results
        ),
        "results": results,
    }


def _catalog_entries(policy, category):
    try:
        return policy["lifecycle_catalog"]["user_units"][category]
    except (KeyError, TypeError) as error:
        raise ValueError("missing lifecycle catalogue policy") from error


def _manager_result(adapter, action, unit):
    if not callable(adapter):
        return {"ok": False, "error": "missing manager adapter", "unit": unit}
    try:
        result = adapter(action, unit)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": _bounded_text(str(error)), "unit": unit}
    if type(result) is not dict:
        return {"ok": False, "error": "invalid manager adapter result", "unit": unit}
    return result


def _stop_with_escalation(adapter, unit, immediate, policy, wait):
    results = []
    if not immediate:
        cooperative = _manager_result(adapter, "stop", unit)
        results.append(cooperative)
        if cooperative.get("ok") is True:
            return {"ok": True, "unit": unit, "stages": results}
    results.append(_manager_result(adapter, "terminate", unit))
    wait(time_policy.seconds(
        policy["timing_policy"], "lifecycle", "terminate_grace_seconds",
    ))
    final = _manager_result(adapter, "kill", unit)
    results.append(final)
    wait(time_policy.seconds(
        policy["timing_policy"], "lifecycle", "kill_grace_seconds",
    ))
    stopped = _manager_result(adapter, "stop", unit)
    results.append(stopped)
    return {
        "ok": final.get("exit_code", 0) == 0 and stopped.get("ok") is True,
        "unit": unit,
        "stages": results,
    }


def _runtime_path(policy, request_id):
    try:
        store = Path(policy["store_path"])
    except (KeyError, TypeError) as error:
        raise ValueError("missing lifecycle store policy") from error
    return store / "lifecycle-runtime" / f"{request_id}.json"


def _read_runtime(policy, request_id):
    path = _runtime_path(policy, request_id)
    try:
        value = decode_json_object(path.read_bytes(), "lifecycle runtime")
    except OSError as error:
        raise ValueError("missing lifecycle runtime snapshot") from error
    if (
        set(value) != {
            "schema_version", "request_id", "previous_pause",
            "previous_active_user_units", "interrupted_jobs",
        }
        or value.get("schema_version") != 1
        or value.get("request_id") != request_id
        or type(value.get("previous_pause")) is not bool
        or type(value.get("previous_active_user_units")) is not list
        or any(type(unit) is not str for unit in value["previous_active_user_units"])
        or type(value.get("interrupted_jobs")) is not list
    ):
        raise ValueError("invalid lifecycle runtime snapshot")
    return value


def _write_runtime(policy, value):
    records.atomic_json(_runtime_path(policy, value["request_id"]), value)


def execute_effect(effect: dict, adapters: dict, policy: dict) -> dict:
    """Interpret one Task 2 effect through explicit external adapters."""
    _validate_effect(effect)
    if type(adapters) is not dict or type(policy) is not dict:
        raise ValueError("invalid effect execution context")
    kind = effect["kind"]
    effect_key = effect["idempotency_key"]

    if kind in DIRECT_EFFECT_KINDS:
        adapter = adapters.get(kind)
        if not callable(adapter):
            return _normalise_effect_result(kind, effect_key, [{
                "ok": False,
                "error": f"missing {kind} adapter",
            }])
        try:
            result = adapter(dict(effect), dict(policy))
        except (OSError, RuntimeError, ValueError) as error:
            result = {"ok": False, "error": _bounded_text(str(error))}
        if type(result) is not dict:
            result = {"ok": False, "error": f"invalid {kind} adapter result"}
        return _normalise_effect_result(kind, effect_key, [result])

    results = []
    user_adapter = adapters.get("user")
    system_adapter = adapters.get("system")
    wait = adapters.get("wait", lambda _seconds: None)
    if not callable(wait):
        raise ValueError("invalid lifecycle wait adapter")
    if kind == "stop_units":
        for category in (
            "activation_sources", "ordinary_services", "control_services",
            "inference_prerequisites", "inactive_units",
        ):
            for entry in _catalog_entries(policy, category):
                results.append(_stop_with_escalation(
                    user_adapter, entry["unit"], immediate=False,
                    policy=policy, wait=wait,
                ))
    elif kind == "kill_units":
        for entry in _catalog_entries(policy, "activation_sources"):
            results.append(_stop_with_escalation(
                user_adapter, entry["unit"], immediate=False,
                policy=policy, wait=wait,
            ))
        for category in (
            "ordinary_services", "control_services", "inference_prerequisites",
            "inactive_units",
        ):
            for entry in _catalog_entries(policy, category):
                results.append(_stop_with_escalation(
                    user_adapter, entry["unit"], immediate=True,
                    policy=policy, wait=wait,
                ))
    elif kind == "stop_lemonade":
        results.append(_stop_with_escalation(
            system_adapter,
            policy["lifecycle_catalog"]["backend_unit"],
            immediate=False,
            policy=policy,
            wait=wait,
        ))
    elif kind == "start_lemonade":
        results.append(_manager_result(
            system_adapter, "reset_failed", policy["lifecycle_catalog"]["backend_unit"],
        ))
        results.append(_manager_result(
            system_adapter, "start", policy["lifecycle_catalog"]["backend_unit"],
        ))
    elif kind == "start_units":
        runtime = _read_runtime(policy, effect["request_id"])
        previous_active = set(runtime["previous_active_user_units"])
        for entry in _catalog_entries(policy, "inference_prerequisites"):
            results.append(_manager_result(user_adapter, "reset_failed", entry["unit"]))
            results.append(_manager_result(user_adapter, "start", entry["unit"]))
        for entry in _catalog_entries(policy, "control_services"):
            if entry["unit"] in previous_active:
                results.append(_manager_result(user_adapter, "reset_failed", entry["unit"]))
                results.append(_manager_result(user_adapter, "start", entry["unit"]))
    else:
        return _normalise_effect_result(kind, effect_key, [{
            "ok": False,
            "error": f"unsupported lifecycle effect: {kind}",
        }])

    return _normalise_effect_result(kind, effect_key, results)


def _request_path(store: Path, request_id: str) -> Path:
    return Path(store) / "lifecycle" / f"{request_id}.json"


def _request_record(command: dict, state: dict) -> dict:
    return {
        "schema_version": 1,
        "command": dict(command),
        "state": state,
    }


def _read_request(path: Path) -> dict:
    try:
        record = decode_json_object(path.read_bytes(), "lifecycle request")
    except OSError as error:
        raise ValueError(f"cannot read lifecycle request: {path}") from error
    if type(record) is not dict or set(record) != REQUEST_FIELDS:
        raise ValueError("invalid lifecycle request fields")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("invalid lifecycle request version")
    protocol.encode_command(record["command"])
    lifecycle._validate_state(record["state"])
    if (
        record["state"]["request_id"] != record["command"]["request_id"]
        or record["state"]["command"] != record["command"]["command"]
    ):
        raise ValueError("lifecycle request identity mismatch")
    return record


def _write_request(path: Path, command: dict, state: dict) -> None:
    lifecycle._validate_state(state)
    records.atomic_json(path, _request_record(command, state))


def accept_request(store: Path, command: dict, previous_pause: bool) -> Path:
    """Create or exactly replay one durable Task 2 lifecycle request."""
    protocol.encode_command(command)
    path = _request_path(Path(store), command["request_id"])
    if path.exists():
        record = _read_request(path)
        if (
            record["command"] != command
            or record["state"]["previous_pause"] is not previous_pause
        ):
            raise ValueError("lifecycle request identity mismatch")
        return path
    state = lifecycle.new_lifecycle(command, previous_pause)
    _write_request(path, command, state)
    return path


def _effect_result_directory(path, effect_key):
    digest = hashlib.sha256(effect_key.encode("utf-8")).hexdigest()
    return path.parent / "results" / path.stem / digest


def _store_effect_result(path, effect, result):
    """Publish one complete immutable result attempt; a torn peer cannot poison it."""
    directory = _effect_result_directory(Path(path), effect["idempotency_key"])
    directory.mkdir(parents=True, exist_ok=True)
    attempts = [
        int(candidate.stem)
        for candidate in directory.glob("[0-9][0-9][0-9][0-9][0-9][0-9].json")
        if candidate.stem.isdecimal()
    ]
    attempt = max(attempts, default=0) + 1
    destination = directory / f"{attempt:06d}.json"
    value = {
        "schema_version": 1,
        "effect_idempotency_key": effect["idempotency_key"],
        "ok": result.get("ok") is True,
        "result": result,
    }
    records._create_exclusive_json(destination, value)
    return destination


def _append_effect_result(path: Path, effect: dict, result: dict) -> None:
    _store_effect_result(path, effect, result)


def _quarantine_result(path, result_path, reason):
    directory = path.parent.parent / "lifecycle-result-quarantine"
    directory.mkdir(parents=True, exist_ok=True)
    identity = f"{path.stem}-{time.time_ns()}-{result_path.name}"
    quarantined = directory / f"{identity}.record"
    os.replace(result_path, quarantined)
    records.atomic_json(directory / f"{identity}.json", {
        "schema_version": 1,
        "source_path": str(result_path),
        "quarantined_path": str(quarantined),
        "error_reason": str(reason),
    })


def _verified_effect_result(path: Path, effect_key: str) -> dict | None:
    directory = _effect_result_directory(Path(path), effect_key)
    if not directory.exists():
        return None
    verified = None
    for result_path in sorted(directory.glob("*.json")):
        try:
            record = decode_json_object(result_path.read_bytes(), "lifecycle effect result")
            if type(record) is not dict or set(record) != RESULT_FIELDS:
                raise ValueError("invalid lifecycle effect result")
            if (
                type(record["schema_version"]) is not int
                or record["schema_version"] != 1
                or record["effect_idempotency_key"] != effect_key
                or type(record["ok"]) is not bool
                or type(record["result"]) is not dict
            ):
                raise ValueError("invalid lifecycle effect result")
        except (OSError, ValueError) as error:
            _quarantine_result(Path(path), result_path, str(error))
            continue
        if record["ok"] is True:
            verified = record["result"]
    return verified


def _persist_reduction(path: Path, command: dict, state: dict, event: dict) -> dict:
    next_state, _effects = lifecycle.reduce_lifecycle(state, event)
    if next_state is not state:
        _write_request(path, command, next_state)
        return _read_request(path)["state"]
    return state


def _pending_blocked_report(state):
    return next((
        dict(effect)
        for effect in reversed(state["pending_effects"])
        if effect["kind"] == "notify"
    ), None)


def advance_request(path: Path, adapters: dict, policy: dict) -> dict:
    """Advance only persisted Task 2 effects across crash-safe commit boundaries."""
    if type(policy) is not dict:
        raise ValueError("invalid lifecycle policy")
    path = Path(path)
    record = _read_request(path)
    command = record["command"]
    state = record["state"]

    verified_event = policy.get("verified_event")
    if verified_event is not None:
        state = _persist_reduction(path, command, state, verified_event)

    maximum_effects = policy.get(
        "maximum_effects", MAXIMUM_EFFECTS_PER_ADVANCE,
    )
    if type(maximum_effects) is not int or maximum_effects <= 0:
        raise ValueError("invalid maximum lifecycle effects")

    completed_count = 0
    while state["pending_effects"] and completed_count < maximum_effects:
        effect = dict(state["pending_effects"][0])
        result = _verified_effect_result(path, effect["idempotency_key"])
        if result is None:
            result = execute_effect(effect, adapters, policy)
            _store_effect_result(path, effect, result)
            if result["ok"] is not True:
                if state["phase"] not in {"blocked", "failed"}:
                    state = _persist_reduction(path, command, state, {
                        "kind": "blocked",
                        "idempotency_key": (
                            f"{state['request_id']}:blocked:{effect['idempotency_key']}"
                        ),
                    })
                    report = _pending_blocked_report(state)
                    if report is not None:
                        report_result = execute_effect(report, adapters, policy)
                        _store_effect_result(path, report, report_result)
                        if report_result["ok"] is True:
                            state = _persist_reduction(path, command, state, {
                                "kind": "effect_completed",
                                "effect_idempotency_key": report["idempotency_key"],
                            })
                return {
                    "ok": False,
                    "phase": state["phase"],
                    "remaining_effects": len(state["pending_effects"]),
                    "failed_effect": effect["idempotency_key"],
                }

        state = _persist_reduction(path, command, state, {
            "kind": "effect_completed",
            "effect_idempotency_key": effect["idempotency_key"],
        })
        completion_event = EFFECT_COMPLETION_EVENTS.get(effect["kind"])
        if completion_event is not None:
            state = _persist_reduction(path, command, state, {
                "kind": completion_event,
            })
        completed_count += 1

    return {
        "ok": state["phase"] == "completed" and not state["pending_effects"],
        "phase": state["phase"],
        "remaining_effects": len(state["pending_effects"]),
    }


def commit_acknowledgement(path):
    """Make an accepted socket response imply durable pending lifecycle work."""
    path = Path(path)
    record = _read_request(path)
    state = record["state"]
    if state["phase"] == "accepted":
        _persist_reduction(path, record["command"], state, {"kind": "ack_committed"})
    return _read_request(path)["state"]


def recover_request(path):
    path = Path(path)
    record = _read_request(path)
    state = record["state"]
    if state["phase"] in {"blocked", "failed"}:
        return _persist_reduction(path, record["command"], state, {
            "kind": "recover",
            "idempotency_key": f"{state['request_id']}:recover:{time.time_ns()}",
        })
    return state


def incomplete_request_paths(store):
    directory = Path(store) / "lifecycle"
    if not directory.is_dir():
        return []
    paths = []
    for path in sorted(directory.glob("telegram-*.json")):
        record = _read_request(path)
        state = record["state"]
        if state["phase"] != "completed" or state["pending_effects"]:
            paths.append(path)
    return sorted(
        paths,
        key=lambda path: _read_request(path)["command"]["telegram_update_id"],
    )


def prior_pause_for_new_request(store, agent_state_path):
    """Preserve the operator state across any serialized lifecycle queue."""
    pending = incomplete_request_paths(store)
    if pending:
        return _read_request(pending[0])["state"]["previous_pause"]
    return (Path(agent_state_path) / "PAUSED").exists()


def new_lifecycle(command: dict, previous_pause: bool) -> dict:
    return lifecycle.new_lifecycle(command, previous_pause)


def reduce_lifecycle(state: dict, event: dict) -> tuple[dict, list[dict]]:
    return lifecycle.reduce_lifecycle(state, event)


def _agent_record(path):
    try:
        return decode_json_object(path.read_bytes(), "agent runtime record")
    except OSError as error:
        raise ValueError(f"cannot read agent runtime record: {path}") from error


def _write_agent_record(path, value):
    metadata = path.stat()
    records.atomic_json(
        path,
        value,
        mode=records.PRIVATE_RECORD_MODE,
        owner=(metadata.st_uid, metadata.st_gid),
    )


def _active_job_paths(agent_state_path):
    directory = Path(agent_state_path) / "jobs"
    if not directory.is_dir():
        return []
    paths = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = _agent_record(path)
        except ValueError:
            continue
        if value.get("kind") == "agent-task" and value.get("state") in ACTIVE_JOB_STATES:
            paths.append(path)
    return paths


def _canonical_request_id(request_id):
    if type(request_id) is not str or not request_id.startswith("telegram-"):
        raise ValueError("invalid lifecycle request identity")
    update_id = request_id.removeprefix("telegram-")
    if not update_id.isdecimal() or f"telegram-{int(update_id)}" != request_id:
        raise ValueError("invalid lifecycle request identity")
    return request_id


def _canonical_job_id(job_id):
    if (
        type(job_id) is not str
        or not job_id
        or Path(job_id).name != job_id
        or job_id in {".", ".."}
    ):
        raise ValueError("invalid lifecycle job identity")
    return job_id


def _job_path(config, job_id):
    return (
        Path(config["agent_state_path"])
        / "jobs"
        / f"{_canonical_job_id(job_id)}.json"
    )


def _job_identity(config, path):
    path = Path(path)
    jobs = Path(config["agent_state_path"]) / "jobs"
    job_id = path.stem
    if path != jobs / f"{job_id}.json":
        raise ValueError("job path is outside the lifecycle job store")
    job = _agent_record(path)
    if job.get("kind") != "agent-task" or job.get("id") != job_id:
        raise ValueError("invalid lifecycle job identity")
    return job_id, job


def _job_transition_directory(config, request_id):
    return (
        Path(config["store_path"])
        / "lifecycle-transitions"
        / _canonical_request_id(request_id)
    )


def _job_transition_path(config, request_id, job_id):
    return _job_transition_directory(config, request_id) / (
        f"{_canonical_job_id(job_id)}.json"
    )


def _validate_job_transition(value, request_id, job_id):
    if (
        type(value) is not dict
        or set(value) != JOB_TRANSITION_FIELDS
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("request_id") != request_id
        or value.get("job_id") != job_id
        or type(value.get("transition_state")) is not str
        or value.get("transition_state") not in JOB_TRANSITION_STATES
        or (
            value.get("opencode_session") is not None
            and (
                type(value["opencode_session"]) is not str
                or not value["opencode_session"].startswith("ses_")
            )
        )
    ):
        raise ValueError("invalid lifecycle job transition")
    return value


def _read_job_transition(path, request_id, job_id):
    try:
        value = decode_json_object(Path(path).read_bytes(), "lifecycle job transition")
    except OSError as error:
        raise ValueError("missing lifecycle job transition") from error
    return _validate_job_transition(value, request_id, job_id)


def _job_interruption_postcondition(job, request_id, session):
    if (
        job.get("state") != "interrupted"
        or job.get("interrupted_by") != request_id
        or job.get("interruption_reason") != "survival lifecycle teardown"
        or job.get("resume_available") is not (session is not None)
    ):
        return False
    if session is None:
        return "opencode_session" not in job
    return job.get("opencode_session") == session


def _interrupt_one_job(config, request_id, path, checkpoint_session=None):
    job_id, job = _job_identity(config, path)
    transition_path = _job_transition_path(config, request_id, job_id)
    if transition_path.exists():
        transition = _read_job_transition(transition_path, request_id, job_id)
    else:
        if job.get("state") not in ACTIVE_JOB_STATES:
            return
        session = checkpoint_session
        transition = {
            "schema_version": 1,
            "request_id": request_id,
            "job_id": job_id,
            "transition_state": "intended",
            "opencode_session": session,
        }
        records.atomic_json(transition_path, transition)

    session = transition["opencode_session"]
    if not _job_interruption_postcondition(job, request_id, session):
        if job.get("state") not in ACTIVE_JOB_STATES:
            raise ValueError("job does not satisfy its interruption intent")
        job["state"] = "interrupted"
        job["interrupted_by"] = request_id
        job["interruption_reason"] = "survival lifecycle teardown"
        job["resume_available"] = session is not None
        if session is None:
            job.pop("opencode_session", None)
        else:
            job["opencode_session"] = session
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_agent_record(path, job)
        job = _agent_record(path)
        if not _job_interruption_postcondition(job, request_id, session):
            raise ValueError("job interruption postcondition was not observed")

    if transition["transition_state"] != "completed":
        completed = dict(transition)
        completed["transition_state"] = "completed"
        records.atomic_json(transition_path, completed)


def _derived_interrupted_jobs(config, request_id):
    directory = _job_transition_directory(config, request_id)
    interrupted = []
    if not directory.is_dir():
        return interrupted
    for transition_path in sorted(directory.glob("*.json")):
        job_id = transition_path.stem
        transition = _read_job_transition(transition_path, request_id, job_id)
        if transition["transition_state"] != "completed":
            continue
        _job_id, job = _job_identity(config, _job_path(config, job_id))
        if not _job_interruption_postcondition(
            job, request_id, transition["opencode_session"],
        ):
            raise ValueError("completed job interruption lost its postcondition")
        interrupted.append(job_id)
    return interrupted


def _interrupt_job_records(
    config,
    effect,
    paths,
    deadline_expired=None,
    checkpoint_sessions=None,
):
    request_id = _canonical_request_id(effect["request_id"])
    if checkpoint_sessions is None:
        checkpoint_sessions = {}
    if (
        type(checkpoint_sessions) is not dict
        or any(
            type(job_id) is not str
            or type(session) is not str
            or not session.startswith("ses_")
            for job_id, session in checkpoint_sessions.items()
        )
    ):
        raise ValueError("invalid checkpoint handoff map")
    candidates = {}
    for path in paths:
        job_id, _job = _job_identity(config, path)
        candidates[job_id] = Path(path)
    directory = _job_transition_directory(config, request_id)
    if directory.is_dir():
        for transition_path in directory.glob("*.json"):
            job_id = transition_path.stem
            candidates[job_id] = _job_path(config, job_id)
    for job_id in sorted(candidates):
        if deadline_expired is not None and deadline_expired():
            raise RuntimeError("lifecycle reconciliation deadline expired")
        _interrupt_one_job(
            config,
            request_id,
            candidates[job_id],
            checkpoint_session=checkpoint_sessions.get(job_id),
        )
    return _derived_interrupted_jobs(config, request_id)


def _critical_message(policy, effect, text, suffix):
    from survival import telegram_api

    request = _read_request(_request_path(policy["store_path"], effect["request_id"]))
    identifier = effect["idempotency_key"].replace(":", "-") + f"-{suffix}"
    telegram_api.store_critical_outbox_entry(policy["store_path"], {
        "schema_version": 1,
        "id": identifier,
        "chat_id": request["command"]["telegram_user_id"],
        "text": text,
        "egress_state": "ready",
    })
    return {"ok": True, "message_id": identifier}


def _default_model_probe(catalog, deadline):
    import http.client

    contract = catalog["model_health"]
    connection = http.client.HTTPConnection(
        contract["host"], contract["port"], timeout=deadline,
    )
    try:
        connection.request("GET", contract["path"])
        response = connection.getresponse()
        payload = response.read(MAX_EFFECT_OUTPUT_BYTES + 1)
    except (OSError, TimeoutError) as error:
        return {"ok": False, "error": _bounded_text(str(error))}
    finally:
        connection.close()
    if response.status != 200 or len(payload) > MAX_EFFECT_OUTPUT_BYTES:
        return {"ok": False, "status": response.status}
    try:
        value = decode_json_object(payload, "Lemonade health")
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    expected = contract["required_model"]
    models = value.get("all_models_loaded")
    alive = type(models) is list and any(
        type(item) is dict
        and item.get("model_name") == expected
        and item.get("loaded") is True
        and item.get("status") in {"ready", "busy", "in_use"}
        for item in models
    )
    return {"ok": alive, "required_model": expected}


def _runtime_snapshot(config, request_id, observe_user):
    request = _read_request(_request_path(config["store_path"], request_id))
    previous_active = []
    for category in CATALOG_CATEGORIES:
        for entry in config["lifecycle_catalog"]["user_units"][category]:
            if observe_user(entry["unit"]) == "active":
                previous_active.append(entry["unit"])
    return {
        "schema_version": 1,
        "request_id": request_id,
        "previous_pause": request["state"]["previous_pause"],
        "previous_active_user_units": sorted(previous_active),
        "interrupted_jobs": [],
    }


def _ensure_admission_closed(config, effect, observe_user, sync):
    runtime_path = _runtime_path(config, effect["request_id"])
    if runtime_path.exists():
        runtime = _read_runtime(config, effect["request_id"])
    else:
        runtime = _runtime_snapshot(config, effect["request_id"], observe_user)
        _write_runtime(config, runtime)
    paused = Path(config["agent_state_path"]) / "PAUSED"
    if not paused.exists():
        records.atomic_json(paused, {
            "schema_version": 1,
            "request_id": effect["request_id"],
            "state": "lifecycle_paused",
        })
    if not paused.exists():
        return {"ok": False, "error": "admission pause was not observed"}
    request = _read_request(_request_path(config["store_path"], effect["request_id"]))
    if request["command"]["command"] == "reset":
        runtime["interrupted_jobs"] = _interrupt_job_records(
            config,
            effect,
            _active_job_paths(config["agent_state_path"]),
        )
        _write_runtime(config, runtime)
    sync()
    _critical_message(
        config,
        effect,
        f"{effect['request_id']} lifecycle recovery started; admission is closed.",
        "started",
    )
    return {"ok": True, "previous_pause": runtime["previous_pause"]}


def _checkpoint_runtime(
    config,
    effect,
    sleep,
    sync,
    monotonic=time.monotonic,
    boot_id=telegram_api.current_boot_id,
):
    runtime = _read_runtime(config, effect["request_id"])
    agent_state_path = Path(config["agent_state_path"])
    request_root, result_root = checkpoint.checkpoint_paths(
        config["store_path"], config["lifecycle_catalog"],
    )
    request_root.mkdir(parents=True, exist_ok=True)
    request_path = request_root / f"{effect['request_id']}.json"
    current_boot_id = checkpoint.observe_boot_id(boot_id)
    if request_path.exists() or request_path.is_symlink():
        request = checkpoint.validate_checkpoint_request(
            decode_json_object(request_path.read_bytes(), "checkpoint request"),
        )
        if request["request_id"] != effect["request_id"]:
            raise ValueError("checkpoint request identity mismatch")
        active_paths = [
            _job_path(config, job_id) for job_id in request["job_ids"]
        ]
    else:
        active_paths = _active_job_paths(agent_state_path)
        grace = time_policy.seconds(
            config["timing_policy"],
            "lifecycle",
            "restart_checkpoint_grace_seconds",
        )
        deadline_monotonic = 0.0
        if current_boot_id is not None:
            deadline_monotonic = monotonic() + grace
        request = {
            "schema_version": 1,
            "request_id": effect["request_id"],
            "job_ids": [path.stem for path in active_paths],
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "boot_id": current_boot_id,
            "deadline_monotonic": deadline_monotonic,
        }
        checkpoint.validate_checkpoint_request(request)
        request_metadata = request_root.stat()
        records.atomic_json(
            request_path,
            request,
            mode=records.SHARED_RECORD_MODE,
            owner=(os.geteuid(), request_metadata.st_gid),
        )

    accepted_results = {}
    intent_owned_jobs = set()
    deadline_is_comparable = checkpoint.deadline_boot_matches(
        request, current_boot_id,
    )
    while (
        deadline_is_comparable
        and len(accepted_results) + len(intent_owned_jobs) < len(request["job_ids"])
    ):
        result_directory = result_root / request["request_id"]
        result_directory_is_safe = not (
            result_root.is_symlink() or result_directory.is_symlink()
        )
        for job_id in request["job_ids"]:
            if job_id in accepted_results or job_id in intent_owned_jobs:
                continue
            transition_path = _job_transition_path(
                config, request["request_id"], job_id,
            )
            transition = None
            if transition_path.exists():
                transition = _read_job_transition(
                    transition_path, request["request_id"], job_id,
                )
            if not result_directory_is_safe:
                if transition is not None:
                    intent_owned_jobs.add(job_id)
                continue
            result_path = result_directory / f"{job_id}.json"
            if not result_path.exists() or result_path.is_symlink():
                if transition is not None:
                    intent_owned_jobs.add(job_id)
                continue
            try:
                result = checkpoint.validate_checkpoint_result(
                    decode_json_object(result_path.read_bytes(), "checkpoint result"),
                    request["request_id"],
                    job_id,
                )
            except (OSError, ValueError):
                if transition is not None:
                    intent_owned_jobs.add(job_id)
                continue
            if result["state"] == "checkpointed" and checkpoint.verified_handoff_session(
                agent_state_path, job_id, result["opencode_session"],
            ) != result["opencode_session"]:
                if transition is not None:
                    intent_owned_jobs.add(job_id)
                continue
            if transition is not None:
                if (
                    result["state"] == "checkpointed"
                    and transition["opencode_session"] == result["opencode_session"]
                ):
                    accepted_results[job_id] = result
                else:
                    intent_owned_jobs.add(job_id)
                continue
            accepted_results[job_id] = result
        if len(accepted_results) + len(intent_owned_jobs) == len(request["job_ids"]):
            break
        remaining = checkpoint.checkpoint_deadline_remaining(
            request, current_boot_id, monotonic,
        )
        if remaining <= 0:
            break
        sleep(min(
            remaining,
            time_policy.seconds(
                config["timing_policy"], "heartbeat", "guardian_poll_seconds",
            ),
        ))

    verified_checkpoint_sessions = {
        job_id: result["opencode_session"]
        for job_id, result in accepted_results.items()
        if result["state"] == "checkpointed"
    }
    runtime["interrupted_jobs"] = _interrupt_job_records(
        config,
        effect,
        active_paths,
        checkpoint_sessions=verified_checkpoint_sessions,
    )
    committed_checkpoint_sessions = {}
    for job_id, session in verified_checkpoint_sessions.items():
        transition_path = _job_transition_path(config, request["request_id"], job_id)
        if not transition_path.exists():
            continue
        transition = _read_job_transition(
            transition_path, request["request_id"], job_id,
        )
        if transition["opencode_session"] == session:
            committed_checkpoint_sessions[job_id] = session
    _write_runtime(config, runtime)
    sync()
    return {
        "ok": True,
        "checkpointed_jobs": sorted(committed_checkpoint_sessions),
        "interrupted_jobs": runtime["interrupted_jobs"],
    }


def _reconcile_runtime(config, effect):
    deadline = time.monotonic() + time_policy.seconds(
        config["timing_policy"], "lifecycle", "reconciliation_deadline_seconds",
    )

    def deadline_expired():
        return time.monotonic() >= deadline

    runtime = _read_runtime(config, effect["request_id"])
    try:
        runtime["interrupted_jobs"] = _interrupt_job_records(
            config,
            effect,
            _active_job_paths(config["agent_state_path"]),
            deadline_expired=deadline_expired,
        )
    except RuntimeError as error:
        return {"ok": False, "error": str(error)}
    _write_runtime(config, runtime)
    outbox_unknown = []
    jobs_directory = Path(config["agent_state_path"]) / "jobs"
    for path in sorted(jobs_directory.glob("outbox-*.json")):
        if deadline_expired():
            return {"ok": False, "error": "lifecycle reconciliation deadline expired"}
        job = _agent_record(path)
        if job.get("kind") != "outbound-message" or job.get("state") != "sending":
            continue
        job["state"] = "delivery_unknown"
        job["error"] = "survival lifecycle interrupted Telegram delivery; not replayed"
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_agent_record(path, job)
        outbox_unknown.append(path.stem)

    recovered_turns = []
    turns_directory = Path(config["agent_state_path"]) / "control-turns"
    for path in sorted(turns_directory.glob("telegram-*.json")):
        if deadline_expired():
            return {"ok": False, "error": "lifecycle reconciliation deadline expired"}
        turn = _agent_record(path)
        if turn.get("deep_state") not in {"reserved", "running", "followup_ready"}:
            continue
        turn["deep_state"] = "queued"
        turn["deep_recovered_at"] = datetime.now(timezone.utc).isoformat()
        for field in (
            "deep_owner_pid", "deep_owner_identity", "deep_worker_pid",
            "deep_worker_identity",
        ):
            turn.pop(field, None)
        _write_agent_record(path, turn)
        recovered_turns.append(path.stem)

    awaiting_verifications = []
    for path in sorted(jobs_directory.glob("*.json")):
        if deadline_expired():
            return {"ok": False, "error": "lifecycle reconciliation deadline expired"}
        job = _agent_record(path)
        if job.get("kind") == "agent-task" and job.get("state") == "awaiting_verification":
            awaiting_verifications.append(path.stem)
    remaining = _active_job_paths(config["agent_state_path"])
    return {
        "ok": not remaining,
        "interrupted_jobs": runtime["interrupted_jobs"],
        "recovered_control_turns": recovered_turns,
        "uncertain_outbox": outbox_unknown,
        "awaiting_verifications": awaiting_verifications,
    }


def _restore_inference_state(config, effect, user_adapter, wait):
    runtime = _read_runtime(config, effect["request_id"])
    prior_active = set(runtime["previous_active_user_units"])
    results = []
    for entry in config["lifecycle_catalog"]["user_units"]["inference_prerequisites"]:
        if entry["unit"] not in prior_active:
            results.append(_stop_with_escalation(
                user_adapter,
                entry["unit"],
                immediate=False,
                policy=config,
                wait=wait,
            ))
    return results


def _resume_runtime(config, effect, user_adapter, wait):
    runtime = _read_runtime(config, effect["request_id"])
    for identifier in runtime["interrupted_jobs"]:
        path = Path(config["agent_state_path"]) / "jobs" / f"{identifier}.json"
        if not path.exists():
            continue
        job = _agent_record(path)
        if job.get("state") != "interrupted" or job.get("interrupted_by") != effect["request_id"]:
            continue
        job["state"] = "ready" if job.get("resume_available") is True else "queued"
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_agent_record(path, job)
    results = _restore_inference_state(config, effect, user_adapter, wait)
    prior_active = set(runtime["previous_active_user_units"])
    for entry in config["lifecycle_catalog"]["user_units"]["ordinary_services"]:
        if entry["unit"] in prior_active:
            results.append(_manager_result(user_adapter, "start", entry["unit"]))
    for entry in config["lifecycle_catalog"]["user_units"]["activation_sources"]:
        if entry["unit"] in prior_active:
            results.append(_manager_result(user_adapter, "start", entry["unit"]))
    paused = Path(config["agent_state_path"]) / "PAUSED"
    paused.unlink(missing_ok=True)
    return {
        "ok": all(result.get("ok") is True for result in results) and not paused.exists(),
        "activation_results": results,
    }


def _verify_runtime(config, effect, observe_system, observe_user, model_probe):
    runtime = _read_runtime(config, effect["request_id"])
    catalogue = config["lifecycle_catalog"]
    checks = [{
        "name": "backend",
        "ok": observe_system(catalogue["backend_unit"]) == "active",
    }]
    prior_active = set(runtime["previous_active_user_units"])
    for entry in catalogue["user_units"]["inference_prerequisites"]:
        checks.append({
            "name": entry["unit"],
            "ok": observe_user(entry["unit"]) == "active",
        })
    for entry in catalogue["user_units"]["control_services"]:
        if entry["unit"] in prior_active:
            checks.append({
                "name": entry["unit"],
                "ok": observe_user(entry["unit"]) == "active",
            })
    for entry in catalogue["user_units"]["ordinary_services"]:
        checks.append({
            "name": f"gated:{entry['unit']}",
            "ok": observe_user(entry["unit"]) != "active",
        })
    for entry in catalogue["user_units"]["activation_sources"]:
        checks.append({
            "name": f"gated:{entry['unit']}",
            "ok": observe_user(entry["unit"]) != "active",
        })
    for entry in catalogue["user_units"]["inactive_units"]:
        checks.append({
            "name": f"inactive:{entry['unit']}",
            "ok": observe_user(entry["unit"]) != "active",
        })
    canary = model_probe(
        catalogue,
        time_policy.seconds(
            config["timing_policy"], "inference", "health_verification_deadline_seconds",
        ),
    )
    checks.append({"name": "fast_model_canary", "ok": canary.get("ok") is True})
    return {"ok": all(check["ok"] for check in checks), "checks": checks, "canary": canary}


def _validate_catalog_presence(config, observe_system, observe_user):
    catalogue = config["lifecycle_catalog"]
    if observe_system(catalogue["backend_unit"]) == "not-found":
        raise RuntimeError(f"required lifecycle unit is not installed: {catalogue['backend_unit']}")
    for category in CATALOG_CATEGORIES:
        for entry in catalogue["user_units"][category]:
            if entry["required"] and observe_user(entry["unit"]) == "not-found":
                raise RuntimeError(f"required lifecycle unit is not installed: {entry['unit']}")


def _required_environment(environ: dict, name: str) -> str:
    value = environ.get(name)
    if type(value) is not str or not value:
        raise RuntimeError(f"missing {name}")
    return value


def _parse_uid(environ: dict, name: str) -> int:
    value = _required_environment(environ, name)
    if not value.isascii() or not value.isdecimal():
        raise RuntimeError(f"invalid {name}")
    uid = int(value)
    if uid < 0 or str(uid) != value:
        raise RuntimeError(f"invalid {name}")
    return uid


def load_production_config(environ: dict | None = None) -> dict:
    """Load every installed lifecycle identity and fully validated policy."""
    if environ is None:
        environ = os.environ
    store_path = Path(_required_environment(environ, "SURVIVAL_STORE_DIR"))
    time_config_path = Path(_required_environment(environ, "TIME_CONFIG_PATH"))
    accepted_policy_path = store_path / "policy" / "time.json"
    try:
        timing, policy_error = time_policy.adopt_last_known_good(
            time_config_path, accepted_policy_path,
        )
        catalogue = load_lifecycle_catalog(
            Path(_required_environment(environ, "LIFECYCLE_CATALOG_PATH")),
        )
    except (OSError, ValueError) as error:
        raise RuntimeError(str(error) or "invalid lifecycle policy") from error
    return {
        "socket_path": _required_environment(environ, "GUARDIAN_SOCKET_PATH"),
        "store_path": store_path,
        "agent_state_path": Path(_required_environment(environ, "AGENT_STATE_DIR")),
        "gateway_uid": _parse_uid(environ, "GUARDIAN_GATEWAY_UID"),
        "user_manager_uid": _parse_uid(environ, "USER_MANAGER_UID"),
        "time_config_path": time_config_path,
        "accepted_policy_path": accepted_policy_path,
        "timing_policy": timing,
        "timing_policy_error": policy_error,
        "lifecycle_catalog": catalogue,
        "guardian_poll_seconds": time_policy.seconds(
            timing, "heartbeat", "guardian_poll_seconds",
        ),
    }


def refresh_timing_policy(config):
    """Adopt one complete live policy and durably expose any rejected edit."""
    required = {"time_config_path", "accepted_policy_path", "timing_policy", "store_path"}
    if not required <= set(config):
        return None
    policy, error = time_policy.adopt_last_known_good(
        config["time_config_path"], config["accepted_policy_path"],
    )
    config["timing_policy"] = policy
    config["timing_policy_error"] = error
    config["guardian_poll_seconds"] = time_policy.seconds(
        policy, "heartbeat", "guardian_poll_seconds",
    )
    status = {
        "schema_version": 1,
        "state": "accepted" if error is None else "rejected",
        "error": error,
    }
    status_path = Path(config["store_path"]) / "policy" / "status.json"
    if not status_path.exists() or decode_json_object(
        status_path.read_bytes(), "timing policy status",
    ) != status:
        records.atomic_json(status_path, status)
    if error is not None:
        _report_policy_rejection(config, error)
    return error


def _report_policy_rejection(config, error):
    from survival import telegram_api

    request = _latest_lifecycle_request(config["store_path"])
    if request is None:
        return
    fingerprint = hashlib.sha256(str(error).encode("utf-8")).hexdigest()[:24]
    telegram_api.store_critical_outbox_entry(config["store_path"], {
        "schema_version": 1,
        "id": f"policy-rejected-{fingerprint}",
        "chat_id": request["command"]["telegram_user_id"],
        "text": f"Timing policy edit rejected; last known good remains active: {error}",
        "egress_state": "ready",
    })


def _latest_lifecycle_request(store):
    directory = Path(store) / "lifecycle"
    candidates = sorted(directory.glob("telegram-*.json")) if directory.is_dir() else []
    if not candidates:
        return None
    return max(
        (_read_request(path) for path in candidates),
        key=lambda record: record["command"]["telegram_update_id"],
    )


def report_gateway_data_health(config):
    """Translate every gateway-owned degradation fact into root-owned reports."""
    from survival import telegram_api

    gateway_path = Path(config["store_path"]) / "gateway"
    candidates = []
    incident_directory = gateway_path / "data-health-incidents"
    try:
        if incident_directory.is_dir():
            candidates.extend(sorted(incident_directory.glob("*.json")))
    except OSError:
        pass
    latest_path = gateway_path / "data-health.json"
    if latest_path.exists():
        candidates.append(latest_path)
    values = {}
    for path in candidates:
        try:
            value = decode_json_object(path.read_bytes(), "gateway data health")
        except (OSError, ValueError):
            continue
        if _valid_gateway_data_health(value):
            values[value["incident_id"]] = value
    request = _latest_lifecycle_request(config["store_path"])
    if request is None:
        return None
    reported = None
    for incident_id in sorted(values):
        value = values[incident_id]
        message_id = f"gateway-quarantine-{incident_id}"
        outcome = (
            "isolated a malformed survival record"
            if value["quarantine_succeeded"]
            else "could not isolate a malformed survival record"
        )
        telegram_api.store_critical_outbox_entry(config["store_path"], {
            "schema_version": 1,
            "id": message_id,
            "chat_id": request["command"]["telegram_user_id"],
            "text": (
                f"Gateway {outcome} and contact remains live: "
                f"{value['error_reason']}"
            ),
            "egress_state": "ready",
        })
        reported = message_id
    return reported


def _valid_gateway_data_health(value):
    fields = {
        "schema_version", "state", "incident_id", "source_path",
        "error_reason", "quarantine_succeeded",
    }
    return not (
        set(value) != fields
        or value.get("schema_version") != 1
        or value.get("state") != "degraded"
        or type(value.get("incident_id")) is not str
        or not value["incident_id"]
        or type(value.get("source_path")) is not str
        or type(value.get("error_reason")) is not str
        or type(value.get("quarantine_succeeded")) is not bool
    )


def production_adapters(
    config,
    *,
    system_adapter=None,
    user_adapter=None,
    observe_system=None,
    observe_user=None,
    model_probe=None,
    sleep=time.sleep,
    sync=os.sync,
    monotonic=time.monotonic,
):
    """Compose every reducer effect over only literal injected fingertips."""
    user_manager_uid = config["user_manager_uid"]

    def heartbeat():
        systemd_notify.notify_systemd("WATCHDOG=1")

    def progress_wait(seconds):
        remaining = float(seconds)
        while remaining > 0:
            interval = min(1.0, remaining)
            sleep(interval)
            remaining -= interval
            heartbeat()

    if model_probe is None:
        model_probe = _default_model_probe

    def guarded_model_probe(catalogue, deadline):
        return _run_with_watchdog(
            lambda: model_probe(catalogue, deadline),
            deadline,
            heartbeat,
        )

    if system_adapter is None:
        def system_adapter(action, unit):
            if action == "start":
                section, key = "inference", "model_start_deadline_seconds"
            elif unit == config["lifecycle_catalog"]["backend_unit"]:
                section, key = "inference", "model_stop_deadline_seconds"
            else:
                section, key = "lifecycle", "service_stop_deadline_seconds"
            deadline = time_policy.seconds(config["timing_policy"], section, key)
            run = lambda argv: _subprocess_runner(
                argv, timeout=deadline, heartbeat=heartbeat,
            )
            return system_unit(action, unit, runner=run, query=run)

    if user_adapter is None:
        def user_adapter(action, unit):
            if action == "start" and unit == "agent-models.service":
                section, key = "inference", "model_start_deadline_seconds"
            else:
                section, key = "lifecycle", "service_stop_deadline_seconds"
            deadline = time_policy.seconds(config["timing_policy"], section, key)
            run = lambda argv: _subprocess_runner(
                argv, timeout=deadline, heartbeat=heartbeat,
            )
            return user_unit(
                action, unit, uid=user_manager_uid, runner=run, query=run,
            )

    if observe_system is None:
        observe_system = lambda unit: system_adapter("status", unit).get("state", "unknown")
    if observe_user is None:
        observe_user = lambda unit: user_adapter("status", unit).get("state", "unknown")

    for adapter in (
        system_adapter, user_adapter, observe_system, observe_user, model_probe, sleep,
        sync, monotonic,
    ):
        if not callable(adapter):
            raise RuntimeError("incomplete production lifecycle adapter composition")
    _validate_catalog_presence(config, observe_system, observe_user)

    def notify(effect, _policy):
        return _critical_message(
            config,
            effect,
            f"{effect['request_id']} lifecycle recovery is blocked; retry remains scheduled.",
            "blocked",
        )

    def close_admission(effect, _policy):
        return _ensure_admission_closed(config, effect, observe_user, sync)

    def checkpoint(effect, _policy):
        return _checkpoint_runtime(
            config, effect, progress_wait, sync, monotonic=monotonic,
        )

    def reconcile(effect, _policy):
        return _reconcile_runtime(config, effect)

    def verify(effect, _policy):
        return _verify_runtime(
            config, effect, observe_system, observe_user, guarded_model_probe,
        )

    def resume(effect, _policy):
        return _resume_runtime(config, effect, user_adapter, progress_wait)

    def finish(effect, _policy):
        restoration = _restore_inference_state(
            config, effect, user_adapter, progress_wait,
        )
        if not all(result.get("ok") is True for result in restoration):
            return {
                "ok": False,
                "error": "prior inference state was not restored",
                "restoration": restoration,
            }
        records.atomic_json(
            Path(config["store_path"]) / "lifecycle-completions" / f"{effect['request_id']}.json",
            {
                "schema_version": 1,
                "request_id": effect["request_id"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        report = _critical_message(
            config,
            effect,
            f"{effect['request_id']} lifecycle recovery completed and passed verification.",
            "completed",
        )
        return {"ok": report["ok"] is True, "restoration": restoration, **report}

    adapters = {
        "system": system_adapter,
        "user": user_adapter,
        "notify": notify,
        "close_admission": close_admission,
        "checkpoint": checkpoint,
        "reconcile": reconcile,
        "verify": verify,
        "resume": resume,
        "finish": finish,
        "wait": progress_wait,
    }
    if set(adapters) != PRODUCTION_ADAPTER_KINDS:
        raise RuntimeError("incomplete production lifecycle adapter composition")
    return adapters
