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
DEFAULT_DEGRADED_DEADLINE_SECONDS = 300


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
    """Record acknowledgement state for an accepted update.

    Stores in a dedicated ack file rather than mutating the
    immutable accepted command record.
    """
    ack_path = store / "acks" / f"{update_id}.json"
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    ack_record = {
        "update_id": update_id,
        "acknowledged_at": datetime.now(timezone.utc).isoformat(),
    }
    telegram_api.atomic_json(ack_path, ack_record)


def send_due_degraded_responses(root: Path, send: "Callable",
                                now: float) -> int:
    """Send degraded replies for inbox messages past their deadline.

    Strictly parses each record; skips malformed entries without
    corrupting state.  Returns the number of messages responded to.
    """
    due = telegram_api.list_inbox_due(root, now)
    count = 0
    for path in due:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if type(data) is not dict:
            continue
        chat_id = data.get("chat_id")
        if chat_id is not None and type(chat_id) is int:
            send(chat_id, DEGRADED_REPLY)
        telegram_api.update_inbox_state(path, "delivered")
        count += 1
    return count


def drain_critical_outbox(store: Path, send: "Callable") -> int:
    """Send messages from the critical outbox and mark them delivered.

    Crash-truthful: persist ``sending`` before the send attempt.
    A failed send becomes ``delivery_unknown`` (no automatic replay).
    Malformed records are never marked delivered.

    Returns the number of messages drained.
    """
    entries = telegram_api.list_critical_outbox(store)
    count = 0
    for path in entries:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if type(data) is not dict:
            continue
        egress = data.get("egress_state")
        if egress not in ("ready", "sending"):
            continue
        chat_id = data.get("chat_id")
        text = data.get("text")
        if chat_id is None or text is None:
            continue
        if egress != "sending":
            data["egress_state"] = "sending"
            telegram_api.atomic_json(path, data)
        try:
            send(chat_id, text)
            data["egress_state"] = "delivered"
            telegram_api.atomic_json(path, data)
        except Exception:
            data["egress_state"] = "delivery_unknown"
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


def _poll_child(store: Path, allowed: set[int],
                send: "Callable", send_command: "Callable") -> None:
    """Blocking long-poll worker: read Telegram updates and dispatch."""
    _reap_children()
    try:
        import ecosystem.telegram as telegram_mod
    except ImportError:
        sys.exit(1)
    while True:
        update = telegram_mod.poll_update()
        if update is not None:
            handle_update(update, allowed, store, send, send_command)
        time.sleep(1)


def _outbox_child(store: Path, send: "Callable") -> None:
    """Critical-outbox/deadline worker."""
    _reap_children()
    while True:
        try:
            drain_critical_outbox(store, send)
            mark_gateway_heartbeat(store, time.monotonic())
            now = time.monotonic()
            send_due_degraded_responses(store, send, now)
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
        _poll_child(store, allowed, send, send_command)
        sys.exit(0)

    outbox_pid = os.fork()
    if outbox_pid == 0:
        _outbox_child(store, send)
        sys.exit(0)

    # Parent: reap and restart children with tracked PIDs
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
            _reap_children()
            if pid == poll_pid:
                new_pid = os.fork()
                if new_pid == 0:
                    _poll_child(store, allowed, send, send_command)
                    sys.exit(0)
                poll_pid = new_pid
            elif pid == outbox_pid:
                new_pid = os.fork()
                if new_pid == 0:
                    _outbox_child(store, send)
                    sys.exit(0)
                outbox_pid = new_pid
        except ChildProcessError:
            break


if __name__ == "__main__":
    from survival.telegram_api import store_inbound, store_critical_outbox_entry  # noqa: F401

    store_path = Path(os.environ.get("STORE_DIR", "state"))

    allowed_env = os.environ.get("ALLOWED_USERS", "")
    if allowed_env:
        allowed_ids = {int(u) for u in allowed_env.split(",")}
    else:
        allowed_ids = set()

    def _send(chat_id: int, text: str) -> None:
        now = datetime.now(timezone.utc)
        msg_id = f"outbound-{chat_id}-{int(time.time())}"
        record = {
            "schema_version": 1,
            "id": msg_id,
            "telegram_update_id": 0,
            "telegram_user_id": chat_id,
            "chat_id": chat_id,
            "text": text,
            "received_at": now.isoformat(),
            "egress_state": "ready",
        }
        store_critical_outbox_entry(store_path, record)

    def _send_command(command: dict) -> None:
        path = store_path / "commands" / f"{command['request_id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        telegram_api.atomic_json(path, command)

    main(store_path, allowed_ids, _send, _send_command)
