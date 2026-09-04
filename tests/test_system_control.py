"""Behavioral tests for the immutable survival system-control boundary."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from survival import checkpoint, lifecycle, system_control, telegram_api, time_policy


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
    root = path.parent / "results" / path.stem
    return [
        json.loads(candidate.read_text(encoding="utf-8"))
        for candidate in sorted(root.glob("*/*.json"))
    ] if root.exists() else []


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
        "wait": lambda _seconds: None,
    }
    for kind in (
        "notify", "close_admission", "checkpoint", "reconcile", "verify",
        "resume", "finish",
    ):
        adapters[kind] = direct(kind)
    return adapters


def lifecycle_policy(store, request_id="telegram-1"):
    policy = {
        "store_path": Path(store),
        "lifecycle_catalog": system_control.load_lifecycle_catalog(
            Path("config/survival-lifecycle.json"),
        ),
        "timing_policy": time_policy.load(Path("config/time.cfg")),
    }
    system_control._write_runtime(policy, {
        "schema_version": 1,
        "request_id": request_id,
        "previous_pause": False,
        "previous_active_user_units": ["agent-notifier.service"],
        "interrupted_jobs": [],
    })
    return policy


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


def test_inactive_unit_with_no_realized_cgroup_is_verified_empty():
    def query(argv):
        if "--property=ControlGroup" in argv:
            return process_result(0, stdout="\n")
        return process_result(3, stdout="inactive\n")

    result = system_control.user_unit(
        "stop",
        "agent-telegram.service",
        uid=1000,
        runner=lambda _argv: process_result(0),
        query=query,
    )

    assert result["ok"] is True
    assert result["state"] == "inactive"
    assert result["cgroup_empty"] is True
    assert result["cgroup"]["path"] == ""


def test_reset_failed_uses_exact_allowlisted_systemctl_argv():
    calls = []

    def runner(argv):
        calls.append(argv)
        return process_result(0)

    result = system_control.system_unit(
        "reset_failed",
        "lemond.service",
        runner=runner,
        query=lambda _argv: process_result(3, stdout="inactive\n"),
        cgroup=lambda *_args: {"empty": True},
    )

    assert result["ok"] is True
    assert calls == [["systemctl", "--system", "reset-failed", "lemond.service"]]


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


def test_status_distinguishes_an_uninstalled_required_unit():
    calls = []

    def query(argv):
        calls.append(argv)
        if "--property=LoadState" in argv:
            return process_result(0, stdout="not-found\n")
        return process_result(4, stdout="inactive\n")

    result = system_control.user_unit(
        "status", "agent-models.service", uid=1000,
        query=query,
        cgroup=lambda *_args: {"empty": True},
    )
    assert result["installed"] is False
    assert result["state"] == "not-found"
    assert any("--property=LoadState" in call for call in calls)


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

    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary)
        policy = {
            "store_path": store,
            "lifecycle_catalog": system_control.load_lifecycle_catalog(
                Path("config/survival-lifecycle.json"),
            ),
            "timing_policy": time_policy.load(Path("config/time.cfg")),
        }
        system_control._write_runtime(policy, {
            "schema_version": 1,
            "request_id": "telegram-1",
            "previous_pause": False,
            "previous_active_user_units": ["agent-notifier.service"],
            "interrupted_jobs": [],
        })
        for effect in effects:
            result = system_control.execute_effect(effect, adapters, policy)
            assert result["ok"] is True

    user_events = [event for event in events if event[0] == "user"]
    system_events = [event for event in events if event[0] == "system"]
    assert {event[1] for event in user_events} == {
        "start", "stop", "terminate", "kill", "reset_failed",
    }
    assert {event[2] for event in user_events} == set(
        system_control.DESTRUCTIBLE_USER_UNITS
    )
    assert system_events == [
        ("system", "stop", "lemond.service"),
        ("system", "reset_failed", "lemond.service"),
        ("system", "start", "lemond.service"),
    ]


def test_watchdog_runner_pulses_during_a_bounded_external_probe():
    release = threading.Event()
    pulses = []

    def operation():
        assert release.wait(1.0)
        return {"ok": True, "proof": "fresh"}

    result = system_control._run_with_watchdog(
        operation,
        deadline_seconds=1.0,
        heartbeat=lambda: (pulses.append(True), release.set()),
        pulse_seconds=0.01,
    )

    assert result == {"ok": True, "proof": "fresh"}
    assert pulses


def test_escalation_observes_configured_terminate_and_kill_grace():
    waits = []
    adapters = successful_adapters()

    def manager(action, unit):
        return {
            "ok": action != "stop",
            "action": action,
            "unit": unit,
            "exit_code": 0,
            "state": "inactive" if action == "kill" else "deactivating",
            "cgroup_empty": action == "kill",
        }

    adapters["user"] = manager
    adapters["wait"] = lambda seconds: waits.append(seconds)
    with tempfile.TemporaryDirectory() as temporary:
        policy = lifecycle_policy(Path(temporary))
        result = system_control.execute_effect({
            "kind": "kill_units",
            "request_id": "telegram-1",
            "phase": "stopping",
            "idempotency_key": "telegram-1:stopping:kill_units",
        }, adapters, policy)
    assert result["ok"] is False
    assert waits
    assert set(waits) == {5.0, 2.0}


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
        system_control.commit_acknowledgement(path)
        observations = []

        def observe(*_arguments):
            state = read_request_state(path)
            assert state["pending_effects"]
            observations.append((
                state["phase"], state["pending_effects"][0]["kind"],
            ))

        events = []
        policy = lifecycle_policy(store)
        result = system_control.advance_request(
            path,
            successful_adapters(events, observe),
            policy,
        )

        assert result == {"ok": True, "phase": "completed", "remaining_effects": 0}
        assert read_request_state(path)["phase"] == "completed"
        assert observations[0] == ("acknowledged", "close_admission")
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
        system_control.commit_acknowledgement(path)
        adapters = successful_adapters()
        adapters["close_admission"] = lambda _effect, _policy: {
            "ok": False,
            "error": "admission latch not observed",
        }

        result = system_control.advance_request(
            path,
            adapters,
            {},
        )

        state = read_request_state(path)
        assert result["ok"] is False
        assert result["failed_effect"] == "telegram-1:acknowledged:close_admission"
        assert state["phase"] == "blocked"
        assert [effect["kind"] for effect in state["pending_effects"]] == ["close_admission"]
        assert state["completed_effects"] == [
            "telegram-1:blocked:notify",
        ]
        assert any(result["ok"] is False for result in read_results(path))


def test_permanent_effect_failure_retries_without_duplicate_blocked_report():
    with tempfile.TemporaryDirectory() as temporary:
        path = system_control.accept_request(
            Path(temporary), command_record("reset"), previous_pause=False,
        )
        system_control.commit_acknowledgement(path)
        attempts = []
        adapters = successful_adapters()

        def fail_permanently(_effect, _policy):
            attempts.append("close_admission")
            return {"ok": False, "error": "permanent admission failure"}

        adapters["close_admission"] = fail_permanently
        results = []
        for _attempt in range(3):
            results.append(system_control.advance_request(path, adapters, {}))
            system_control.recover_request(path)

        reports = [
            result for result in read_results(path)
            if result["effect_idempotency_key"] == "telegram-1:blocked:notify"
        ]
        assert [result["phase"] for result in results] == ["blocked"] * 3
        assert attempts == ["close_admission"] * 3
        assert len(reports) == 1
        assert reports[0]["ok"] is True


def test_durable_verified_result_is_written_before_reducer_completion_and_recovers():
    with tempfile.TemporaryDirectory() as temporary:
        path = system_control.accept_request(
            Path(temporary), command_record("reset"), previous_pause=False,
        )
        system_control.commit_acknowledgement(path)
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
                    lifecycle_policy(Path(temporary)),
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
            lifecycle_policy(Path(temporary)),
        )
        assert result["ok"] is True
        assert read_request_state(path)["phase"] == "completed"


def test_every_success_path_effect_recovers_after_external_action_before_result_commit():
    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary)
        path = system_control.accept_request(
            store, command_record("restart"), previous_pause=False,
        )
        system_control.commit_acknowledgement(path)
        policy = lifecycle_policy(store) | {"maximum_effects": 1}
        adapters = successful_adapters()
        crashed_kinds = []

        while (
            read_request_state(path)["phase"] != "completed"
            or read_request_state(path)["pending_effects"]
        ):
            state = read_request_state(path)
            assert state["pending_effects"]
            effect = state["pending_effects"][0]
            crashed_kinds.append(effect["kind"])
            with patch.object(
                system_control,
                "_store_effect_result",
                side_effect=RuntimeError("simulated death before result publication"),
            ):
                with unittest.TestCase().assertRaisesRegex(RuntimeError, "simulated death"):
                    system_control.advance_request(path, adapters, policy)
            assert read_request_state(path)["pending_effects"][0] == effect
            system_control.advance_request(path, adapters, policy)

        assert crashed_kinds == [
            "close_admission", "checkpoint", "stop_units", "stop_lemonade",
            "start_lemonade", "start_units", "reconcile", "verify", "resume",
            "finish",
        ], crashed_kinds


def test_every_verified_effect_result_survives_death_before_state_reduction():
    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary)
        path = system_control.accept_request(
            store, command_record("restart"), previous_pause=False,
        )
        system_control.commit_acknowledgement(path)
        policy = lifecycle_policy(store) | {"maximum_effects": 1}
        events = []
        adapters = successful_adapters(events)
        real_reduce = system_control.lifecycle.reduce_lifecycle
        crashed_kinds = []

        while (
            read_request_state(path)["phase"] != "completed"
            or read_request_state(path)["pending_effects"]
        ):
            effect = read_request_state(path)["pending_effects"][0]
            crashed_kinds.append(effect["kind"])

            def interrupt_after_result(state, event):
                if event["kind"] == "effect_completed":
                    raise RuntimeError("simulated death after result publication")
                return real_reduce(state, event)

            with patch.object(
                system_control.lifecycle,
                "reduce_lifecycle",
                interrupt_after_result,
            ):
                with unittest.TestCase().assertRaisesRegex(RuntimeError, "after result"):
                    system_control.advance_request(path, adapters, policy)
            event_count = len(events)
            system_control.advance_request(path, adapters, policy)
            assert len(events) == event_count

        assert crashed_kinds == [
            "close_admission", "checkpoint", "stop_units", "stop_lemonade",
            "start_lemonade", "start_units", "reconcile", "verify", "resume",
            "finish",
        ]


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
        "TIME_CONFIG_PATH": str(Path("config/time.cfg").resolve()),
        "LIFECYCLE_CATALOG_PATH": str(Path("config/survival-lifecycle.json").resolve()),
        "AGENT_STATE_DIR": str(root / "agent-state"),
    }


def test_load_config_parses_one_explicit_gateway_and_user_manager_uid():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = system_control.load_production_config(guardian_environment(root))
        assert config["socket_path"] == str(root / "guardian.sock")
        assert config["store_path"] == root / "state"
        assert config["agent_state_path"] == root / "agent-state"
        assert config["gateway_uid"] == 991
        assert config["user_manager_uid"] == 1000
        assert config["timing_policy"] == time_policy.load(Path("config/time.cfg"))
        assert config["lifecycle_catalog"]["schema_version"] == 1


def test_guardian_live_policy_reload_persists_rejection_and_keeps_last_known_good():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "time.cfg"
        source.write_bytes(Path("config/time.cfg").read_bytes())
        environment = guardian_environment(root) | {"TIME_CONFIG_PATH": str(source)}
        config = system_control.load_production_config(environment)
        original = config["timing_policy"]
        path = system_control.accept_request(
            config["store_path"], command_record("restart"), previous_pause=False,
        )
        system_control.commit_acknowledgement(path)

        source.write_text("[lifecycle]\nservice_stop_deadline_seconds = nan\n")
        error = system_control.refresh_timing_policy(config)
        assert "time policy" in error
        assert config["timing_policy"] == original
        status = json.loads(
            (config["store_path"] / "policy/status.json").read_text(encoding="utf-8")
        )
        assert status["state"] == "rejected"
        reports = list((config["store_path"] / "outbox/critical").glob("policy-*.json"))
        assert len(reports) == 1
        system_control.refresh_timing_policy(config)
        assert len(list((config["store_path"] / "outbox/critical").glob("policy-*.json"))) == 1


def test_guardian_reports_each_gateway_quarantine_incident_once():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = root / "store"
        path = system_control.accept_request(
            store, command_record("restart"), previous_pause=False,
        )
        system_control.commit_acknowledgement(path)
        records_path = store / "gateway/data-health.json"
        records_path.parent.mkdir(parents=True, exist_ok=True)
        records_path.write_text(json.dumps({
            "schema_version": 1,
            "state": "degraded",
            "incident_id": "quarantine-one",
            "source_path": "/var/lib/cointelprofessional/inbox/bad.json",
            "error_reason": "invalid inbox JSON",
            "quarantine_succeeded": True,
        }), encoding="utf-8")
        config = {"store_path": store}
        system_control.report_gateway_data_health(config)
        system_control.report_gateway_data_health(config)
        reports = list((store / "outbox/critical").glob("gateway-quarantine-*.json"))
        assert len(reports) == 1
        assert "invalid inbox JSON" in json.loads(reports[0].read_text())["text"]

        records_path.write_text(json.dumps({
            "schema_version": 1,
            "state": "degraded",
            "incident_id": "quarantine-two",
            "source_path": "/var/lib/cointelprofessional/inbox/stuck.json",
            "error_reason": "quarantine rename failed",
            "quarantine_succeeded": False,
        }), encoding="utf-8")
        system_control.report_gateway_data_health(config)
        failed_report = json.loads(
            (store / "outbox/critical/gateway-quarantine-quarantine-two.json")
            .read_text(encoding="utf-8")
        )
        assert "could not isolate" in failed_report["text"]
        assert "contact remains live" in failed_report["text"]


def test_guardian_reports_every_gateway_incident_even_when_scans_find_several():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = root / "store"
        path = system_control.accept_request(
            store, command_record("restart"), previous_pause=False,
        )
        system_control.commit_acknowledgement(path)
        inbox = store / "inbox"
        inbox.mkdir(parents=True)
        for name in ("bad-one.json", "bad-two.json"):
            source = inbox / name
            source.write_text("{", encoding="utf-8")
            assert telegram_api.quarantine_record(
                store, source, f"invalid {name}",
            ) is True

        system_control.report_gateway_data_health({"store_path": store})

        reports = list((store / "outbox/critical").glob("gateway-quarantine-*.json"))
        assert len(reports) == 2


def _checkpoint_clock():
    state = {"now": 0.0}

    def monotonic():
        return state["now"]

    def sleep(seconds):
        state["now"] += seconds

    return monotonic, sleep


def _write_checkpoint_job(agent_state, job_id, session=None):
    job = {
        "id": job_id,
        "kind": "agent-task",
        "state": "running",
        "output": f"logs/runs/{job_id}.opencode.log",
    }
    if session is not None:
        job["opencode_session"] = session
    path = agent_state / "jobs" / f"{job_id}.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    if session is not None:
        output = agent_state.parent / job["output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"sessionID": session}) + "\n", encoding="utf-8",
        )
    return path


def test_restart_checkpoint_request_is_observed_and_all_active_jobs_use_task_1_transition():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        policy = lifecycle_policy(root / "survival") | {
            "agent_state_path": agent_state,
        }
        checkpointed_path = _write_checkpoint_job(
            agent_state, "task-checkpointed", "ses_checkpointed",
        )
        unsupported_path = _write_checkpoint_job(
            agent_state, "task-unsupported",
        )
        effect = {
            "request_id": "telegram-1",
            "idempotency_key": "telegram-1:checkpointing:checkpoint",
        }
        monotonic, advance_clock = _checkpoint_clock()

        def consume_request(seconds):
            request_root, result_root = checkpoint.checkpoint_paths(
                policy["store_path"], policy["lifecycle_catalog"],
            )
            request_path = request_root / "telegram-1.json"
            checkpoint.process_checkpoint_request(
                request_path, agent_state, result_root, now=monotonic,
            )
            advance_clock(seconds)

        result = system_control._checkpoint_runtime(
            policy, effect, sleep=consume_request, sync=lambda: None,
            monotonic=monotonic,
        )

        request_root, result_root = checkpoint.checkpoint_paths(
            policy["store_path"], policy["lifecycle_catalog"],
        )
        request_path = request_root / "telegram-1.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        checkpoint_metadata = request_path.stat()
        request_directory_metadata = request_root.stat()
        assert set(request) == checkpoint.CHECKPOINT_REQUEST_FIELDS
        assert request["job_ids"] == ["task-checkpointed", "task-unsupported"]
        assert request["deadline_monotonic"] == 30.0
        assert checkpoint_metadata.st_uid == request_directory_metadata.st_uid
        assert checkpoint_metadata.st_gid == request_directory_metadata.st_gid
        assert checkpoint_metadata.st_mode & 0o777 == 0o640
        assert result == {
            "ok": True,
            "checkpointed_jobs": ["task-checkpointed"],
            "interrupted_jobs": ["task-checkpointed", "task-unsupported"],
        }
        assert json.loads(checkpointed_path.read_text())["state"] == "interrupted"
        assert json.loads(checkpointed_path.read_text())["resume_available"] is True
        assert json.loads(unsupported_path.read_text())["state"] == "interrupted"
        assert json.loads(unsupported_path.read_text())["resume_available"] is False
        assert json.loads(
            (policy["store_path"] / "lifecycle-transitions/telegram-1/task-checkpointed.json")
            .read_text(encoding="utf-8")
        )["transition_state"] == "completed"
        assert json.loads(
            (policy["store_path"] / "lifecycle-transitions/telegram-1/task-unsupported.json")
            .read_text(encoding="utf-8")
        )["transition_state"] == "completed"
        assert json.loads(
            (result_root / "telegram-1/task-checkpointed.json").read_text()
        )["opencode_session"] == "ses_checkpointed"


def test_elapsed_checkpoint_wait_without_results_interrupts_instead_of_succeeding():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        job_path = _write_checkpoint_job(
            agent_state, "task-active", "ses_active",
        )
        policy = lifecycle_policy(root / "survival") | {
            "agent_state_path": agent_state,
        }
        effect = {
            "request_id": "telegram-1",
            "idempotency_key": "telegram-1:checkpointing:checkpoint",
        }
        monotonic, sleep = _checkpoint_clock()

        result = system_control._checkpoint_runtime(
            policy, effect, sleep=sleep, sync=lambda: None, monotonic=monotonic,
        )

        assert result == {
            "ok": True,
            "checkpointed_jobs": [],
            "interrupted_jobs": ["task-active"],
        }
        job = json.loads(job_path.read_text())
        assert job["state"] == "interrupted"
        assert job["resume_available"] is False
        assert "opencode_session" not in job
        request_root, result_root = checkpoint.checkpoint_paths(
            policy["store_path"], policy["lifecycle_catalog"],
        )
        assert (request_root / "telegram-1.json").exists()
        assert not (result_root / "telegram-1/task-active.json").exists()


def test_guardian_rejects_a_checkpoint_result_without_its_claimed_handoff():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        job_path = _write_checkpoint_job(
            agent_state, "task-active", "ses_real",
        )
        policy = lifecycle_policy(root / "survival") | {
            "agent_state_path": agent_state,
        }
        effect = {
            "request_id": "telegram-1",
            "idempotency_key": "telegram-1:checkpointing:checkpoint",
        }
        monotonic, advance_clock = _checkpoint_clock()

        def publish_tampered_result(seconds):
            _request_root, result_root = checkpoint.checkpoint_paths(
                policy["store_path"], policy["lifecycle_catalog"],
            )
            result_path = result_root / "telegram-1/task-active.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps({
                "schema_version": 1,
                "request_id": "telegram-1",
                "job_id": "task-active",
                "state": "checkpointed",
                "opencode_session": "ses_forged",
            }), encoding="utf-8")
            advance_clock(seconds)

        result = system_control._checkpoint_runtime(
            policy,
            effect,
            sleep=publish_tampered_result,
            sync=lambda: None,
            monotonic=monotonic,
        )

        assert result["checkpointed_jobs"] == []
        job = json.loads(job_path.read_text())
        assert job["state"] == "interrupted"
        assert job["resume_available"] is False
        assert "opencode_session" not in job


def test_guardian_rejects_checkpoint_results_through_a_symlinked_request_directory():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        job_path = _write_checkpoint_job(
            agent_state, "task-active", "ses_real",
        )
        policy = lifecycle_policy(root / "survival") | {
            "agent_state_path": agent_state,
        }
        effect = {
            "request_id": "telegram-1",
            "idempotency_key": "telegram-1:checkpointing:checkpoint",
        }
        monotonic, advance_clock = _checkpoint_clock()

        def publish_outside_result(seconds):
            _request_root, result_root = checkpoint.checkpoint_paths(
                policy["store_path"], policy["lifecycle_catalog"],
            )
            result_root.mkdir(parents=True, exist_ok=True)
            outside = root / "outside-results"
            outside.mkdir(exist_ok=True)
            (outside / "task-active.json").write_text(json.dumps({
                "schema_version": 1,
                "request_id": "telegram-1",
                "job_id": "task-active",
                "state": "checkpointed",
                "opencode_session": "ses_real",
            }), encoding="utf-8")
            linked = result_root / "telegram-1"
            if not linked.is_symlink():
                linked.symlink_to(outside, target_is_directory=True)
            advance_clock(seconds)

        result = system_control._checkpoint_runtime(
            policy,
            effect,
            sleep=publish_outside_result,
            sync=lambda: None,
            monotonic=monotonic,
        )

        assert result["checkpointed_jobs"] == []
        assert json.loads(job_path.read_text())["state"] == "interrupted"


def test_rebooted_checkpoint_request_expires_without_comparing_monotonic_clocks():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        job_path = _write_checkpoint_job(
            agent_state, "task-active", "ses_active",
        )
        policy = lifecycle_policy(root / "survival") | {
            "agent_state_path": agent_state,
        }
        effect = {
            "request_id": "telegram-1",
            "idempotency_key": "telegram-1:checkpointing:checkpoint",
        }
        request_root, _result_root = checkpoint.checkpoint_paths(
            policy["store_path"], policy["lifecycle_catalog"],
        )
        request_root.mkdir(parents=True, exist_ok=True)
        (request_root / "telegram-1.json").write_text(json.dumps({
            "schema_version": 1,
            "request_id": "telegram-1",
            "job_ids": ["task-active"],
            "requested_at": "2026-09-05T00:00:00+00:00",
            "boot_id": "boot-old",
            "deadline_monotonic": 900000.0,
        }), encoding="utf-8")

        result = system_control._checkpoint_runtime(
            policy,
            effect,
            sleep=lambda _seconds: (_ for _ in ()).throw(
                AssertionError("rebooted deadline must not sleep")
            ),
            sync=lambda: None,
            monotonic=lambda: (_ for _ in ()).throw(
                AssertionError("unrelated monotonic clock must not be read")
            ),
            boot_id=lambda: "boot-new",
        )

        assert result["checkpointed_jobs"] == []
        job = json.loads(job_path.read_text())
        assert job["state"] == "interrupted"
        assert job["resume_available"] is False


def test_fresh_checkpoint_request_without_boot_identity_never_reads_monotonic_clock():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        job_path = _write_checkpoint_job(
            agent_state, "task-active", "ses_unverified",
        )
        policy = lifecycle_policy(root / "survival") | {
            "agent_state_path": agent_state,
        }
        effect = {
            "request_id": "telegram-1",
            "idempotency_key": "telegram-1:checkpointing:checkpoint",
        }

        result = system_control._checkpoint_runtime(
            policy,
            effect,
            sleep=lambda _seconds: (_ for _ in ()).throw(
                AssertionError("unavailable boot must not wait")
            ),
            sync=lambda: None,
            monotonic=lambda: (_ for _ in ()).throw(
                AssertionError("unavailable boot must not read monotonic")
            ),
            boot_id=lambda: None,
        )

        request_root, _result_root = checkpoint.checkpoint_paths(
            policy["store_path"], policy["lifecycle_catalog"],
        )
        request = json.loads(
            (request_root / "telegram-1.json").read_text(encoding="utf-8")
        )
        assert set(request) == checkpoint.CHECKPOINT_REQUEST_FIELDS
        assert request["boot_id"] is None
        assert request["deadline_monotonic"] == 0.0
        assert result == {
            "ok": True,
            "checkpointed_jobs": [],
            "interrupted_jobs": ["task-active"],
        }
        job = json.loads(job_path.read_text(encoding="utf-8"))
        assert job["state"] == "interrupted"
        assert job["resume_available"] is False
        assert "opencode_session" not in job


def test_late_checkpoint_result_cannot_override_an_existing_interruption_intent():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        job_path = _write_checkpoint_job(
            agent_state, "task-active", "ses_late",
        )
        policy = lifecycle_policy(root / "survival") | {
            "agent_state_path": agent_state,
        }
        effect = {
            "request_id": "telegram-1",
            "idempotency_key": "telegram-1:checkpointing:checkpoint",
        }
        request_root, result_root = checkpoint.checkpoint_paths(
            policy["store_path"], policy["lifecycle_catalog"],
        )
        request_root.mkdir(parents=True, exist_ok=True)
        (request_root / "telegram-1.json").write_text(json.dumps({
            "schema_version": 1,
            "request_id": "telegram-1",
            "job_ids": ["task-active"],
            "requested_at": "2026-09-05T00:00:00+00:00",
            "boot_id": "boot-a",
            "deadline_monotonic": 30.0,
        }), encoding="utf-8")
        transition_path = (
            policy["store_path"]
            / "lifecycle-transitions/telegram-1/task-active.json"
        )
        real_atomic_json = system_control.records.atomic_json

        def crash_after_intent(path, value, *arguments, **keywords):
            real_atomic_json(path, value, *arguments, **keywords)
            if (
                Path(path) == transition_path
                and value.get("transition_state") == "intended"
            ):
                raise RuntimeError("simulated death after interruption intent")

        with patch.object(
            system_control.records, "atomic_json", crash_after_intent,
        ):
            with unittest.TestCase().assertRaisesRegex(
                RuntimeError, "death after interruption intent",
            ):
                system_control._interrupt_one_job(
                    policy, "telegram-1", job_path, checkpoint_session=None,
                )
        assert json.loads(job_path.read_text())["state"] == "running"
        assert json.loads(transition_path.read_text())["transition_state"] == "intended"
        result_path = result_root / "telegram-1/task-active.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_text(json.dumps({
            "schema_version": 1,
            "request_id": "telegram-1",
            "job_id": "task-active",
            "state": "checkpointed",
            "opencode_session": "ses_late",
        }), encoding="utf-8")

        result = system_control._checkpoint_runtime(
            policy,
            effect,
            sleep=lambda _seconds: None,
            sync=lambda: None,
            monotonic=lambda: 1.0,
            boot_id=lambda: "boot-a",
        )

        assert result == {
            "ok": True,
            "checkpointed_jobs": [],
            "interrupted_jobs": ["task-active"],
        }
        job = json.loads(job_path.read_text())
        assert job["state"] == "interrupted"
        assert job["resume_available"] is False
        assert "opencode_session" not in job
        assert json.loads(transition_path.read_text())["transition_state"] == "completed"
        assert json.loads(transition_path.read_text())["opencode_session"] is None


def test_load_config_rejects_missing_or_noncanonical_uid():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        environment = guardian_environment(root)
        for name in (
            "GUARDIAN_GATEWAY_UID", "USER_MANAGER_UID", "TIME_CONFIG_PATH",
            "LIFECYCLE_CATALOG_PATH", "AGENT_STATE_DIR",
        ):
            missing = dict(environment)
            del missing[name]
            with unittest.TestCase().assertRaisesRegex(RuntimeError, name):
                system_control.load_production_config(missing)
        for value in ("", "-1", "+991", "0991", "not-a-uid"):
            malformed = dict(environment) | {"GUARDIAN_GATEWAY_UID": value}
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "GUARDIAN_GATEWAY_UID"):
                system_control.load_production_config(malformed)


def test_catalog_has_semantic_stages_and_excludes_survival_units():
    catalog = system_control.load_lifecycle_catalog(
        Path("config/survival-lifecycle.json"),
    )
    assert set(catalog["user_units"]) == {
        "activation_sources", "inference_prerequisites", "control_services",
        "ordinary_services", "inactive_units",
    }
    units = [
        item["unit"]
        for category in catalog["user_units"].values()
        for item in category
    ]
    assert not set(units) & system_control.SURVIVAL_UNITS
    assert "agent-resource-guard.service" in {
        item["unit"] for item in catalog["user_units"]["inactive_units"]
    }


def test_production_constructor_is_complete_and_drives_both_commands():
    for command in ("restart", "reset"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            agent_state = root / "agent-state"
            (agent_state / "jobs").mkdir(parents=True)
            (agent_state / "jobs" / "task-live.json").write_text(json.dumps({
                "id": "task-live",
                "kind": "agent-task",
                "state": "running",
                "opencode_session": "ses_live",
            }), encoding="utf-8")
            catalog = system_control.load_lifecycle_catalog(
                Path("config/survival-lifecycle.json"),
            )
            state = {
                ("system", catalog["backend_unit"]): "active",
            }
            for category, entries in catalog["user_units"].items():
                for entry in entries:
                    state[("user", entry["unit"])] = (
                        "inactive" if category == "inactive_units" else "active"
                    )
            trace = []

            def manager(kind):
                def run(action, unit):
                    trace.append((kind, action, unit))
                    if action == "start":
                        state[(kind, unit)] = "active"
                    elif action in {"stop", "terminate", "kill"}:
                        state[(kind, unit)] = "inactive"
                    return {
                        "ok": True,
                        "action": action,
                        "unit": unit,
                        "state": state[(kind, unit)],
                        "cgroup_empty": state[(kind, unit)] == "inactive",
                    }
                return run

            config = {
                "store_path": root / "survival",
                "agent_state_path": agent_state,
                "user_manager_uid": 1000,
                "lifecycle_catalog": catalog,
                "timing_policy": time_policy.load(Path("config/time.cfg")),
            }
            monotonic, checkpoint_sleep = _checkpoint_clock()
            adapters = system_control.production_adapters(
                config,
                system_adapter=manager("system"),
                user_adapter=manager("user"),
                observe_system=lambda unit: state[("system", unit)],
                observe_user=lambda unit: state[("user", unit)],
                model_probe=lambda _catalog, _deadline: {"ok": True},
                sleep=checkpoint_sleep,
                sync=lambda: None,
                monotonic=monotonic,
            )
            assert set(adapters) == system_control.PRODUCTION_ADAPTER_KINDS

            path = system_control.accept_request(
                config["store_path"], command_record(command), previous_pause=False,
            )
            system_control.commit_acknowledgement(path)
            result = system_control.advance_request(path, adapters, config)

            assert result == {"ok": True, "phase": "completed", "remaining_effects": 0}
            assert state[("system", catalog["backend_unit"])] == "active"
            assert state[("user", "agent-models.service")] == "active"
            assert state[("user", "agent-ecosystem.service")] == "active"
            assert state[("user", "agent-watchdog.service")] == "active"
            assert state[("user", "agent-resource-guard.service")] == "inactive"
            first_activation_stop = next(
                index for index, event in enumerate(trace)
                if event[1:] == ("stop", "agent-ecosystem.path")
            )
            lemonade_stop = trace.index(("system", "stop", catalog["backend_unit"]))
            lemonade_start = trace.index(("system", "start", catalog["backend_unit"]))
            activation_restart = max(
                index for index, event in enumerate(trace)
                if event[1:] == ("start", "agent-ecosystem.path")
            )
            assert first_activation_stop < lemonade_stop < lemonade_start < activation_restart
            job = json.loads(
                (agent_state / "jobs" / "task-live.json").read_text(encoding="utf-8")
            )
            assert job["state"] == "queued"
            assert job["resume_available"] is False
            assert "opencode_session" not in job
            assert not (agent_state / "PAUSED").exists()


def test_production_route_restores_an_initially_inactive_inference_service():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        catalog = system_control.load_lifecycle_catalog(
            Path("config/survival-lifecycle.json"),
        )
        state = {("system", catalog["backend_unit"]): "active"}
        for entries in catalog["user_units"].values():
            for entry in entries:
                state[("user", entry["unit"])] = "inactive"
        trace = []

        def manager(kind):
            def run(action, unit):
                trace.append((kind, action, unit))
                if action == "start":
                    state[(kind, unit)] = "active"
                elif action in {"stop", "terminate", "kill"}:
                    state[(kind, unit)] = "inactive"
                return {
                    "ok": True,
                    "exit_code": 0,
                    "action": action,
                    "unit": unit,
                    "state": state[(kind, unit)],
                    "cgroup_empty": state[(kind, unit)] == "inactive",
                }
            return run

        config = {
            "store_path": root / "survival",
            "agent_state_path": agent_state,
            "user_manager_uid": os.getuid(),
            "lifecycle_catalog": catalog,
            "timing_policy": time_policy.load(Path("config/time.cfg")),
        }
        monotonic, checkpoint_sleep = _checkpoint_clock()
        adapters = system_control.production_adapters(
            config,
            system_adapter=manager("system"),
            user_adapter=manager("user"),
            observe_system=lambda unit: state[("system", unit)],
            observe_user=lambda unit: state[("user", unit)],
            model_probe=lambda _catalog, _deadline: {"ok": True},
            sleep=checkpoint_sleep,
            sync=lambda: None,
            monotonic=monotonic,
        )
        path = system_control.accept_request(
            config["store_path"], command_record("restart"), previous_pause=True,
        )
        system_control.commit_acknowledgement(path)

        result = system_control.advance_request(path, adapters, config)

        model = catalog["user_units"]["inference_prerequisites"][0]["unit"]
        assert result["ok"] is True
        assert state[("user", model)] == "inactive"
        assert (agent_state / "PAUSED").exists()
        start_index = trace.index(("user", "start", model))
        assert any(
            index > start_index and event == ("user", "stop", model)
            for index, event in enumerate(trace)
        )


def test_production_route_turns_over_disposable_real_process_groups():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "agent-state"
        (agent_state / "jobs").mkdir(parents=True)
        catalog = system_control.load_lifecycle_catalog(
            Path("config/survival-lifecycle.json"),
        )
        processes = {}

        def launch(kind, unit):
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            processes[(kind, unit)] = process
            return process

        def observed(kind, unit):
            process = processes.get((kind, unit))
            return "active" if process is not None and process.poll() is None else "inactive"

        def manager(kind):
            def run(action, unit):
                process = processes.get((kind, unit))
                if action == "start" and observed(kind, unit) != "active":
                    process = launch(kind, unit)
                elif action in {"stop", "terminate", "kill"} and process is not None:
                    if process.poll() is None:
                        os.killpg(
                            process.pid,
                            signal.SIGKILL if action == "kill" else signal.SIGTERM,
                        )
                        process.wait(timeout=2)
                state = observed(kind, unit)
                return {
                    "ok": state == ("active" if action == "start" else "inactive"),
                    "exit_code": 0,
                    "action": action,
                    "unit": unit,
                    "state": state,
                    "cgroup_empty": state == "inactive",
                }
            return run

        try:
            backend = launch("system", catalog["backend_unit"])
            for category, entries in catalog["user_units"].items():
                if category == "inactive_units":
                    continue
                for entry in entries:
                    launch("user", entry["unit"])
            config = {
                "store_path": root / "survival",
                "agent_state_path": agent_state,
                "user_manager_uid": os.getuid(),
                "lifecycle_catalog": catalog,
                "timing_policy": time_policy.load(Path("config/time.cfg")),
            }
            monotonic, checkpoint_sleep = _checkpoint_clock()
            adapters = system_control.production_adapters(
                config,
                system_adapter=manager("system"),
                user_adapter=manager("user"),
                observe_system=lambda unit: observed("system", unit),
                observe_user=lambda unit: observed("user", unit),
                model_probe=lambda _catalog, _deadline: {"ok": True},
                sleep=checkpoint_sleep,
                sync=lambda: None,
                monotonic=monotonic,
            )
            for update_id, command in enumerate(("restart", "reset"), start=1):
                original_backend_pid = processes[("system", catalog["backend_unit"])].pid
                original_model_pid = processes[("user", "agent-models.service")].pid
                path = system_control.accept_request(
                    config["store_path"],
                    command_record(command, update_id=update_id),
                    previous_pause=False,
                )
                system_control.commit_acknowledgement(path)
                result = system_control.advance_request(path, adapters, config)
                assert result["ok"] is True
                assert processes[("system", catalog["backend_unit"])].pid != original_backend_pid
                assert processes[("user", "agent-models.service")].pid != original_model_pid
                assert processes[("system", catalog["backend_unit"])].poll() is None
                assert processes[("user", "agent-models.service")].poll() is None
        finally:
            for process in processes.values():
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)


def test_reconciliation_repairs_jobs_control_turns_outbox_and_verification_ownership():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        agent_state = root / "state"
        (agent_state / "jobs").mkdir(parents=True)
        (agent_state / "control-turns").mkdir()
        (agent_state / "verifications").mkdir()
        (agent_state / "jobs/task-running.json").write_text(json.dumps({
            "id": "task-running", "kind": "agent-task", "state": "running",
        }), encoding="utf-8")
        (agent_state / "jobs/outbox-one.json").write_text(json.dumps({
            "id": "outbox-one", "kind": "outbound-message", "state": "sending",
        }), encoding="utf-8")
        (agent_state / "jobs/task-awaiting.json").write_text(json.dumps({
            "id": "task-awaiting", "kind": "agent-task",
            "state": "awaiting_verification",
        }), encoding="utf-8")
        (agent_state / "control-turns/telegram-8.json").write_text(json.dumps({
            "schema_version": 1, "id": "telegram-8", "deep_state": "running",
            "deep_worker_pid": 777, "deep_worker_identity": "old:777:1",
        }), encoding="utf-8")
        config = {
            "store_path": root / "survival",
            "agent_state_path": agent_state,
            "lifecycle_catalog": system_control.load_lifecycle_catalog(
                Path("config/survival-lifecycle.json"),
            ),
            "timing_policy": time_policy.load(Path("config/time.cfg")),
        }
        system_control._write_runtime(config, {
            "schema_version": 1,
            "request_id": "telegram-1",
            "previous_pause": False,
            "previous_active_user_units": [],
            "interrupted_jobs": [],
        })
        result = system_control._reconcile_runtime(config, {
            "request_id": "telegram-1",
        })
        assert result["ok"] is True
        assert json.loads((agent_state / "jobs/task-running.json").read_text())["state"] == "interrupted"
        assert json.loads((agent_state / "jobs/outbox-one.json").read_text())["state"] == "delivery_unknown"
        turn = json.loads((agent_state / "control-turns/telegram-8.json").read_text())
        assert turn["deep_state"] == "queued"
        assert "deep_worker_pid" not in turn
        assert result["awaiting_verifications"] == ["task-awaiting"]


def test_interruption_without_a_verified_checkpoint_discards_raw_handoff_fields():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        state = root / "state"
        logs = root / "logs/runs"
        (state / "jobs").mkdir(parents=True)
        logs.mkdir(parents=True)
        output = logs / "task-live.opencode.log"
        output.write_text('{"sessionID":"ses_durable"}\n', encoding="utf-8")
        job_path = state / "jobs/task-live.json"
        job_path.write_text(json.dumps({
            "id": "task-live",
            "kind": "agent-task",
            "state": "running",
            "output": "logs/runs/task-live.opencode.log",
        }), encoding="utf-8")
        store = root / "survival"
        interrupted = system_control._interrupt_job_records(
            {"agent_state_path": state, "store_path": store},
            {"request_id": "telegram-1"},
            [job_path],
        )
        job = json.loads(job_path.read_text(encoding="utf-8"))
        assert interrupted == ["task-live"]
        assert "opencode_session" not in job
        assert job["resume_available"] is False


def _assert_job_interruption_recovers_across_crash(crash_cut):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = root / "survival"
        agent_state = root / "state"
        jobs = agent_state / "jobs"
        jobs.mkdir(parents=True)
        sessions = {
            "task-alpha": "ses_alpha",
            "task-beta": "ses_beta",
        }
        for job_id, session in sessions.items():
            (jobs / f"{job_id}.json").write_text(json.dumps({
                "id": job_id,
                "kind": "agent-task",
                "state": "running",
                "opencode_session": session,
            }), encoding="utf-8")
        system_control.accept_request(
            store, command_record("reset"), previous_pause=False,
        )
        config = lifecycle_policy(store) | {"agent_state_path": agent_state}
        effect = {
            "request_id": "telegram-1",
            "idempotency_key": "telegram-1:acknowledged:close_admission",
        }
        transition_path = (
            store / "lifecycle-transitions/telegram-1/task-alpha.json"
        )
        first_job_path = jobs / "task-alpha.json"
        real_atomic_json = system_control.records.atomic_json
        crashed = False

        def crash_at_cut(path, value, *arguments, **keywords):
            nonlocal crashed
            path = Path(path)
            is_intent = (
                path == transition_path
                and value.get("transition_state") == "intended"
            )
            is_job_mutation = (
                path == first_job_path
                and value.get("state") == "interrupted"
            )
            is_completion = (
                path == transition_path
                and value.get("transition_state") == "completed"
            )
            matches = {
                "before_intent": is_intent,
                "after_intent": is_intent,
                "after_job_mutation": is_job_mutation,
                "after_completion": is_completion,
            }[crash_cut]
            if matches and not crashed:
                crashed = True
                if crash_cut != "before_intent":
                    real_atomic_json(path, value, *arguments, **keywords)
                raise RuntimeError(f"simulated death {crash_cut}")
            return real_atomic_json(path, value, *arguments, **keywords)

        with patch.object(system_control.records, "atomic_json", crash_at_cut):
            with unittest.TestCase().assertRaisesRegex(RuntimeError, crash_cut):
                system_control._ensure_admission_closed(
                    config, effect, observe_user=lambda _unit: "inactive",
                    sync=lambda: None,
                )

        assert crashed is True
        result = system_control._ensure_admission_closed(
            dict(config), dict(effect), observe_user=lambda _unit: "inactive",
            sync=lambda: None,
        )

        runtime = system_control._read_runtime(config, "telegram-1")
        assert result["ok"] is True
        assert runtime["interrupted_jobs"] == ["task-alpha", "task-beta"]
        for job_id, session in sessions.items():
            job = json.loads((jobs / f"{job_id}.json").read_text(encoding="utf-8"))
            transition = json.loads((
                store / f"lifecycle-transitions/telegram-1/{job_id}.json"
            ).read_text(encoding="utf-8"))
            assert job["state"] == "interrupted"
            assert job["interrupted_by"] == "telegram-1"
            assert "opencode_session" not in job
            assert job["resume_available"] is False
            assert transition == {
                "schema_version": 1,
                "request_id": "telegram-1",
                "job_id": job_id,
                "transition_state": "completed",
                "opencode_session": None,
            }


def test_job_interruption_recovers_after_death_before_transition_intent():
    _assert_job_interruption_recovers_across_crash("before_intent")


def test_job_interruption_recovers_after_death_after_transition_intent():
    _assert_job_interruption_recovers_across_crash("after_intent")


def test_job_interruption_recovers_after_death_after_job_mutation():
    _assert_job_interruption_recovers_across_crash("after_job_mutation")


def test_job_interruption_recovers_after_death_after_transition_completion():
    _assert_job_interruption_recovers_across_crash("after_completion")


def test_job_interruption_rejects_a_boolean_transition_schema_version():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = root / "survival"
        agent_state = root / "state"
        jobs = agent_state / "jobs"
        jobs.mkdir(parents=True)
        (jobs / "task-alpha.json").write_text(json.dumps({
            "id": "task-alpha",
            "kind": "agent-task",
            "state": "interrupted",
            "interrupted_by": "telegram-1",
            "interruption_reason": "survival lifecycle teardown",
            "resume_available": True,
            "opencode_session": "ses_alpha",
        }), encoding="utf-8")
        transition = store / "lifecycle-transitions/telegram-1/task-alpha.json"
        transition.parent.mkdir(parents=True)
        transition.write_text(json.dumps({
            "schema_version": True,
            "request_id": "telegram-1",
            "job_id": "task-alpha",
            "transition_state": "completed",
            "opencode_session": "ses_alpha",
        }), encoding="utf-8")

        with unittest.TestCase().assertRaisesRegex(ValueError, "transition"):
            system_control._derived_interrupted_jobs({
                "store_path": store,
                "agent_state_path": agent_state,
            }, "telegram-1")


def test_job_interruption_rejects_a_non_scalar_transition_state():
    malformed = {
        "schema_version": 1,
        "request_id": "telegram-1",
        "job_id": "task-alpha",
        "transition_state": ["completed"],
        "opencode_session": "ses_alpha",
    }
    with unittest.TestCase().assertRaisesRegex(ValueError, "transition"):
        system_control._validate_job_transition(
            malformed, "telegram-1", "task-alpha",
        )


def test_atomic_result_records_isolate_a_torn_attempt_tail():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = system_control.accept_request(
            root, command_record("reset"), previous_pause=False,
        )
        system_control.commit_acknowledgement(path)
        effect = read_request_state(path)["pending_effects"][0]
        system_control._store_effect_result(path, effect, {"ok": True, "proof": "done"})
        attempt_directory = system_control._effect_result_directory(path, effect["idempotency_key"])
        (attempt_directory / "000002.json").write_text('{"partial":', encoding="utf-8")

        assert system_control._verified_effect_result(
            path, effect["idempotency_key"],
        )["proof"] == "done"
        assert not (attempt_directory / "000002.json").exists()
        assert list((root / "lifecycle-result-quarantine").glob("*.record"))


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions
    )
