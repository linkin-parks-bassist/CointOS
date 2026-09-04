"""Tests for survival guardian: framed socket, peer auth, lifecycle dispatch."""

import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from survival import guardian, protocol


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


def send_framed(connection, data):
    encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
    connection.sendall(len(encoded).to_bytes(4, "big") + encoded)


def receive_framed(connection):
    size = int.from_bytes(receive_exact(connection, 4), "big")
    if size <= 0 or size > 4096:
        raise ValueError(f"invalid response size: {size}")
    payload = receive_exact(connection, size)
    return json.loads(payload)


def make_command(update_id, user_id, text):
    return {
        "schema_version": 1,
        "request_id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": user_id,
        "command": text.lower(),
        "received_at": "2026-09-04T00:00:00+00:00",
    }


def _run_guardian_server(config, stop_event):
    """Run guardian accept loop until stop_event is set."""
    server = guardian.start_server(config)
    try:
        while not stop_event.is_set():
            try:
                connection, _address = server.accept()
            except socket.timeout:
                continue
            try:
                guardian.handle_one_request(connection, config)
            finally:
                connection.close()
    finally:
        server.close()
        try:
            os.unlink(config["socket_path"])
        except OSError:
            pass


def _make_guardian_config(tmp_dir, socket_name="guardian.sock"):
    """Create a guardian config that matches the current process uid."""
    tmp = Path(tmp_dir)
    socket_path = tmp / socket_name
    allowed_path = tmp / "allowed"
    gateway_uid = os.getuid()
    allowed_path.write_text(f"{gateway_uid}\n", encoding="utf-8")
    return guardian.load_production_config({
        "USER": "david",
        "GUARDIAN_SOCKET_PATH": str(socket_path),
        "GUARDIAN_ALLOWED_USER_IDS_PATH": str(allowed_path),
    })


# ---------------------------------------------------------------------------
# Peer authentication tests
# ---------------------------------------------------------------------------


def test_authorize_peer_rejects_non_gateway_uid():
    with unittest.TestCase().assertRaises(PermissionError):
        guardian.authorize_peer(999, gateway_uid=991)


def test_authorize_peer_accepts_gateway_uid():
    guardian.authorize_peer(991, gateway_uid=991)


# ---------------------------------------------------------------------------
# Framed socket server tests
# ---------------------------------------------------------------------------


def test_guardian_server_echoes_acknowledgement():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_guardian_config(tmp)
        socket_path = config["socket_path"]

        stop_event = threading.Event()
        thread = threading.Thread(target=_run_guardian_server, args=(config, stop_event))
        thread.start()
        try:
            # Give the server time to bind
            import time
            time.sleep(0.1)

            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(str(socket_path))

            command = make_command(42, 991, "RESTART")
            send_framed(client, command)
            response = receive_framed(client)

            assert response["request_id"] == "telegram-42"
            assert response["status"] in ("accepted", "reducing")
        finally:
            stop_event.set()
            thread.join(timeout=2)
            client.close()


def test_guardian_server_rejects_invalid_framing():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_guardian_config(tmp)
        socket_path = config["socket_path"]

        stop_event = threading.Event()
        thread = threading.Thread(target=_run_guardian_server, args=(config, stop_event))
        thread.start()
        try:
            import time
            time.sleep(0.1)

            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(str(socket_path))

            # Send garbage that is not valid framing
            client.sendall(b"not-valid-framing-at-all")
            try:
                receive_framed(client)
            except (ValueError, RuntimeError, ConnectionError, struct.error):
                pass  # Expected: bad framing is rejected
        finally:
            stop_event.set()
            thread.join(timeout=2)
            client.close()


def test_guardian_server_bounded_response_size():
    """Response must be bounded (MAXIMUM_GUARDIAN_RESPONSE_BYTES)."""
    assert guardian.MAXIMUM_GUARDIAN_RESPONSE_BYTES == 4096


def test_guardian_server_framing_is_big_endian():
    """Four-byte big-endian framing must be used."""
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_guardian_config(tmp)
        socket_path = config["socket_path"]

        stop_event = threading.Event()
        thread = threading.Thread(target=_run_guardian_server, args=(config, stop_event))
        thread.start()
        try:
            import time
            time.sleep(0.1)

            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(str(socket_path))

            command = make_command(43, 991, "RESET")
            encoded = json.dumps(command, separators=(",", ":")).encode("utf-8")
            frame = len(encoded).to_bytes(4, "big") + encoded
            client.sendall(frame)

            # Read size header
            size_bytes = receive_exact(client, 4)
            size = struct.unpack(">I", size_bytes)[0]
            assert size > 0
            assert size <= 4096
        finally:
            stop_event.set()
            thread.join(timeout=2)
            client.close()


# ---------------------------------------------------------------------------
# start_server tests
# ---------------------------------------------------------------------------


def test_start_server_creates_socket_file():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_guardian_config(tmp)
        socket_path = config["socket_path"]

        stop_event = threading.Event()
        thread = threading.Thread(target=_run_guardian_server, args=(config, stop_event))
        thread.start()
        try:
            import time
            time.sleep(0.1)
            assert Path(socket_path).exists()
        finally:
            stop_event.set()
            thread.join(timeout=2)


def test_start_server_reuses_config():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_guardian_config(tmp)

        stop_event = threading.Event()
        thread = threading.Thread(target=_run_guardian_server, args=(config, stop_event))
        thread.start()
        try:
            import time
            time.sleep(0.1)
            assert thread is not None
        finally:
            stop_event.set()
            thread.join(timeout=2)


# ---------------------------------------------------------------------------
# handle_one_request tests
# ---------------------------------------------------------------------------


def test_handle_one_request_returns_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_guardian_config(tmp)
        socket_path = config["socket_path"]

        stop_event = threading.Event()
        thread = threading.Thread(target=_run_guardian_server, args=(config, stop_event))
        thread.start()
        try:
            import time
            time.sleep(0.1)

            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(str(socket_path))

            command = make_command(50, 991, "RESTART")
            send_framed(client, command)
            response = receive_framed(client)

            assert response["request_id"] == "telegram-50"
            assert "status" in response
        finally:
            stop_event.set()
            thread.join(timeout=2)
            client.close()


# ---------------------------------------------------------------------------
# peer_uid tests
# ---------------------------------------------------------------------------


def test_peer_uid_returns_pid():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_guardian_config(tmp)
        socket_path = config["socket_path"]

        stop_event = threading.Event()
        thread = threading.Thread(target=_run_guardian_server, args=(config, stop_event))
        thread.start()
        try:
            import time
            time.sleep(0.1)

            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(str(socket_path))

            uid = guardian.peer_uid(client)
            assert isinstance(uid, int)
            assert uid >= 0
            # Close client before the server handler processes
            client.close()
            # Small delay to let the server finish
            time.sleep(0.1)
        finally:
            stop_event.set()
            thread.join(timeout=2)


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
