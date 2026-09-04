"""Literal Telegram, guardian-socket, and gateway-record fingertips."""

import http.client
import hashlib
import json
import math
import os
import socket
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from survival import protocol, records
from survival.json_codec import decode_json_object


INBOX_FIELDS = records.ACCEPTED_UPDATE_FIELDS | {
    "boot_id", "accepted_monotonic_at", "deadline_at", "egress_state",
}
CRITICAL_EGRESS_FIELDS = {
    "schema_version", "id", "chat_id", "text", "egress_state",
}
COMMAND_DELIVERY_FIELDS = {"schema_version", "request_id", "egress_state"}
CRITICAL_DELIVERY_FIELDS = {"schema_version", "message_id", "egress_state"}
CRITICAL_ATTEMPT_FIELDS = {
    "schema_version", "message_id", "attempt_observed",
}
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
DISPOSITION_FIELDS = {
    "schema_version", "telegram_update_id", "state", "reason",
}
INCIDENT_DESTINATION_FIELDS = {
    "schema_version", "telegram_user_id", "chat_id",
}
POLL_OFFSET_FIELDS = {"schema_version", "offset"}
EGRESS_STATES = {"ready", "sending", "delivered", "delivery_unknown"}
WORKERS = {"poll", "egress"}
MAXIMUM_GUARDIAN_RESPONSE_BYTES = 4096
_BOOT_ID_UNSET = object()


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
    query_values = {"timeout": _format_seconds(timeout)}
    if offset is not None:
        query_values["offset"] = str(offset)
    query_values["allowed_updates"] = json.dumps(["message"], separators=(",", ":"))
    query = urllib.parse.urlencode(query_values)
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
    deadline = time.monotonic() + timeout
    try:
        connection.settimeout(_remaining_seconds(deadline))
        connection.connect(socket_path)
        connection.settimeout(_remaining_seconds(deadline))
        connection.sendall(request)
        response_size = int.from_bytes(
            _receive_exact(connection, 4, deadline=deadline), "big",
        )
        if response_size <= 0 or response_size > MAXIMUM_GUARDIAN_RESPONSE_BYTES:
            raise ValueError("invalid guardian acknowledgement size")
        acknowledgement = decode_json_object(
            _receive_exact(connection, response_size, deadline=deadline),
            "guardian acknowledgement",
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


def _receive_exact(connection, size, deadline=None):
    result = bytearray()
    while len(result) < size:
        if deadline is not None:
            connection.settimeout(_remaining_seconds(deadline))
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise ConnectionError("guardian closed socket before complete acknowledgement")
        result.extend(chunk)
    return bytes(result)


def _remaining_seconds(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("guardian acknowledgement deadline expired")
    return remaining


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


def read_incident_destination(path):
    """Decode the one installed root-owned destination for survival incidents."""
    value = _read_record(Path(path), "incident destination")
    validate_incident_destination(value)
    return value


def validate_incident_destination(value):
    if type(value) is not dict or set(value) != INCIDENT_DESTINATION_FIELDS:
        raise ValueError("invalid incident destination fields")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["telegram_user_id"]) is not int
        or value["telegram_user_id"] <= 0
        or type(value["chat_id"]) is not int
        or value["chat_id"] != value["telegram_user_id"]
    ):
        raise ValueError("invalid incident destination value")


def current_boot_id(path=Path("/proc/sys/kernel/random/boot_id")):
    """Return the kernel boot identity owning monotonic timestamps."""
    try:
        value = Path(path).read_text(encoding="ascii").strip()
    except OSError as error:
        raise RuntimeError("cannot read kernel boot identity") from error
    if not value or any(character.isspace() for character in value):
        raise RuntimeError("invalid kernel boot identity")
    return value


def telegram_update_id(update):
    """Decode only the durable Telegram identity before interpreting its body."""
    try:
        update_id = update["update_id"]
    except (KeyError, TypeError) as error:
        raise ValueError("invalid Telegram update identity") from error
    if type(update_id) is not int or update_id < 0:
        raise ValueError("invalid Telegram update identity")
    return update_id


