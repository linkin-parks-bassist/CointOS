"""Pure durable transition reduction for typed restart and reset requests."""

from survival import protocol


PHASES = (
    "accepted", "acknowledged", "admission_closed", "checkpointing", "stopping",
    "backend_stopped", "starting", "reconciling", "verifying", "resumed",
    "completed", "blocked", "failed",
)
EFFECT_KINDS = {
    "notify", "close_admission", "checkpoint", "stop_units", "kill_units",
    "stop_lemonade", "start_lemonade", "start_units", "reconcile", "verify",
    "resume", "finish",
}
EFFECT_FIELDS = {"kind", "request_id", "phase", "idempotency_key"}
STATE_FIELDS = {
    "request_id", "command", "previous_pause", "phase", "applied_events",
    "pending_effects", "completed_effects", "recovery_phase",
}
EVENT_COMPLETIONS = {
    "checkpointed": "checkpoint",
    "units_stopped": "stop_units",
    "units_killed": "kill_units",
    "backend_stopped": "stop_lemonade",
    "lemonade_started": "start_lemonade",
    "units_started": "start_units",
    "reconciled": "reconcile",
    "verified": "verify",
}


_RECOVERY_TRANSITIONS = {
    ("starting", "lemonade_started"): ("starting", ("start_units",)),
    ("starting", "units_started"): ("reconciling", ("reconcile",)),
    ("reconciling", "reconciled"): ("verifying", ("verify",)),
    ("verifying", "verified"): ("resumed", ("resume",)),
    ("resumed", "resumed"): ("completed", ("finish",)),
    ("resumed", "finished"): ("completed", ()),
    ("completed", "finished"): ("completed", ()),
}
TRANSITIONS = {
    ("restart", "accepted", "ack_committed"): ("acknowledged", ("close_admission",)),
    ("restart", "acknowledged", "admission_closed"): ("checkpointing", ("checkpoint",)),
    ("restart", "checkpointing", "checkpointed"): ("stopping", ("stop_units",)),
    ("restart", "stopping", "units_stopped"): ("backend_stopped", ("stop_lemonade",)),
    ("restart", "backend_stopped", "backend_stopped"): ("starting", ("start_lemonade",)),
    ("reset", "accepted", "ack_committed"): ("acknowledged", ("close_admission",)),
    ("reset", "acknowledged", "admission_closed"): ("stopping", ("kill_units",)),
    ("reset", "stopping", "units_killed"): ("backend_stopped", ("stop_lemonade",)),
    ("reset", "backend_stopped", "backend_stopped"): ("starting", ("start_lemonade",)),
}

for command in ("restart", "reset"):
    for (phase, event_kind), transition in _RECOVERY_TRANSITIONS.items():
        TRANSITIONS[(command, phase, event_kind)] = transition


def new_lifecycle(command: dict, previous_pause: bool) -> dict:
    """Create minimal durable state from one strict Task 1 command record."""
    try:
        protocol.encode_command(command)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid lifecycle command") from error
    if type(previous_pause) is not bool:
        raise ValueError("invalid prior pause")
    return {
        "request_id": command["request_id"],
        "command": command["command"],
        "previous_pause": previous_pause,
        "phase": "accepted",
        "applied_events": [],
        "pending_effects": [],
        "completed_effects": [],
        "recovery_phase": None,
    }


def reduce_lifecycle(state: dict, event: dict) -> tuple[dict, list[dict]]:
    """Reduce one verified event and return only the still-required effects."""
    _validate_state(state)
    event_key = _event_key(state["request_id"], event)
    if event["kind"] == "recover":
        return _recover(state, event_key)
    if event["kind"] in {"blocked", "failed"}:
        if event_key in state["applied_events"]:
            return _repeat_failure(state, event["kind"], event_key)
        return _block_or_fail(state, event["kind"], event_key)
    if event_key in state["applied_events"]:
        return state, []
    if event["kind"] == "effect_completed":
        return _complete_named_effect(state, event, event_key)
    key = (state["command"], state["phase"], event["kind"])
    transition = TRANSITIONS.get(key)
    if transition is None:
        raise ValueError(f"illegal lifecycle transition {key!r}")
    return apply_transition(state, event, transition, event_key)


