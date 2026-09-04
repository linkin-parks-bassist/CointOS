"""Low-level file-based Telegram I/O for the survival gateway."""

import json
from datetime import datetime
from pathlib import Path

from survival.records import atomic_json

INBOX_DIR = "inbox"
OUTBOX_DIR = "outbox"
CRITICAL_OUTBOX_DIR = "critical"


def store_inbound(root: Path, accepted: dict) -> None:
    """Persist an accepted ordinary update to the inbox."""
    record = dict(accepted)
    record["egress_state"] = "ready"
    path = root / INBOX_DIR / f"{accepted['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, record)


def store_denied_audit(root: Path, chat_id: int) -> None:
    """Record a denied user's attempt without message text."""
    record = {"chat_id": chat_id, "egress_state": "denied"}
    path = root / INBOX_DIR / f"denied-{chat_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, record)


def store_critical_outbox_entry(root: Path, record: dict) -> None:
    """Queue a message in the critical outbox for guaranteed delivery."""
    path = root / OUTBOX_DIR / CRITICAL_OUTBOX_DIR / f"{record['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, record)


def list_critical_outbox(root: Path) -> list[Path]:
    """Return paths to all critical outbox entries."""
    outbox_dir = root / OUTBOX_DIR / CRITICAL_OUTBOX_DIR
    if not outbox_dir.is_dir():
        return []
    return sorted(outbox_dir.glob("*.json"))


def read_outbox_entry(path: Path) -> dict:
    """Read one critical outbox entry."""
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def update_outbox_state(path: Path, egress_state: str) -> None:
    """Update the egress_state field of an outbox entry."""
    data = read_outbox_entry(path)
    data["egress_state"] = egress_state
    atomic_json(path, data)


def list_inbox_due(root: Path, now: float,
                   deadline_seconds: int = 300) -> list[Path]:
    """Return paths to inbox entries past their degraded-reply deadline.

    An entry is considered due when its ``egress_state`` is ``ready``
    and the stored ``received_at`` timestamp is older than
    ``deadline_seconds`` relative to ``now``.
    """
    inbox_dir = root / INBOX_DIR
    if not inbox_dir.is_dir():
        return []
    due = []
    for path in sorted(inbox_dir.glob("telegram-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if type(data) is not dict:
            continue
        if data.get("egress_state") != "ready":
            continue
        received_at = data.get("received_at")
        if type(received_at) is not str:
            continue
        try:
            ts = datetime.fromisoformat(received_at)
        except ValueError:
            continue
        age = now - ts.timestamp()
        if age >= deadline_seconds:
            due.append(path)
    return due


def update_inbox_state(path: Path, egress_state: str) -> None:
    """Update the egress_state field of an inbox entry."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["egress_state"] = egress_state
    atomic_json(path, data)


def write_heartbeat(root: Path, timestamp: float) -> None:
    """Write the gateway heartbeat marker."""
    path = root / "heartbeat.json"
    atomic_json(path, {"gateway_heartbeat": timestamp})
