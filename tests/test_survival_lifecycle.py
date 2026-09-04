import unittest

from survival import lifecycle


def command_record(command: str) -> dict:
    return {
        "schema_version": 1,
        "request_id": "telegram-1",
        "telegram_update_id": 1,
        "telegram_user_id": 42,
        "command": command,
        "received_at": "2026-09-04T00:00:00+00:00",
    }


def lifecycle_state(command="restart", phase="accepted", previous_pause=False) -> dict:
    return {
        "request_id": "telegram-1",
        "command": command,
        "previous_pause": previous_pause,
        "phase": phase,
        "applied_events": [],
        "pending_effects": [],
        "completed_effects": [],
        "recovery_phase": None,
    }


def effect_kinds(effects: list[dict]) -> list[str]:
    return [effect["kind"] for effect in effects]


def test_new_lifecycle_retains_strict_command_identity_and_prior_pause():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=True)
    assert state == lifecycle_state(previous_pause=True)


def test_new_lifecycle_rejects_forged_or_incomplete_command_records():
    for command in (
        {"request_id": "telegram-1", "command": "restart"},
        command_record("restart") | {"unit": "agent-ecosystem.service"},
        command_record("restart") | {"telegram_update_id": True},
        command_record("restart") | {"received_at": "not a timestamp"},
    ):
        with unittest.TestCase().assertRaises(ValueError):
            lifecycle.new_lifecycle(command, previous_pause=False)


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
    assert all(effect["request_id"] == "telegram-1" for effect in effects)
    assert all(effect["phase"] == state["phase"] for effect in effects)
    assert len({effect["idempotency_key"] for effect in effects}) == len(effects)


def test_pending_effects_survive_a_guardian_restart_without_replaying_completed_work():
    state, effects = lifecycle.reduce_lifecycle(
        lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
        {"kind": "ack_delivered"},
    )
    close_admission, checkpoint = effects
    assert state["pending_effects"] == effects
    state, repeated = lifecycle.reduce_lifecycle(state, {
        "kind": "effect_completed",
        "idempotency_key": "telegram-1:close-admission-completed",
        "effect_idempotency_key": close_admission["idempotency_key"],
    })
    assert repeated == []
    assert state["completed_effects"] == [close_admission["idempotency_key"]]
    assert state["pending_effects"] == [checkpoint]
    _, recovered = lifecycle.reduce_lifecycle(state, {
        "kind": "recover",
        "idempotency_key": "telegram-1:guardian-restart-1",
    })
    assert recovered == [checkpoint]


def test_keyless_effect_completions_use_the_effect_identity_and_replay_independently():
    state, effects = lifecycle.reduce_lifecycle(
        lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
        {"kind": "ack_delivered"},
    )
    close_admission, checkpoint = effects
    first_event = {
        "kind": "effect_completed",
        "effect_idempotency_key": close_admission["idempotency_key"],
    }
    state, ignored = lifecycle.reduce_lifecycle(state, first_event)
    assert ignored == []
    state, ignored = lifecycle.reduce_lifecycle(state, {
        "kind": "effect_completed",
        "effect_idempotency_key": checkpoint["idempotency_key"],
    })
    assert ignored == []
    assert state["pending_effects"] == []
    assert state["completed_effects"] == [
        close_admission["idempotency_key"], checkpoint["idempotency_key"],
    ]
    replayed, ignored = lifecycle.reduce_lifecycle(state, first_event)
    assert replayed == state
    assert ignored == []


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
    event = {"kind": "backend_stopped", "idempotency_key": "telegram-1:backend-stopped"}
    first = lifecycle.reduce_lifecycle(state, event)
    second = lifecycle.reduce_lifecycle(first[0], event)
    assert second == (first[0], [])


def test_keyless_acknowledgement_replay_is_a_request_scoped_no_op():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=False)
    first = lifecycle.reduce_lifecycle(state, {"kind": "ack_delivered"})
    second = lifecycle.reduce_lifecycle(first[0], {"kind": "ack_delivered"})
    assert first[0]["applied_events"] == ["telegram-1:ack_delivered"]
    assert second == (first[0], [])


def test_provided_event_key_must_be_a_nonempty_key_for_this_request():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=False)
    for key in ("", "telegram-2:ack_delivered", 3):
        with unittest.TestCase().assertRaisesRegex(ValueError, "idempotency"):
            lifecycle.reduce_lifecycle(state, {"kind": "ack_delivered", "idempotency_key": key})


def test_blocked_or_failed_lifecycle_retains_pending_work_and_can_recover():
    for terminal_phase in ("blocked", "failed"):
        state, initial_effects = lifecycle.reduce_lifecycle(
            lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
            {"kind": "ack_delivered"},
        )
        state, effects = lifecycle.reduce_lifecycle(state, {"kind": terminal_phase})
        assert state["phase"] == terminal_phase
        assert state["recovery_phase"] == "admission_closed"
        assert state["pending_effects"] == [*initial_effects, *effects]
        assert effect_kinds(effects) == ["notify"]
        state, recovered = lifecycle.reduce_lifecycle(state, {"kind": "recover"})
        assert state["phase"] == "admission_closed"
        assert state["recovery_phase"] is None
        assert state["applied_events"].count("telegram-1:recover") == 1
        assert recovered == [*initial_effects, *effects]
        repeated, reissued = lifecycle.reduce_lifecycle(state, {"kind": "recover"})
        assert repeated == state
        assert reissued == recovered


def test_malformed_state_and_event_are_rejected_before_reduction():
    malformed_state = lifecycle_state() | {"pending_effects": [{"kind": "checkpoint"}]}
    with unittest.TestCase().assertRaisesRegex(ValueError, "state"):
        lifecycle.reduce_lifecycle(malformed_state, {"kind": "ack_delivered"})
    with unittest.TestCase().assertRaisesRegex(ValueError, "state"):
        lifecycle.reduce_lifecycle(
            lifecycle_state() | {"completed_effects": ["telegram-1:forged"]},
            {"kind": "ack_delivered"},
        )
    for field in ("command", "applied_events", "completed_effects"):
        with unittest.TestCase().assertRaisesRegex(ValueError, "state"):
            lifecycle.reduce_lifecycle(
                lifecycle_state() | {field: [[]]},
                {"kind": "ack_delivered"},
            )
    with unittest.TestCase().assertRaisesRegex(ValueError, "event"):
        lifecycle.reduce_lifecycle(lifecycle_state(), {"kind": 1})


def test_illegal_transition_is_rejected_without_a_matching_replay_key():
    with unittest.TestCase().assertRaisesRegex(ValueError, "illegal lifecycle transition"):
        lifecycle.reduce_lifecycle(lifecycle_state(), {"kind": "units_started"})


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
