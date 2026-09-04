"""Behavioral tests for the immutable survival system-control boundary."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from survival import system_control


def command_record(command="reset", update_id=1):
    return {
        "schema_version": 1,
        "request_id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": 42,
        "command": command,
        "received_at": "2026-09-04T00:00:00+00:00",
    }


def process_result(exit_code=0, stdout="", stderr=""):
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}


def read_request_state(path):
    return json.loads(path.read_text(encoding="utf-8"))["state"]


def read_results(path):
    results_path = path.with_suffix(".results.jsonl")
    if not results_path.exists():
        return []
    return [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]


def successful_adapters(events=None, observe=None):
    if events is None:
        events = []

    def manager(name):
        def run(action, unit):
            if observe is not None:
                observe(name, action, unit)
            events.append((name, action, unit))
            state = "active" if action == "start" else "inactive"
            return {
                "ok": True,
                "action": action,
                "unit": unit,
                "state": state,
                "cgroup_empty": action != "start",
            }

        return run

    def direct(kind):
        def run(effect, policy):
            if observe is not None:
                observe(kind, effect, policy)
            events.append((kind,))
            return {"ok": True, "operation": kind}

        return run

    adapters = {
        "system": manager("system"),
        "user": manager("user"),
    }
    for kind in (
        "notify", "close_admission", "checkpoint", "reconcile", "verify",
        "resume", "finish",
    ):
        adapters[kind] = direct(kind)
    return adapters


def test_only_gateway_uid_can_submit_lifecycle_request():
    system_control.authorize_peer(991, gateway_uid=991)
    with unittest.TestCase().assertRaises(PermissionError):
        system_control.authorize_peer(1000, gateway_uid=991)
    with unittest.TestCase().assertRaises(PermissionError):
        system_control.authorize_peer(True, gateway_uid=1)


def test_only_explicit_destructible_units_are_admitted():
    for unit in system_control.SURVIVAL_UNITS:
        with unittest.TestCase().assertRaisesRegex(ValueError, "survival"):
            system_control.validate_destructible_units([unit])
    with unittest.TestCase().assertRaisesRegex(ValueError, "allowlist"):
        system_control.validate_destructible_units(["ssh.service"])
    assert system_control.validate_destructible_units(["lemond.service"]) == [
        "lemond.service"
    ]


def test_zero_exit_without_postcondition_is_failure():
    result = system_control.checked_action(
        run=lambda: process_result(0),
        verify=lambda: False,
    )
    assert result == {"ok": False, "exit_code": 0}


def test_nonzero_exit_with_postcondition_is_failure():
    result = system_control.checked_action(
        run=lambda: process_result(1),
        verify=lambda: True,
    )
    assert result == {"ok": False, "exit_code": 1}


def test_system_unit_uses_exact_argv_and_requires_inactive_empty_postcondition():
    action_calls = []
    query_calls = []
    cgroup_calls = []

    def runner(argv):
        action_calls.append(argv)
        return process_result(0, stdout="stopped\n", stderr="x" * 5000)

    def query(argv):
        query_calls.append(argv)
        return process_result(3, stdout="inactive\n")

    def cgroup(manager, unit, uid):
        cgroup_calls.append((manager, unit, uid))
        return {"empty": True, "path": "/system.slice/lemond.service"}

    result = system_control.system_unit(
        "stop", "lemond.service", runner=runner, query=query, cgroup=cgroup,
    )

    assert action_calls == [["systemctl", "--system", "stop", "lemond.service"]]
    assert query_calls == [[
        "systemctl", "--system", "is-active", "lemond.service",
    ]]
    assert cgroup_calls == [("system", "lemond.service", None)]
    assert result["ok"] is True
    assert result["state"] == "inactive"
    assert result["cgroup_empty"] is True
    assert len(result["stderr"]) == system_control.MAX_EFFECT_OUTPUT_BYTES


def test_user_unit_uses_configured_uid_and_exact_machine_argv():
    action_calls = []
    query_calls = []
    cgroup_calls = []

    def runner(argv):
        action_calls.append(argv)
        return process_result(0)

    def query(argv):
        query_calls.append(argv)
        return process_result(0, stdout="active\n")

    def cgroup(manager, unit, uid):
        cgroup_calls.append((manager, unit, uid))
        return {"empty": False, "path": "/user.slice/user-1000.slice"}

    result = system_control.user_unit(
        "start",
        "agent-ecosystem.service",
        uid=1000,
        runner=runner,
        query=query,
        cgroup=cgroup,
    )

    prefix = ["systemctl", "--user", "--machine=david@.host"]
    assert action_calls == [prefix + ["start", "agent-ecosystem.service"]]
    assert query_calls == [prefix + ["is-active", "agent-ecosystem.service"]]
    assert cgroup_calls == [("user", "agent-ecosystem.service", 1000)]
    assert result["ok"] is True
    assert result["state"] == "active"


def test_zero_exit_and_state_without_cgroup_proof_is_failure():
    result = system_control.system_unit(
        "stop",
        "lemond.service",
        runner=lambda _argv: process_result(0),
        query=lambda _argv: process_result(3, stdout="inactive\n"),
        cgroup=lambda _manager, _unit, _uid: {
            "empty": False,
            "error": "cgroup unreadable",
        },
    )
    assert result["ok"] is False
    assert result["cgroup_empty"] is False


def test_unit_adapters_reject_actions_and_units_before_calling_runner():
    def fail_if_called(_argv):
        raise AssertionError("runner must not be called")

    for call in (
        lambda: system_control.system_unit(
            "restart", "lemond.service", runner=fail_if_called,
        ),
        lambda: system_control.system_unit(
            "stop", "cointelprofessional-gateway.service", runner=fail_if_called,
        ),
        lambda: system_control.user_unit(
            "stop", "ssh.service", uid=1000, runner=fail_if_called,
        ),
        lambda: system_control.user_unit(
            "stop", "agent-ecosystem.service", uid=None, runner=fail_if_called,
        ),
    ):
        with unittest.TestCase().assertRaises(ValueError):
            call()


def test_lifecycle_effects_map_only_to_legal_allowlisted_systemctl_calls():
    events = []
    adapters = successful_adapters(events)
    effects = (
        {"kind": "stop_units", "request_id": "telegram-1", "phase": "stopping",
         "idempotency_key": "telegram-1:stopping:stop_units"},
        {"kind": "kill_units", "request_id": "telegram-1", "phase": "admission_closed",
         "idempotency_key": "telegram-1:admission_closed:kill_units"},
        {"kind": "stop_lemonade", "request_id": "telegram-1", "phase": "backend_stopped",
         "idempotency_key": "telegram-1:backend_stopped:stop_lemonade"},
        {"kind": "start_lemonade", "request_id": "telegram-1", "phase": "starting",
         "idempotency_key": "telegram-1:starting:start_lemonade"},
        {"kind": "start_units", "request_id": "telegram-1", "phase": "reconciling",
         "idempotency_key": "telegram-1:reconciling:start_units"},
    )

    for effect in effects:
        result = system_control.execute_effect(effect, adapters, {})
        assert result["ok"] is True

    user_events = [event for event in events if event[0] == "user"]
    system_events = [event for event in events if event[0] == "system"]
    assert {event[1] for event in user_events} == {"start", "stop", "kill"}
    assert {event[2] for event in user_events} == set(
        system_control.DESTRUCTIBLE_USER_UNITS
    )
    assert system_events == [
        ("system", "stop", "lemond.service"),
        ("system", "start", "lemond.service"),
    ]


def test_execute_effect_rejects_a_mismatched_effect_identity():
    effect = {
        "kind": "stop_lemonade",
        "request_id": "telegram-1",
        "phase": "backend_stopped",
        "idempotency_key": "telegram-1:backend_stopped:start_lemonade",
    }
    with unittest.TestCase().assertRaisesRegex(ValueError, "effect"):
        system_control.execute_effect(effect, successful_adapters(), {})


def test_advance_request_persists_reducer_state_before_every_external_action():
    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary)
        path = system_control.accept_request(
            store, command_record("reset"), previous_pause=False,
        )
        observations = []

        def observe(*_arguments):
            state = read_request_state(path)
            assert state["pending_effects"]
            observations.append((
                state["phase"], state["pending_effects"][0]["kind"],
            ))

        events = []
        result = system_control.advance_request(
            path,
            successful_adapters(events, observe),
            {"verified_event": {"kind": "ack_delivered"}},
        )

        assert result == {"ok": True, "phase": "completed", "remaining_effects": 0}
        assert read_request_state(path)["phase"] == "completed"
        assert observations[0] == ("admission_closed", "close_admission")
        assert all(pending_kind in {
            "close_admission", "kill_units", "stop_lemonade", "start_lemonade",
            "start_units", "reconcile", "verify", "resume", "finish",
        } for _phase, pending_kind in observations)

        first_kill = events.index(next(event for event in events
                                       if event[:2] == ("user", "kill")))
        stop_lemonade = events.index(("system", "stop", "lemond.service"))
        start_lemonade = events.index(("system", "start", "lemond.service"))
        assert first_kill < stop_lemonade < start_lemonade


def test_unverified_effect_result_is_durable_and_effect_remains_pending():
    with tempfile.TemporaryDirectory() as temporary:
        path = system_control.accept_request(
            Path(temporary), command_record("reset"), previous_pause=False,
        )
        adapters = successful_adapters()
        adapters["close_admission"] = lambda _effect, _policy: {
            "ok": False,
            "error": "admission latch not observed",
        }

        result = system_control.advance_request(
            path,
            adapters,
            {"verified_event": {"kind": "ack_delivered"}},
        )

        state = read_request_state(path)
        assert result["ok"] is False
        assert result["failed_effect"] == "telegram-1:admission_closed:close_admission"
        assert [effect["kind"] for effect in state["pending_effects"]] == [
            "close_admission", "kill_units",
        ]
        assert state["completed_effects"] == []
        assert read_results(path)[-1]["ok"] is False


def test_durable_verified_result_is_written_before_reducer_completion_and_recovers():
    with tempfile.TemporaryDirectory() as temporary:
        path = system_control.accept_request(
            Path(temporary), command_record("reset"), previous_pause=False,
        )
        calls = []
        adapters = successful_adapters(calls)
        real_reduce = system_control.lifecycle.reduce_lifecycle

        def interrupt_after_result(state, event):
            if event["kind"] == "effect_completed":
                assert read_results(path)[-1]["ok"] is True
                raise RuntimeError("simulated crash after durable result")
            return real_reduce(state, event)

        with patch.object(system_control.lifecycle, "reduce_lifecycle", interrupt_after_result):
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "simulated crash"):
                system_control.advance_request(
                    path,
                    adapters,
                    {"verified_event": {"kind": "ack_delivered"}},
                )

        state = read_request_state(path)
        assert state["pending_effects"][0]["kind"] == "close_admission"
        assert calls == [("close_admission",)]

        recovered_adapters = successful_adapters()

        def fail_if_replayed(_effect, _policy):
            raise AssertionError("durably verified effect was replayed")

        recovered_adapters["close_admission"] = fail_if_replayed
        result = system_control.advance_request(
            path,
            recovered_adapters,
            {"verified_event": {"kind": "ack_delivered"}},
        )
        assert result["ok"] is True
        assert read_request_state(path)["phase"] == "completed"


def test_accepted_request_without_verified_event_does_not_synthesize_effects():
    with tempfile.TemporaryDirectory() as temporary:
        path = system_control.accept_request(
            Path(temporary), command_record("restart"), previous_pause=False,
        )

        def fail_if_called(*_arguments):
            raise AssertionError("no reducer effect is pending")

        result = system_control.advance_request(
            path,
            {"system": fail_if_called, "user": fail_if_called},
            {},
        )
        assert result == {"ok": False, "phase": "accepted", "remaining_effects": 0}


def test_request_identity_replay_is_exact_and_reuses_one_lifecycle_path():
    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary)
        command = command_record("restart")
        first = system_control.accept_request(store, command, previous_pause=True)
        second = system_control.accept_request(store, command, previous_pause=True)
        assert first == second
        assert read_request_state(first)["previous_pause"] is True
        with unittest.TestCase().assertRaisesRegex(ValueError, "identity"):
            system_control.accept_request(
                store,
                command | {"telegram_user_id": 99},
                previous_pause=True,
            )


def guardian_environment(root):
    return {
        "GUARDIAN_SOCKET_PATH": str(root / "guardian.sock"),
        "SURVIVAL_STORE_DIR": str(root / "state"),
        "GUARDIAN_GATEWAY_UID": "991",
        "USER_MANAGER_UID": "1000",
    }


def test_load_config_parses_one_explicit_gateway_and_user_manager_uid():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = system_control.load_production_config(guardian_environment(root))
        assert config == {
            "socket_path": str(root / "guardian.sock"),
            "store_path": root / "state",
            "gateway_uid": 991,
            "user_manager_uid": 1000,
        }


def test_load_config_rejects_missing_or_noncanonical_uid():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        environment = guardian_environment(root)
        for name in ("GUARDIAN_GATEWAY_UID", "USER_MANAGER_UID"):
            missing = dict(environment)
            del missing[name]
            with unittest.TestCase().assertRaisesRegex(RuntimeError, name):
                system_control.load_production_config(missing)
        for value in ("", "-1", "+991", "0991", "not-a-uid"):
            malformed = dict(environment) | {"GUARDIAN_GATEWAY_UID": value}
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "GUARDIAN_GATEWAY_UID"):
                system_control.load_production_config(malformed)


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions
    )
