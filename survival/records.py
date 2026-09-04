"""Filesystem-backed durable records for authenticated literal commands."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from survival.protocol import COMMAND_FIELDS, encode_command, parse_literal_command


def atomic_json(path: Path, value: dict) -> None:
    """Atomically replace a JSON record after forcing its bytes to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def append_event(path: Path, event: dict) -> None:
    """Append one durable JSONL event without changing previous events."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        json.dump(event, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def accept_update(root: Path, update: dict, allowed_user_ids: set[int]) -> dict:
    """Persist one authorized literal command, deduplicated by Telegram update ID."""
    identity = _telegram_identity(update)
    if identity["telegram_user_id"] not in allowed_user_ids:
        raise ValueError("unauthorized Telegram user")
    command = parse_literal_command(identity["telegram_text"])
    if command is None:
        raise ValueError("update is not a literal command")

    request_id = f"telegram-{identity['telegram_update_id']}"
    accepted = {
        "id": request_id,
        "schema_version": 1,
        "request_id": request_id,
        "telegram_update_id": identity["telegram_update_id"],
        "telegram_user_id": identity["telegram_user_id"],
        "command": command,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "telegram_identity": identity,
    }
    path = root / "commands" / f"{request_id}.json"
    try:
        _create_exclusive_json(path, accepted)
    except FileExistsError:
        existing = _read_existing_command(path)
        existing_identity = existing.get("telegram_identity")
        if not _identity_is_typed(existing_identity) or existing_identity != identity:
            raise ValueError("replayed update identity mismatch")
        _validate_existing_command(existing, request_id, command)
        return existing
    return accepted


def _telegram_identity(update: object) -> dict:
    try:
        update_id = update["update_id"]
        message = update["message"]
        user_id = message["from"]["id"]
        chat_id = message["chat"]["id"]
        text = message["text"]
    except (KeyError, TypeError) as error:
        raise ValueError("invalid Telegram update") from error
    if type(update_id) is not int or type(user_id) is not int or type(chat_id) is not int:
        raise ValueError("invalid Telegram update")
    if type(text) is not str:
        raise ValueError("invalid Telegram update")
    return {
        "telegram_update_id": update_id,
        "telegram_user_id": user_id,
        "telegram_chat_id": chat_id,
        "telegram_text": text,
    }


def _identity_is_typed(value: object) -> bool:
    if type(value) is not dict or set(value) != {
        "telegram_update_id",
        "telegram_user_id",
        "telegram_chat_id",
        "telegram_text",
    }:
        return False
    return (
        type(value["telegram_update_id"]) is int
        and type(value["telegram_user_id"]) is int
        and type(value["telegram_chat_id"]) is int
        and type(value["telegram_text"]) is str
    )


def _validate_existing_command(existing: dict, request_id: str, command: str) -> None:
    try:
        typed_command = {field: existing[field] for field in COMMAND_FIELDS}
        encode_command(typed_command)
    except (KeyError, ValueError) as error:
        raise ValueError("invalid existing command record") from error
    if existing.get("id") != request_id or typed_command["command"] != command:
        raise ValueError("replayed update command mismatch")


def _create_exclusive_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, separators=(",", ":"))
        output.flush()
        os.fsync(output.fileno())
    _fsync_directory(path.parent)


def _read_existing_command(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid existing command record") from error
    if type(value) is not dict:
        raise ValueError("invalid existing command record")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