def apply_transition(
    state: dict,
    event: dict,
    transition: tuple[str, tuple[str, ...]],
    event_key: str | None = None,
) -> tuple[dict, list[dict]]:
    """Return copied state and persist every effect before returning it."""
    phase, effect_kinds = transition
    pending, completed = _complete_effect(
        state, _completed_effect_key(state, event["kind"]), required=False,
    )
    kinds = list(effect_kinds)
    if state["phase"] == "verifying" and event["kind"] == "verified":
        kinds = ["resume"] if not state["previous_pause"] else ["finish"]
    effects = [_effect(state["request_id"], phase, kind) for kind in kinds]
    pending = [*pending, *(_copy_effect(effect) for effect in effects)]
    next_state = _next_state(
        state, phase, event_key or _event_key(state["request_id"], event), pending,
        completed, None,
    )
    return next_state, effects


def _recover(state: dict, event_key: str) -> tuple[dict, list[dict]]:
    if state["phase"] in {"blocked", "failed"}:
        next_state = _next_state(
            state, state["recovery_phase"], None,
            _copy_effects(state["pending_effects"]), list(state["completed_effects"]), None,
        )
    else:
        next_state = state
    if event_key not in next_state["applied_events"]:
        next_state = _next_state(
            next_state, next_state["phase"], event_key,
            _copy_effects(next_state["pending_effects"]),
            list(next_state["completed_effects"]), next_state["recovery_phase"],
        )
    return next_state, _copy_effects(next_state["pending_effects"])


def _complete_named_effect(state: dict, event: dict, event_key: str) -> tuple[dict, list[dict]]:
    effect_key = event.get("effect_idempotency_key")
    if not _is_effect_key(effect_key, state["request_id"]):
        raise ValueError("invalid effect idempotency key")
    pending, completed = _complete_effect(state, effect_key, required=True)
    return _next_state(
        state, state["phase"], event_key, pending, completed, state["recovery_phase"],
    ), []


def _block_or_fail(state: dict, phase: str, event_key: str) -> tuple[dict, list[dict]]:
    if state["phase"] in {"completed", "blocked", "failed"}:
        raise ValueError(f"illegal lifecycle transition {(state['command'], state['phase'], phase)!r}")
    effect = _effect(state["request_id"], phase, "notify")
    pending = [*_copy_effects(state["pending_effects"]), _copy_effect(effect)]
    return _next_state(
        state, phase, event_key, pending, list(state["completed_effects"]), state["phase"],
    ), [effect]


def _repeat_failure(state: dict, phase: str, event_key: str) -> tuple[dict, list[dict]]:
    """Re-enter a failure phase only while its exact failed effect is pending."""
    if state["phase"] in {"completed", "blocked", "failed"}:
        return state, []
    pending_failure_keys = {
        f"{state['request_id']}:{phase}:{effect['idempotency_key']}"
        for effect in state["pending_effects"]
    }
    if event_key not in pending_failure_keys:
        return state, []
    return _next_state(
        state, phase, None, _copy_effects(state["pending_effects"]),
        list(state["completed_effects"]), state["phase"],
    ), []


def _completed_effect_key(state: dict, event_kind: str) -> str | None:
    effect_kind = EVENT_COMPLETIONS.get(event_kind)
    if effect_kind is None:
        return None
    return _effect_key(state["request_id"], state["phase"], effect_kind)


def _complete_effect(state: dict, effect_key: str | None, required: bool) -> tuple[list[dict], list[str]]:
    pending = _copy_effects(state["pending_effects"])
    completed = list(state["completed_effects"])
    if effect_key is None:
        return pending, completed
    matching = [effect for effect in pending if effect["idempotency_key"] == effect_key]
    if not matching and required and effect_key not in completed:
        raise ValueError("unknown pending effect")
    pending = [effect for effect in pending if effect["idempotency_key"] != effect_key]
    if effect_key not in completed:
        completed.append(effect_key)
    return pending, completed


def _next_state(
    state: dict,
    phase: str,
    event_key: str | None,
    pending_effects: list[dict],
    completed_effects: list[str],
    recovery_phase: str | None,
) -> dict:
    applied_events = list(state["applied_events"])
    if event_key is not None:
        applied_events.append(event_key)
    return {
        "request_id": state["request_id"],
        "command": state["command"],
        "previous_pause": state["previous_pause"],
        "phase": phase,
        "applied_events": applied_events,
        "pending_effects": pending_effects,
        "completed_effects": completed_effects,
        "recovery_phase": recovery_phase,
    }


