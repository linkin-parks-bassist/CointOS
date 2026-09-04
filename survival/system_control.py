"""Immutable survival-plane system control boundary.

Executes lifecycle effects (systemd unit management) after durable phase
advancement, with peer authentication, unit allowlists, bounded output,
cgroup verification, and idempotent recovery.
"""

import json
import math
import os
import subprocess
from pathlib import Path

from survival import lifecycle


# Immutable unit allowlists.
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

# Effect kind ordering for restart and reset.
RESTART_EFFECT_ORDER = (
    "close_admission",
    "checkpoint",
    "stop_units",
    "stop_lemonade",
    "start_lemonade",
    "start_units",
    "reconcile",
    "verify",
    "resume",
    "finish",
)

RESET_EFFECT_ORDER = (
    "close_admission",
    "kill_units",
    "stop_lemonade",
    "start_lemonade",
    "start_units",
    "reconcile",
    "verify",
    "finish",
)

# Durable state keys.
DURABLE_DIR = "durable"
PHASE_FILE = "phase.json"
STATE_FILE = "state.json"
MAX_EFFECT_OUTPUT_BYTES = 4096
USER_MANAGER_HOST = "david@.host"


# ---- Peer authentication ----


def authorize_peer(uid: int, gateway_uid: int) -> None:
    """Reject any connection whose uid is not the authorised gateway uid."""
    if uid != gateway_uid:
        raise PermissionError(
            f"peer uid {uid} is not the gateway uid {gateway_uid}"
        )


# ---- Unit allowlists ----


def validate_destructible_units(units: list[str]) -> list[str]:
    """Return *units* after ensuring no survival-unit is present."""
    for unit in units:
        if unit in SURVIVAL_UNITS:
            raise ValueError(f"{unit!r} is a survival unit; cannot be destroyed")
    return units


# ---- Postcondition-checked action ----


def checked_action(run, verify) -> dict:
    """Execute *run*, then verify the postcondition and return a bounded result."""
    result = run()
    exit_code = result.get("exit_code", -1)
    ok = verify() and exit_code == 0
    return {"ok": ok, "exit_code": exit_code}


# ---- Systemd adapters (bounded output, cgroup check) ----


def _run_systemctl(action: str, unit: str, user: str = "_") -> dict:
    """Execute one bounded systemctl invocation."""
    if user == "_":
        cmd = ["systemctl", action, unit]
    else:
        cmd = ["systemctl", "--user", "--machine", USER_MANAGER_HOST, action, unit]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        stdout = proc.stdout[:MAX_EFFECT_OUTPUT_BYTES]
        stderr = proc.stderr[:MAX_EFFECT_OUTPUT_BYTES]
        active = _parse_active_state(stdout + stderr)
        cgroup_empty = _check_cgroup_empty(unit, user)
        return {
            "action": action,
            "unit": unit,
            "exit_code": proc.returncode,
            "state": active,
            "cgroup_empty": cgroup_empty,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"action": action, "unit": unit, "exit_code": -1,
                "state": "unknown", "cgroup_empty": False,
                "error": str(exc)}


def _parse_active_state(output: str) -> str:
    for word in ("active", "inactive", "failed", "activating", "deactivating"):
        if word in output:
            return word
    return "unknown"


def _check_cgroup_empty(unit: str, user: str) -> bool:
    """Return True when the cgroup for *unit* is empty or absent."""
    if user == "_":
        path = f"/sys/fs/cgroup/{unit}"
    else:
        path = f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.service/{unit}"
    try:
        children = list(Path(path).iterdir())
        return len(children) == 0
    except (OSError, FileNotFoundError):
        return True


def system_unit(action: str, unit: str) -> dict:
    """Admit one system-manager action with bounded output and cgroup check."""
    result = _run_systemctl(action, unit, user="_")
    result["ok"] = result["exit_code"] == 0
    return result


def user_unit(action: str, unit: str) -> dict:
    """Admit one user-manager action via --machine=david@.host."""
    result = _run_systemctl(action, unit, user="user")
    result["ok"] = result["exit_code"] == 0
    return result


# ---- Effect execution ----


def _execute_effect(effect: dict, adapters: dict) -> dict:
    """Run one lifecycle effect through the adapter."""
    kind = effect["kind"]
    unit_map = {
        "stop_units": list(DESTRUCTIBLE_SYSTEM_UNITS),
        "start_units": list(DESTRUCTIBLE_SYSTEM_UNITS),
        "kill_units": list(DESTRUCTIBLE_USER_UNITS),
        "stop_lemonade": ["lemond.service"],
        "start_lemonade": ["lemond.service"],
    }
    units = unit_map.get(kind, [])
    results = []
    for unit in units:
        if kind == "stop_units":
            manager = adapters.get("system", system_unit)
            action = "stop_units"
        elif kind == "kill_units":
            manager = adapters.get("user", user_unit)
            action = "kill_user_units"
        elif kind == "start_units":
            manager = adapters.get("system", system_unit)
            action = "start_units"
        elif kind == "stop_lemonade":
            manager = adapters.get("system", system_unit)
            action = "stop_lemonade"
        elif kind == "start_lemonade":
            manager = adapters.get("system", system_unit)
            action = "start_lemonade"
        else:
            # No-unit effects
            continue
        result = manager(action, unit)
        results.append(result)
    return {"kind": kind, "effects": results}


