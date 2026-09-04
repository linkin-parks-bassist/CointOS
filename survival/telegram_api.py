"""Literal Telegram, guardian-socket, and gateway-record fingertips."""

import http.client
import json
import math
import os
import socket
import time
from datetime import datetime
from pathlib import Path

from survival import protocol, records
from survival.json_codec import decode_json_object


INBOX_FIELDS = records.ACCEPTED_UPDATE_FIELDS | {
    "accepted_monotonic_at", "deadline_at", "egress_state",
}
CRITICAL_EGRESS_FIELDS = {
    "schema_version", "id", "chat_id", "text", "egress_state",
}
COMMAND_DELIVERY_FIELDS = {"schema_version", "request_id", "egress_state"}
ACKNOWLEDGEMENT_FIELDS = {
    "schema_version", "request_id", "chat_id", "text", "egress_state",
}
DENIAL_FIELDS = {
    "schema_version", "telegram_update_id", "telegram_user_id", "chat_id", "state",
}
WORKER_HEARTBEAT_FIELDS = {"schema_version", "worker", "monotonic_at"}
GATEWAY_HEARTBEAT_FIELDS = {
    "schema_version", "poll_monotonic_at", "egress_monotonic_at", "monotonic_at",
}
GUARDIAN_ACKNOWLEDGEMENT_FIELDS = {"schema_version", "request_id", "status"}
QUARANTINE_FIELDS = {
    "schema_version", "source_path", "quarantined_path", "error_reason",
    "quarantined_at",
}
EGRESS_STATES = {"ready", "sending", "delivered", "delivery_unknown"}
WORKERS = {"poll", "egress"}
MAXIMUM_GUARDIAN_RESPONSE_BYTES = 4096


def read_bot_token(credentials_directory):
    """Read a nonempty Telegram token from an explicit credential directory."""
    if type(credentials_directory) is not str or not credentials_directory:
        raise RuntimeError("missing CREDENTIALS_DIRECTORY")
    path = Path(credentials_directory) / "telegram_bot_token"
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"cannot read Telegram bot credential: {path}") from error
    if not token:
        raise RuntimeError("Telegram bot credential is empty")
    return token


def _get_bot_token():
    """Compatibility entry point using the explicit systemd credential variable."""
    return read_bot_token(os.environ.get("CREDENTIALS_DIRECTORY"))


