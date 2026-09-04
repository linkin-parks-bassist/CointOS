"""Filesystem-backed durable records for authenticated Telegram updates."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from survival.json_codec import decode_json_object

ACCEPTED_UPDATE_FIELDS = {
    "schema_version",
    "id",
    "telegram_update_id",
    "telegram_user_id",
    "chat_id",
    "text",
    "received_at",
}


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
    """Persist one authorized Telegram update, deduplicated by its update ID."""
    accepted = _accepted_update(update)
    if accepted["telegram_user_id"] not in allowed_user_ids:
        raise ValueError("unauthorized Telegram user")
    path = root / "commands" / f"{accepted['id']}.json"
    try:
        _create_exclusive_json(path, accepted)
    except FileExistsError:
        existing = _read_existing_command(path)
        _validate_accepted_update(existing)
        if not _same_update_identity(existing, accepted):
            raise ValueError("replayed update identity mismatch")
        return existing
    return accepted


def _accepted_update(update: object) -> dict:
    try:
        update_id = update["update_id"]
        message = update["message"]
        user_id = message["from"]["id"]
        chat_id = message["chat"]["id"]
        text = message["text"]
    except (KeyError, TypeError) as error:
        raise ValueError("invalid Telegram update") from error
    if (
        type(update_id) is not int
        or update_id < 0
        or type(user_id) is not int
        or type(chat_id) is not int
    ):
        raise ValueError("invalid Telegram update")
    if type(text) is not str:
        raise ValueError("invalid Telegram update")
    return {
        "schema_version": 1,
        "id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": user_id,
        "chat_id": chat_id,
        "text": text,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def _validate_accepted_update(existing: object) -> None:
    if type(existing) is not dict or set(existing) != ACCEPTED_UPDATE_FIELDS:
        raise ValueError("invalid accepted update fields")
    if type(existing["schema_version"]) is not int or existing["schema_version"] != 1:
        raise ValueError("invalid accepted update fields")
    if type(existing["telegram_update_id"]) is not int or existing["telegram_update_id"] < 0:
        raise ValueError("invalid accepted update fields")
    if existing["id"] != f"telegram-{existing['telegram_update_id']}":
        raise ValueError("invalid accepted update fields")
    if type(existing["telegram_user_id"]) is not int or type(existing["chat_id"]) is not int:
        raise ValueError("invalid accepted update fields")
    if type(existing["text"]) is not str or type(existing["received_at"]) is not str:
        raise ValueError("invalid accepted update fields")
    try:
        timestamp = datetime.fromisoformat(existing["received_at"])
    except ValueError as error:
        raise ValueError("invalid accepted update fields") from error
    if timestamp.tzinfo is None:
        raise ValueError("invalid accepted update fields")


def _same_update_identity(first: dict, second: dict) -> bool:
    return all(first[field] == second[field] for field in (
        "telegram_update_id", "telegram_user_id", "chat_id", "text",
    ))


def _create_exclusive_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _read_existing_command(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as source:
            return decode_json_object(source.read(), "accepted update")
    except OSError as error:
        raise ValueError("invalid existing command record") from error


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
