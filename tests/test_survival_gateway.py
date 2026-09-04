"""Behavioral tests for the permanent survival-plane gateway."""

import builtins
import importlib
import json
import math
import os
import signal
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from survival import gateway, protocol, records, telegram_api, time_policy


def telegram_update(update_id, user_id, text, chat_id=None):
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": user_id},
            "chat": {"id": user_id if chat_id is None else chat_id},
            "text": text,
        },
    }


def write_time_config(path, degraded_deadline=3, heartbeat_maximum_age=60):
    path.write_text(
        "\n".join((
            "[telegram]",
            "poll_seconds = 1",
            "long_poll_seconds = 25",
            "request_timeout_seconds = 40",
            "command_acknowledgement_deadline_seconds = 2",
            f"degraded_response_deadline_seconds = {degraded_deadline}",
            "",
            "[fast_control]",
            "response_deadline_seconds = 10",
            "maximum_queue_age_seconds = 5",
            "",
            "[inference]",
            "model_stop_deadline_seconds = 15",
            "model_start_deadline_seconds = 180",
            "health_verification_deadline_seconds = 60",
            "",
            "[heartbeat]",
            "probe_period_seconds = 20",
            "probe_deadline_seconds = 15",
            f"maximum_age_seconds = {heartbeat_maximum_age}",
            "guardian_poll_seconds = 5",
            "",
            "[monitor]",
            "activation_period_seconds = 300",
            "stagger_spacing_seconds = 25",
            "run_deadline_seconds = 120",
            "",
            "[repair]",
            "initial_model_deadline_seconds = 180",
            "progress_lease_seconds = 60",
            "progress_update_period_seconds = 60",
            "emergency_model_deadline_seconds = 900",
            "",
            "[resource]",
            "poll_seconds = 1",
            "pressure_confirmation_seconds = 5",
            "emergency_confirmation_seconds = 10",
            "healthy_release_seconds = 60",
            "",
            "[lifecycle]",
            "restart_checkpoint_grace_seconds = 30",
            "service_stop_deadline_seconds = 10",
            "terminate_grace_seconds = 5",
            "kill_grace_seconds = 2",
            "reconciliation_deadline_seconds = 60",
            "progress_update_period_seconds = 30",
            "",
            "[control_turn]",
            "run_deadline_seconds = 600",
            "",
            "[executor]",
            "run_deadline_seconds = 1800",
            "time_slice_seconds = 300",
            "",
            "[verification]",
            "run_deadline_seconds = 900",
            "",
            "[outbox]",
            "poll_seconds = 2",
            "retry_initial_seconds = 5",
            "retry_maximum_seconds = 60",
            "",
        )),
        encoding="utf-8",
    )


def production_environment(root, time_config):
    credentials = root / "credentials"
    credentials.mkdir()
    (credentials / "telegram_bot_token").write_text("123:secret\n", encoding="utf-8")
    allowed = root / "allowed_user_ids"
    allowed.write_text("42\n", encoding="utf-8")
    return {
        "CREDENTIALS_DIRECTORY": str(credentials),
        "GUARDIAN_ALLOWED_USER_IDS_PATH": str(allowed),
        "SURVIVAL_STORE_DIR": str(root / "state"),
        "GUARDIAN_SOCKET_PATH": str(root / "guardian.sock"),
        "TIME_CONFIG_PATH": str(time_config),
    }


def inbox_record(
    update_id,
    state="ready",
    deadline_at=103.0,
    extra=None,
    boot_id="boot-a",
):
    value = {
        "schema_version": 1,
        "id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": 42,
        "chat_id": 42,
        "text": f"message {update_id}",
        "received_at": "2026-09-04T00:00:00+00:00",
        "boot_id": boot_id,
        "accepted_monotonic_at": 100.0,
        "deadline_at": deadline_at,
        "egress_state": state,
    }
    if extra is not None:
        value.update(extra)
    return value


def critical_record(message_id, state="ready", extra=None):
    value = {
        "schema_version": 1,
        "id": message_id,
        "chat_id": 42,
        "text": "critical message",
        "egress_state": state,
    }
    if extra is not None:
        value.update(extra)
    return value


def write_json(path, value):
    records.atomic_json(path, value)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_load_production_config_owns_deadline_from_parsed_time_config():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        time_config = root / "time.cfg"
        write_time_config(time_config, degraded_deadline=7)
        config = gateway.load_production_config(production_environment(root, time_config))
        assert config["degraded_response_deadline_seconds"] == 7.0
        assert config["poll_seconds"] == 1.0
        assert config["long_poll_seconds"] == 25.0
        assert config["request_timeout_seconds"] == 40.0
        assert config["outbox_poll_seconds"] == 2.0
        assert config["heartbeat_maximum_age_seconds"] == 60.0


def test_missing_explicit_config_fails_before_heartbeat():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "CREDENTIALS_DIRECTORY"):
            gateway.load_production_config({})
        assert not (root / "gateway/heartbeat.json").exists()


def test_gateway_timing_rejects_nonfinite_values():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "time.cfg"
        write_time_config(path, degraded_deadline="nan")
        with unittest.TestCase().assertRaisesRegex(
            RuntimeError, "telegram.degraded_response_deadline_seconds",
        ):
            gateway.load_gateway_timing(path)


def test_gateway_timing_rejects_unknown_global_policy_instead_of_parsing_a_subset():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "time.cfg"
        write_time_config(path)
        with path.open("a", encoding="utf-8") as output:
            output.write("\n[unknown]\nperiod_seconds = 1\n")
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "unknown time policy section"):
            gateway.load_gateway_timing(path)


