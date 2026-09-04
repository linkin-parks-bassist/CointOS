"""Behavioral tests for the permanent survival-plane gateway."""

import builtins
import importlib
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

from survival import gateway, protocol, records, telegram_api


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
            "[heartbeat]",
            f"maximum_age_seconds = {heartbeat_maximum_age}",
            "",
            "[outbox]",
            "poll_seconds = 2",
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


def inbox_record(update_id, state="ready", deadline_at=103.0, extra=None):
    value = {
        "schema_version": 1,
        "id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": 42,
        "chat_id": 42,
        "text": f"message {update_id}",
        "received_at": "2026-09-04T00:00:00+00:00",
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
        assert not (root / "heartbeat.json").exists()


def test_gateway_timing_rejects_nonfinite_values():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "time.cfg"
        write_time_config(path, degraded_deadline="nan")
        with unittest.TestCase().assertRaisesRegex(
            RuntimeError, "telegram.degraded_response_deadline_seconds",
        ):
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


def test_acknowledgement_exception_is_recorded_unknown_and_remains_fatal():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        def fail_send(_chat_id, _text):
            raise ConnectionError("Telegram request failed")

        with unittest.TestCase().assertRaises(ConnectionError):
            gateway.handle_update(
                telegram_update(15, 42, "RESTART"), {42}, root,
                send=fail_send,
                send_command=lambda *_: None,
            )
        assert read_json(root / "acks" / "telegram-15.json")["egress_state"] == "delivery_unknown"


def test_due_degraded_reply_persists_sending_before_https_and_delivered_after():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-20.json"
        write_json(path, inbox_record(20))
        observed = []

        def send(chat_id, text):
            observed.append((chat_id, text, read_json(path)["egress_state"]))
            return True

        count = gateway.send_due_degraded_responses(root, send, now=104.0)
        assert count == 1
        assert observed == [(42, gateway.DEGRADED_REPLY, "sending")]
        assert read_json(path)["egress_state"] == "delivered"


def test_due_degraded_reply_failure_becomes_delivery_unknown_and_is_not_replayed():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-21.json"
        write_json(path, inbox_record(21))
        calls = []
        assert gateway.send_due_degraded_responses(
            root, lambda *args: calls.append(args) or False, now=104.0,
        ) == 1
        assert read_json(path)["egress_state"] == "delivery_unknown"
        assert gateway.send_due_degraded_responses(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")), now=105.0,
        ) == 0
        assert len(calls) == 1


def test_degraded_reply_discovered_sending_becomes_unknown_without_replay():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-22.json"
        write_json(path, inbox_record(22, state="sending"))
        assert gateway.send_due_degraded_responses(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")), now=104.0,
        ) == 1
        assert read_json(path)["egress_state"] == "delivery_unknown"


def test_degraded_scan_quarantines_malformed_json_instead_of_silently_skipping():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-23.json"
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")
        assert gateway.send_due_degraded_responses(root, lambda *_: True, now=104.0) == 0
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
            observed.append((chat_id, text, read_json(path)["egress_state"]))
            return True

        assert gateway.drain_critical_outbox(root, send) == 1
        assert observed == [(42, "critical message", "sending")]
        assert read_json(path)["egress_state"] == "delivered"


def test_critical_false_return_is_unknown_and_never_recursively_requeued():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "outbox" / "critical" / "message-2.json"
        write_json(path, critical_record("message-2"))
        assert gateway.drain_critical_outbox(root, lambda *_: False) == 1
        assert read_json(path)["egress_state"] == "delivery_unknown"
        assert [entry.name for entry in telegram_api.list_critical_outbox(root)] == ["message-2.json"]
        assert gateway.drain_critical_outbox(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")),
        ) == 0


def test_critical_discovered_sending_becomes_unknown_without_replay():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "outbox" / "critical" / "message-3.json"
        write_json(path, critical_record("message-3", state="sending"))
        assert gateway.drain_critical_outbox(
            root, lambda *_: (_ for _ in ()).throw(AssertionError("replayed")),
        ) == 1
        assert read_json(path)["egress_state"] == "delivery_unknown"


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
        assert read_json(root / "heartbeat.json")["monotonic_at"] == 11.0


def test_overall_health_requires_both_fresh_heartbeats():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        gateway.mark_worker_heartbeat(root, "poll", 10.0, 5.0)
        gateway.mark_worker_heartbeat(root, "egress", 11.0, 5.0)
        assert gateway.gateway_is_healthy(root, 12.0, 5.0) is True
        previous = read_json(root / "heartbeat.json")
        gateway.mark_worker_heartbeat(root, "egress", 17.0, 5.0)
        assert gateway.gateway_is_healthy(root, 17.0, 5.0) is False
        assert read_json(root / "heartbeat.json") == previous


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


def test_quarantine_prevents_egress_heartbeat_renewal():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / "inbox" / "telegram-30.json"
        path.parent.mkdir(parents=True)
        path.write_text("bad", encoding="utf-8")
        gateway.egress_child(
            root, lambda *_: True,
            outbox_poll_seconds=0.0,
            heartbeat_maximum_age_seconds=5.0,
            monotonic_now=lambda: 20.0,
            sleep=lambda _seconds: None,
            maximum_iterations=1,
        )
        assert not (root / "heartbeats" / "egress.json").exists()
        assert gateway.check_quarantine_health(root) is False


def test_orphaned_quarantine_payload_is_still_unhealthy():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        directory = root / "quarantine"
        directory.mkdir()
        (directory / "interrupted.record").write_bytes(b"corrupt source")
        assert gateway.check_quarantine_health(root) is False


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
        "/bot123:abc/getUpdates?timeout=25&offset=5", None, {},
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
