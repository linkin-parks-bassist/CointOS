import unittest

from survival import lifecycle


def command_record(command: str) -> dict:
    return {
        "schema_version": 1,
        "request_id": "request-1",
        "telegram_update_id": 1,
        "telegram_user_id": 42,
        "command": command,
        "received_at": "2026-09-04T00:00:00+00:00",
    }


def lifecycle_state(command="restart", phase="accepted", previous_pause=False) -> dict:
    return {
        "request_id": "request-1",
        "command": command,
        "previous_pause": previous_pause,
        "phase": phase,
        "applied_events": [],
    }


def effect_kinds(effects: list[dict]) -> list[str]:
    return [effect["kind"] for effect in effects]


def test_new_lifecycle_retains_only_command_identity_and_prior_pause():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=True)
    assert state == lifecycle_state(previous_pause=True)


def test_restart_requests_checkpoint_after_acknowledgement():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=False)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "ack_delivered"})
    assert state["phase"] == "admission_closed"
    assert effect_kinds(effects) == ["close_admission", "checkpoint"]


def test_reset_skips_checkpoint():
    state = lifecycle.new_lifecycle(command_record("reset"), previous_pause=True)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "ack_delivered"})
    assert effect_kinds(effects) == ["close_admission", "kill_units"]


def test_restart_uses_the_durable_recovery_transition_table():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=False)
    transitions = (
        ("ack_delivered", "admission_closed", ["close_admission", "checkpoint"]),
        ("checkpointed", "stopping", ["stop_units"]),
        ("units_stopped", "backend_stopped", ["stop_lemonade"]),
        ("backend_stopped", "starting", ["start_lemonade"]),
        ("lemonade_started", "reconciling", ["start_units"]),
        ("units_started", "verifying", ["reconcile"]),
        ("reconciled", "resumed", ["verify"]),
        ("verified", "completed", ["resume", "finish"]),
    )
    for event_kind, phase, kinds in transitions:
        state, effects = lifecycle.reduce_lifecycle(state, {"kind": event_kind})
        assert state["phase"] == phase
        assert effect_kinds(effects) == kinds


def test_reset_uses_the_fast_recovery_transition_table():
    state = lifecycle.new_lifecycle(command_record("reset"), previous_pause=True)
    transitions = (
        ("ack_delivered", "admission_closed", ["close_admission", "kill_units"]),
        ("units_killed", "backend_stopped", ["stop_lemonade"]),
        ("backend_stopped", "starting", ["start_lemonade"]),
        ("lemonade_started", "reconciling", ["start_units"]),
        ("units_started", "verifying", ["reconcile"]),
        ("reconciled", "resumed", ["verify"]),
        ("verified", "completed", ["finish"]),
    )
    for event_kind, phase, kinds in transitions:
        state, effects = lifecycle.reduce_lifecycle(state, {"kind": event_kind})
        assert state["phase"] == phase
        assert effect_kinds(effects) == kinds


def test_effects_are_complete_declarative_idempotent_requests():
    state, effects = lifecycle.reduce_lifecycle(
        lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
        {"kind": "ack_delivered"},
    )
    assert all(set(effect) == {"kind", "request_id", "phase", "idempotency_key"}
               for effect in effects)
    assert all(effect["request_id"] == "request-1" for effect in effects)
    assert all(effect["phase"] == state["phase"] for effect in effects)
    assert len({effect["idempotency_key"] for effect in effects}) == len(effects)


def test_verification_restores_an_unpaused_lifecycle_only_after_the_health_gate():
    state = lifecycle_state(phase="resumed", previous_pause=False)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "verified"})
    assert state["previous_pause"] is False
    assert effect_kinds(effects) == ["resume", "finish"]


def test_verification_restores_a_paused_lifecycle_without_resuming_work():
    state = lifecycle_state(phase="resumed", previous_pause=True)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "verified"})
    assert state["previous_pause"] is True
    assert effect_kinds(effects) == ["finish"]


def test_replayed_effect_completion_is_idempotent():
    state = lifecycle_state(phase="backend_stopped")
    event = {"kind": "backend_stopped", "idempotency_key": "request-1:backend-stopped"}
    first = lifecycle.reduce_lifecycle(state, event)
    second = lifecycle.reduce_lifecycle(first[0], event)
    assert second == (first[0], [])


def test_illegal_transition_is_rejected_without_a_matching_replay_key():
    with unittest.TestCase().assertRaisesRegex(ValueError, "illegal lifecycle transition"):
        lifecycle.reduce_lifecycle(lifecycle_state(), {"kind": "units_started"})


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