def test_ordinary_message_uses_injected_configured_deadline_without_model_call():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result = gateway.handle_update(
            telegram_update(8, 42, "how is scheduler?"),
            {42},
            root,
            send=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected send")),
            send_command=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected command")),
            monotonic_now=lambda: 100.0,
            degraded_response_deadline_seconds=7.0,
        )
        assert result == {"kind": "ordinary", "id": "telegram-8"}
        stored = read_json(root / "inbox" / "telegram-8.json")
        assert stored["accepted_monotonic_at"] == 100.0
        assert stored["deadline_at"] == 107.0
        assert stored["egress_state"] == "ready"
        assert (root / "inbox" / "telegram-8.json").stat().st_mode & 0o777 == 0o640


def test_ordinary_replay_preserves_existing_egress_state_and_deadline():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        update = telegram_update(9, 42, "hello")
        arguments = {
            "send": lambda *_: None,
            "send_command": lambda *_: None,
            "degraded_response_deadline_seconds": 7.0,
        }
        gateway.handle_update(update, {42}, root, monotonic_now=lambda: 100.0, **arguments)
        path = root / "inbox" / "telegram-9.json"
        value = read_json(path)
        value["egress_state"] = "delivered"
        write_json(path, value)
        gateway.handle_update(update, {42}, root, monotonic_now=lambda: 900.0, **arguments)
        replayed = read_json(path)
        assert replayed["egress_state"] == "delivered"
        assert replayed["deadline_at"] == 107.0


def test_denied_user_creates_only_minimal_audit():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result = gateway.handle_update(
            telegram_update(10, 7, "RESTART"), {42}, root,
            send=lambda *_: None,
            send_command=lambda *_: None,
            degraded_response_deadline_seconds=3.0,
        )
        assert result == {"kind": "denied", "id": "telegram-10"}
        stored = read_json(root / "inbox" / "denied-10.json")
        assert set(stored) == {"schema_version", "telegram_update_id", "telegram_user_id", "chat_id", "state"}
        assert "text" not in stored


def test_command_replay_emits_one_guardian_submission_and_one_acknowledgement():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        submissions = []
        messages = []

        def send_command(command):
            state = read_json(root / "gateway_commands" / "telegram-11.json")
            assert state["egress_state"] == "sending"
            submissions.append(dict(command))

        def send(chat_id, text):
            state = read_json(root / "acks" / "telegram-11.json")
            assert state["egress_state"] == "sending"
            messages.append((chat_id, text))
            return True

        update = telegram_update(11, 42, "RESET")
        first = gateway.handle_update(update, {42}, root, send, send_command)
        second = gateway.handle_update(update, {42}, root, send, send_command)
        assert first == second == {"kind": "command", "id": "telegram-11"}
        assert [entry["request_id"] for entry in submissions] == ["telegram-11"]
        assert messages == [(42, "Reset accepted. I am staying online while the agent system restarts.")]
        accepted = read_json(root / "commands" / "telegram-11.json")
        assert set(accepted) == records.ACCEPTED_UPDATE_FIELDS
        assert read_json(root / "gateway_commands" / "telegram-11.json") == {
            "schema_version": 1,
            "request_id": "telegram-11",
            "egress_state": "delivered",
        }
        assert read_json(root / "acks" / "telegram-11.json") == {
            "schema_version": 1,
            "request_id": "telegram-11",
            "chat_id": 42,
            "text": "Reset accepted. I am staying online while the agent system restarts.",
            "egress_state": "delivered",
        }
        for path in (
            root / "commands" / "telegram-11.json",
            root / "gateway_commands" / "telegram-11.json",
            root / "acks" / "telegram-11.json",
        ):
            assert path.stat().st_mode & 0o777 == 0o600


def test_unknown_guardian_submission_retries_only_same_request_identity():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        request_ids = []

        def send_command(command):
            request_ids.append(command["request_id"])
            if len(request_ids) == 1:
                raise ConnectionError("lost acknowledgement")

        update = telegram_update(12, 42, "RESTART")
        with unittest.TestCase().assertRaises(ConnectionError):
            gateway.handle_update(update, {42}, root, lambda *_: True, send_command)
        assert read_json(root / "gateway_commands" / "telegram-12.json")["egress_state"] == "delivery_unknown"
        gateway.handle_update(update, {42}, root, lambda *_: True, send_command)
        gateway.handle_update(update, {42}, root, lambda *_: True, send_command)
        assert request_ids == ["telegram-12", "telegram-12"]


def test_acknowledgement_discovered_sending_becomes_unknown_without_replay():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        update = telegram_update(13, 42, "RESTART")
        gateway.handle_update(update, {42}, root, lambda *_: True, lambda *_: None)
        ack_path = root / "acks" / "telegram-13.json"
        ack = read_json(ack_path)
        ack["egress_state"] = "sending"
        write_json(ack_path, ack)
        sent = []
        gateway.handle_update(update, {42}, root, lambda *args: sent.append(args), lambda *_: None)
        assert sent == []
        assert read_json(ack_path)["egress_state"] == "delivery_unknown"


def test_acknowledgement_false_return_is_delivery_unknown_not_delivered():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        gateway.handle_update(
            telegram_update(14, 42, "RESTART"), {42}, root,
            send=lambda *_: False,
            send_command=lambda *_: None,
        )
        assert read_json(root / "acks" / "telegram-14.json")["egress_state"] == "delivery_unknown"


