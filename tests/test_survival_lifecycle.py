import unittest
import json
from pathlib import Path

from survival import lifecycle, system_control


def test_guardian_allowlist_includes_proxy_without_gateway_dependency():
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / "config/survival-lifecycle.json").read_text())
    controls = policy["user_units"]["control_services"]
    assert {item["unit"] for item in controls} >= {"agent-inference-proxy.service"}
    unit = (root / "services/systemd/agent-inference-proxy.service").read_text()
    assert "PartOf=" not in unit
    assert "Requires=" not in unit
    catalog = system_control.load_lifecycle_catalog(
        root / "config/survival-lifecycle.json")
    proxy_units = {
        entry["unit"] for entry in catalog["user_units"]["control_services"]
    }
    assert "agent-inference-proxy.service" in proxy_units


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
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "ack_committed"})
    assert state["phase"] == "acknowledged"
    assert effect_kinds(effects) == ["close_admission"]


def test_reset_skips_checkpoint():
    state = lifecycle.new_lifecycle(command_record("reset"), previous_pause=True)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "ack_committed"})
    assert effect_kinds(effects) == ["close_admission"]
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "admission_closed"})
    assert state["phase"] == "stopping"
    assert effect_kinds(effects) == ["kill_units"]


def test_restart_uses_the_durable_recovery_transition_table():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=False)
    transitions = (
        ("ack_committed", "acknowledged", ["close_admission"]),
        ("admission_closed", "checkpointing", ["checkpoint"]),
        ("checkpointed", "stopping", ["stop_units"]),
        ("units_stopped", "backend_stopped", ["stop_lemonade"]),
        ("backend_stopped", "starting", ["start_lemonade"]),
        ("lemonade_started", "starting", ["start_units"]),
        ("units_started", "reconciling", ["reconcile"]),
        ("reconciled", "verifying", ["verify"]),
        ("verified", "resumed", ["resume"]),
        ("resumed", "completed", ["finish"]),
        ("finished", "completed", []),
    )
    for event_kind, phase, kinds in transitions:
        state, effects = lifecycle.reduce_lifecycle(state, {"kind": event_kind})
        assert state["phase"] == phase
        assert effect_kinds(effects) == kinds


def test_reset_uses_the_fast_recovery_transition_table():
    state = lifecycle.new_lifecycle(command_record("reset"), previous_pause=True)
    transitions = (
        ("ack_committed", "acknowledged", ["close_admission"]),
        ("admission_closed", "stopping", ["kill_units"]),
        ("units_killed", "backend_stopped", ["stop_lemonade"]),
        ("backend_stopped", "starting", ["start_lemonade"]),
        ("lemonade_started", "starting", ["start_units"]),
        ("units_started", "reconciling", ["reconcile"]),
        ("reconciled", "verifying", ["verify"]),
        ("verified", "resumed", ["finish"]),
        ("finished", "completed", []),
    )
    for event_kind, phase, kinds in transitions:
        state, effects = lifecycle.reduce_lifecycle(state, {"kind": event_kind})
        assert state["phase"] == phase
        assert effect_kinds(effects) == kinds


def test_effects_are_complete_declarative_idempotent_requests():
    state, effects = lifecycle.reduce_lifecycle(
        lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
        {"kind": "ack_committed"},
    )
    assert all(set(effect) == {"kind", "request_id", "phase", "idempotency_key"}
               for effect in effects)
    assert all(effect["request_id"] == "telegram-1" for effect in effects)
    assert all(effect["phase"] == state["phase"] for effect in effects)
    assert len({effect["idempotency_key"] for effect in effects}) == len(effects)


def test_pending_effects_survive_a_guardian_restart_without_replaying_completed_work():
    state, effects = lifecycle.reduce_lifecycle(
        lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
        {"kind": "ack_committed"},
    )
    close_admission = effects[0]
    assert state["pending_effects"] == effects
    state, repeated = lifecycle.reduce_lifecycle(state, {
        "kind": "effect_completed",
        "idempotency_key": "telegram-1:close-admission-completed",
        "effect_idempotency_key": close_admission["idempotency_key"],
    })
    assert repeated == []
    assert state["completed_effects"] == [close_admission["idempotency_key"]]
    assert state["pending_effects"] == []
    _, recovered = lifecycle.reduce_lifecycle(state, {
        "kind": "recover",
        "idempotency_key": "telegram-1:guardian-restart-1",
    })
    assert recovered == []


def test_keyless_effect_completions_use_the_effect_identity_and_replay_independently():
    state, effects = lifecycle.reduce_lifecycle(
        lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
        {"kind": "ack_committed"},
    )
    close_admission = effects[0]
    first_event = {
        "kind": "effect_completed",
        "effect_idempotency_key": close_admission["idempotency_key"],
    }
    state, ignored = lifecycle.reduce_lifecycle(state, first_event)
    assert ignored == []
    state, checkpoint_effects = lifecycle.reduce_lifecycle(
        state, {"kind": "admission_closed"},
    )
    checkpoint = checkpoint_effects[0]
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
    state = lifecycle_state(phase="verifying", previous_pause=False)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "verified"})
    assert state["previous_pause"] is False
    assert state["phase"] == "resumed"
    assert effect_kinds(effects) == ["resume"]


