"""Peer-authenticated guardian transport for durable lifecycle requests."""

import json
import os
import socket
import struct

from survival import protocol, systemd_notify, system_control


MAXIMUM_GUARDIAN_RESPONSE_BYTES = 4096


def peer_uid(connection: socket.socket) -> int:
    """Read the connected Unix peer uid from Linux ``SO_PEERCRED``."""
    try:
        credentials = connection.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            struct.calcsize("@3i"),
        )
        _pid, uid, _gid = struct.unpack("@3i", credentials)
    except (OSError, struct.error) as error:
        raise PermissionError("cannot determine peer uid") from error
    return uid


def authorize_peer(uid: int, gateway_uid: int) -> None:
    system_control.authorize_peer(uid, gateway_uid)


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    payload = bytearray()
    while len(payload) < size:
        chunk = connection.recv(size - len(payload))
        if not chunk:
            raise ConnectionError("socket closed before complete frame")
        payload.extend(chunk)
    return bytes(payload)


def _receive_framed(connection: socket.socket) -> dict:
    """Decode one four-byte big-endian framed Task 1 command."""
    size = int.from_bytes(_recv_exact(connection, 4), "big")
    if size <= 0 or size > MAXIMUM_GUARDIAN_RESPONSE_BYTES:
        raise ValueError(f"invalid command size: {size}")
    return protocol.decode_command(_recv_exact(connection, size))


def _send_framed(connection: socket.socket, data: dict) -> bool:
    """Send one complete bounded JSON frame, or report a disconnected peer."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAXIMUM_GUARDIAN_RESPONSE_BYTES:
        raise ValueError(f"invalid response size: {len(encoded)}")
    try:
        connection.sendall(len(encoded).to_bytes(4, "big") + encoded)
    except (BrokenPipeError, ConnectionResetError):
        return False
    return True


def start_server(config: dict) -> socket.socket:
    """Bind the configured Unix socket; deployment owns its parent permissions."""
    socket_path = config["socket_path"]
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(socket_path)
        server.listen(5)
        timeout = config["guardian_poll_seconds"]
        if type(timeout) not in (int, float) or timeout <= 0:
            raise ValueError("invalid guardian poll period")
        server.settimeout(timeout)
    except BaseException:
        server.close()
        raise
    return server


def inherited_server(environ=None, current_pid=os.getpid):
    """Consume systemd's one inherited listener, if this process owns it."""
    if environ is None:
        environ = os.environ
    listen_pid = environ.get("LISTEN_PID")
    listen_fds = environ.get("LISTEN_FDS")
    if listen_pid is None and listen_fds is None:
        return None
    if listen_pid is None or listen_fds is None:
        raise RuntimeError("incomplete systemd socket activation environment")
    try:
        owner_pid = int(listen_pid)
        descriptor_count = int(listen_fds)
    except ValueError as error:
        raise RuntimeError("invalid systemd socket activation environment") from error
    if owner_pid != current_pid():
        return None
    if descriptor_count != 1:
        raise RuntimeError("guardian requires exactly one inherited listener")
    return socket.socket(fileno=3)


def acquire_server(config, environ=None):
    """Return the listener and whether this process owns its filesystem node."""
    server = inherited_server(environ)
    if server is not None:
        server.settimeout(config["guardian_poll_seconds"])
        return server, False
    return start_server(config), True


def handle_one_request(
    connection: socket.socket,
    config: dict,
    *,
    get_peer_uid=peer_uid,
    send_response=_send_framed,
) -> dict | None:
    """Durably accept, acknowledge, and advance one authenticated command."""
    try:
        authorize_peer(get_peer_uid(connection), config["gateway_uid"])
        command = _receive_framed(connection)
    except (PermissionError, ValueError, ConnectionError):
        return None

    system_control.refresh_timing_policy(config)

    previous_pause = system_control.prior_pause_for_new_request(
        config["store_path"], config.get("agent_state_path", config["store_path"]),
    )
    request_path = system_control.accept_request(
        config["store_path"], command, previous_pause,
    )
    system_control.report_gateway_data_health(config)
    system_control.commit_acknowledgement(request_path)
    acknowledgement = {
        "schema_version": 1,
        "request_id": command["request_id"],
        "status": "accepted",
    }
    response_delivered = send_response(connection, acknowledgement)

    adapters = config.get("adapters")
    if adapters is None:
        adapters = system_control.production_adapters(config)
    result = resume_pending_request(config, adapters, recover_blocked=False)
    if response_delivered is False and result is None:
        return None
    return result


def resume_pending_request(config, adapters=None, recover_blocked=True):
    """Advance only the oldest incomplete lifecycle, including after restart."""
    paths = system_control.incomplete_request_paths(config["store_path"])
    if not paths:
        return None
    path = paths[0]
    state = system_control._read_request(path)["state"]
    if state["phase"] == "accepted":
        state = system_control.commit_acknowledgement(path)
    if recover_blocked and state["phase"] in {"blocked", "failed"}:
        system_control.recover_request(path)
    if adapters is None:
        adapters = config.get("adapters")
    if adapters is None:
        adapters = system_control.production_adapters(config)
    return system_control.advance_request(
        path,
        adapters,
        {
            **config,
            "maximum_effects": config.get(
                "maximum_effects", system_control.MAXIMUM_EFFECTS_PER_ADVANCE,
            ),
        },
    )


def run_loop(config: dict, on_accept=None, environ=None) -> None:
    """Serve serially so one lifecycle owns the privileged mutation boundary."""
    server, remove_socket = acquire_server(config, environ)
    adapters = config.get("adapters")
    if adapters is None:
        adapters = system_control.production_adapters(config)
    try:
        systemd_notify.notify_systemd("READY=1")
        system_control.refresh_timing_policy(config)
        system_control.report_gateway_data_health(config)
        server.settimeout(config["guardian_poll_seconds"])
        resume_pending_request(config, adapters, recover_blocked=True)
        while True:
            try:
                connection, _address = server.accept()
            except socket.timeout:
                system_control.refresh_timing_policy(config)
                system_control.report_gateway_data_health(config)
                server.settimeout(config["guardian_poll_seconds"])
                resume_pending_request(config, adapters, recover_blocked=True)
                systemd_notify.notify_systemd("WATCHDOG=1")
                continue
            try:
                if on_accept is not None:
                    on_accept(connection)
                result = handle_one_request(connection, config)
                if result is not None:
                    systemd_notify.notify_systemd("WATCHDOG=1")
            finally:
                connection.close()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        if remove_socket:
            try:
                os.unlink(config["socket_path"])
            except OSError:
                pass


def load_production_config(environ: dict | None = None) -> dict:
    return system_control.load_production_config(environ)


def run_production(environ: dict | None = None) -> None:
    config = load_production_config(environ)
    config["adapters"] = system_control.production_adapters(config)
    run_loop(config)


if __name__ == "__main__":
    run_production()