def test_acknowledgement_exception_is_recorded_unknown_without_stopping_contact():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        def fail_send(_chat_id, _text):
            raise ConnectionError("Telegram request failed")

        result = gateway.handle_update(
            telegram_update(15, 42, "RESTART"), {42}, root,
            send=fail_send,
            send_command=lambda *_: None,
        )
        assert result == {"kind": "command", "id": "telegram-15"}
        assert read_json(root / "acks" / "telegram-15.json")["egress_state"] == "delivery_unknown"


def test_acknowledgement_uses_its_own_deadline_and_failure_does_not_cancel_command():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        commands = []

        def fail_ack(_chat_id, _text):
            raise TimeoutError("two-second acknowledgement deadline")

        result = gateway.handle_update(
            telegram_update(16, 42, "RESET"),
            {42},
            root,
            send=lambda *_: (_ for _ in ()).throw(AssertionError("generic send used")),
            send_acknowledgement=fail_ack,
            send_command=lambda command: commands.append(command),
        )

        assert result == {"kind": "command", "id": "telegram-16"}
        assert [command["request_id"] for command in commands] == ["telegram-16"]
        assert read_json(root / "acks" / "telegram-16.json")["egress_state"] == "delivery_unknown"


def test_acknowledgement_deadline_is_an_overall_wall_clock_bound():
    release = threading.Event()
    try:
        assert gateway._call_with_deadline(
            lambda: release.wait(1.0) or True,
            0.01,
        ) is False
    finally:
        release.set()


def test_acknowledgement_api_rejection_is_durably_unknown():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        def rejected_send(chat_id, text):
            return telegram_api.send_message(
                "123:abc", chat_id, text, request_timeout=2.0,
                https_exchange=lambda *_args: (200, b'{"ok":false}'),
            )

        assert gateway._deliver_acknowledgement(
            root, "telegram-17", 42, "accepted", rejected_send,
        ) == "delivery_unknown"
        assert read_json(root / "acks/telegram-17.json")["egress_state"] == "delivery_unknown"


def test_due_degraded_reply_persists_sending_before_https_and_delivered_after():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-20.json"
        write_json(path, inbox_record(20))
        observed = []

        def send(chat_id, text):
            observed.append((chat_id, text, read_json(path)["egress_state"]))
            return True

        count = gateway.send_due_degraded_responses(
            root, send, now=104.0, current_boot_id="boot-a",
        )
        assert count == 1
        assert observed == [(42, gateway.DEGRADED_REPLY, "sending")]
        assert read_json(path)["egress_state"] == "delivered"
        assert path.stat().st_mode & 0o777 == 0o640


def test_due_degraded_reply_failure_becomes_delivery_unknown_and_is_not_replayed():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-21.json"
        write_json(path, inbox_record(21))
        calls = []
        assert gateway.send_due_degraded_responses(
            root, lambda *args: calls.append(args) or False, now=104.0,
            current_boot_id="boot-a",
        ) == 1
        assert read_json(path)["egress_state"] == "delivery_unknown"
        assert gateway.send_due_degraded_responses(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")), now=105.0,
            current_boot_id="boot-a",
        ) == 0
        assert len(calls) == 1


def test_degraded_reply_discovered_sending_becomes_unknown_without_replay():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-22.json"
        write_json(path, inbox_record(22, state="sending"))
        assert gateway.send_due_degraded_responses(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")), now=104.0,
            current_boot_id="boot-a",
        ) == 1
        assert read_json(path)["egress_state"] == "delivery_unknown"


def test_degraded_scan_quarantines_malformed_json_instead_of_silently_skipping():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-23.json"
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        assert gateway.send_due_degraded_responses(
            root, lambda *_: True, now=104.0, current_boot_id="boot-a",
        ) == 0
        assert not path.exists()
        errors = telegram_api.list_quarantine_errors(root)
        assert len(errors) == 1
        assert read_json(errors[0])["error_reason"] == "invalid inbox JSON"
        assert gateway.check_quarantine_health(root) is False


def test_degraded_scan_quarantines_extra_fields_before_delivery():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-24.json"
        write_json(path, inbox_record(24, extra={"unexpected": True}))
        assert gateway.send_due_degraded_responses(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("malformed delivery")), now=104.0,
            current_boot_id="boot-a",
        ) == 0
        assert not path.exists()
        assert len(telegram_api.list_quarantine_errors(root)) == 1


def test_nonfinite_persisted_deadline_is_quarantined_before_egress():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox/telegram-25.json"
        write_json(path, inbox_record(25, deadline_at=math.inf))
        assert gateway.send_due_degraded_responses(
            root,
            lambda *_: (_ for _ in ()).throw(AssertionError("nonfinite delivery")),
            now=104.0,
            current_boot_id="boot-a",
        ) == 0
        assert not path.exists()
        assert len(telegram_api.list_quarantine_errors(root)) == 1


def test_critical_outbox_is_exact_and_crash_truthful():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "outbox" / "critical" / "message-1.json"
        write_json(path, critical_record("message-1"))
        observed = []

        def send(chat_id, text):
            delivery = root / "gateway/critical-delivery/message-1.json"
            attempt = root / "gateway/critical-attempts/message-1.json"
            observed.append((
                chat_id,
                text,
                read_json(delivery)["egress_state"],
                read_json(attempt),
            ))
            return True

        assert gateway.drain_critical_outbox(root, send) == 1
        assert observed == [(
            42,
            "critical message",
            "sending",
            {
                "schema_version": 1,
                "message_id": "message-1",
                "attempt_observed": True,
            },
        )]
        assert read_json(path)["egress_state"] == "ready"
        assert read_json(
            root / "gateway/critical-delivery/message-1.json"
        )["egress_state"] == "delivered"
        assert (
            root / "gateway/critical-attempts/message-1.json"
        ).stat().st_mode & 0o777 == 0o600