def store_ignored_update(root, update_id, reason="unsupported Telegram update"):
    """Durably dispose one identified update without retaining unneeded content."""
    if type(update_id) is not int or update_id < 0 or type(reason) is not str or not reason:
        raise ValueError("invalid Telegram update disposition")
    value = {
        "schema_version": 1,
        "telegram_update_id": update_id,
        "state": "ignored",
        "reason": reason,
    }
    path = root / "dispositions" / f"telegram-{update_id}.json"
    if path.exists():
        existing = _read_record(path, "Telegram update disposition")
        if existing != value:
            raise ValueError("replayed Telegram update disposition mismatch")
        return existing
    records.atomic_json(path, value)
    return value


def store_inbound(
    root, accepted, monotonic_now, deadline_seconds, boot_id=_BOOT_ID_UNSET,
):
    """Create an idempotent ordinary-message projection with one owned deadline."""
    _require_number(monotonic_now, "inbox acceptance time")
    _require_positive_number(deadline_seconds, "degraded response deadline")
    if boot_id is _BOOT_ID_UNSET:
        try:
            boot_id = current_boot_id()
        except RuntimeError:
            boot_id = None
    if boot_id is not None and (type(boot_id) is not str or not boot_id):
        raise ValueError("invalid inbox boot identity")
    path = root / "inbox" / f"{accepted['id']}.json"
    if path.exists():
        existing = read_inbox_entry(path)
        if any(existing[field] != accepted[field] for field in records.ACCEPTED_UPDATE_FIELDS):
            raise ValueError("replayed inbox identity mismatch")
        return existing
    value = dict(accepted)
    value.update({
        "boot_id": boot_id,
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
    if value["boot_id"] is not None and (
        type(value["boot_id"]) is not str or not value["boot_id"]
    ):
        raise ValueError("invalid inbox boot identity")
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
    if path.exists():
        existing = read_critical_outbox_entry(path)
        if existing != value:
            raise ValueError("replayed critical message identity mismatch")
        return existing
    _write_shared_record(path, value)
    return value


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


def ensure_critical_delivery(root, message_id, initial_state="ready"):
    """Own gateway delivery state without mutating a guardian-owned message."""
    if type(message_id) is not str or not message_id:
        raise ValueError("invalid critical message identity")
    _validate_egress_state(initial_state)
    attempt_observed = _critical_attempt_path(root, message_id).exists()
    if initial_state != "ready":
        observe_critical_delivery_attempt(root, message_id)
        attempt_observed = True
    value = {
        "schema_version": 1,
        "message_id": message_id,
        "egress_state": "delivery_unknown" if attempt_observed else initial_state,
    }
    path = root / "gateway" / "critical-delivery" / f"{message_id}.json"
    if not path.exists():
        records.atomic_json(path, value)
        if attempt_observed:
            record_critical_delivery_unknown(root, message_id)
        return path, value
    existing = _read_record(path, "critical delivery")
    _validate_critical_delivery(existing, message_id)
    if existing["egress_state"] != "ready":
        observe_critical_delivery_attempt(root, message_id)
    elif attempt_observed:
        existing = update_critical_delivery_state(path, "delivery_unknown")
        record_critical_delivery_unknown(root, message_id)
    return path, existing


def update_critical_delivery_state(path, state):
    value = _read_record(path, "critical delivery")
    _validate_critical_delivery(value, path.stem)
    _validate_egress_state(state)
    allowed = {
        "ready": {"sending", "delivery_unknown"},
        "sending": {"delivered", "delivery_unknown"},
        "delivered": {"delivered"},
        "delivery_unknown": {"delivery_unknown"},
    }
    if state not in allowed[value["egress_state"]]:
        raise ValueError("critical delivery terminal state cannot transition")
    value["egress_state"] = state
    records.atomic_json(path, value)
    return value


def _validate_critical_delivery(value, message_id):
    if type(value) is not dict or set(value) != CRITICAL_DELIVERY_FIELDS:
        raise ValueError("invalid critical delivery fields")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["message_id"] != message_id
    ):
        raise ValueError("invalid critical delivery value")
    _validate_egress_state(value["egress_state"])


def _critical_attempt_path(root, message_id):
    return Path(root) / "gateway" / "critical-attempts" / f"{message_id}.json"


def observe_critical_delivery_attempt(root, message_id):
    """Publish the immutable fact that Telegram egress may have begun."""
    if type(message_id) is not str or not message_id:
        raise ValueError("invalid critical message identity")
    value = {
        "schema_version": 1,
        "message_id": message_id,
        "attempt_observed": True,
    }
    path = _critical_attempt_path(root, message_id)
    try:
        records._create_exclusive_json(path, value)
    except FileExistsError:
        existing = _read_record(path, "critical delivery attempt")
        _validate_critical_delivery_attempt(existing, message_id)
    return path, value


def _validate_critical_delivery_attempt(value, message_id):
    if (
        type(value) is not dict
        or set(value) != CRITICAL_ATTEMPT_FIELDS
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["message_id"] != message_id
        or value["attempt_observed"] is not True
    ):
        raise ValueError("invalid critical delivery attempt")


def record_critical_delivery_unknown(root, message_id):
    """Expose one local health incident for operator delivery adjudication."""
    if type(message_id) is not str or not message_id:
        raise ValueError("invalid critical message identity")
    fingerprint = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
    incident_id = f"critical-delivery-{fingerprint}"
    value = {
        "schema_version": 1,
        "state": "delivery_unknown",
        "incident_id": incident_id,
        "message_id": message_id,
        "error_reason": "critical delivery state is uncertain after an observed attempt",
    }
    path = (
        Path(root) / "gateway" / "delivery-health-incidents" / f"{incident_id}.json"
    )
    try:
        if not path.exists():
            records.atomic_json(path, value)
    except OSError:
        pass
    return incident_id


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
    """Best-effort isolate bad bytes without turning one record into process death."""
    directory = root / "quarantine"
    try:
        metadata = source_path.stat()
        identity_source = "\0".join((
            str(source_path), str(error_reason), str(metadata.st_dev),
            str(metadata.st_ino), str(metadata.st_size), str(metadata.st_mtime_ns),
        ))
    except OSError:
        identity_source = f"{source_path}\0{error_reason}"
    incident_id = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:32]
    quarantined_path = directory / f"{incident_id}.record"
    quarantine_succeeded = False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _replace_record(source_path, quarantined_path)
        quarantine_succeeded = True
        error = {
            "schema_version": 1,
            "source_path": str(source_path),
            "quarantined_path": str(quarantined_path),
            "error_reason": str(error_reason),
            "quarantined_at": datetime.now().astimezone().isoformat(),
        }
        error_path = directory / f"{incident_id}.json"
        if not error_path.exists():
            records.atomic_json(error_path, error)
    except OSError:
        pass
    health = {
        "schema_version": 1,
        "state": "degraded",
        "incident_id": incident_id,
        "source_path": str(source_path),
        "error_reason": str(error_reason),
        "quarantine_succeeded": quarantine_succeeded,
    }
    health_directory = root / "gateway" / "data-health-incidents"
    try:
        records.atomic_json(health_directory / f"{incident_id}.json", health)
    except OSError:
        pass
    try:
        records.atomic_json(root / "gateway" / "data-health.json", health)
        if not quarantine_succeeded:
            error_path = directory / f"{incident_id}.json"
            if not error_path.exists():
                records.atomic_json(error_path, {
                    "schema_version": 1,
                    "source_path": str(source_path),
                    "quarantined_path": "",
                    "error_reason": str(error_reason),
                    "quarantined_at": datetime.now().astimezone().isoformat(),
                })
    except OSError:
        pass
    return quarantine_succeeded


