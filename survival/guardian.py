"""Guardian server: framed-socket lifecycle effect executor.

Accepts four-byte big-endian framed commands from the gateway over a
Unix domain socket, authenticates the peer, dispatches lifecycle
advancement through system_control, and returns bounded typed
acknowledgements.
"""

import json
import os
import socket
import struct
import traceback

from survival import protocol, system_control

MAXIMUM_GUARDIAN_RESPONSE_BYTES = 4096


# ---- Peer authentication ----


def peer_uid(connection: socket.socket) -> int:
    """Return the effective uid of the connected peer."""
    try:
        creds = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED,
            struct.calcsize("@3i"),
        )
        _, uid, _ = struct.unpack("@3i", creds)
        return uid
    except (OSError, struct.error):
        raise PermissionError("cannot determine peer uid")


def authorize_peer(uid: int, gateway_uid: int) -> None:
    """Reject connections whose uid does not match the gateway uid."""
    system_control.authorize_peer(uid, gateway_uid)


# ---- Framed I/O helpers ----


def _receive_framed(connection: socket.socket) -> dict:
    """Read one four-byte big-endian framed JSON command."""
    size_bytes = _recv_exact(connection, 4)
    size = struct.unpack(">I", size_bytes)[0]
    if size <= 0 or size > MAXIMUM_GUARDIAN_RESPONSE_BYTES:
        raise ValueError(f"invalid command size: {size}")
    payload = _recv_exact(connection, size)
    return protocol.decode_command(payload)


def _send_framed(connection: socket.socket, data: dict) -> None:
    """Write one four-byte big-endian framed JSON acknowledgement."""
    encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAXIMUM_GUARDIAN_RESPONSE_BYTES:
        encoded = encoded[:MAXIMUM_GUARDIAN_RESPONSE_BYTES]
    connection.sendall(len(encoded).to_bytes(4, "big") + encoded)


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    """Read exactly *size* bytes or raise."""
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed before complete frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


# ---- Server ----


def start_server(config: dict) -> socket.socket:
    """Create, bind, and listen on the guardian Unix domain socket."""
    socket_path = config["socket_path"]
    gateway_uid = config["gateway_uid"]

    # Remove stale socket file
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(socket_path)
    server.listen(5)
    server.settimeout(1.0)
    return server


def handle_one_request(connection: socket.socket, config: dict) -> None:
    """Authenticate, dispatch, and acknowledge one framed request."""
    gateway_uid = config["gateway_uid"]
    store = config.get("store")

    try:
        # Step 1: authenticate peer
        uid = peer_uid(connection)
        authorize_peer(uid, gateway_uid)

        # Step 2: receive framed command
        command = _receive_framed(connection)

        # Step 3: validate command fields
        if not isinstance(command, dict):
            _send_framed(connection, {
                "schema_version": 1,
                "request_id": "unknown",
                "status": "rejected",
            })
            return

        request_id = command.get("request_id", "unknown")
        cmd = command.get("command", "restart")

        # Step 4: dispatch through system_control
        if store:
            result = system_control.advance_request(
                store,
                adapters={"system": system_control.system_unit,
                          "user": system_control.user_unit},
                policy={"command": cmd, "max_retries": 10},
            )
            status = result.get("phase", "reducing")
        else:
            # Minimal acknowledgement without full lifecycle
            status = "accepted"

        # Step 5: send bounded acknowledgement
        _send_framed(connection, {
            "schema_version": 1,
            "request_id": request_id,
            "status": status,
        })

    except PermissionError:
        _send_framed(connection, {
            "schema_version": 1,
            "request_id": "unknown",
            "status": "unauthorised",
        })
    except (ValueError, ConnectionError) as exc:
        _send_framed(connection, {
            "schema_version": 1,
            "request_id": "unknown",
            "status": "rejected",
            "error": str(exc),
        })
    except Exception:
        _send_framed(connection, {
            "schema_version": 1,
            "request_id": "unknown",
            "status": "error",
            "error": traceback.format_exc(),
        })


def run_loop(config: dict, on_accept=None) -> None:
    """Accept and handle requests until interrupted."""
    server = start_server(config)
    try:
        while True:
            try:
                connection, _address = server.accept()
            except socket.timeout:
                continue
            try:
                if on_accept:
                    on_accept(connection)
                handle_one_request(connection, config)
            finally:
                connection.close()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        try:
            os.unlink(config["socket_path"])
        except OSError:
            pass


# ---- Production config ----


def load_production_config(environ: dict | None = None) -> dict:
    """Load guardian config from environment variables."""
    return system_control.load_production_config(environ)


if __name__ == "__main__":
    config = load_production_config()
    run_loop(config)
