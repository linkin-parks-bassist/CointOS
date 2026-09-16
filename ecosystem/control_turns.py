"""Durable lifecycle for Telegram control-plane turns."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from ecosystem import cli


SCHEMA_VERSION = 1
FRONT_TERMINAL_STATES = {"delivered", "failed", "delivery_unknown"}


def turn_id(update_id: int) -> str:
    return f"telegram-{update_id}"


def directory() -> Path:
    path = cli.ROOT / "state/control-turns"
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_for(identifier: str) -> Path:
    if not identifier.startswith("telegram-") or not identifier[9:].isdigit():
        raise ValueError("invalid control turn identifier")
    return directory() / f"{identifier}.json"


def _exclusive_json(path: Path, value: dict) -> bool:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        Path(temporary).unlink(missing_ok=True)


def accept(update_id: int, chat_id: int, user_id: int, message: str) -> tuple[dict, bool]:
    identifier = turn_id(update_id)
    path = path_for(identifier)
    now = cli.now()
    record = {
        "schema_version": SCHEMA_VERSION,
        "id": identifier,
        "transport": "telegram",
        "update_id": update_id,
        "chat_id": chat_id,
        "user_id": user_id,
        "message": message,
        "received_at": now,
        "updated_at": now,
        "front_state": "pending",
        "deep_state": "queued",
        "deep_attempts": 0,
        "actions": {},
    }
    created = _exclusive_json(path, record)
    saved = record if created else json.loads(path.read_text(encoding="utf-8"))
    identity = (saved.get("chat_id"), saved.get("user_id"), saved.get("message"))
    if identity != (chat_id, user_id, message):
        raise ValueError("Telegram update identity changed after acceptance")
    if created:
        cli.audit("control_turn.received", turn_id=identifier, update_id=update_id,
                  chat_id=chat_id, user_id=user_id, received_at=now)
    return saved, created


def load(identifier: str) -> dict:
    return json.loads(path_for(identifier).read_text(encoding="utf-8"))


def _mutate(identifier: str, change: Callable[[dict], None]) -> dict:
    path = path_for(identifier)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        record = json.loads(path.read_text(encoding="utf-8"))
        change(record)
        record["updated_at"] = cli.now()
        cli.atomic_json(path, record)
        return record


def mark_front_attempt(identifier: str) -> dict:
    def change(record: dict) -> None:
        if record["front_state"] == "pending":
            record["front_state"] = "generating"
            record["front_attempted_at"] = cli.now()
    return _mutate(identifier, change)


def mark_front_failed(identifier: str, error: str) -> dict:
    def change(record: dict) -> None:
        record.update(front_state="failed", front_error=error,
                      front_finished_at=cli.now())
    return _mutate(identifier, change)


def mark_front_ready(identifier: str, message: str) -> dict:
    def change(record: dict) -> None:
        record.update(front_state="ready", initial_response=message,
                      front_generated_at=cli.now())
    return _mutate(identifier, change)


def mark_front_sending(identifier: str) -> dict:
    def change(record: dict) -> None:
        if record.get("front_state") == "ready":
            record.update(front_state="sending", front_send_started_at=cli.now())
    return _mutate(identifier, change)


def mark_front_delivered(identifier: str) -> dict:
    def change(record: dict) -> None:
        now = cli.now()
        record.update(front_state="delivered", front_delivered_at=now,
                      generated_response_delivered_at=now)
    return _mutate(identifier, change)


def mark_front_delivery_unknown(identifier: str, error: str) -> dict:
    def change(record: dict) -> None:
        record.update(front_state="delivery_unknown", front_error=error,
                      front_finished_at=cli.now())
    return _mutate(identifier, change)


def _process_identity(pid: int) -> str:
    boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(") ", 1)[1].split()
        started = fields[19]
    except (FileNotFoundError, IndexError):
        started = "missing"
    return f"{boot}:{pid}:{started}"


def _process_alive(identity: str | None) -> bool:
    if not identity:
        return False
    try:
        _boot, raw_pid, started = identity.rsplit(":", 2)
        pid = int(raw_pid)
    except (ValueError, AttributeError):
        return False
    return started != "missing" and _process_identity(pid) == identity


def recover_interrupted() -> int:
    recovered = 0
    for path in sorted(directory().glob("telegram-*.json")):
        identifier = path.stem
        record = load(identifier)
        state = record.get("deep_state")
        owner = record.get("deep_owner_identity") or record.get("deep_worker_identity")
        if state not in {"reserved", "running", "followup_ready", "followup_sending"} or _process_alive(owner):
            continue
        changed = False
        def change(current: dict) -> None:
            nonlocal recovered, changed
            current_owner = current.get("deep_owner_identity") or current.get("deep_worker_identity")
            current_state = current.get("deep_state")
            if current_state in {"reserved", "running", "followup_ready"} and not _process_alive(current_owner):
                current.update(deep_state="queued", deep_recovered_at=cli.now())
                current.pop("deep_owner_pid", None)
                current.pop("deep_owner_identity", None)
                current.pop("deep_worker_pid", None)
                current.pop("deep_worker_identity", None)
                recovered += 1
                changed = True
            elif current_state == "followup_sending" and not _process_alive(current_owner):
                current.update(deep_state="delivery_unknown", deep_finished_at=cli.now(),
                               deep_error="worker stopped during Telegram delivery; not replayed")
                current.pop("deep_worker_pid", None)
                current.pop("deep_worker_identity", None)
                recovered += 1
                changed = True
        _mutate(identifier, change)
        if changed:
            cli.audit("control_turn.recovered", turn_id=identifier)
    return recovered


def reserve_next(owner_pid: int) -> str | None:
    for path in sorted(directory().glob("telegram-*.json")):
        identifier = path.stem
        selected = False
        def change(record: dict) -> None:
            nonlocal selected
            if (record.get("front_state") in FRONT_TERMINAL_STATES
                    and record.get("deep_state") == "queued"):
                record.update(deep_state="reserved", deep_owner_pid=owner_pid,
                              deep_owner_identity=_process_identity(owner_pid))
                selected = True
        _mutate(identifier, change)
        if selected:
            return identifier
    return None


def release_reservation(identifier: str, owner_pid: int) -> bool:
    released = False
    def change(record: dict) -> None:
        nonlocal released
        if (record.get("deep_state") == "reserved"
                and record.get("deep_owner_identity") == _process_identity(owner_pid)):
            record.update(deep_state="queued", deep_reservation_released_at=cli.now())
            record.pop("deep_owner_pid", None)
            record.pop("deep_owner_identity", None)
            released = True
    _mutate(identifier, change)
    return released


def claim_reserved(identifier: str, owner_pid: int, worker_pid: int) -> bool:
    claimed = False
    def change(record: dict) -> None:
        nonlocal claimed
        if (record.get("deep_state") == "reserved"
                and record.get("deep_owner_identity") == _process_identity(owner_pid)):
            record.update(deep_state="running", deep_worker_pid=worker_pid,
                          deep_worker_identity=_process_identity(worker_pid),
                          deep_started_at=cli.now(), deep_attempts=record.get("deep_attempts", 0) + 1)
            record.pop("deep_owner_pid", None)
            record.pop("deep_owner_identity", None)
            claimed = True
    _mutate(identifier, change)
    return claimed


def action_result(identifier: str, key: str) -> dict | None:
    return load(identifier).get("actions", {}).get(key)


def record_action(identifier: str, key: str, name: str, arguments: dict, result: dict) -> None:
    def change(record: dict) -> None:
        record.setdefault("actions", {}).setdefault(key, {
            "name": name, "arguments": arguments, "result": result, "completed_at": cli.now()
        })
    _mutate(identifier, change)


def mark_deep_completed(identifier: str, followup: str | None) -> dict:
    def change(record: dict) -> None:
        record.update(deep_state="followup_ready" if followup else "completed",
                      deep_finished_at=cli.now(), followup=followup)
        if not followup:
            record.pop("deep_worker_pid", None)
            record.pop("deep_worker_identity", None)
    return _mutate(identifier, change)


def mark_followup_sending(identifier: str) -> dict:
    def change(record: dict) -> None:
        if record.get("deep_state") == "followup_ready":
            record.update(deep_state="followup_sending", followup_send_started_at=cli.now())
    return _mutate(identifier, change)


def mark_followup_delivered(identifier: str) -> dict:
    def change(record: dict) -> None:
        now = cli.now()
        record.update(deep_state="completed", followup_delivered_at=now,
                      generated_response_delivered_at=now)
        record.pop("deep_worker_pid", None)
        record.pop("deep_worker_identity", None)
    return _mutate(identifier, change)


def mark_deep_failed(identifier: str, error: str) -> dict:
    def change(record: dict) -> None:
        record.update(deep_state="failed", deep_error=error, deep_finished_at=cli.now())
        record.pop("deep_worker_pid", None)
        record.pop("deep_worker_identity", None)
    return _mutate(identifier, change)


def mark_deep_retry(identifier: str, error: str) -> dict:
    def change(record: dict) -> None:
        record.update(deep_state="queued", deep_last_error=error,
                      deep_retry_queued_at=cli.now())
        record.pop("deep_worker_pid", None)
        record.pop("deep_worker_identity", None)
    return _mutate(identifier, change)


def mark_followup_delivery_unknown(identifier: str, error: str) -> dict:
    def change(record: dict) -> None:
        record.update(deep_state="delivery_unknown", deep_error=error,
                      deep_finished_at=cli.now())
        record.pop("deep_worker_pid", None)
        record.pop("deep_worker_identity", None)
    return _mutate(identifier, change)


def due_for_disaster(now: datetime | None = None, seconds: int = 300) -> list[dict]:
    instant = now or datetime.now(timezone.utc)
    due = []
    for path in sorted(directory().glob("telegram-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        received = datetime.fromisoformat(record["received_at"])
        uncertain = record.get("front_state") == "delivery_unknown" or record.get("deep_state") == "delivery_unknown"
        if ((instant - received).total_seconds() >= seconds
                and not record.get("generated_response_delivered_at")
                and not record.get("disaster_delivered_at") and not uncertain):
            due.append(record)
    return due


def mark_disaster_delivered(identifier: str) -> dict:
    def change(record: dict) -> None:
        if not record.get("generated_response_delivered_at"):
            record["disaster_delivered_at"] = cli.now()
    return _mutate(identifier, change)
