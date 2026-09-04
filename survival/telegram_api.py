"""Low-level file-based Telegram I/O for the survival gateway.

Implements:
- Standard-library HTTPS Telegram API client (get_updates, send_message)
- Guardian Unix-domain-socket client (encode_command + bounded ack)
- Inbox/outbox CRUD with monotonic deadline tracking
- Quarantine for corrupted/malformed records
"""

import http.client
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from survival.records import atomic_json

INBOX_DIR = "inbox"
OUTBOX_DIR = "outbox"
CRITICAL_OUTBOX_DIR = "critical"
QUARANTINE_DIR = "quarantine"


# ---------------------------------------------------------------------------
# Telegram API client (standard-library HTTPS)
# ---------------------------------------------------------------------------

def _get_bot_token() -> str:
    """Read the Telegram bot token from the systemd credential path."""
    credentials_dir = os.environ.get("CREDENTIALS_DIRECTORY", "")
    if not credentials_dir:
        raise RuntimeError("missing CREDENTIALS_DIRECTORY environment variable")
    token_path = os.path.join(credentials_dir, "telegram_bot_token")
    try:
        token = Path(token_path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"telegram bot token not found at {token_path}"
        )
    if not token:
        raise RuntimeError("telegram bot token is empty")
    return token


def get_updates(bot_token: str = None, offset: int = None,
                timeout: int = 30) -> list | None:
    """Blocking long-poll: return list of updates or None on empty."""
    if bot_token is None:
        bot_token = _get_bot_token()
    params = {"timeout": str(timeout)}
    if offset is not None:
        params["offset"] = str(offset)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    token = bot_token.lstrip("Bot").lstrip("bot")
    host = "api.telegram.org"
    conn = http.client.HTTPSConnection(host, timeout=timeout + 5)
    try:
        conn.request("GET", f"/bot{token}/getUpdates?{query}")
        resp = conn.getresponse()
        if resp.status != 200:
            return None
        body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            return None
        return body.get("result", [])
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    finally:
        conn.close()


def send_message(bot_token: str = None, chat_id: int = None,
                 text: str = None) -> bool:
    """Send a Telegram message via HTTPS.  Returns True on success."""
    if bot_token is None:
        bot_token = _get_bot_token()
    if chat_id is None or text is None:
        raise ValueError("chat_id and text are required for send_message")
    query = json.dumps(
        {"chat_id": chat_id, "text": text},
        separators=(",", ":"),
    ).encode("utf-8")
    token = bot_token.lstrip("Bot").lstrip("bot")
    host = "api.telegram.org"
    conn = http.client.HTTPSConnection(host, timeout=30)
    try:
        conn.request(
            "POST",
            f"/bot{token}/sendMessage",
            body=query,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("ok", False)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Guardian socket client
# ---------------------------------------------------------------------------

def submit_to_guardian(socket_path: str,
                       command: dict) -> dict | None:
    """Send an encoded command to the guardian via Unix domain socket
    and return the typed acknowledgement, or None on failure."""
    encoded = protocol_encode_command(command)
    conn = http.client.HTTPConnection("localhost")  # placeholder
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(socket_path)
        # Write length-prefixed frame: 4-byte big-endian length + payload
        length_header = len(encoded).to_bytes(4, byteorder="big")
        sock.sendall(length_header + encoded)
        # Read response: bounded read up to 65536 bytes
        buf = b""
        while len(buf) < 65536:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        if not buf:
            return None
        ack = json.loads(buf.decode("utf-8"))
        if type(ack) is not dict:
            return None
        return ack
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if sock is not None:
            sock.close()


def protocol_encode_command(command: dict) -> bytes:
    """Encode a command record as bytes using protocol.encode_command."""
    from survival import protocol
    return protocol.encode_command(command)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def read_allowed_user_ids(user_ids_path: str) -> set[int]:
    """Read allowed Telegram user IDs from a root-installed file.

    Each line contains a single integer user ID.
    Raises RuntimeError if the file is absent or malformed.
    """
    try:
        lines = Path(user_ids_path).read_text(encoding="utf-8").strip().splitlines()
    except FileNotFoundError:
        raise RuntimeError(f"allowed user IDs file not found: {user_ids_path}")
    ids = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ids.add(int(line))
        except ValueError:
            raise RuntimeError(
                f"malformed user ID in {user_ids_path}: {line!r}"
            )
    return ids


# ---------------------------------------------------------------------------
# Inbox management with monotonic deadline
# ---------------------------------------------------------------------------

def store_inbound(root: Path, accepted: dict,
                  monotonic_now: float = None,
                  deadline_seconds: int = 3) -> None:
    """Persist an accepted ordinary update to the inbox with monotonic deadline."""
    record = dict(accepted)
    record["egress_state"] = "ready"
    if monotonic_now is not None:
        record["deadline_at"] = monotonic_now + deadline_seconds
    path = root / INBOX_DIR / f"{accepted['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, record)


def store_denied_audit(root: Path, chat_id: int) -> None:
    """Record a denied user's attempt without message text."""
    record = {"chat_id": chat_id, "egress_state": "denied"}
    path = root / INBOX_DIR / f"denied-{chat_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, record)


def quarantine_record(root: Path, source_path: Path,
                      error_reason: str, record: dict = None) -> None:
    """Move a corrupted/malformed record to quarantine and log the error."""
    quarantine_dir = root / QUARANTINE_DIR
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    error_record = {
        "original_path": str(source_path),
        "error_reason": error_reason,
        "quarantined_at": datetime.now(timezone.utc).isoformat(),
        "egress_state": "quarantined",
    }
    if record is not None:
        error_record["original_record"] = record
    error_path = quarantine_dir / f"quarantine-{int(time.time() * 1000)}.json"
    atomic_json(error_path, error_record)
    # Remove from source
    try:
        source_path.unlink()
    except OSError:
        pass


def list_quarantine_errors(root: Path) -> list[Path]:
    """Return paths to all quarantine error records."""
    quarantine_dir = root / QUARANTINE_DIR
    if not quarantine_dir.is_dir():
        return []
    return sorted(quarantine_dir.glob("quarantine-*.json"))


# ---------------------------------------------------------------------------
# Outbox management
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Inbox deadline queries
# ---------------------------------------------------------------------------

def list_inbox_due(root: Path,
                   now: float = None,
                   deadline_seconds: int = 3) -> list[Path]:
    """Return paths to inbox entries past their degraded-reply deadline.

    Compares monotonic ``deadline_at`` values against ``now`` (which must
    be a monotonic timestamp).  Entries without a monotonic deadline or
    with a non-ready egress state are skipped.  UTC ``received_at`` is
    audit data only and never used for comparison.
    """
    if now is None:
        now = time.monotonic()
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
        deadline_at = data.get("deadline_at")
        if type(deadline_at) is not float:
            continue
        try:
            if now >= deadline_at:
                due.append(path)
        except TypeError:
            continue
    return due


def update_inbox_state(path: Path, egress_state: str) -> None:
    """Update the egress_state field of an inbox entry."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["egress_state"] = egress_state
    atomic_json(path, data)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def write_heartbeat(root: Path, timestamp: float) -> None:
    """Write the gateway heartbeat marker."""
    path = root / "heartbeat.json"
    atomic_json(path, {"gateway_heartbeat": timestamp})