def https_exchange(host, timeout, method, path, body, headers):
    """Perform one HTTPS request and return its status and complete body."""
    connection = http.client.HTTPSConnection(host, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def get_updates(
    bot_token,
    offset,
    timeout,
    request_timeout,
    https_exchange=https_exchange,
):
    """Perform one typed Telegram ``getUpdates`` long poll."""
    _validate_bot_token(bot_token)
    if offset is not None and (type(offset) is not int or offset < 0):
        raise ValueError("invalid Telegram update offset")
    _require_positive_number(timeout, "Telegram long-poll timeout")
    _require_positive_number(request_timeout, "Telegram request timeout")
    query = f"timeout={_format_seconds(timeout)}"
    if offset is not None:
        query += f"&offset={offset}"
    status, payload = https_exchange(
        "api.telegram.org",
        request_timeout,
        "GET",
        f"/bot{bot_token}/getUpdates?{query}",
        None,
        {},
    )
    response = _decode_telegram_response(status, payload)
    result = response.get("result")
    if type(result) is not list:
        raise RuntimeError("invalid Telegram getUpdates result")
    return result


def send_message(
    bot_token,
    chat_id,
    text,
    request_timeout,
    https_exchange=https_exchange,
):
    """Perform one Telegram ``sendMessage`` request or fail explicitly."""
    _validate_bot_token(bot_token)
    if type(chat_id) is not int or type(text) is not str:
        raise ValueError("invalid Telegram message")
    _require_positive_number(request_timeout, "Telegram request timeout")
    body = json.dumps(
        {"chat_id": chat_id, "text": text}, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    status, payload = https_exchange(
        "api.telegram.org",
        request_timeout,
        "POST",
        f"/bot{bot_token}/sendMessage",
        body,
        {"Content-Type": "application/json"},
    )
    _decode_telegram_response(status, payload)
    return True


def _decode_telegram_response(status, payload):
    try:
        response = json.loads(payload)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("invalid Telegram response") from error
    if type(status) is not int or status != 200:
        raise RuntimeError(f"Telegram HTTPS request failed with status {status!r}")
    if type(response) is not dict or response.get("ok") is not True:
        raise RuntimeError("Telegram API rejected request")
    return response


def submit_to_guardian(socket_path, command, timeout):
    """Submit one framed command and require a bounded typed acknowledgement."""
    if type(socket_path) is not str or not socket_path:
        raise ValueError("invalid guardian socket path")
    _require_positive_number(timeout, "guardian acknowledgement timeout")
    encoded = protocol.encode_command(command)
    request = len(encoded).to_bytes(4, "big") + encoded
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout)
        connection.connect(socket_path)
        connection.sendall(request)
        response_size = int.from_bytes(_receive_exact(connection, 4), "big")
        if response_size <= 0 or response_size > MAXIMUM_GUARDIAN_RESPONSE_BYTES:
            raise ValueError("invalid guardian acknowledgement size")
        acknowledgement = decode_json_object(
            _receive_exact(connection, response_size), "guardian acknowledgement",
        )
    finally:
        connection.close()
    if set(acknowledgement) != GUARDIAN_ACKNOWLEDGEMENT_FIELDS:
        raise ValueError("invalid guardian acknowledgement fields")
    if (
        type(acknowledgement["schema_version"]) is not int
        or acknowledgement["schema_version"] != 1
        or acknowledgement["request_id"] != command["request_id"]
        or acknowledgement["status"] != "accepted"
    ):
        raise ValueError("invalid guardian acknowledgement value")
    return acknowledgement


def _receive_exact(connection, size):
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise ConnectionError("guardian closed socket before complete acknowledgement")
        result.extend(chunk)
    return bytes(result)


def read_allowed_user_ids(path):
    """Read a nonempty set of exact integer user identities."""
    if type(path) is not str or not path:
        raise RuntimeError("missing GUARDIAN_ALLOWED_USER_IDS_PATH")
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError(f"cannot read allowed user identities: {path}") from error
    allowed = set()
    for line in lines:
        value = line.strip()
        if not value:
            continue
        try:
            user_id = int(value)
        except ValueError as error:
            raise RuntimeError(f"invalid allowed user identity: {value!r}") from error
        if str(user_id) != value:
            raise RuntimeError(f"invalid allowed user identity: {value!r}")
        allowed.add(user_id)
    if not allowed:
        raise RuntimeError("allowed user identity set is empty")
    return allowed


def store_inbound(root, accepted, monotonic_now, deadline_seconds):
    """Create an idempotent ordinary-message projection with one owned deadline."""
    _require_number(monotonic_now, "inbox acceptance time")
    _require_positive_number(deadline_seconds, "degraded response deadline")
    path = root / "inbox" / f"{accepted['id']}.json"
    if path.exists():
        existing = read_inbox_entry(path)
        if any(existing[field] != accepted[field] for field in records.ACCEPTED_UPDATE_FIELDS):
            raise ValueError("replayed inbox identity mismatch")
        return existing
    value = dict(accepted)
    value.update({
        "accepted_monotonic_at": float(monotonic_now),
        "deadline_at": float(monotonic_now + deadline_seconds),
        "egress_state": "ready",
    })
    validate_inbox_entry(value)
    _write_shared_record(path, value)
    return value


def store_denied_audit(root, update):
    """Store only the identity needed to audit a denied Telegram update."""
    try:
        update_id = update["update_id"]
        user_id = update["message"]["from"]["id"]
        chat_id = update["message"]["chat"]["id"]
    except (KeyError, TypeError) as error:
        raise ValueError("invalid denied Telegram update") from error
    if any(type(value) is not int for value in (update_id, user_id, chat_id)):
        raise ValueError("invalid denied Telegram update")
    value = {
        "schema_version": 1,
        "telegram_update_id": update_id,
        "telegram_user_id": user_id,
        "chat_id": chat_id,
        "state": "denied",
    }
    records.atomic_json(root / "inbox" / f"denied-{update_id}.json", value)


def list_inbox_entries(root):
    directory = root / "inbox"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("telegram-*.json"))