def _effect(request_id: str, phase: str, kind: str) -> dict:
    return {
        "kind": kind,
        "request_id": request_id,
        "phase": phase,
        "idempotency_key": _effect_key(request_id, phase, kind),
    }


def _effect_key(request_id: str, phase: str, kind: str) -> str:
    return f"{request_id}:{phase}:{kind}"


def _event_key(request_id: str, event: object) -> str:
    if type(event) is not dict or type(event.get("kind")) is not str or not event["kind"]:
        raise ValueError("invalid lifecycle event")
    if "idempotency_key" not in event:
        if event["kind"] == "effect_completed":
            effect_key = event.get("effect_idempotency_key")
            if not _is_effect_key(effect_key, request_id):
                raise ValueError("invalid effect idempotency key")
            return f"{request_id}:effect_completed:{effect_key}"
        return f"{request_id}:{event['kind']}"
    value = event["idempotency_key"]
    if not _is_scoped_key(value, request_id):
        raise ValueError("invalid event idempotency key")
    return value


def _is_scoped_key(value: object, request_id: str) -> bool:
    return type(value) is str and value.startswith(f"{request_id}:") and len(value) > len(request_id) + 1


def _is_effect_key(value: object, request_id: str) -> bool:
    return type(value) is str and any(
        value == _effect_key(request_id, phase, kind)
        for phase in PHASES
        for kind in EFFECT_KINDS
    )


def _copy_effect(effect: dict) -> dict:
    return dict(effect)


def _copy_effects(effects: list[dict]) -> list[dict]:
    return [_copy_effect(effect) for effect in effects]


def _validate_state(state: object) -> None:
    if type(state) is not dict or set(state) != STATE_FIELDS:
        raise ValueError("invalid lifecycle state")
    request_id = state["request_id"]
    if (
        type(request_id) is not str
        or not request_id
        or type(state["command"]) is not str
        or state["command"] not in {"restart", "reset"}
        or type(state["previous_pause"]) is not bool
        or type(state["phase"]) is not str
        or state["phase"] not in PHASES
        or type(state["applied_events"]) is not list
        or type(state["pending_effects"]) is not list
        or type(state["completed_effects"]) is not list
        or (state["recovery_phase"] is not None
            and (type(state["recovery_phase"]) is not str
                 or state["recovery_phase"] not in PHASES[:-2]))
    ):
        raise ValueError("invalid lifecycle state")
    if state["phase"] in {"blocked", "failed"} and state["recovery_phase"] is None:
        raise ValueError("invalid lifecycle state")
    if state["phase"] not in {"blocked", "failed"} and state["recovery_phase"] is not None:
        raise ValueError("invalid lifecycle state")
    if any(type(value) is not str for value in state["applied_events"]):
        raise ValueError("invalid lifecycle state")
    if any(type(value) is not str for value in state["completed_effects"]):
        raise ValueError("invalid lifecycle state")
    if (
        len(set(state["applied_events"])) != len(state["applied_events"])
        or any(not _is_scoped_key(value, request_id) for value in state["applied_events"])
        or len(set(state["completed_effects"])) != len(state["completed_effects"])
        or any(not _is_effect_key(value, request_id) for value in state["completed_effects"])
    ):
        raise ValueError("invalid lifecycle state")
    pending_keys = []
    for effect in state["pending_effects"]:
        if (
            type(effect) is not dict
            or set(effect) != EFFECT_FIELDS
            or type(effect["kind"]) is not str
            or type(effect["request_id"]) is not str
            or type(effect["phase"]) is not str
            or type(effect["idempotency_key"]) is not str
            or effect["kind"] not in EFFECT_KINDS
            or effect["request_id"] != request_id
            or effect["phase"] not in PHASES
            or effect["idempotency_key"] != _effect_key(request_id, effect["phase"], effect["kind"])
        ):
            raise ValueError("invalid lifecycle state")
        pending_keys.append(effect["idempotency_key"])
    if len(set(pending_keys)) != len(pending_keys) or set(pending_keys) & set(state["completed_effects"]):
        raise ValueError("invalid lifecycle state")
