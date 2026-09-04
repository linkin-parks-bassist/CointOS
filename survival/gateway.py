"""High-level gateway logic for the survival plane.

Provides functional interfaces for processing Telegram updates,
managing the critical outbox, and recording gateway heartbeat.

The entry point (when run as ``python3 -m survival.gateway``)
creates supervised child processes via ``os.fork``: one blocking
long-poll worker and one critical-outbox/deadline worker.  The
parent reaps and restarts either child.  No threads or stateful
classes are introduced.
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from survival import protocol, records, telegram_api

ACKNOWLEDGEMENT_MESSAGES = {
    "restart": "Restart accepted. I am staying online while the agent system restarts.",
    "reset": "Reset accepted. I am staying online while the agent system restarts.",
}
DEGRADED_REPLY = "I am degraded. I will reply properly after restart."


def acknowledgement(command: str) -> str:
    """Return the acknowledgement text for a recognised command."""
    return ACKNOWLEDGEMENT_MESSAGES[command]


def handle_update(update: dict, allowed: set[int], store: Path,
                  send: "Callable", send_command: "Callable") -> dict:
    """Process one Telegram update through the gateway.

    Returns a dict with ``kind`` (``command``, ``ordinary``, or
    ``denied``) and ``id`` (the accepted update id).
    """
    try:
        accepted = records.accept_update(store, update, allowed)
    except ValueError:
        chat_id = update["message"]["chat"]["id"]
        telegram_api.store_denied_audit(store, chat_id)
        return {"kind": "denied", "id": f"telegram-{update['update_id']}"}

    command = protocol.parse_literal_command(accepted["text"])
    if command is None:
        telegram_api.store_inbound(store, accepted)
        return {"kind": "ordinary", "id": accepted["id"]}

    request = command_record(accepted, command)
    send_command(request)
    send(accepted["chat_id"], acknowledgement(command))
    mark_acknowledged(store, accepted["id"])
    return {"kind": "command", "id": accepted["id"]}


def command_record(accepted: dict, command: str) -> dict:
    """Build a strict protocol command record from an accepted update."""
    return {
        "schema_version": 1,
        "request_id": accepted["id"],
        "telegram_update_id": accepted["telegram_update_id"],
        "telegram_user_id": accepted["telegram_user_id"],
        "command": command,
        "received_at": accepted["received_at"],
    }


def mark_acknowledged(store: Path, update_id: str) -> None:
    """Mark an accepted update as acknowledged in the command record."""
    path = store / "commands" / f"{update_id}.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    data["egress_state"] = "delivered"
    telegram_api.atomic_json(path, data)


def send_due_degraded_responses(root: Path, send: "Callable",
                                now: float) -> int:
    """Send degraded replies for due inbox messages.

    Returns the number of messages responded to.
    """
    due = telegram_api.list_inbox_due(root, now)
    count = 0
    for path in due:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        chat_id = data.get("chat_id")
        if chat_id is not None:
            send(chat_id, DEGRADED_REPLY)
            telegram_api.update_inbox_state(path, "delivered")
            count += 1
    return count


def drain_critical_outbox(store: Path, send: "Callable") -> int:
    """Send messages from the critical outbox and mark them delivered.

    Returns the number of messages drained.
    """
    entries = telegram_api.list_critical_outbox(store)
    count = 0
    for path in entries:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("egress_state") in ("ready", "sending"):
            chat_id = data.get("chat_id")
            text = data.get("text")
            if chat_id is not None and text is not None:
                send(chat_id, text)
            data["egress_state"] = "delivered"
            telegram_api.atomic_json(path, data)
            count += 1
    return count


def mark_gateway_heartbeat(store: Path, monotonic_now: float) -> None:
    """Record the gateway heartbeat timestamp."""
    telegram_api.write_heartbeat(store, monotonic_now)


# ---------------------------------------------------------------------------
# Process management (entry point)
# ---------------------------------------------------------------------------

def _reap_children() -> None:
    """Reap any zombie children."""
    try:
        while True:
            os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        pass


def _poll_child(pid: int, store: Path, allowed: set[int],
                send: "Callable", send_command: "Callable") -> None:
    """Blocking long-poll worker: read Telegram updates and dispatch."""
    _reap_children()
    try:
        import ecosystem.telegram as telegram_mod
    except ImportError:
        sys.exit(1)
    while True:
        try:
            update = telegram_mod.poll_update()
            if update is not None:
                handle_update(update, allowed, store, send, send_command)
        except Exception:
            time.sleep(1)


def _outbox_child(store: Path, send: "Callable") -> None:
    """Critical-outbox/deadline worker."""
    _reap_children()
    while True:
        try:
            drain_critical_outbox(store, send)
            mark_gateway_heartbeat(store, time.monotonic())
        except Exception:
            time.sleep(5)
        time.sleep(10)


def main(store: Path, allowed: set[int],
         send: "Callable", send_command: "Callable") -> None:
    """Create supervised child processes and wait."""
    store.mkdir(parents=True, exist_ok=True)

    def _handle_signal(signum, _frame):
        os.kill(0, signal.SIGTERM)

    signal.signal(signal.SIGTERM, _handle_signal)

    poll_pid = os.fork()
    if poll_pid == 0:
        _poll_child(poll_pid, store, allowed, send, send_command)
        sys.exit(0)

    outbox_pid = os.fork()
    if outbox_pid == 0:
        _outbox_child(store, send)
        sys.exit(0)

    # Parent: reap and restart children
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
            _reap_children()
            if pid == poll_pid:
                new_pid = os.fork()
                if new_pid == 0:
                    _poll_child(new_pid, store, allowed, send, send_command)
                    sys.exit(0)
            elif pid == outbox_pid:
                new_pid = os.fork()
                if new_pid == 0:
                    _outbox_child(store, send)
                    sys.exit(0)
        except ChildProcessError:
            break


if __name__ == "__main__":
    from survival.telegram_api import store_inbound  # noqa: F401

    store_path = Path(os.environ.get("STORE_DIR", "state"))
    allowed_ids = {int(u) for u in os.environ.get("ALLOWED_USERS", "42").split(",")}

    def _send(chat_id: int, text: str) -> None:
        store_inbound(store_path, {
            "schema_version": 1,
            "id": f"outbound-{chat_id}-{int(time.time())}",
            "telegram_update_id": 0,
            "telegram_user_id": chat_id,
            "chat_id": chat_id,
            "text": text,
            "received_at": datetime.now(timezone.utc).isoformat(),
        })

    def _send_command(command: dict) -> None:
        pass

    main(store_path, allowed_ids, _send, _send_command)