def test_missing_delivery_after_observed_attempt_becomes_unknown_without_replay():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "outbox/critical/message-missing.json"
        write_json(source, critical_record("message-missing"))
        assert gateway.drain_critical_outbox(root, lambda *_: True) == 1
        delivery = root / "gateway/critical-delivery/message-missing.json"
        delivery.unlink()

        assert gateway.drain_critical_outbox(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")),
        ) == 0
        assert read_json(delivery)["egress_state"] == "delivery_unknown"
        with unittest.TestCase().assertRaisesRegex(ValueError, "terminal"):
            telegram_api.update_critical_delivery_state(delivery, "ready")
        incidents = list((root / "gateway/delivery-health-incidents").glob(
            "critical-delivery-*.json",
        ))
        assert len(incidents) == 1


def test_corrupt_or_quarantined_delivery_after_attempt_never_replays():
    for damage in ("corrupt", "quarantined"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "outbox/critical/message-damaged.json"
            write_json(source, critical_record("message-damaged"))
            assert gateway.drain_critical_outbox(root, lambda *_: True) == 1
            delivery = root / "gateway/critical-delivery/message-damaged.json"
            if damage == "corrupt":
                delivery.write_text("{broken", encoding="utf-8")
            else:
                quarantine = root / "quarantine/prior-delivery.record"
                quarantine.parent.mkdir(parents=True)
                delivery.replace(quarantine)

            assert gateway.drain_critical_outbox(
                root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")),
            ) == 0
            assert read_json(delivery)["egress_state"] == "delivery_unknown"


def test_corruption_before_any_attempt_is_quarantined_then_delivered_once():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "outbox/critical/message-pre-attempt.json"
        delivery = root / "gateway/critical-delivery/message-pre-attempt.json"
        write_json(source, critical_record("message-pre-attempt"))
        delivery.parent.mkdir(parents=True)
        delivery.write_text("{broken", encoding="utf-8")
        sent = []

        assert gateway.drain_critical_outbox(
            root, lambda *arguments: sent.append(arguments) or True,
        ) == 1
        assert sent == [(42, "critical message")]
        assert read_json(delivery)["egress_state"] == "delivered"
        assert (root / "gateway/critical-attempts/message-pre-attempt.json").exists()


def test_crash_after_attempt_observation_cannot_revert_delivery_to_ready():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "outbox/critical/message-crash.json"
        write_json(source, critical_record("message-crash"))
        real_update = telegram_api.update_critical_delivery_state

        def crash_before_sending(path, state):
            if state == "sending":
                assert read_json(
                    root / "gateway/critical-attempts/message-crash.json"
                )["attempt_observed"] is True
                raise OSError("simulated death after attempt observation")
            return real_update(path, state)

        with patch.object(
            telegram_api, "update_critical_delivery_state", crash_before_sending,
        ):
            with unittest.TestCase().assertRaisesRegex(OSError, "simulated death"):
                gateway.drain_critical_outbox(root, lambda *_: True)

        assert gateway.drain_critical_outbox(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")),
        ) == 0
        assert read_json(
            root / "gateway/critical-delivery/message-crash.json"
        )["egress_state"] == "delivery_unknown"


def test_guardian_critical_message_is_group_readable_but_immutable_to_gateway():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        value = critical_record("message-shared")
        telegram_api.store_critical_outbox_entry(root, value)
        path = root / "outbox" / "critical" / "message-shared.json"
        assert path.stat().st_mode & 0o777 == 0o640
        telegram_api.ensure_critical_delivery(root, "message-shared")
        delivery = root / "gateway/critical-delivery/message-shared.json"
        telegram_api.update_critical_delivery_state(delivery, "sending")
        telegram_api.update_critical_delivery_state(delivery, "delivered")
        assert read_json(path)["egress_state"] == "ready"
        assert read_json(delivery)["egress_state"] == "delivered"
        assert delivery.stat().st_mode & 0o777 == 0o600


def test_critical_false_return_is_unknown_and_never_recursively_requeued():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "outbox" / "critical" / "message-2.json"
        write_json(path, critical_record("message-2"))
        assert gateway.drain_critical_outbox(root, lambda *_: False) == 1
        assert read_json(path)["egress_state"] == "ready"
        assert read_json(
            root / "gateway/critical-delivery/message-2.json"
        )["egress_state"] == "delivery_unknown"
        assert [entry.name for entry in telegram_api.list_critical_outbox(root)] == ["message-2.json"]
        assert len(list((root / "gateway/delivery-health-incidents").glob(
            "critical-delivery-*.json",
        ))) == 1
        assert gateway.drain_critical_outbox(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")),
        ) == 0


def test_critical_send_exception_records_local_uncertainty_before_worker_exit():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "outbox/critical/message-exception.json"
        write_json(source, critical_record("message-exception"))

        with unittest.TestCase().assertRaisesRegex(ConnectionError, "Telegram unavailable"):
            gateway.drain_critical_outbox(
                root,
                lambda *_: (_ for _ in ()).throw(
                    ConnectionError("Telegram unavailable")
                ),
            )

        assert read_json(
            root / "gateway/critical-delivery/message-exception.json"
        )["egress_state"] == "delivery_unknown"
        assert len(list((root / "gateway/delivery-health-incidents").glob(
            "critical-delivery-*.json",
        ))) == 1


def test_critical_discovered_sending_becomes_unknown_without_replay():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "outbox" / "critical" / "message-3.json"
        write_json(path, critical_record("message-3", state="sending"))
        assert gateway.drain_critical_outbox(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")),
        ) == 1
        assert read_json(path)["egress_state"] == "sending"
        assert read_json(
            root / "gateway/critical-delivery/message-3.json"
        )["egress_state"] == "delivery_unknown"


def test_critical_scan_quarantines_nonexact_record():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "outbox" / "critical" / "message-4.json"
        write_json(path, critical_record("message-4", extra={"unexpected": True}))
        assert gateway.drain_critical_outbox(root, lambda *_: True) == 0
        assert not path.exists()
        assert len(telegram_api.list_quarantine_errors(root)) == 1


def test_poll_and_egress_workers_renew_independent_heartbeats():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        gateway.poll_child(
            root, {42}, lambda *_: True, lambda *_: None,
            degraded_response_deadline_seconds=3.0,
            poll_seconds=0.0,
            long_poll_seconds=25.0,
            request_timeout_seconds=40.0,
            heartbeat_maximum_age_seconds=5.0,
            get_updates=lambda **_kwargs: [],
            monotonic_now=lambda: 10.0,
            sleep=lambda _seconds: None,
            maximum_iterations=1,
        )
        assert read_json(root / "heartbeats" / "poll.json")["monotonic_at"] == 10.0
        assert not (root / "heartbeat.json").exists()
        gateway.egress_child(
            root, lambda *_: True,
            outbox_poll_seconds=0.0,
            heartbeat_maximum_age_seconds=5.0,
            monotonic_now=lambda: 11.0,
            sleep=lambda _seconds: None,
            maximum_iterations=1,
        )
        assert read_json(root / "heartbeats" / "egress.json")["monotonic_at"] == 11.0
        assert gateway.gateway_is_healthy(root, 12.0, 5.0) is True
        assert read_json(root / "gateway/heartbeat.json")["monotonic_at"] == 11.0
        for path in (
            root / "heartbeats" / "poll.json",
            root / "heartbeats" / "egress.json",
            root / "gateway/heartbeat.json",
        ):
            assert path.stat().st_mode & 0o777 == 0o600


def test_overall_health_requires_both_fresh_heartbeats():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        gateway.mark_worker_heartbeat(root, "poll", 10.0, 5.0)
        gateway.mark_worker_heartbeat(root, "egress", 11.0, 5.0)
        assert gateway.gateway_is_healthy(root, 12.0, 5.0) is True
        previous = read_json(root / "gateway/heartbeat.json")
        gateway.mark_worker_heartbeat(root, "egress", 17.0, 5.0)
        assert gateway.gateway_is_healthy(root, 17.0, 5.0) is False
        assert read_json(root / "gateway/heartbeat.json") == previous


def test_fatal_poll_error_propagates_and_does_not_renew_poll_heartbeat():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        def fail_poll(**_kwargs):
            raise ConnectionError("Telegram unavailable")

        with unittest.TestCase().assertRaises(ConnectionError):
            gateway.poll_child(
                root, {42}, lambda *_: True, lambda *_: None,
                degraded_response_deadline_seconds=3.0,
                poll_seconds=0.0,
                long_poll_seconds=25.0,
                request_timeout_seconds=40.0,
                heartbeat_maximum_age_seconds=5.0,
                get_updates=fail_poll,
                monotonic_now=lambda: 10.0,
                sleep=lambda _seconds: None,
                maximum_iterations=1,
            )
        assert not (root / "heartbeats" / "poll.json").exists()


def test_quarantine_degrades_data_health_without_stopping_egress_heartbeat():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-30.json"
        path.parent.mkdir(parents=True)
        path.write_text("bad", encoding="utf-8")
        gateway.egress_child(
            root, lambda *_: True,
            allowed={42},
            outbox_poll_seconds=0.0,
            heartbeat_maximum_age_seconds=5.0,
            monotonic_now=lambda: 20.0,
            boot_id=lambda: "boot-a",
            sleep=lambda _seconds: None,
            maximum_iterations=1,
        )
        assert read_json(root / "heartbeats" / "egress.json")["monotonic_at"] == 20.0
        assert gateway.check_quarantine_health(root) is False


def test_unmovable_malformed_record_does_not_withhold_egress_heartbeat():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox/telegram-29.json"
        path.parent.mkdir(parents=True)
        path.write_text("bad", encoding="utf-8")
        original_quarantine = telegram_api.quarantine_record
        telegram_api.quarantine_record = lambda *_args: False
        try:
            gateway.egress_child(
                root, lambda *_: True,
                outbox_poll_seconds=0.0,
                heartbeat_maximum_age_seconds=5.0,
                monotonic_now=lambda: 20.0,
                boot_id=lambda: "boot-a",
                sleep=lambda _seconds: None,
                maximum_iterations=1,
            )
        finally:
            telegram_api.quarantine_record = original_quarantine
        assert path.exists()
        assert read_json(root / "heartbeats/egress.json")["monotonic_at"] == 20.0


def test_unmovable_quarantine_incident_is_deduplicated_and_visible():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox/telegram-28.json"
        path.parent.mkdir(parents=True)
        path.write_text("bad", encoding="utf-8")
        with patch.object(
            telegram_api, "_replace_record", side_effect=PermissionError("read-only source"),
        ):
            assert telegram_api.quarantine_record(root, path, "invalid inbox JSON") is False
            assert telegram_api.quarantine_record(root, path, "invalid inbox JSON") is False
        assert len(telegram_api.list_quarantine_errors(root)) == 1
        health = read_json(root / "gateway/data-health.json")
        assert health["state"] == "degraded"
        assert health["quarantine_succeeded"] is False


def test_boot_id_read_failure_does_not_crash_poll_or_egress():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        updates = [telegram_update(32, 42, "ordinary")]

        def fail_boot_id():
            raise RuntimeError("proc unavailable")

        gateway.poll_child(
            root, {42}, lambda *_: True, lambda *_: None,
            degraded_response_deadline_seconds=3.0,
            poll_seconds=0.0,
            long_poll_seconds=25.0,
            request_timeout_seconds=40.0,
            heartbeat_maximum_age_seconds=5.0,
            get_updates=lambda **_arguments: updates,
            monotonic_now=lambda: 20.0,
            boot_id=fail_boot_id,
            maximum_iterations=1,
        )
        assert read_json(root / "inbox/telegram-32.json")["boot_id"] is None
        sent = []
        gateway.egress_child(
            root, lambda *arguments: sent.append(arguments) or True,
            outbox_poll_seconds=0.0,
            heartbeat_maximum_age_seconds=5.0,
            monotonic_now=lambda: 20.1,
            boot_id=fail_boot_id,
            maximum_iterations=1,
        )
        assert sent == [(42, gateway.DEGRADED_REPLY)]
        assert read_json(root / "heartbeats/egress.json")["monotonic_at"] == 20.1


def test_orphaned_quarantine_payload_is_still_unhealthy():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        directory = root / "quarantine"
        directory.mkdir()
        (directory / "interrupted.record").write_bytes(b"corrupt source")
        assert gateway.check_quarantine_health(root) is False


def test_rebooted_monotonic_deadline_is_immediately_due():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-31.json"
        write_json(path, inbox_record(31, deadline_at=900000.0, boot_id="old-boot"))
        sent = []

        assert gateway.send_due_degraded_responses(
            root,
            lambda *arguments: sent.append(arguments) or True,
            now=1.0,
            current_boot_id="new-boot",
        ) == 1
        assert sent == [(42, gateway.DEGRADED_REPLY)]
        assert read_json(path)["egress_state"] == "delivered"


def test_unsupported_update_is_disposed_and_later_command_is_received():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        submissions = []
        batches = iter(([
            {"update_id": 40, "callback_query": {"id": "callback"}},
            telegram_update(41, 42, "RESTART"),
        ],))

        gateway.poll_child(
            root,
            {42},
            lambda *_: True,
            lambda command: submissions.append(command),
            degraded_response_deadline_seconds=3.0,
            poll_seconds=0.0,
            long_poll_seconds=25.0,
            request_timeout_seconds=40.0,
            heartbeat_maximum_age_seconds=5.0,
            get_updates=lambda **_arguments: next(batches),
            monotonic_now=lambda: 10.0,
            boot_id=lambda: "boot-a",
            sleep=lambda _seconds: None,
            maximum_iterations=1,
        )

        assert [command["request_id"] for command in submissions] == ["telegram-41"]
        assert read_json(root / "dispositions" / "telegram-40.json") == {
            "schema_version": 1,
            "telegram_update_id": 40,
            "state": "ignored",
            "reason": "unsupported Telegram update",
        }


def test_all_identified_non_message_shapes_are_disposed_and_offset_survives_restart():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        unsupported = [
            {"update_id": 50, "callback_query": {"id": "callback"}},
            {"update_id": 51, "channel_post": {"text": "channel"}},
            {"update_id": 52, "edited_message": {"text": "edited"}},
            {"update_id": 53, "message": {"chat": {"id": 42}}},
        ]
        observed_offsets = []

        gateway.poll_child(
            root, {42}, lambda *_: True, lambda *_: None,
            degraded_response_deadline_seconds=3.0,
            poll_seconds=0.0,
            long_poll_seconds=25.0,
            request_timeout_seconds=40.0,
            heartbeat_maximum_age_seconds=5.0,
            get_updates=lambda **arguments: (
                observed_offsets.append(arguments["offset"]) or unsupported
            ),
            monotonic_now=lambda: 10.0,
            boot_id=lambda: "boot-a",
            maximum_iterations=1,
        )
        gateway.poll_child(
            root, {42}, lambda *_: True, lambda *_: None,
            degraded_response_deadline_seconds=3.0,
            poll_seconds=0.0,
            long_poll_seconds=25.0,
            request_timeout_seconds=40.0,
            heartbeat_maximum_age_seconds=5.0,
            get_updates=lambda **arguments: (
                observed_offsets.append(arguments["offset"]) or []
            ),
            monotonic_now=lambda: 11.0,
            boot_id=lambda: "boot-a",
            maximum_iterations=1,
        )
        assert observed_offsets == [None, 54]
        assert sorted(path.stem for path in (root / "dispositions").glob("*.json")) == [
            "telegram-50", "telegram-51", "telegram-52", "telegram-53",
        ]


def test_http_200_non_json_response_is_explicit_failure():
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "invalid Telegram response"):
        telegram_api.get_updates(
            "123:abc", offset=None, timeout=25.0, request_timeout=40.0,
            https_exchange=lambda *_args: (200, b"not-json"),
        )