def _replace_record(source_path, quarantined_path):
    os.replace(source_path, quarantined_path)


def list_quarantine_errors(root):
    directory = root / "quarantine"
    if not directory.is_dir():
        return []
    try:
        return sorted(directory.glob("*.json"))
    except OSError:
        return []


def quarantine_is_empty(root):
    directory = root / "quarantine"
    try:
        return not directory.is_dir() or next(directory.iterdir(), None) is None
    except OSError:
        return False


def read_poll_offset(root):
    path = root / "gateway" / "poll-offset.json"
    if not path.exists():
        return None
    value = _read_record(path, "Telegram poll offset")
    if (
        type(value) is not dict
        or set(value) != POLL_OFFSET_FIELDS
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["offset"]) is not int
        or value["offset"] < 0
    ):
        raise ValueError("invalid Telegram poll offset")
    return value["offset"]


def store_poll_offset(root, offset):
    if type(offset) is not int or offset < 0:
        raise ValueError("invalid Telegram poll offset")
    previous = read_poll_offset(root)
    if previous is not None and offset < previous:
        raise ValueError("Telegram poll offset cannot move backwards")
    records.atomic_json(root / "gateway" / "poll-offset.json", {
        "schema_version": 1,
        "offset": offset,
    })


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
    records.atomic_json(root / "gateway" / "heartbeat.json", {
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
