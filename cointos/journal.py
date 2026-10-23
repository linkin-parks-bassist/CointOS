"""Stage immutable diagnostics; flush two bounded files outside the state lock."""
from collections import deque
import json
import threading
from cointos.config import STATE

PENDING = deque()
PENDING_LOCK = threading.Lock()
WRITE_LOCK = threading.Lock()
SEQUENCE = 0
RESULT = (0, None)


def write(event: dict, limit: int) -> None:
    """Freeze a record and its destination without touching the filesystem."""
    global SEQUENCE
    # Keep identifiers, sizes, reasons and receipts; never write model prompts.
    record = {key: (value[:1000] if isinstance(value, str) else value)
              for key, value in event.items() if key not in ("notes", "brief", "prompt", "tokens")}
    data = (json.dumps(record, ensure_ascii=False) + "\n").encode()
    if len(data) > limit:
        record = {k: event[k] for k in ("at", "event", "task", "agent") if k in event}
        data = (json.dumps(record) + "\n").encode()
    with PENDING_LOCK:
        SEQUENCE += 1
        PENDING.append((SEQUENCE, STATE / "events.jsonl", data, limit))


def flush() -> tuple[int, str | None]:
    """Attempt the captured queue prefix in order. Never call while holding state.LOCK.

    New records can be staged during slow I/O. Failed records remain best-effort,
    as before; report any failure in this batch until a later batch succeeds.
    The completion sequence prevents a delayed status publisher hiding newer errors.
    """
    global RESULT
    with WRITE_LOCK:
        with PENDING_LOCK:
            count = len(PENDING)
        error = None
        for _ in range(count):
            with PENDING_LOCK:
                sequence, path, data, limit = PENDING.popleft()
            try:
                _append(path, data, limit)
            except OSError as failed:
                error = str(failed)
            RESULT = (sequence, error)
        return RESULT


def _append(path, data: bytes, limit: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size + len(data) > limit:
        path.replace(path.with_suffix(".jsonl.1"))
    with path.open("ab") as stream:
        stream.write(data)