def test_main_behaviorally_tracks_two_successive_replacements_per_role():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fork_results = iter((100, 200, 101, 201, 102, 202))
        deaths = iter((100, 200, 101, 201))
        fork_calls = []
        wait_calls = []

        def fork():
            fork_calls.append(True)
            return next(fork_results)

        def waitpid(pid, options):
            wait_calls.append((pid, options))
            try:
                return next(deaths), 0
            except StopIteration as error:
                raise ChildProcessError from error

        tracked = gateway.main(
            root, {42}, lambda *_: True, lambda *_: None,
            degraded_response_deadline_seconds=3.0,
            poll_seconds=1.0,
            long_poll_seconds=25.0,
            request_timeout_seconds=40.0,
            outbox_poll_seconds=2.0,
            heartbeat_maximum_age_seconds=60.0,
            fork=fork,
            waitpid=waitpid,
            install_signal_handlers=lambda: None,
        )
        assert len(fork_calls) == 6
        assert wait_calls == [(-1, 0), (-1, 0), (-1, 0), (-1, 0), (-1, 0)]
        assert tracked == {"poll": 102, "egress": 202}


def test_gateway_supervisor_applies_live_heartbeat_age_policy():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        telegram_api.write_worker_heartbeat(root, "poll", 50.0)
        telegram_api.write_worker_heartbeat(root, "egress", 50.0)
        handlers = {}
        notifications = []

        def install_handler(number, handler):
            previous = handlers.get(number, signal.SIG_DFL)
            handlers[number] = handler
            return previous

        def waitpid(_pid, _options):
            handlers[signal.SIGUSR1](signal.SIGUSR1, None)
            raise ChildProcessError

        with (
            patch.object(gateway.signal, "signal", side_effect=install_handler),
            patch.object(gateway.time, "monotonic", return_value=100.0),
            patch.object(
                gateway.systemd_notify,
                "notify_systemd",
                side_effect=lambda value: notifications.append(value),
            ),
        ):
            gateway.main(
                root, {42}, lambda *_: True, lambda *_: None,
                degraded_response_deadline_seconds=3.0,
                poll_seconds=1.0,
                long_poll_seconds=25.0,
                request_timeout_seconds=40.0,
                outbox_poll_seconds=2.0,
                heartbeat_maximum_age_seconds=1.0,
                fork=lambda: 100,
                waitpid=waitpid,
                install_signal_handlers=lambda: None,
                reload_timing=lambda: {"heartbeat_maximum_age_seconds": 60.0},
            )

        assert notifications == ["READY=1", "WATCHDOG=1"]


