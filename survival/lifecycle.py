"""Pure durable transition reduction for typed restart and reset requests."""


PHASES = (
    "accepted",
    "acknowledged",
    "admission_closed",
    "checkpointing",
    "stopping",
    "backend_stopped",
    "starting",
    "reconciling",
    "verifying",
    "resumed",
    "completed",
    "blocked",
    "failed",
)


_RECOVERY_TRANSITIONS = {
    ("starting", "lemonade_started"): ("reconciling", ("start_units",)),
    ("reconciling", "units_started"): ("verifying", ("reconcile",)),
    ("verifying", "reconciled"): ("resumed", ("verify",)),
    ("resumed", "verified"): ("completed", ()),
}


TRANSITIONS = {
    ("restart", "accepted", "ack_delivered"): (
        "admission_closed", ("close_admission", "checkpoint"),
    ),
    ("restart", "admission_closed", "checkpointed"): ("stopping", ("stop_units",)),
    ("restart", "checkpointing", "checkpointed"): ("stopping", ("stop_units",)),
    ("restart", "stopping", "units_stopped"): ("backend_stopped", ("stop_lemonade",)),
    ("restart", "backend_stopped", "backend_stopped"): ("starting", ("start_lemonade",)),
    ("reset", "accepted", "ack_delivered"): (
        "admission_closed", ("close_admission", "kill_units"),
    ),
    ("reset", "admission_closed", "units_killed"): (
        "backend_stopped", ("stop_lemonade",),
    ),
    ("reset", "stopping", "units_killed"): ("backend_stopped", ("stop_lemonade",)),
    ("reset", "backend_stopped", "backend_stopped"): ("starting", ("start_lemonade",)),
}

for command in ("restart", "reset"):
    for (phase, event_kind), transition in _RECOVERY_TRANSITIONS.items():
        TRANSITIONS[(command, phase, event_kind)] = transition


def new_lifecycle(command: dict, previous_pause: bool) -> dict:
    """Create minimal lifecycle state from one already decoded command record."""
    if type(command) is not dict:
        raise ValueError("invalid lifecycle command")
    if type(command.get("request_id")) is not str or command.get("command") not in {"restart", "reset"}:
        raise ValueError("invalid lifecycle command")
    if type(previous_pause) is not bool:
        raise ValueError("invalid prior pause")
    return {
        "request_id": command["request_id"],
        "command": command["command"],
        "previous_pause": previous_pause,
        "phase": "accepted",
        "applied_events": [],
    }


def reduce_lifecycle(state: dict, event: dict) -> tuple[dict, list[dict]]:
    """Apply one verified lifecycle event without touching an external authority."""
    _validate_state(state)
    if type(event) is not dict or type(event.get("kind")) is not str:
        raise ValueError("invalid lifecycle event")
    key = (state["command"], state["phase"], event["kind"])
    transition = TRANSITIONS.get(key)
    if transition is None:
        if event.get("idempotency_key") in state["applied_events"]:
            return state, []
        if event["kind"] in {"blocked", "failed"} and state["phase"] not in {
            "completed", "blocked", "failed",
        }:
            transition = (event["kind"], ("notify",))
        else:
            raise ValueError(f"illegal lifecycle transition {key!r}")
    return apply_transition(state, event, transition)


def apply_transition(state: dict, event: dict, transition: tuple[str, tuple[str, ...]]) -> tuple[dict, list[dict]]:
    """Return copied state and typed effects for a transition-table entry."""
    phase, effect_kinds = transition
    next_state = state | {"phase": phase}
    event_key = event.get("idempotency_key")
    if type(event_key) is str:
        next_state["applied_events"] = [*state["applied_events"], event_key]
    effects = [_effect(next_state["request_id"], phase, kind) for kind in effect_kinds]
    if phase == "completed":
        if not state["previous_pause"]:
            effects.insert(0, _effect(next_state["request_id"], phase, "resume"))
        effects.append(_effect(next_state["request_id"], phase, "finish"))
    return next_state, effects


def _effect(request_id: str, phase: str, kind: str) -> dict:
    return {
        "kind": kind,
        "request_id": request_id,
        "phase": phase,
        "idempotency_key": f"{request_id}:{phase}:{kind}",
    }


def _validate_state(state: object) -> None:
    if type(state) is not dict:
        raise ValueError("invalid lifecycle state")
    if (
        type(state.get("request_id")) is not str
        or state.get("command") not in {"restart", "reset"}
        or type(state.get("previous_pause")) is not bool
        or state.get("phase") not in PHASES
        or type(state.get("applied_events")) is not list
        or any(type(value) is not str for value in state["applied_events"])
    ):
        raise ValueError("invalid lifecycle state")
