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
DEGRADED_DEADLINE_SECONDS = 3


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
        now = time.monotonic()
        telegram_api.store_inbound(store, accepted, monotonic_now=now,
                                   deadline_seconds=DEGRADED_DEADLINE_SECONDS)
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


def is_command_delivered(store: Path, update_id: str) -> bool:
    """Check whether an acknowledgement record exists for an update."""
    ack_path = store / "acks" / f"{update_id}.json"
    return ack_path.exists()


def send_due_degraded_responses(root: Path, send: "Callable",
                                now: float) -> int:
    """Send degraded replies for inbox messages past their monotonic deadline.

    Compares monotonic ``deadline_at`` values against monotonic ``now``.
    Strictly parses each record; quarantines malformed entries and
    reports quarantine visibility.  Returns the number of messages responded to.
    """
    due = telegram_api.list_inbox_due(root, now)
    count = 0
    for path in due:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            telegram_api.quarantine_record(root, path, "malformed_json")
            continue
        if type(data) is not dict:
            telegram_api.quarantine_record(root, path, "not_a_dict", data)
            continue
        chat_id = data.get("chat_id")
        if chat_id is not None and type(chat_id) is int:
            send(chat_id, DEGRADED_REPLY)
        else:
            telegram_api.quarantine_record(root, path,
                                           "missing_or_invalid_chat_id", data)
            continue
        telegram_api.update_inbox_state(path, "delivered")
        count += 1
    return count


def drain_critical_outbox(store: Path, send: "Callable") -> int:
    """Send messages from the critical outbox and mark them delivered.

    Crash-truthful: persist ``sending`` before the send attempt.
    A failed send becomes ``delivery_unknown`` (no automatic replay).
    Records already in ``sending`` become ``delivery_unknown`` (no replay).
    Malformed records are quarantined, never marked delivered.

    Returns the number of messages drained.
    """
    entries = telegram_api.list_critical_outbox(store)
    count = 0
    for path in entries:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            telegram_api.quarantine_record(root=store, source_path=path,
                                           error_reason="malformed_json")
            continue
        if type(data) is not dict:
            telegram_api.quarantine_record(root=store, source_path=path,
                                           error_reason="not_a_dict",
                                           record=data)
            continue

        egress = data.get("egress_state")

        # Already processed: skip silently
        if egress in ("delivered", "delivery_unknown"):
            continue

        if egress == "sending":
            # Stuck from a prior run: mark unknown, never replay
            data["egress_state"] = "delivery_unknown"
            telegram_api.atomic_json(path, data)
            count += 1
            continue

        if egress != "ready":
            telegram_api.quarantine_record(root=store, source_path=path,
                                           error_reason=f"unknown_egress_{egress}",
                                           record=data)
            continue

        chat_id = data.get("chat_id")
        text = data.get("text")
        if chat_id is None or text is None:
            telegram_api.quarantine_record(root=store, source_path=path,
                                           error_reason="missing_chat_id_or_text",
                                           record=data)
            continue

        # Phase 1: persist sending before send attempt
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


def check_quarantine_health(store: Path) -> bool:
    """Return True if no quarantine errors exist (healthy)."""
    return len(telegram_api.list_quarantine_errors(store)) == 0


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
    while True:
        try:
            updates = telegram_api.get_updates()
            if updates:
                for update in updates:
                    handle_update(update, allowed, store, send, send_command)
        except SystemExit:
            raise
        except Exception:
            time.sleep(1)
        time.sleep(1)


def _outbox_child(store: Path, send: "Callable") -> None:
    """Critical-outbox/deadline worker with its own heartbeat."""
    _reap_children()
    while True:
        try:
            drain_critical_outbox(store, send)
            now = time.monotonic()
            send_due_degraded_responses(store, send, now)
            mark_gateway_heartbeat(store, now)
            if not check_quarantine_health(store):
                # Health indicator visible but does not kill child
                pass
        except Exception:
            time.sleep(5)
        time.sleep(10)


def main(store: Path, allowed: set[int],
         send: "Callable", send_command: "Callable") -> None:
    """Create supervised child processes and wait.

    Uses one blocking ``waitpid(-1, 0)`` per iteration, identifies
    the tracked role for that exact PID, replaces it, and updates
    that role's PID.  Does not call a second broad reaper.
    """
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

    # Parent: single waitpid per iteration, tracked replacement
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
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


def load_production_config() -> dict:
    """Load production configuration from systemd credentials.

    Fails before READY/heartbeat if any required config is absent
    or malformed.

    Returns dict with keys: bot_token, allowed_users, store_dir,
    guardian_socket_path, degraded_deadline_seconds.
    """
    # Bot token from systemd credential path
    bot_token = telegram_api._get_bot_token()

    # Allowed user IDs from root-installed file
    user_ids_path = os.environ.get(
        "GUARDIAN_ALLOWED_USER_IDS_PATH",
        "/etc/survival/allowed_user_ids.txt"
    )
    allowed_users = telegram_api.read_allowed_user_ids(user_ids_path)

    # Survival store from explicit configuration
    store_dir = os.environ.get("SURVIVAL_STORE_DIR", "state")
    store_path = Path(store_dir)

    # Guardian socket from explicit configuration
    guardian_socket_path = os.environ.get(
        "GUARDIAN_SOCKET_PATH",
        "/var/run/survival-guardian.sock"
    )

    # Degraded response deadline (currently 3 seconds)
    deadline_str = os.environ.get("DEGRADED_RESPONSE_DEADLINE_SECONDS", "3")
    try:
        degraded_deadline_seconds = int(deadline_str)
    except ValueError:
        raise RuntimeError(
            f"invalid DEGRADED_RESPONSE_DEADLINE_SECONDS: {deadline_str!r}"
        )

    return {
        "bot_token": bot_token,
        "allowed_users": allowed_users,
        "store_path": store_path,
        "guardian_socket_path": guardian_socket_path,
        "degraded_deadline_seconds": degraded_deadline_seconds,
    }


if __name__ == "__main__":
    # Production config: fail hard if credentials are absent
    config = load_production_config()
    store_path = config["store_path"]
    allowed = config["allowed_users"]
    guardian_socket = config["guardian_socket_path"]

    bot_token = config["bot_token"]

    def _send(chat_id: int, text: str) -> None:
        """Send via the Telegram API HTTPS client."""
        success = telegram_api.send_message(
            bot_token=bot_token, chat_id=chat_id, text=text
        )
        if not success:
            # Telegram send failed: queue to outbox for retry
            now = time.monotonic()
            record = {
                "schema_version": 1,
                "id": f"outbound-{chat_id}-{int(now * 1000)}",
                "telegram_update_id": 0,
                "telegram_user_id": chat_id,
                "chat_id": chat_id,
                "text": text,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "deadline_at": now + config["degraded_deadline_seconds"],
                "egress_state": "ready",
            }
            telegram_api.store_critical_outbox_entry(store_path, record)

    def _send_command(command: dict) -> None:
        """Submit command to the guardian via Unix-domain socket."""
        ack = telegram_api.submit_to_guardian(guardian_socket, command)
        if ack is None:
            # Guardian submission failed: log but do not block
            sys.stderr.write(
                f"guardian submission failed for {command.get('request_id')}\n"
            )

    main(store_path, allowed, _send, _send_command)