def test_send_message_exercises_https_encoding_through_injected_exchange():
    calls = []

    def exchange(host, timeout, method, path, body, headers):
        calls.append((host, timeout, method, path, body, headers))
        return 200, b'{"ok":true,"result":{"message_id":9}}'

    assert telegram_api.send_message(
        "123:abc", 42, "hello", request_timeout=7.0, https_exchange=exchange,
    ) is True
    host, timeout, method, path, body, headers = calls[0]
    assert (host, timeout, method, path) == (
        "api.telegram.org", 7.0, "POST", "/bot123:abc/sendMessage",
    )
    assert json.loads(body) == {"chat_id": 42, "text": "hello"}
    assert headers == {"Content-Type": "application/json"}


def test_get_updates_exercises_https_long_poll_through_injected_exchange():
    calls = []

    def exchange(host, timeout, method, path, body, headers):
        calls.append((host, timeout, method, path, body, headers))
        return 200, b'{"ok":true,"result":[{"update_id":7}]}'

    updates = telegram_api.get_updates(
        "123:abc", offset=5, timeout=25.0, request_timeout=40.0,
        https_exchange=exchange,
    )
    assert updates == [{"update_id": 7}]
    assert calls == [(
        "api.telegram.org", 40.0, "GET",
        "/bot123:abc/getUpdates?timeout=25&offset=5&allowed_updates=%5B%22message%22%5D", None, {},
    )]


