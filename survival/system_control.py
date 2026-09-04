"""Durable lifecycle-effect execution at the privileged system fingertip."""

import os
import subprocess
from pathlib import Path

from survival import lifecycle, protocol, records
from survival.json_codec import decode_json_object


SURVIVAL_UNITS = frozenset((
    "cointelprofessional-gateway.service",
    "cointelprofessional-guardian.service",
    "cointelprofessional-guardian.socket",
))
DESTRUCTIBLE_SYSTEM_UNITS = frozenset(("lemond.service",))
DESTRUCTIBLE_USER_UNITS = frozenset((
    "agent-models.service",
    "agent-inference-arbiter.service",
    "agent-fast-control.service",
    "agent-control-worker.service",
    "agent-notifier.service",
    "agent-ecosystem.service",
    "agent-ecosystem.path",
    "agent-ecosystem.timer",
    "agent-watchdog.service",
    "agent-watchdog.timer",
    "agent-resource-guard.service",
))
DESTRUCTIBLE_UNITS = DESTRUCTIBLE_SYSTEM_UNITS | DESTRUCTIBLE_USER_UNITS
SYSTEMCTL_ACTIONS = frozenset(("start", "stop", "kill"))
DIRECT_EFFECT_KINDS = frozenset((
    "notify", "close_admission", "checkpoint", "reconcile", "verify",
    "resume", "finish",
))
EFFECT_COMPLETION_EVENTS = {
    "checkpoint": "checkpointed",
    "stop_units": "units_stopped",
    "kill_units": "units_killed",
    "stop_lemonade": "backend_stopped",
    "start_lemonade": "lemonade_started",
    "start_units": "units_started",
    "reconcile": "reconciled",
    "verify": "verified",
}
REQUEST_FIELDS = frozenset(("schema_version", "command", "state"))
RESULT_FIELDS = frozenset((
    "schema_version", "effect_idempotency_key", "ok", "result",
))
MAX_EFFECT_OUTPUT_BYTES = 4096
MAXIMUM_EFFECTS_PER_ADVANCE = 128
USER_MANAGER_HOST = "david@.host"


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


def checked_action(run, verify) -> dict:
    """Require both a zero command status and an independently checked condition."""
    result = _normalise_process_result(run())
    verified = verify()
    return {
        "ok": result["exit_code"] == 0 and verified is True,
        "exit_code": result["exit_code"],
    }


def _subprocess_runner(argv: list[str]) -> dict:
    """Run one fixed-argv command and retain only bounded diagnostics."""
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": _bounded_text(str(error)),
        }
    return _normalise_process_result(result)


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
    if show["exit_code"] != 0 or not cgroup_path.startswith("/"):
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
    action_result = _invoke(runner, prefix + [action, unit])
    state_result = _invoke(query, prefix + ["is-active", unit])
    state = _active_state(state_result)
    if cgroup is None:
        cgroup_result = _query_cgroup_empty(manager, unit, uid, query)
    else:
        try:
            cgroup_result = _normalise_cgroup_result(cgroup(manager, unit, uid))
        except OSError as error:
            cgroup_result = {"empty": False, "error": _bounded_text(str(error))}

    if action == "start":
        postcondition = state == "active"
    elif action == "stop":
        postcondition = state == "inactive" and cgroup_result["empty"] is True
    else:
        postcondition = (
            state in {"active", "inactive", "failed"}
            and cgroup_result["empty"] is True
        )
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
        result = adapter(dict(effect), dict(policy))
        if type(result) is not dict:
            result = {"ok": False, "error": f"invalid {kind} adapter result"}
        return _normalise_effect_result(kind, effect_key, [result])

    operations = []
    if kind == "stop_units":
        operations = [
            ("user", "stop", unit) for unit in sorted(DESTRUCTIBLE_USER_UNITS)
        ]
    elif kind == "kill_units":
        for unit in sorted(DESTRUCTIBLE_USER_UNITS):
            operations.extend((("user", "kill", unit), ("user", "stop", unit)))
    elif kind == "stop_lemonade":
        operations = [("system", "stop", "lemond.service")]
    elif kind == "start_lemonade":
        operations = [("system", "start", "lemond.service")]
    elif kind == "start_units":
        operations = [
            ("user", "start", unit) for unit in sorted(DESTRUCTIBLE_USER_UNITS)
        ]
    else:
        return _normalise_effect_result(kind, effect_key, [{
            "ok": False,
            "error": f"unsupported lifecycle effect: {kind}",
        }])

    results = []
    for manager, action, unit in operations:
        adapter = adapters.get(manager)
        if not callable(adapter):
            results.append({"ok": False, "error": f"missing {manager} adapter"})
            continue
        results.append(adapter(action, unit))
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


def _results_path(path: Path) -> Path:
    return path.with_suffix(".results.jsonl")


def _append_effect_result(path: Path, effect: dict, result: dict) -> None:
    records.append_event(_results_path(path), {
        "schema_version": 1,
        "effect_idempotency_key": effect["idempotency_key"],
        "ok": result.get("ok") is True,
        "result": result,
    })


def _verified_effect_result(path: Path, effect_key: str) -> dict | None:
    results_path = _results_path(path)
    if not results_path.exists():
        return None
    try:
        lines = results_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read lifecycle results: {results_path}") from error
    verified = None
    for line in lines:
        record = decode_json_object(line, "lifecycle effect result")
        if type(record) is not dict or set(record) != RESULT_FIELDS:
            raise ValueError("invalid lifecycle effect result")
        if (
            type(record["schema_version"]) is not int
            or record["schema_version"] != 1
            or type(record["effect_idempotency_key"]) is not str
            or type(record["ok"]) is not bool
            or type(record["result"]) is not dict
        ):
            raise ValueError("invalid lifecycle effect result")
        if record["effect_idempotency_key"] == effect_key and record["ok"] is True:
            verified = record["result"]
    return verified


def _persist_reduction(path: Path, command: dict, state: dict, event: dict) -> dict:
    next_state, _effects = lifecycle.reduce_lifecycle(state, event)
    if next_state is not state:
        _write_request(path, command, next_state)
        return _read_request(path)["state"]
    return state


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
            _append_effect_result(path, effect, result)
            if result["ok"] is not True:
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


def new_lifecycle(command: dict, previous_pause: bool) -> dict:
    return lifecycle.new_lifecycle(command, previous_pause)


def reduce_lifecycle(state: dict, event: dict) -> tuple[dict, list[dict]]:
    return lifecycle.reduce_lifecycle(state, event)


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
    """Load explicit peer, user-manager, socket, and durable-store identities."""
    if environ is None:
        environ = os.environ
    return {
        "socket_path": _required_environment(environ, "GUARDIAN_SOCKET_PATH"),
        "store_path": Path(_required_environment(environ, "SURVIVAL_STORE_DIR")),
        "gateway_uid": _parse_uid(environ, "GUARDIAN_GATEWAY_UID"),
        "user_manager_uid": _parse_uid(environ, "USER_MANAGER_UID"),
    }


def production_adapters(config: dict) -> dict:
    """Bind the configured user uid to the two literal systemd fingertips."""
    user_manager_uid = config["user_manager_uid"]

    def run_user_unit(action, unit):
        return user_unit(action, unit, uid=user_manager_uid)

    return {
        "system": system_unit,
        "user": run_user_unit,
    }
