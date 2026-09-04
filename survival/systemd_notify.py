"""Send readiness and watchdog state to systemd's notification fingertip."""

import os
import socket


def notify_systemd(message: str, socket_path: str | None = None) -> None:
    """Send one datagram, or remain a no-op outside a systemd service."""
    if socket_path is None:
        socket_path = os.environ.get("NOTIFY_SOCKET", "")
    if not socket_path:
        return
    if socket_path.startswith("@"):
        socket_path = "\0" + socket_path[1:]
    notification_socket = None
    try:
        notification_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        notification_socket.sendto(message.encode("utf-8"), socket_path)
    except OSError:
        pass
    finally:
        if notification_socket is not None:
            notification_socket.close()