def test_telegram_api_failure_is_explicit_not_a_false_success():
    def exchange(*_args):
        return 500, b'{"ok":false,"description":"down"}'

    with unittest.TestCase().assertRaisesRegex(RuntimeError, "Telegram"):
        telegram_api.send_message(
            "123:abc", 42, "hello", request_timeout=7.0,
            https_exchange=exchange,
        )


def test_production_send_adapter_never_recursively_creates_a_ready_record():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        time_config = root / "time.cfg"
        write_time_config(time_config)
        environment = production_environment(root, time_config)
        https_calls = []

        def send_message(bot_token, chat_id, text, request_timeout):
            https_calls.append((bot_token, chat_id, text, request_timeout))
            return False

        def run_main(_store, _allowed, send, _send_command, **_arguments):
            assert send(42, "message") is False

        gateway.run_production(
            environment,
            send_message=send_message,
            submit_to_guardian=lambda *_args, **_kwargs: None,
            get_updates_api=lambda *_args, **_kwargs: [],
            run_main=run_main,
        )
        assert https_calls == [("123:secret", 42, "message", 40.0)]
        assert telegram_api.list_critical_outbox(root / "state") == []


def test_production_acknowledgement_adapter_uses_command_deadline():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        time_config = root / "time.cfg"
        write_time_config(time_config)
        environment = production_environment(root, time_config)
        calls = []

        def send_message(bot_token, chat_id, text, request_timeout):
            calls.append((bot_token, chat_id, text, request_timeout))
            return True

        def run_main(_store, _allowed, _send, _send_command, **arguments):
            arguments["send_acknowledgement"](42, "ack")

        gateway.run_production(
            environment,
            send_message=send_message,
            submit_to_guardian=lambda *_args, **_kwargs: None,
            get_updates_api=lambda *_args, **_kwargs: [],
            run_main=run_main,
        )
        assert calls == [("123:secret", 42, "ack", 2.0)]


