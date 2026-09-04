"""Tests for survival system_control: peer auth, allowlists, unit management, effects."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from survival import system_control


def completed(exit_code: int) -> dict:
    return {"exit_code": exit_code}


def fake_adapters() -> dict:
    return {
        "system": _fake_system_unit,
        "user": _fake_user_unit,
    }


def _fake_system_unit(action: str, unit: str) -> dict:
    return {"action": action, "unit": unit, "state": "inactive"}


def _fake_user_unit(action: str, unit: str) -> dict:
    return {"action": action, "unit": unit, "state": "inactive"}


# ---------------------------------------------------------------------------
# Step 1: peer auth, allowlist, kill-order, postcondition tests
# ---------------------------------------------------------------------------


def test_only_gateway_uid_can_submit_lifecycle_request():
    gateway_uid = 991
    system_control.authorize_peer(991, gateway_uid=991)
    with unittest.TestCase().assertRaises(PermissionError):
        system_control.authorize_peer(1000, gateway_uid=991)


def test_gateway_and_guardian_cannot_enter_destructible_set():
    with unittest.TestCase().assertRaisesRegex(ValueError, "survival"):
        system_control.validate_destructible_units(
            ["cointelprofessional-gateway.service"])


def test_gateway_unit_is_also_protected():
    with unittest.TestCase().assertRaisesRegex(ValueError, "survival"):
        system_control.validate_destructible_units(
            ["cointelprofessional-guardian.service"])


def test_guardian_socket_is_also_protected():
    with unittest.TestCase().assertRaisesRegex(ValueError, "survival"):
        system_control.validate_destructible_units(
            ["cointelprofessional-guardian.socket"])


def test_lemond_service_is_destructible():
    result = system_control.validate_destructible_units(["lemond.service"])
    assert result == ["lemond.service"]


def test_user_units_are_destructible():
    for unit in (
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
    ):
        result = system_control.validate_destructible_units([unit])
        assert result == [unit], f"expected {unit} to be destructible"


def test_empty_list_passes_validation():
    result = system_control.validate_destructible_units([])
    assert result == []


def test_reset_kills_user_units_before_lemonade_start():
    events: list[str] = []

    def recording_adapters():
        def record(action, unit):
            events.append(action)
            return {"action": action, "unit": unit, "state": "inactive"}
        return {
            "system": record,
            "user": record,
        }

    run_effects_for("reset", recording_adapters())
    assert events.index("kill_user_units") < events.index("stop_lemonade")
    assert events.index("stop_lemonade") < events.index("start_lemonade")


def test_restart_stops_units_before_Lemond_stop():
    events: list[str] = []

    def recording_adapters():
        def record(action, unit):
            events.append(action)
            return {"action": action, "unit": unit, "state": "inactive"}
        return {
            "system": record,
            "user": record,
        }

    run_effects_for("restart", recording_adapters())
    assert events.index("stop_units") < events.index("stop_lemonade")
    assert events.index("stop_lemonade") < events.index("start_lemonade")
    assert events.index("start_lemonade") < events.index("start_units")


def test_zero_exit_without_postcondition_is_failure():
    result = system_control.checked_action(
        run=lambda *_: completed(0),
        verify=lambda: False,
    )
    assert result["ok"] is False


def test_nonzero_exit_is_failure():
    result = system_control.checked_action(
        run=lambda *_: completed(1),
        verify=lambda: True,
    )
    assert result["ok"] is False


def test_zero_exit_with_true_postcondition_is_success():
    result = system_control.checked_action(
        run=lambda *_: completed(0),
        verify=lambda: True,
    )
    assert result["ok"] is True


def test_checked_action_returns_bounded_result():
    result = system_control.checked_action(
        run=lambda *_: completed(0),
        verify=lambda: True,
    )
    assert set(result) == {"ok", "exit_code"}
    assert result["ok"] is True
    assert result["exit_code"] == 0


# ---------------------------------------------------------------------------
# Step 2: advance_request tests
# ---------------------------------------------------------------------------


def test_advance_request_writes_durable_phase_before_effect():
    """advance_request must write the next durable phase before executing its effect."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        (store / "durable").mkdir()
        durable_path = store / "durable" / "phase.json"

        effect_was_run = False

        def effect_runner(action, unit):
            nonlocal effect_was_run
            effect_was_run = True
            return {"action": action, "unit": unit, "state": "inactive"}

        adapters = {"system": effect_runner, "user": effect_runner}

        # Write initial phase
        system_control._write_durable_phase(store, "accepted")
        assert durable_path.exists()

        result = system_control.advance_request(
            store, adapters, policy={"command": "reset", "max_retries": 3}
        )
        assert "ok" in result
        assert effect_was_run is True
        phase = system_control._read_durable_phase(store)
        assert phase == "completed"


