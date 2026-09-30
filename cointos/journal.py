"""Two bounded event files, independent of the ledger's short dashboard history."""
import json
from cointos.config import STATE


def write(event: dict, limit: int) -> None:
    path = STATE / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep identifiers, sizes, reasons and receipts; never write model prompts.
    record = {key: (value[:1000] if isinstance(value, str) else value)
              for key, value in event.items() if key not in ("notes", "brief", "prompt", "tokens")}
    data = (json.dumps(record, ensure_ascii=False) + "\n").encode()
    if len(data) > limit:
        record = {k: event[k] for k in ("at", "event", "task", "agent") if k in event}
        data = (json.dumps(record) + "\n").encode()
    if path.exists() and path.stat().st_size + len(data) > limit:
        path.replace(path.with_suffix(".jsonl.1"))
    with path.open("ab") as stream:
        stream.write(data)