def test_production_gateway_live_reload_adopts_complete_policy_and_retains_invalid_edit():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        time_config = root / "time.cfg"
        write_time_config(time_config)
        environment = production_environment(root, time_config)
        calls = []

        def send_message(_token, _chat_id, _text, request_timeout):
            calls.append(request_timeout)
            return True

        def run_main(_store, _allowed, _send, _send_command, **arguments):
            write_time_config(time_config)
            text = time_config.read_text(encoding="utf-8").replace(
                "command_acknowledgement_deadline_seconds = 2",
                "command_acknowledgement_deadline_seconds = 1.5",
            )
            time_config.write_text(text, encoding="utf-8")
            arguments["reload_timing"]()
            arguments["send_acknowledgement"](42, "ack")
            time_config.write_text("[telegram]\nbroken = yes\n", encoding="utf-8")
            arguments["reload_timing"]()
            arguments["send_acknowledgement"](42, "ack")

        gateway.run_production(
            environment,
            send_message=send_message,
            submit_to_guardian=lambda *_args, **_kwargs: None,
            get_updates_api=lambda *_args, **_kwargs: [],
            run_main=run_main,
        )
        assert calls == [1.5, 1.5]
        status = read_json(root / "state/gateway/time-policy-status.json")
        assert status["state"] == "rejected"
        assert "unknown time policy" in status["error"]


def test_gateway_restart_uses_guardian_last_known_good_when_mutable_source_is_invalid():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        time_config = root / "time.cfg"
        write_time_config(time_config)
        environment = production_environment(root, time_config)
        accepted = root / "state/policy/time.json"
        time_policy.adopt_last_known_good(time_config, accepted)
        time_config.write_text("[telegram]\nbroken = yes\n", encoding="utf-8")
        config = gateway.load_production_config(environment)
        assert config["command_acknowledgement_deadline_seconds"] == 2.0
        assert accepted.stat().st_mode & 0o777 == 0o640
        gateway.refresh_gateway_timing(config)
        status = read_json(root / "state/gateway/time-policy-status.json")
        assert status["state"] == "rejected"


def receive_exact(connection, size):
    chunks = []
    received = 0
    while received < size:
        chunk = connection.recv(size - received)
        if not chunk:
            raise RuntimeError("unexpected socket EOF")
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)


def test_submit_to_guardian_uses_real_unix_socket_and_typed_framing():
    with tempfile.TemporaryDirectory() as temporary:
        socket_path = str(Path(temporary) / "guardian.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(socket_path)
        listener.listen(1)
        pid = os.fork()
        if pid == 0:
            try:
                connection, _address = listener.accept()
                with connection:
                    size = int.from_bytes(receive_exact(connection, 4), "big")
                    command = protocol.decode_command(receive_exact(connection, size))
                    response = json.dumps({
                        "schema_version": 1,
                        "request_id": command["request_id"],
                        "status": "accepted",
                    }, separators=(",", ":")).encode("utf-8")
                    connection.sendall(len(response).to_bytes(4, "big") + response)
                os._exit(0)
            except BaseException:
                os._exit(1)
        command = {
            "schema_version": 1,
            "request_id": "telegram-40",
            "telegram_update_id": 40,
            "telegram_user_id": 42,
            "command": "restart",
            "received_at": "2026-09-04T00:00:00+00:00",
        }
        try:
            acknowledgement = telegram_api.submit_to_guardian(
                socket_path, command, timeout=2.0,
            )
        finally:
            listener.close()
        child_pid, status = os.waitpid(pid, 0)
        assert child_pid == pid
        assert os.waitstatus_to_exitcode(status) == 0
        assert acknowledgement == {
            "schema_version": 1,
            "request_id": "telegram-40",
            "status": "accepted",
        }


def test_guardian_acknowledgement_deadline_bounds_a_dribbling_frame():
    with tempfile.TemporaryDirectory() as temporary:
        socket_path = str(Path(temporary) / "guardian.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(socket_path)
        listener.listen(1)
        command = {
            "schema_version": 1,
            "request_id": "telegram-41",
            "telegram_update_id": 41,
            "telegram_user_id": 42,
            "command": "restart",
            "received_at": "2026-09-04T00:00:00+00:00",
        }

        def serve():
            connection, _address = listener.accept()
            try:
                request_size = int.from_bytes(receive_exact(connection, 4), "big")
                receive_exact(connection, request_size)
                response = json.dumps({
                    "schema_version": 1,
                    "request_id": "telegram-41",
                    "status": "accepted",
                }, separators=(",", ":")).encode("utf-8")
                frame = len(response).to_bytes(4, "big") + response
                for byte in frame:
                    time.sleep(0.01)
                    connection.sendall(bytes((byte,)))
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                connection.close()

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        try:
            with unittest.TestCase().assertRaises(TimeoutError):
                telegram_api.submit_to_guardian(socket_path, command, timeout=0.05)
        finally:
            listener.close()
            server.join(1.0)


def test_gateway_import_succeeds_when_ecosystem_imports_are_forbidden():
    survival_package = importlib.import_module("survival")
    previous_module = sys.modules.pop("survival.gateway", None)
    previous_attribute = getattr(survival_package, "gateway", None)
    if hasattr(survival_package, "gateway"):
        delattr(survival_package, "gateway")
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "ecosystem" or name.startswith("ecosystem."):
            raise AssertionError(f"forbidden mutable import: {name}")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = guarded_import
    try:
        imported = importlib.import_module("survival.gateway")
        assert callable(imported.handle_update)
    finally:
        builtins.__import__ = original_import
        sys.modules.pop("survival.gateway", None)
        if previous_module is not None:
            sys.modules["survival.gateway"] = previous_module
        if previous_attribute is not None:
            survival_package.gateway = previous_attribute


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
