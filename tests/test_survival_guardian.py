"""Behavioral tests for guardian authentication, framing, and lifecycle dispatch."""

import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from survival import guardian, telegram_api


def command_record(command="restart", update_id=42):
    return {
        "schema_version": 1,
        "request_id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": 42,
        "command": command,
        "received_at": "2026-09-04T00:00:00+00:00",
    }


def send_framed(connection, data):
    encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
    connection.sendall(len(encoded).to_bytes(4, "big") + encoded)


def receive_exact(connection, size):
    payload = bytearray()
    while len(payload) < size:
        chunk = connection.recv(size - len(payload))
        if not chunk:
            raise ConnectionError("unexpected socket EOF")
        payload.extend(chunk)
    return bytes(payload)


def receive_framed(connection):
    size = int.from_bytes(receive_exact(connection, 4), "big")
    return json.loads(receive_exact(connection, size))


def successful_adapters(events=None):
    if events is None:
        events = []

    def manager(name):
        def run(action, unit):
            events.append((name, action, unit))
            return {"ok": True, "action": action, "unit": unit}

        return run

    def direct(kind):
        def run(_effect, _policy):
            events.append((kind,))
            return {"ok": True, "operation": kind}

        return run

    adapters = {"system": manager("system"), "user": manager("user")}
    for kind in (
        "notify", "close_admission", "checkpoint", "reconcile", "verify",
        "resume", "finish",
    ):
        adapters[kind] = direct(kind)
    return adapters


def guardian_config(root, adapters=None):
    if adapters is None:
        adapters = successful_adapters()
    return {
        "socket_path": str(root / "guardian.sock"),
        "store_path": root / "state",
        "gateway_uid": os.getuid(),
        "user_manager_uid": os.getuid(),
        "adapters": adapters,
    }


def test_peer_uid_uses_unix_peer_credentials():
    guardian_end, client_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        assert guardian.peer_uid(guardian_end) == os.getuid()
    finally:
        guardian_end.close()
        client_end.close()


def test_only_gateway_uid_is_authorized():
    guardian.authorize_peer(991, gateway_uid=991)
    with unittest.TestCase().assertRaises(PermissionError):
        guardian.authorize_peer(1000, gateway_uid=991)


def test_send_framed_uses_four_byte_big_endian_length():
    guardian_end, client_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        acknowledgement = {
            "schema_version": 1,
            "request_id": "telegram-42",
            "status": "accepted",
        }
        assert guardian._send_framed(guardian_end, acknowledgement) is True
        header = receive_exact(client_end, 4)
        payload = receive_exact(client_end, int.from_bytes(header, "big"))
        assert header == len(payload).to_bytes(4, "big")
        assert json.loads(payload) == acknowledgement
    finally:
        guardian_end.close()
        client_end.close()


def test_send_framed_rejects_oversize_json_instead_of_truncating_it():
    guardian_end, client_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        with unittest.TestCase().assertRaisesRegex(ValueError, "response size"):
            guardian._send_framed(guardian_end, {"text": "x" * 5000})
    finally:
        guardian_end.close()
        client_end.close()


def test_successful_submission_emits_exact_task_3_acknowledgement():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = guardian_config(root)
        guardian_end, client_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            send_framed(client_end, command_record())
            result = guardian.handle_one_request(guardian_end, config)
            assert receive_framed(client_end) == {
                "schema_version": 1,
                "request_id": "telegram-42",
                "status": "accepted",
            }
            assert result["ok"] is True
            request_path = root / "state" / "lifecycle" / "telegram-42.json"
            state = json.loads(request_path.read_text(encoding="utf-8"))["state"]
            assert state["phase"] == "completed"
        finally:
            guardian_end.close()
            client_end.close()


def test_disconnected_response_peer_leaves_accepted_state_without_noisy_error():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        events = []
        config = guardian_config(root, successful_adapters(events))
        guardian_end, client_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        send_framed(client_end, command_record(update_id=43))
        client_end.close()
        try:
            result = guardian.handle_one_request(guardian_end, config)
        finally:
            guardian_end.close()

        request_path = root / "state" / "lifecycle" / "telegram-43.json"
        state = json.loads(request_path.read_text(encoding="utf-8"))["state"]
        assert result is None
        assert state["phase"] == "accepted"
        assert state["pending_effects"] == []
        assert events == []


def test_unauthorized_request_is_not_acknowledged_or_persisted():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = guardian_config(root)
        guardian_end, client_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            send_framed(client_end, command_record())
            result = guardian.handle_one_request(
                guardian_end,
                config,
                get_peer_uid=lambda _connection: config["gateway_uid"] + 1,
            )
            assert result is None
            client_end.settimeout(0.1)
            with unittest.TestCase().assertRaises(socket.timeout):
                client_end.recv(1)
            assert not (root / "state" / "lifecycle").exists()
        finally:
            guardian_end.close()
            client_end.close()


def test_socket_server_and_task_3_client_interoperate_without_real_systemd():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = guardian_config(root)
        server = guardian.start_server(config)
        errors = []

        def serve_one():
            try:
                connection, _address = server.accept()
                with connection:
                    guardian.handle_one_request(connection, config)
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=serve_one)
        thread.start()
        try:
            acknowledgement = telegram_api.submit_to_guardian(
                config["socket_path"], command_record("reset", 44), timeout=2.0,
            )
        finally:
            thread.join(timeout=2.0)
            server.close()
            try:
                os.unlink(config["socket_path"])
            except FileNotFoundError:
                pass

        assert thread.is_alive() is False
        assert errors == []
        assert acknowledgement == {
            "schema_version": 1,
            "request_id": "telegram-44",
            "status": "accepted",
        }


def test_start_server_creates_the_configured_unix_socket():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        config = guardian_config(root)
        server = guardian.start_server(config)
        try:
            assert Path(config["socket_path"]).is_socket()
        finally:
            server.close()
            os.unlink(config["socket_path"])


def test_load_production_config_delegates_explicit_identity_and_paths():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        environment = {
            "GUARDIAN_SOCKET_PATH": str(root / "guardian.sock"),
            "SURVIVAL_STORE_DIR": str(root / "state"),
            "GUARDIAN_GATEWAY_UID": "991",
            "USER_MANAGER_UID": "1000",
        }
        assert guardian.load_production_config(environment) == {
            "socket_path": str(root / "guardian.sock"),
            "store_path": root / "state",
            "gateway_uid": 991,
            "user_manager_uid": 1000,
        }


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions
    )