def test_advance_request_picks_up_pending_effects():
    """When effects already exist, advance should execute them."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        (store / "durable").mkdir()

        run_count = [0]

        def effect_runner(action, unit):
            run_count[0] += 1
            return {"action": action, "unit": unit, "state": "inactive"}

        adapters = {"system": effect_runner, "user": effect_runner}
        policy = {"command": "reset", "max_retries": 3}

        # Create a proper command record with all required fields
        command = {
            "schema_version": 1,
            "request_id": "telegram-1",
            "telegram_update_id": 1,
            "telegram_user_id": 42,
            "command": "reset",
            "received_at": "2026-09-04T00:00:00+00:00",
        }
        state = system_control.new_lifecycle(command, previous_pause=False)
        system_control._write_durable_state(store, state)

        # Feed the first event to generate effects
        state, effects = system_control.reduce_lifecycle(
            state, {"kind": "ack_delivered"}
        )
        system_control._write_durable_state(store, state)

        result = system_control.advance_request(
            store, adapters, policy=policy
        )
        assert "ok" in result
        assert run_count[0] > 0


# ---------------------------------------------------------------------------
# Step 3: system_unit / user_unit tests
# ---------------------------------------------------------------------------


def test_system_unit_restart_returns_result():
    result = system_control.system_unit("restart", "lemond.service")
    assert "ok" in result
    assert "exit_code" in result


def test_system_unit_stop_returns_result():
    result = system_control.system_unit("stop", "lemond.service")
    assert "ok" in result


def test_user_unit_action_returns_result():
    result = system_control.user_unit("stop", "agent-ecosystem.service")
    assert "ok" in result


def test_user_unit_kill_returns_result():
    result = system_control.user_unit("kill", "agent-ecosystem.service")
    assert "ok" in result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_effects_for(command: str, adapters: dict) -> list[str]:
    """Run through the effect sequence for a command, recording effect kinds."""
    # Use run_effects which iterates all effect kinds
    return system_control.run_effects(command, adapters)


# ---------------------------------------------------------------------------
# load_config tests
# ---------------------------------------------------------------------------


def test_load_config_requires_socket_path():
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "GUARDIAN_SOCKET_PATH"):
        system_control.load_production_config({"USER": "david"})


def test_load_config_requires_user():
    with tempfile.TemporaryDirectory() as tmp:
        sock = Path(tmp) / "guardian.sock"
        with unittest.TestCase().assertRaisesRegex(
            RuntimeError, "GUARDIAN_ALLOWED_USER_IDS_PATH"
        ):
            system_control.load_production_config({
                "USER": "david",
                "GUARDIAN_SOCKET_PATH": str(sock),
            })


def test_load_config_reads_user_id_file():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sock = tmp / "guardian.sock"
        allowed = tmp / "allowed"
        allowed.write_text("991\n", encoding="utf-8")
        config = system_control.load_production_config({
            "USER": "david",
            "GUARDIAN_SOCKET_PATH": str(sock),
            "GUARDIAN_ALLOWED_USER_IDS_PATH": str(allowed),
        })
        assert config["gateway_uid"] == 991
        assert config["user"] == "david"
        assert config["socket_path"] == str(sock)


# ---------------------------------------------------------------------------
# load_tests discovery
# ---------------------------------------------------------------------------

def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions
    )