def read_inbox_entry(path):
    value = _read_record(path, "inbox")
    validate_inbox_entry(value)
    return value


def validate_inbox_entry(value):
    if type(value) is not dict or set(value) != INBOX_FIELDS:
        raise ValueError("invalid inbox fields")
    _validate_accepted_projection(value)
    _require_number(value["accepted_monotonic_at"], "inbox acceptance time")
    _require_number(value["deadline_at"], "inbox deadline")
    if value["deadline_at"] <= value["accepted_monotonic_at"]:
        raise ValueError("invalid inbox deadline")
    _validate_egress_state(value["egress_state"])


def update_inbox_state(path, state):
    value = read_inbox_entry(path)
    _validate_egress_state(state)
    value["egress_state"] = state
    _write_shared_record(path, value)
    return value


def store_critical_outbox_entry(root, value):
    validate_critical_outbox_entry(value)
    path = root / "outbox" / "critical" / f"{value['id']}.json"
    _write_shared_record(path, value)


def list_critical_outbox(root):
    directory = root / "outbox" / "critical"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def read_critical_outbox_entry(path):
    value = _read_record(path, "critical outbox")
    validate_critical_outbox_entry(value)
    if path.stem != value["id"]:
        raise ValueError("invalid critical outbox identity")
    return value


def validate_critical_outbox_entry(value):
    if type(value) is not dict or set(value) != CRITICAL_EGRESS_FIELDS:
        raise ValueError("invalid critical outbox fields")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["id"]) is not str
        or not value["id"]
        or type(value["chat_id"]) is not int
        or type(value["text"]) is not str
    ):
        raise ValueError("invalid critical outbox value")
    _validate_egress_state(value["egress_state"])


def update_critical_outbox_state(path, state):
    value = read_critical_outbox_entry(path)
    _validate_egress_state(state)
    value["egress_state"] = state
    _write_shared_record(path, value)
    return value


def _write_shared_record(path, value):
    records.atomic_json(path, value, mode=records.SHARED_RECORD_MODE)


def ensure_command_delivery(root, request_id):
    value = {
        "schema_version": 1,
        "request_id": request_id,
        "egress_state": "ready",
    }
    path = root / "gateway_commands" / f"{request_id}.json"
    return path, _ensure_exact_record(
        root, path, value, COMMAND_DELIVERY_FIELDS, "guardian command delivery",
    )


def update_command_delivery_state(path, state):
    value = _read_record(path, "guardian command delivery")
    _validate_command_delivery(value, path.stem)
    _validate_egress_state(state)
    value["egress_state"] = state
    records.atomic_json(path, value)
    return value


def ensure_acknowledgement(root, request_id, chat_id, text):
    value = {
        "schema_version": 1,
        "request_id": request_id,
        "chat_id": chat_id,
        "text": text,
        "egress_state": "ready",
    }
    path = root / "acks" / f"{request_id}.json"
    return path, _ensure_exact_record(
        root, path, value, ACKNOWLEDGEMENT_FIELDS, "Telegram acknowledgement",
    )


def update_acknowledgement_state(path, state):
    value = _read_record(path, "Telegram acknowledgement")
    _validate_acknowledgement(value, path.stem)
    _validate_egress_state(state)
    value["egress_state"] = state
    records.atomic_json(path, value)
    return value


def _ensure_exact_record(root, path, expected, fields, name):
    if not path.exists():
        records.atomic_json(path, expected)
        return dict(expected)
    try:
        value = _read_record(path, name)
        if fields == COMMAND_DELIVERY_FIELDS:
            _validate_command_delivery(value, expected["request_id"])
        else:
            _validate_acknowledgement(value, expected["request_id"])
        if any(value[field] != expected[field] for field in fields - {"egress_state"}):
            raise ValueError(f"replayed {name} identity mismatch")
        return value
    except (OSError, ValueError) as error:
        quarantine_record(root, path, str(error))
        raise RuntimeError(f"corrupt {name} state") from error