def test_verification_restores_a_paused_lifecycle_without_resuming_work():
    state = lifecycle_state(phase="verifying", previous_pause=True)
    state, effects = lifecycle.reduce_lifecycle(state, {"kind": "verified"})
    assert state["previous_pause"] is True
    assert state["phase"] == "resumed"
    assert effect_kinds(effects) == ["finish"]


def test_replayed_effect_completion_is_idempotent():
    state = lifecycle_state(phase="backend_stopped")
    event = {"kind": "backend_stopped", "idempotency_key": "telegram-1:backend-stopped"}
    first = lifecycle.reduce_lifecycle(state, event)
    second = lifecycle.reduce_lifecycle(first[0], event)
    assert second == (first[0], [])


def test_keyless_acknowledgement_commit_replay_is_a_request_scoped_no_op():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=False)
    first = lifecycle.reduce_lifecycle(state, {"kind": "ack_committed"})
    second = lifecycle.reduce_lifecycle(first[0], {"kind": "ack_committed"})
    assert first[0]["applied_events"] == ["telegram-1:ack_committed"]
    assert second == (first[0], [])


def test_provided_event_key_must_be_a_nonempty_key_for_this_request():
    state = lifecycle.new_lifecycle(command_record("restart"), previous_pause=False)
    for key in ("", "telegram-2:ack_committed", 3):
        with unittest.TestCase().assertRaisesRegex(ValueError, "idempotency"):
            lifecycle.reduce_lifecycle(state, {"kind": "ack_committed", "idempotency_key": key})


def test_blocked_or_failed_lifecycle_retains_pending_work_and_can_recover():
    for terminal_phase in ("blocked", "failed"):
        state, initial_effects = lifecycle.reduce_lifecycle(
            lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
        {"kind": "ack_committed"},
        )
        state, effects = lifecycle.reduce_lifecycle(state, {"kind": terminal_phase})
        assert state["phase"] == terminal_phase
        assert state["recovery_phase"] == "acknowledged"
        assert state["pending_effects"] == [*initial_effects, *effects]
        assert effect_kinds(effects) == ["notify"]
        state, recovered = lifecycle.reduce_lifecycle(state, {"kind": "recover"})
        assert state["phase"] == "acknowledged"
        assert state["recovery_phase"] is None
        assert state["applied_events"].count("telegram-1:recover") == 1
        assert recovered == [*initial_effects, *effects]
        repeated, reissued = lifecycle.reduce_lifecycle(state, {"kind": "recover"})
        assert repeated == state
        assert reissued == recovered


def test_replayed_blocked_event_reblocks_without_duplicating_the_report():
    state, _effects = lifecycle.reduce_lifecycle(
        lifecycle.new_lifecycle(command_record("restart"), previous_pause=False),
        {"kind": "ack_committed"},
    )
    blocked_event = {
        "kind": "blocked",
        "idempotency_key": (
            "telegram-1:blocked:telegram-1:acknowledged:close_admission"
        ),
    }
    state, effects = lifecycle.reduce_lifecycle(state, blocked_event)
    report = effects[0]
    state, _effects = lifecycle.reduce_lifecycle(state, {
        "kind": "effect_completed",
        "effect_idempotency_key": report["idempotency_key"],
    })
    state, _effects = lifecycle.reduce_lifecycle(state, {
        "kind": "recover",
        "idempotency_key": "telegram-1:recover:1",
    })

    state, effects = lifecycle.reduce_lifecycle(state, blocked_event)

    assert state["phase"] == "blocked"
    assert state["recovery_phase"] == "acknowledged"
    assert effect_kinds(state["pending_effects"]) == ["close_admission"]
    assert effects == []


def test_malformed_state_and_event_are_rejected_before_reduction():
    malformed_state = lifecycle_state() | {"pending_effects": [{"kind": "checkpoint"}]}
    with unittest.TestCase().assertRaisesRegex(ValueError, "state"):
        lifecycle.reduce_lifecycle(malformed_state, {"kind": "ack_committed"})
    with unittest.TestCase().assertRaisesRegex(ValueError, "state"):
        lifecycle.reduce_lifecycle(
            lifecycle_state() | {"completed_effects": ["telegram-1:forged"]},
            {"kind": "ack_committed"},
        )
    for field in ("command", "applied_events", "completed_effects"):
        with unittest.TestCase().assertRaisesRegex(ValueError, "state"):
            lifecycle.reduce_lifecycle(
                lifecycle_state() | {field: [[]]},
                {"kind": "ack_committed"},
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
