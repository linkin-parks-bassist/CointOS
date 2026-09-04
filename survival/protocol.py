"""Strict literal-command parsing and lifecycle-socket encoding."""

import json
from datetime import datetime

from survival.json_codec import decode_json_object


COMMAND_FIELDS = {
    "schema_version",
    "request_id",
    "telegram_update_id",
    "telegram_user_id",
    "command",
    "received_at",
}
COMMANDS = {"restart", "reset"}
LITERAL_COMMANDS = {"RESTART": "restart", "RESET": "reset"}


def parse_literal_command(text: str) -> str | None:
    """Return a command only for an exact, case-sensitive Telegram body."""
    return LITERAL_COMMANDS.get(text)


def encode_command(command: dict) -> bytes:
    """Encode one fully validated lifecycle command record as UTF-8 JSON."""
    _validate_command(command)
    return json.dumps(command, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_command(payload: bytes) -> dict:
    """Decode and validate one complete lifecycle command record."""
    value = decode_json_object(payload, "command")
    _validate_command(value)
    return value


def _validate_command(value: object) -> None:
    if type(value) is not dict or set(value) != COMMAND_FIELDS:
        raise ValueError("invalid command fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("invalid command value")
    if type(value["command"]) is not str or value["command"] not in COMMANDS:
        raise ValueError("invalid command value")
    if type(value["telegram_update_id"]) is not int or value["telegram_update_id"] < 0:
        raise ValueError("invalid command value")
    if type(value["telegram_user_id"]) is not int:
        raise ValueError("invalid command value")
    if type(value["request_id"]) is not str or value["request_id"] != (
        f"telegram-{value['telegram_update_id']}"
    ):
        raise ValueError("invalid command value")
    if type(value["received_at"]) is not str:
        raise ValueError("invalid command value")
    try:
        timestamp = datetime.fromisoformat(value["received_at"])
    except ValueError as error:
        raise ValueError("invalid command value") from error
    if timestamp.tzinfo is None:
        raise ValueError("invalid command value")