def _validate_command_delivery(value, request_id):
    if type(value) is not dict or set(value) != COMMAND_DELIVERY_FIELDS:
        raise ValueError("invalid guardian command delivery fields")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["request_id"] != request_id
    ):
        raise ValueError("invalid guardian command delivery value")
    _validate_egress_state(value["egress_state"])


def _validate_acknowledgement(value, request_id):
    if type(value) is not dict or set(value) != ACKNOWLEDGEMENT_FIELDS:
        raise ValueError("invalid Telegram acknowledgement fields")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["request_id"] != request_id
        or type(value["chat_id"]) is not int
        or type(value["text"]) is not str
    ):
        raise ValueError("invalid Telegram acknowledgement value")
    _validate_egress_state(value["egress_state"])


def quarantine_record(root, source_path, error_reason):
    """Move bad bytes aside, then durably publish one visible error record."""
    directory = root / "quarantine"
    directory.mkdir(parents=True, exist_ok=True)
    identity = f"{time.time_ns()}-{source_path.name}"
    quarantined_path = directory / f"{identity}.record"
    os.replace(source_path, quarantined_path)
    error = {
        "schema_version": 1,
        "source_path": str(source_path),
        "quarantined_path": str(quarantined_path),
        "error_reason": str(error_reason),
        "quarantined_at": datetime.now().astimezone().isoformat(),
    }
    records.atomic_json(directory / f"{identity}.json", error)


def list_quarantine_errors(root):
    directory = root / "quarantine"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def quarantine_is_empty(root):
    directory = root / "quarantine"
    return not directory.is_dir() or next(directory.iterdir(), None) is None


def write_worker_heartbeat(root, worker, monotonic_at):
    if worker not in WORKERS:
        raise ValueError("invalid gateway worker")
    _require_number(monotonic_at, "gateway worker heartbeat")
    value = {
        "schema_version": 1,
        "worker": worker,
        "monotonic_at": float(monotonic_at),
    }
    records.atomic_json(root / "heartbeats" / f"{worker}.json", value)


def read_worker_heartbeat(root, worker):
    if worker not in WORKERS:
        raise ValueError("invalid gateway worker")
    value = _read_record(root / "heartbeats" / f"{worker}.json", "worker heartbeat")
    if type(value) is not dict or set(value) != WORKER_HEARTBEAT_FIELDS:
        raise ValueError("invalid worker heartbeat fields")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["worker"] != worker
    ):
        raise ValueError("invalid worker heartbeat value")
    _require_number(value["monotonic_at"], "gateway worker heartbeat")
    return value


def write_gateway_heartbeat(root, poll_at, egress_at, monotonic_at):
    for value in (poll_at, egress_at, monotonic_at):
        _require_number(value, "gateway heartbeat")
    records.atomic_json(root / "heartbeat.json", {
        "schema_version": 1,
        "poll_monotonic_at": float(poll_at),
        "egress_monotonic_at": float(egress_at),
        "monotonic_at": float(monotonic_at),
    })


def _read_record(path, name):
    try:
        return decode_json_object(path.read_bytes(), name)
    except OSError as error:
        raise ValueError(f"invalid {name} read") from error


def _validate_accepted_projection(value):
    accepted = {field: value[field] for field in records.ACCEPTED_UPDATE_FIELDS}
    records._validate_accepted_update(accepted)


def _validate_egress_state(value):
    if type(value) is not str or value not in EGRESS_STATES:
        raise ValueError("invalid egress state")


def _validate_bot_token(value):
    if type(value) is not str or not value:
        raise ValueError("invalid Telegram bot token")


def _require_number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"invalid {name}")


def _require_positive_number(value, name):
    _require_number(value, name)
    if value <= 0:
        raise ValueError(f"invalid {name}")


def _format_seconds(value):
    numeric = float(value)
    return str(int(numeric)) if numeric.is_integer() else str(numeric)