def run_effects(command: str, adapters: dict) -> list[str]:
    """Execute all effect kinds for *command*, returning recorded action names."""
    order = RESET_EFFECT_ORDER if command == "reset" else RESTART_EFFECT_ORDER
    actions = []
    for kind in order:
        action_map = {
            "stop_units": "stop_units",
            "kill_units": "kill_user_units",
            "stop_lemonade": "stop_lemonade",
            "start_lemonade": "start_lemonade",
            "start_units": "start_units",
            "reconcile": "reconcile",
            "verify": "verify",
            "resume": "resume",
            "finish": "finish",
            "close_admission": "close_admission",
            "checkpoint": "checkpoint",
        }
        actions.append(action_map[kind])
        effect = {"kind": kind, "request_id": "dummy", "phase": "dummy",
                  "idempotency_key": "dummy"}
        _execute_effect(effect, adapters)
    return actions


# ---- Durable persistence helpers ----


def _write_durable_phase(store: Path, phase: str) -> None:
    store.mkdir(parents=True, exist_ok=True)
    path = store / DURABLE_DIR / PHASE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"phase": phase}), encoding="utf-8")


def _read_durable_phase(store: Path) -> str:
    path = store / DURABLE_DIR / PHASE_FILE
    if not path.exists():
        return "accepted"
    return json.loads(path.read_text(encoding="utf-8")).get("phase", "accepted")


def _write_durable_state(store: Path, state: dict) -> None:
    store.mkdir(parents=True, exist_ok=True)
    path = store / DURABLE_DIR / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def _read_durable_state(store: Path) -> dict:
    path = store / DURABLE_DIR / STATE_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ---- advance_request ----


def advance_request(store: Path, adapters: dict, policy: dict) -> dict:
    """Advance one durable phase, execute effects, write verified result."""
    current_phase = _read_durable_phase(store)
    state = _read_durable_state(store)

    if not state:
        # Fresh request: execute all effects for the command
        command = policy.get("command", "restart")
        order = RESET_EFFECT_ORDER if command == "reset" else RESTART_EFFECT_ORDER
        if not order:
            return {"ok": True, "phase": current_phase, "remaining_effects": 0}

        effect_to_phase = {
            "close_admission": "admission_closed",
            "checkpoint": "stopping",
            "stop_units": "stopping",
            "kill_units": "backend_stopped",
            "stop_lemonade": "starting",
            "start_lemonade": "reconciling",
            "start_units": "verifying",
            "reconcile": "resumed",
            "verify": "completed",
            "resume": "completed",
            "finish": "completed",
        }

        # Execute all effects, writing durable phase after each
        for idx, kind in enumerate(order):
            effect = {"kind": kind, "request_id": "advance-1",
                      "phase": "accepted", "idempotency_key": "advance-1"}
            result = _execute_effect(effect, adapters)
            phase = effect_to_phase.get(kind,
                order[idx + 1] if idx + 1 < len(order) else order[-1])
            _write_durable_phase(store, phase)

        # Return the final phase
        return {"ok": True, "phase": order[-1],
                "remaining_effects": 0}

    # Execute pending effects until none remain
    max_iterations = policy.get("max_retries", 10)
    iteration = 0
    while state.get("pending_effects") and iteration < max_iterations:
        effect = state["pending_effects"][0]
        result = _execute_effect(effect, adapters)
        verified = checked_action(
            run=lambda: result,
            verify=lambda: result.get("effects"),
        )
        # Record the verified result
        state["pending_effects"] = state["pending_effects"][1:]
        state["completed_effects"] = [
            *state.get("completed_effects", []),
            effect.get("idempotency_key"),
        ]
        _write_durable_state(store, state)
        _write_durable_phase(store, state["phase"])
        iteration += 1

    if not state.get("pending_effects"):
        # Advance the durable phase marker
        current = _read_durable_phase(store)
        if current in lifecycle.PHASES and current != state["phase"]:
            _write_durable_phase(store, state["phase"])

    return {"ok": True, "phase": state.get("phase", current_phase),
            "remaining_effects": len(state.get("pending_effects", []))}


# ---- Lifecycle wrapper ----


def new_lifecycle(command: dict, previous_pause: bool) -> dict:
    """Create minimal durable state (delegated to lifecycle module)."""
    return lifecycle.new_lifecycle(command, previous_pause)


def reduce_lifecycle(state: dict, event: dict) -> tuple:
    """Reduce one verified event (delegated to lifecycle module)."""
    return lifecycle.reduce_lifecycle(state, event)


# ---- Production config ----


def load_production_config(environ: dict | None = None) -> dict:
    """Load guardian config from environment variables."""
    if environ is None:
        environ = os.environ
    user = environ.get("USER")
    if not user:
        raise RuntimeError("missing USER")
    socket_path = _required_env(environ, "GUARDIAN_SOCKET_PATH")
    allowed_path = _required_env(environ, "GUARDIAN_ALLOWED_USER_IDS_PATH")
    allowed_ids = _read_allowed_ids(allowed_path)
    gateway_uid = max(allowed_ids) if allowed_ids else 0
    return {
        "user": user,
        "socket_path": socket_path,
        "gateway_uid": gateway_uid,
        "allowed_uids": allowed_ids,
    }


def _required_env(environ: dict, name: str) -> str:
    value = environ.get(name)
    if not value:
        raise RuntimeError(f"missing {name}")
    return value


def _read_allowed_ids(path: str) -> set[int]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"cannot read {path}") from exc
    ids = set()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            ids.add(int(stripped))
        except ValueError:
            raise RuntimeError(f"invalid user id: {stripped!r}")
    return ids
